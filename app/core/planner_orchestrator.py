"""
PlannerOrchestrator — Fase 3 (fixed v3)

Fixes respecto a versión anterior:
1. Normalización STT: elimina puntuación final del mensaje de usuario antes
   de procesarlo ("abre google." → "abre google").
2. Atajo browser_open_domain: si el intent_router detecta 'browser_open_domain'
   o 'browser_open_url', construye la URL directamente sin segunda llamada al LLM
   cuando el dominio es reconocible (google, youtube, etc.).
3. _build_synthesis_prompt(): más conciso para qwen2.5:1.5b.
4. Mensaje de confirmación system.close_app añadido a _DIRECT_CONFIRM.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from app.core.tool_registry import TOOLS, get_callable_tool_function

from app.core.intent_router import IntentRouter
from app.core.llm_client import extract_json_robust
from app.core.memory import memory
from app.agents.task_planner import TaskPlan, TaskPlanner
from app.utils.logger import attach_request_id, error_logger, orchestrator_logger

_router = IntentRouter()
_planner = TaskPlanner()

_AGENT_TIMEOUT = 90.0

# Puntuación final que puede generar el STT
_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

# Eventos cuyo resultado merece síntesis en lenguaje natural
_SYNTHESIS_EVENTS = {
    "filesystem.read",
    "filesystem.list",
    "system.info",
    "system.datetime",
    "browser.search",
    "browser.get_text",
    "browser.get_html",
}

# Mensajes de confirmación directa
_DIRECT_CONFIRM = {
    "filesystem.create":    "Archivo creado correctamente.",
    "filesystem.append":    "Contenido añadido al archivo.",
    "filesystem.delete":    "Archivo eliminado.",
    "system.command":       "Comando ejecutado.",
    "system.open_app":      "Aplicación abierta.",
    "system.close_app":     "Aplicación cerrada.",
    "browser.navigate":     "Navegación completada.",
    "browser.click":        "Click realizado.",
    "browser.fill":         "Campo rellenado.",
    "browser.submit":       "Formulario enviado.",
    "browser.screenshot":   "Captura realizada.",
    "browser.scroll":       "Scroll realizado.",
    "browser.evaluate":     "Script ejecutado.",
    "browser.close":        "Navegador cerrado.",
    "computer.screenshot":       "Captura de pantalla realizada.",
    "computer.mouse_move":       "Ratón movido.",
    "computer.mouse_click":      "Click realizado.",
    "computer.keyboard_type":    "Texto escrito.",
    "computer.keyboard_hotkey":  "Atajo de teclado ejecutado.",
    "automation.run_pipeline":   "Pipeline ejecutado.",
}

# Dominios conocidos → URLs
_DOMAIN_MAP = {
    "google":      "https://www.google.com",
    "youtube":     "https://www.youtube.com",
    "facebook":    "https://www.facebook.com",
    "twitter":     "https://www.twitter.com",
    "instagram":   "https://www.instagram.com",
    "linkedin":    "https://www.linkedin.com",
    "amazon":      "https://www.amazon.es",
    "wikipedia":   "https://es.wikipedia.org",
    "github":      "https://www.github.com",
    "reddit":      "https://www.reddit.com",
    "twitch":      "https://www.twitch.tv",
    "netflix":     "https://www.netflix.com",
    "spotify":     "https://open.spotify.com",
}


def _normalize_message(message: str) -> str:
    """Elimina puntuación final que introduce el STT."""
    return _TRAILING_PUNCT_RE.sub("", message.strip())


def _extract_domain_url(message: str) -> str | None:
    """
    Si el mensaje menciona un dominio conocido, devuelve su URL.
    Ej: "abre google" → "https://www.google.com"
    """
    lower = message.lower()
    for domain, url in _DOMAIN_MAP.items():
        if re.search(rf"\b{domain}\b", lower):
            return url
    # URL explícita con www.
    m = re.search(r"www\.([\w\-]+\.\w{2,})", lower)
    if m:
        return f"https://www.{m.group(1)}"
    # URL con protocolo
    m = re.search(r"https?://[\w\-\.]+\.\w{2,}", message)
    if m:
        return m.group(0)
    return None


def _extract_tool_and_args(data: dict) -> tuple[str | None, dict]:
    if "tool" in data:
        return data.get("tool"), data.get("args", {})
    tool_name = next(iter(data.keys()), None)
    if tool_name:
        nested = data.get(tool_name, {})
        if isinstance(nested, dict):
            return tool_name, nested.get("args", {})
    return None, {}


_DELETE_KEYWORDS  = {"elimina", "borra", "delete", "remove", "quitar"}
_DATETIME_KEYWORDS = {"hora", "día", "date", "fecha", "semana", "today", "time", "hoy"}


def _build_synthesis_prompt(user_message: str, event_type: str, tool_result: dict) -> str:
    result_str = json.dumps(tool_result, ensure_ascii=False, indent=None)
    if len(result_str) > 1500:
        result_str = result_str[:1500] + "..."
    return (
        f"El usuario preguntó: \"{user_message}\"\n\n"
        f"Resultado ({event_type}):\n{result_str}\n\n"
        "Responde al usuario en una o dos frases en español usando solo los datos del resultado. "
        "No inventes información. No expliques el sistema."
    )


class PlannerOrchestrator:

    def __init__(self, event_bus=None):
        self._bus = event_bus

    def set_event_bus(self, event_bus) -> None:
        self._bus = event_bus

    async def run(
        self,
        user_message: str,
        llm,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> dict:

        # FIX: normalizar puntuación STT
        user_message = _normalize_message(user_message)

        session_id = session_id or request_id
        logger = attach_request_id(orchestrator_logger, request_id)
        error  = attach_request_id(error_logger, request_id)

        logger.info("PlannerOrchestrator.run iniciado")
        logger.info("USER MESSAGE: %s", user_message)
        logger.info("SESSION_ID: %s", session_id)

        memory_text = memory.get_summary(session_id) if session_id else None
        if session_id:
            memory.add_message(session_id, "user", user_message)

        detail = _router.detect_with_detail(user_message)
        mode   = detail["intent"]
        logger.info(
            "Intent: %s (score=%.2f, reglas=%s)",
            mode, detail["score"], detail["fired_rules"],
        )

        # ── MODO CHAT ─────────────────────────────────────────────────
        if mode == "chat":
            plan = _planner.plan(
                intent="chat", tool_name=None, args={}, fallback_message=user_message
            )
            result = await self._dispatch(plan, llm, session_id, request_id, memory_text, user_message)
            logger.info("Respuesta chat completada")
            return result

        # ── ATAJOS SIN LLM ────────────────────────────────────────────
        fired_categories = {r.split("[")[1].rstrip("]") for r in detail["fired_rules"] if "[" in r}

        # Atajo fecha/hora
        if "datetime_tool" in fired_categories:
            logger.info("Atajo datetime_tool activado")
            plan = _planner.plan(intent="tool", tool_name="get_current_datetime", args={}, fallback_message=user_message)
            execution_result = await self._dispatch(plan, llm, session_id, request_id, memory_text, user_message)
            if execution_result.get("type") == "tool":
                tool_result = execution_result.get("result", {})
                human = tool_result.get("human") if isinstance(tool_result, dict) else None
                if human:
                    response = f"Son las {tool_result.get('time', '')} — {human}."
                    if session_id:
                        memory.add_message(session_id, "assistant", response)
                    return {"type": "chat", "response": response}
            return execution_result

        # FIX: Atajo browser directo para dominios conocidos
        browser_cats = {"browser_open_domain", "browser_open_url", "url_www", "url_explicit", "known_domain_boost"}
        if browser_cats & fired_categories:
            url = _extract_domain_url(user_message)
            if url:
                logger.info("Atajo browser directo: %s", url)
                plan = _planner.plan(
                    intent="tool",
                    tool_name="browser_navigate",
                    args={"url": url},
                    fallback_message=user_message,
                )
                execution_result = await self._dispatch(plan, llm, session_id, request_id, memory_text, user_message)
                if execution_result.get("type") == "tool" and plan.event_type in _DIRECT_CONFIRM:
                    confirm = _DIRECT_CONFIRM[plan.event_type]
                    if session_id:
                        memory.add_message(session_id, "assistant", confirm)
                    return {"type": "chat", "response": confirm}
                return execution_result

        # ── MODO TOOL — LLM genera JSON ────────────────────────────────
        raw = await llm.generate(
            user_message, mode="tool", request_id=request_id, memory=memory_text
        )
        logger.debug("LLM OUTPUT (tool): %s", raw)

        data = extract_json_robust(raw)

        if data is None:
            logger.warning("LLM no devolvió JSON válido — fallback a chat. Raw: %s", raw[:200])
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        tool_name, args = _extract_tool_and_args(data)

        # Cortar cascada LLM_ERROR
        if tool_name == "no_op":
            msg_arg = args.get("message", "")
            if "LLM_ERROR" in msg_arg:
                error.error("LLM_ERROR interceptado: %s", msg_arg)
                return {
                    "type": "error",
                    "message": f"El modelo no respondió a tiempo. Inténtalo de nuevo.",
                }
            return {"type": "chat", "response": msg_arg or "Necesito más información para continuar."}

        # Corrección de alucinaciones
        msg_lower = user_message.lower()

        if tool_name == "system_info" and any(k in msg_lower for k in _DELETE_KEYWORDS):
            logger.warning("Alucinación detectada: system_info → delete_file")
            tool_name = "delete_file"
            if not args.get("path"):
                m = re.search(r"[\w\-]+\.\w{1,6}", user_message)
                if m:
                    args["path"] = m.group(0)

        if tool_name in ("no_op", None) and any(k in msg_lower for k in _DATETIME_KEYWORDS):
            if any(k in msg_lower for k in ("hora", "día", "fecha", "hoy", "semana")):
                logger.warning("Alucinación datetime: %s → get_current_datetime", tool_name)
                tool_name = "get_current_datetime"
                args = {}

        if not tool_name:
            error.error("No se pudo extraer tool del JSON: %s", data)
            return {"type": "error", "message": "No se pudo extraer tool del JSON", "raw": data}

        plan = _planner.plan(
            intent="tool", tool_name=tool_name, args=args, fallback_message=user_message
        )

        logger.info("TaskPlan: event=%s args=%s", plan.event_type, args)
        execution_result = await self._dispatch(plan, llm, session_id, request_id, memory_text, user_message)

        # ── Síntesis condicional ──────────────────────────────────────
        if execution_result.get("type") == "tool" and plan.event_type in _SYNTHESIS_EVENTS:
            logger.info("Síntesis activada para: %s", plan.event_type)
            tool_result = execution_result.get("result", {})
            synthesis_prompt = _build_synthesis_prompt(user_message, plan.event_type, tool_result)
            try:
                final_response = await llm.generate(synthesis_prompt, mode="chat", request_id=request_id)
                if session_id:
                    memory.add_message(session_id, "assistant", final_response)
                return {"type": "chat", "response": final_response, "intermediate_tool": execution_result}
            except Exception as exc:
                logger.warning("Síntesis fallida (%s), devolviendo resultado directo", exc)
                return execution_result

        # ── Confirmación directa ──────────────────────────────────────
        if execution_result.get("type") == "tool" and plan.event_type in _DIRECT_CONFIRM:
            result_payload = execution_result.get("result", {})
            tool_msg = result_payload.get("message") if isinstance(result_payload, dict) else None
            confirm_msg = tool_msg or _DIRECT_CONFIRM[plan.event_type]
            if session_id:
                memory.add_message(session_id, "assistant", confirm_msg)
            return {"type": "chat", "response": confirm_msg}

        logger.info("Agente respondió: %s", execution_result.get("type"))
        return execution_result

    # ─────────────────────────────────────────────────────────────────
    # Dispatch via EventBus
    # ─────────────────────────────────────────────────────────────────

    async def _dispatch(self, plan, llm, session_id, request_id, memory_text, user_message) -> dict:
        logger = attach_request_id(orchestrator_logger, request_id)

        if self._bus is None:
            logger.warning("EventBus no disponible — ejecución directa")
            return await self._direct_execute(plan, llm, session_id, request_id, memory_text, user_message)

        event_data = {
            "event_type":   plan.event_type,
            "args":         plan.args,
            "user_message": user_message,
            "session_id":   session_id,
            "request_id":   request_id,
            "memory_text":  memory_text,
            "_llm":         llm,
        }

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        async def _on_result(agent_result) -> None:
            if not future.done():
                future.set_result(agent_result)

        event_data["_result_callback"] = _on_result
        await self._bus.publish(plan.event_type, event_data)
        logger.debug("Evento publicado: %s", plan.event_type)

        try:
            agent_result = await asyncio.wait_for(future, timeout=_AGENT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error("Timeout esperando agente para %s", plan.event_type)
            return {"type": "error", "message": f"Agente no respondió: {plan.event_type}"}

        return self._agent_result_to_response(agent_result, session_id)

    def _agent_result_to_response(self, agent_result, session_id) -> dict:
        if agent_result.status == "error":
            return {
                "type": "error",
                "message": agent_result.error or f"Error en agente ({agent_result.event_type})",
            }
        payload = agent_result.payload or {}
        if agent_result.event_type == "chat.respond":
            if session_id and payload.get("response"):
                memory.add_message(session_id, "assistant", payload["response"])
            return payload
        if session_id:
            memory.add_message(session_id, "assistant", f"Tool {agent_result.event_type}: {payload}")
        return {
            "type":       "tool",
            "agent":      agent_result.agent,
            "event_type": agent_result.event_type,
            "result":     payload,
        }

    # ─────────────────────────────────────────────────────────────────
    # Ejecución directa (sin EventBus)
    # ─────────────────────────────────────────────────────────────────

    async def _direct_execute(self, plan, llm, session_id, request_id, memory_text, user_message) -> dict:
        from app.core.tool_registry import get_tool

        if plan.is_chat:
            raw = await llm.generate(user_message, mode="chat", request_id=request_id, memory=memory_text)
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        _event_to_tool = {
            "filesystem.create":  "create_file",
            "filesystem.read":    "read_file",
            "filesystem.append":  "append_file",
            "filesystem.list":    "list_directory",
            "filesystem.delete":  "delete_file",
            "system.info":        "system_info",
            "system.datetime":    "get_current_datetime",
            "system.command":     "run_command",
            "system.open_app":    "open_application",
            "system.close_app":   "close_application",
            "browser.navigate":   "browser_navigate",
            "browser.search":     "browser_search",
            "browser.screenshot": "browser_screenshot",
            "browser.get_text":   "browser_get_text",
        }

        tool_name = _event_to_tool.get(plan.event_type, plan.tool_name)
        tool = get_tool(tool_name, request_id=request_id)

        if not tool:
            return {"type": "error", "message": f"Tool no existe: {tool_name}"}

        try:
            result = await tool(**plan.args)
        except TypeError as e:
            return {"type": "error", "message": f"Args incorrectos para {tool_name}: {e}", "tool": tool_name}
        except Exception as e:
            return {"type": "error", "message": str(e), "tool": tool_name}

        if session_id:
            memory.add_message(session_id, "assistant", f"Tool {tool_name}: {result}")

        return {"type": "tool", "tool": tool_name, "result": result}