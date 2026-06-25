from __future__ import annotations

import asyncio
import re

from app.core.intent_router import IntentRouter
from app.core.llm_client import extract_json_robust
from app.core.memory import memory

from app.core.tool_registry import (
    get_tool,
    is_client_tool,
    get_client_action,
)

from app.core.alfonso_bridge import bridge

from app.utils.logger import (
    attach_request_id,
    error_logger,
    orchestrator_logger,
)


_router = IntentRouter()

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

_TOOL_TIMEOUT = 30


_DIRECT_CONFIRM = {
    "browser_navigate": "Navegación completada.",
    "create_file": "Archivo creado correctamente.",
    "delete_file": "Archivo eliminado.",
}


FORCE_TOOL_KEYWORDS = [
    "abre",
    "open",
    "lanza",
    "ejecuta",
    "click",
    "escribe",
    "navega",
    "visita",
]


def _normalize_message(msg):
    
    return _TRAILING_PUNCT_RE.sub("", msg.strip())


def _force_tool(msg):
    
    msg = msg.lower()
    return any(x in msg for x in FORCE_TOOL_KEYWORDS)


def _extract_tool_and_args(data):
    
    if not isinstance(data, dict):
        
        return None, {}

    if "tool" in data:
        
        return data["tool"], data.get("args", {})

    key = next(iter(data), None)
    if key:
        value = data[key]
        if isinstance(value, dict):
            return key, value.get("args", {})

    return None, {}


class PlannerOrchestrator:
    """
    Pipeline único de Alfonso (post Fase 2): no hay EventBus ni AgentRegistry.
    Todo pasa por aquí — detección de intent, llamada al LLM, ejecución de
    tool (cliente vía bridge o servidor vía tool_registry) y, si aplica,
    persistencia en la memoria corta de Fase 1 (SessionMemory).
    """

    async def run(self, user_message, llm, request_id=None, session_id=None):
        logger.info("PlannerOrchestrator.run() — request_id=%s, session_id=%s", request_id, session_id)
        user_message = _normalize_message(user_message)

        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        # Persistimos el turno del usuario en memoria corta ANTES de generar,
        # sea cual sea el intent. Así un mensaje "tool" también queda en el
        # historial que un futuro turno "chat" podrá recuperar como contexto.
        if session_id:
            memory.add_message(session_id, "user", user_message)

        router = _router.detect_with_detail(user_message)

        # ------------------------------------------------------------
        # CHAT
        # ------------------------------------------------------------
        if router["intent"] == "chat" and not _force_tool(user_message):
            logger.info("Intent detectado: chat (no se fuerza tool)")
            memory_text = memory.get_summary(session_id) if session_id else None

            response = await llm.generate(
                user_message,
                mode="chat",
                request_id=request_id,
                memory=memory_text,
            )

            if session_id:
                memory.add_message(session_id, "assistant", response)

            return {
                "type": "chat",
                "response": response,
            }

        # ------------------------------------------------------------
        # TOOL — parseo de la respuesta del LLM en modo tool
        # ------------------------------------------------------------
        raw = await llm.generate(
            user_message,
            mode="tool",
            request_id=request_id,
        )

        data = extract_json_robust(raw)
        logger.info("LLM tool response: %s", data)
        if not data:
            error.warning("LLM no devolvió JSON de tool válido")
            return {
                "type": "error",
                "message": "JSON tool inválido",
                "raw": raw,
            }

        tool_name, args = _extract_tool_and_args(data)

        if not tool_name:
            return {
                "type": "error",
                "message": "Tool desconocida",
            }

        # ------------------------------------------------------------
        # EJECUCIÓN — cliente (bridge) o servidor (tool_registry)
        # ------------------------------------------------------------
        if is_client_tool(tool_name):
            logger.info("Ejecutando tool de cliente: %s", tool_name)
            action = get_client_action(tool_name)
            logger.info("Enviando al cliente %s", action)

            result = await bridge.send_command(action, args)

            if not isinstance(result, dict) or result.get("status") == "error":
                error.warning(
                    "Tool de cliente falló: %s -> %s",
                    tool_name,
                    result,
                )
                return {
                    "type": "error",
                    "execution": "client",
                    "tool": tool_name,
                    "message": (
                        result.get("error", "Error desconocido ejecutando tool en el cliente")
                        if isinstance(result, dict)
                        else "Respuesta inválida del cliente"
                    ),
                    "result": result,
                }

            execution = "client"

        else:
            logger.info("Ejecutando tool de servidor: %s", tool_name)
            tool = get_tool(tool_name, request_id)

            if not tool:
                return {
                    "type": "error",
                    "message": f"No existe {tool_name}",
                }

            try:
                if asyncio.iscoroutinefunction(tool):
                    result = await asyncio.wait_for(
                        tool(**args),
                        timeout=_TOOL_TIMEOUT,
                    )
                else:
                    loop = asyncio.get_running_loop()
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: tool(**args)),
                        timeout=_TOOL_TIMEOUT,
                    )

            except Exception as e:
                error.exception("Error ejecutando tool de servidor: %s", tool_name)
                return {
                    "type": "error",
                    "execution": "server",
                    "tool": tool_name,
                    "message": str(e),
                }

            if isinstance(result, dict) and result.get("status") == "error":
                error.warning(
                    "Tool de servidor falló: %s -> %s",
                    tool_name,
                    result,
                )
                return {
                    "type": "error",
                    "execution": "server",
                    "tool": tool_name,
                    "message": result.get("message", "Error ejecutando tool"),
                    "result": result,
                }

            execution = "server"

        # ------------------------------------------------------------
        # RESPUESTA UNIFICADA
        # ------------------------------------------------------------
        if tool_name in _DIRECT_CONFIRM:
            confirm_text = _DIRECT_CONFIRM[tool_name]
            if session_id:
                memory.add_message(session_id, "assistant", confirm_text)
            return {
                "type": "chat",
                "response": confirm_text,
            }

        logger.info("Ejecución de tool finalizada: %s (%s)", tool_name, execution)

        return {
            "type": "tool",
            "execution": execution,
            "tool": tool_name,
            "result": result,
        }