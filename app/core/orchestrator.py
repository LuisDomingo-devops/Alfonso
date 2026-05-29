"""
Orchestrator — Fase 1 completa.

Cambios respecto a la versión anterior:
- Usa IntentRouter con scoring en lugar de keywords simples.
- Fallback inteligente: si el LLM devuelve texto plano en modo tool,
  reintenta una vez en modo chat en lugar de devolver error.
- Normalización de JSON más robusta (extrae JSON de bloques ```json```).
- Logging más descriptivo.
"""

import json
import re

from app.core.intent_router import IntentRouter
from app.core.memory import memory
from app.core.tool_registry import get_tool
from app.utils.logger import attach_request_id, orchestrator_logger, error_logger

_router = IntentRouter()

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict | None:
    """Intenta extraer un dict JSON del texto del LLM."""
    # 1. Bloque markdown ```json … ```
    m = _JSON_BLOCK.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2. JSON bare (primer { … })
    m = _BARE_JSON.search(raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 3. Intento directo
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return None


def _extract_tool_and_args(data: dict) -> tuple[str | None, dict]:
    """Normaliza los dos formatos que puede devolver el LLM."""
    # Formato estándar: {"tool": "...", "args": {...}}
    if "tool" in data:
        return data.get("tool"), data.get("args", {})

    # Formato QWEN: {"create_file": {"args": {...}}}
    tool_name = next(iter(data.keys()), None)
    if tool_name:
        nested = data.get(tool_name, {})
        if isinstance(nested, dict):
            return tool_name, nested.get("args", {})

    return None, {}


class Orchestrator:

    async def run(
        self,
        user_message: str,
        llm,
        request_id: str = None,
        session_id: str | None = None,
    ) -> dict:

        session_id = session_id or request_id
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        logger.info("REQUEST_ID iniciado")
        logger.info("USER MESSAGE: %s", user_message)
        logger.info("SESSION_ID: %s", session_id)

        # Memoria de sesión
        memory_text = memory.get_summary(session_id) if session_id else None
        if session_id:
            memory.add_message(session_id, "user", user_message)

        # Detección de intención con scoring
        detail = _router.detect_with_detail(user_message)
        mode = detail["intent"]
        logger.info(
            "Intent: %s (score=%.2f, reglas=%s)",
            mode,
            detail["score"],
            detail["fired_rules"],
        )

        # ----------------------------------------------------------------
        # MODO CHAT
        # ----------------------------------------------------------------
        if mode == "chat":
            raw = await llm.generate(
                user_message,
                mode="chat",
                request_id=request_id,
                memory=memory_text,
            )
            logger.info("Respuesta de chat completada")
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        # ----------------------------------------------------------------
        # MODO TOOL
        # ----------------------------------------------------------------
        raw = await llm.generate(
            user_message,
            mode="tool",
            request_id=request_id,
            memory=memory_text,
        )
        logger.debug("LLM OUTPUT (tool): %s", raw)

        data = _extract_json(raw)

        # Fallback: el LLM devolvió texto en vez de JSON → tratarlo como chat
        if data is None:
            logger.warning(
                "LLM no devolvió JSON válido en modo tool — fallback a chat. Raw: %s",
                raw[:200],
            )
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        tool_name, args = _extract_tool_and_args(data)

        if not tool_name:
            error.error("No se pudo extraer tool del JSON: %s", data)
            return {
                "type": "error",
                "message": "No se pudo extraer tool del JSON",
                "raw": data,
            }

        tool = get_tool(tool_name, request_id=request_id)

        if not tool:
            error.error("Tool no existe: %s", tool_name)
            return {"type": "error", "message": f"Tool no existe: {tool_name}"}

        try:
            logger.info("TOOL CALL: %s  args=%s", tool_name, args)
            result = await tool(**args)
            logger.info("TOOL RESULT: %s", result)
        except TypeError as e:
            # Args incorrectos — dar mensaje útil
            error.exception("Args incorrectos para tool %s", tool_name)
            return {
                "type": "error",
                "message": f"Argumentos incorrectos para {tool_name}: {e}",
                "tool": tool_name,
                "args": args,
            }
        except Exception as e:
            error.exception("Error ejecutando tool %s", tool_name)
            return {"type": "error", "message": str(e), "tool": tool_name}

        if session_id:
            memory.add_message(
                session_id,
                "assistant",
                f"Tool {tool_name} result: {result}",
            )

        logger.info("Tool ejecutado exitosamente: %s", tool_name)
        return {"type": "tool", "tool": tool_name, "result": result}