"""
PlannerOrchestrator — Fase 3.

Mejoras respecto a Fase 2:
- Manejo del intent 'datetime_tool': si el IntentRouter detecta una pregunta de fecha/hora,
  se despacha directamente a system.datetime sin pasar por el LLM.
- Corrección de alucinaciones ampliada: detecta también cuando el LLM usa run_command
  o system_info para responder preguntas de fecha.
- Mapa _direct_execute ampliado con system.datetime y browser.*.
"""

from __future__ import annotations

import asyncio
import json
import re

from app.core.intent_router import IntentRouter
from app.core.memory import memory
from app.agents.task_planner import TaskPlan, TaskPlanner
from app.utils.logger import attach_request_id, error_logger, orchestrator_logger

_router = IntentRouter()
_planner = TaskPlanner()

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"\{.*\}", re.DOTALL)

_AGENT_TIMEOUT = 30.0


def _extract_json(raw: str) -> dict | None:
    m = _JSON_BLOCK.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = _BARE_JSON.search(raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
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


# Keywords de intención por categoría (para corrección de alucinaciones)
_DELETE_KEYWORDS = {"elimina", "borra", "delete", "remove", "quitar"}
_DATETIME_KEYWORDS = {"hora", "día", "date", "fecha", "semana", "today", "time"}


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

        session_id = session_id or request_id
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        logger.info("PlannerOrchestrator.run iniciado")
        logger.info("USER MESSAGE: %s", user_message)
        logger.info("SESSION_ID: %s", session_id)

        memory_text = memory.get_summary(session_id) if session_id else None
        if session_id:
            memory.add_message(session_id, "user", user_message)

        detail = _router.detect_with_detail(user_message)
        mode = detail["intent"]
        logger.info(
            "Intent: %s (score=%.2f, reglas=%s)",
            mode, detail["score"], detail["fired_rules"],
        )

        # ── MODO CHAT ───────────────────────────────────────────────
        if mode == "chat":
            plan = _planner.plan(
                intent="chat",
                tool_name=None,
                args={},
                fallback_message=user_message,
            )
            result = await self._dispatch(plan, llm, session_id, request_id, memory_text, user_message)
            logger.info("Respuesta chat completada")
            return result

        # ── ATAJO: FECHA/HORA — evitar que el LLM invente la fecha ──
        fired_categories = {r.split("[")[1].rstrip("]") for r in detail["fired_rules"] if "[" in r}
        if "datetime_tool" in fired_categories:
            logger.info("Atajo datetime_tool activado — sin llamada al LLM")
            plan = _planner.plan(
                intent="tool",
                tool_name="get_current_datetime",
                args={},
                fallback_message=user_message,
            )
            result = await self._dispatch(plan, llm, session_id, request_id, memory_text, user_message)
            logger.info("Datetime tool completada")
            return result

        # ── MODO TOOL — LLM genera JSON ─────────────────────────────
        raw = await llm.generate(
            user_message,
            mode="tool",
            request_id=request_id,
            memory=memory_text,
        )
        logger.debug("LLM OUTPUT (tool): %s", raw)

        data = _extract_json(raw)

        if data is None:
            logger.warning("LLM no devolvió JSON válido — fallback a chat. Raw: %s", raw[:200])
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        tool_name, args = _extract_tool_and_args(data)

        # ── Corrección de alucinaciones ─────────────────────────────
        msg_lower = user_message.lower()

        # Alucinación 1: LLM usa system_info para borrar archivos
        if tool_name == "system_info" and any(k in msg_lower for k in _DELETE_KEYWORDS):
            logger.warning("Alucinación detectada: system_info → delete_file")
            tool_name = "delete_file"
            if not args.get("path"):
                path_match = re.search(r'(/[^\s]+|\\[^\s]+|[a-zA-Z]:\\[^\s]+)', user_message)
                if path_match:
                    args["path"] = path_match.group(1)

        # Alucinación 2: LLM responde con texto para preguntas de fecha
        if tool_name in ("no_op", None) and any(k in msg_lower for k in _DATETIME_KEYWORDS):
            if any(k in msg_lower for k in ("hora", "día", "fecha", "hoy", "semana")):
                logger.warning("Alucinación datetime: %s → get_current_datetime", tool_name)
                tool_name = "get_current_datetime"
                args = {}

        if not tool_name:
            error.error("No se pudo extraer tool del JSON: %s", data)
            return {
                "type": "error",
                "message": "No se pudo extraer tool del JSON",
                "raw": data,
            }

        plan = _planner.plan(
            intent="tool",
            tool_name=tool_name,
            args=args,
            fallback_message=user_message,
        )

        logger.info("TaskPlan: event=%s args=%s", plan.event_type, args)
        result = await self._dispatch(plan, llm, session_id, request_id, memory_text, user_message)
        logger.info("Agente respondió: %s", result.get("type"))
        return result

    async def _dispatch(
        self,
        plan: TaskPlan,
        llm,
        session_id: str | None,
        request_id: str | None,
        memory_text: str | None,
        user_message: str,
    ) -> dict:
        logger = attach_request_id(orchestrator_logger, request_id)

        if self._bus is None:
            logger.warning("EventBus no disponible — ejecución directa")
            return await self._direct_execute(plan, llm, session_id, request_id, memory_text, user_message)

        event_data = {
            "event_type": plan.event_type,
            "args": plan.args,
            "user_message": user_message,
            "session_id": session_id,
            "request_id": request_id,
            "memory_text": memory_text,
            "_llm": llm,
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
            logger.error("Timeout esperando agente para evento %s", plan.event_type)
            return {
                "type": "error",
                "message": f"Agente no respondió a tiempo para: {plan.event_type}",
            }

        return self._agent_result_to_response(agent_result, session_id)

    def _agent_result_to_response(self, agent_result, session_id: str | None) -> dict:
        if agent_result.status == "error":
            return {
                "type": "error",
                "message": agent_result.error or "Error desconocido en agente",
            }

        payload = agent_result.payload or {}

        if agent_result.event_type == "chat.respond":
            if session_id and payload.get("response"):
                memory.add_message(session_id, "assistant", payload["response"])
            return payload

        result = payload
        if session_id:
            memory.add_message(
                session_id,
                "assistant",
                f"Tool {agent_result.event_type} result: {result}",
            )

        return {
            "type": "tool",
            "agent": agent_result.agent,
            "event_type": agent_result.event_type,
            "result": result,
        }

    async def _direct_execute(
        self,
        plan: TaskPlan,
        llm,
        session_id: str | None,
        request_id: str | None,
        memory_text: str | None,
        user_message: str,
    ) -> dict:
        from app.core.tool_registry import get_tool

        if plan.is_chat:
            raw = await llm.generate(
                user_message,
                mode="chat",
                request_id=request_id,
                memory=memory_text,
            )
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        _event_to_tool = {
            "filesystem.create":   "create_file",
            "filesystem.read":     "read_file",
            "filesystem.append":   "append_file",
            "filesystem.list":     "list_directory",
            "filesystem.delete":   "delete_file",
            "system.info":         "system_info",
            "system.datetime":     "get_current_datetime",
            "system.command":      "run_command",
            "system.open_app":     "open_application",
            "browser.navigate":    "browser_navigate",
            "browser.search":      "browser_search",
            "browser.screenshot":  "browser_screenshot",
            "browser.get_text":    "browser_get_text",
        }

        tool_name = _event_to_tool.get(plan.event_type, plan.tool_name)
        tool = get_tool(tool_name, request_id=request_id)

        if not tool:
            return {"type": "error", "message": f"Tool no existe: {tool_name}"}

        try:
            result = await tool(**plan.args)
        except TypeError as e:
            return {
                "type": "error",
                "message": f"Argumentos incorrectos para {tool_name}: {e}",
                "tool": tool_name,
                "args": plan.args,
            }
        except Exception as e:
            return {"type": "error", "message": str(e), "tool": tool_name}

        if session_id:
            memory.add_message(session_id, "assistant", f"Tool {tool_name} result: {result}")

        return {"type": "tool", "tool": tool_name, "result": result}
