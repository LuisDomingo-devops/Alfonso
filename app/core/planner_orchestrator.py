"""
PlannerOrchestrator — FIXED CORE STABLE
"""
from __future__ import annotations

import asyncio
import json
import re

from app.core.intent_router import IntentRouter
from app.core.llm_client import extract_json_robust
from app.core.memory import memory
from app.core.tool_registry import get_tool
from app.utils.logger import attach_request_id, error_logger, orchestrator_logger

_router = IntentRouter()

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

_TOOL_TIMEOUT = 30.0  # segundos máximos por ejecución de tool

# OJO: las claves son el nombre REAL de la tool en el registry
# (lo que devuelve el LLM en "tool"), no el event_type del EventBus.
_DIRECT_CONFIRM = {
    "browser_navigate": "Navegación completada.",
    "create_file": "Archivo creado correctamente.",
    "delete_file": "Archivo eliminado.",
    "open_url": "Página abierta en tu navegador.",
}


def _normalize_message(message: str) -> str:
    return _TRAILING_PUNCT_RE.sub("", message.strip())


def _extract_tool_and_args(data: dict):
    if not isinstance(data, dict):
        return None, {}
    tool = data.get("tool")
    args = data.get("args", {})
    if tool:
        return tool, args
    key = next(iter(data.keys()), None)
    if key:
        nested = data.get(key, {})
        if isinstance(nested, dict):
            return key, nested.get("args", {})
    return None, {}


class PlannerOrchestrator:

    def __init__(self, event_bus=None):
        # Ya no se publica nada en el bus desde aquí (ejecución directa).
        # Se mantiene el parámetro solo por compatibilidad de firma con main.py.
        self._bus = event_bus

    async def run(
        self,
        user_message: str,
        llm,
        request_id: str | None = None,
        session_id: str | None = None,
    ):
        user_message = _normalize_message(user_message)
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)
        logger.info("Planner run: %s", user_message)

        memory_text = memory.get_summary(session_id) if session_id else None
        if session_id:
            memory.add_message(session_id, "user", user_message)

        detail = _router.detect_with_detail(user_message)
        mode = detail["intent"]

        # ---------------- CHAT ----------------
        if mode == "chat":
            raw = await llm.generate(user_message, mode="chat", request_id=request_id)
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        # ---------------- TOOL MODE ----------------
        raw = await llm.generate(
            user_message,
            mode="tool",
            request_id=request_id,
            memory=memory_text,
        )
        logger.debug("LLM RAW: %s", raw)

        data = extract_json_robust(raw)
        if not data:
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {"type": "chat", "response": raw}

        tool_name, args = _extract_tool_and_args(data)
        if not tool_name:
            error.error("No se pudo extraer tool de: %s", data)
            return {"type": "error", "message": "Tool no extraída", "raw": data}

        tool = get_tool(tool_name)
        if tool is None:
            error.warning("Tool no encontrada: %s", tool_name)
            return {"type": "error", "message": f"Tool no existe: {tool_name}"}

        # ---------------- EXECUTION (con timeout) ----------------
        try:
            if asyncio.iscoroutinefunction(tool):
                result = await asyncio.wait_for(tool(**args), timeout=_TOOL_TIMEOUT)
            else:
                result = tool(**args)
        except asyncio.TimeoutError:
            error.error("Timeout ejecutando tool %s (>%ss)", tool_name, _TOOL_TIMEOUT)
            return {"type": "error", "message": f"La herramienta {tool_name} tardó demasiado.", "tool": tool_name}
        except Exception as e:
            error.exception("Tool error")
            return {"type": "error", "message": str(e), "tool": tool_name}

        execution_result = {"type": "tool", "tool": tool_name, "result": result}

        if session_id:
            memory.add_message(session_id, "assistant", json.dumps(result, ensure_ascii=False))

        # ---------------- Caso especial: fecha/hora con valor real ----------------
        if tool_name == "get_current_datetime" and isinstance(result, dict) and result.get("status") == "ok":
            human = result.get("human", "")
            return {"type": "chat", "response": f"Son las {result.get('time', '')} — {human}."}

        # ---------------- DIRECT CONFIRM (solo si la tool de verdad funcionó) ----------------
        if tool_name in _DIRECT_CONFIRM:
            if isinstance(result, dict) and result.get("status") == "ok":
                return {"type": "chat", "response": _DIRECT_CONFIRM[tool_name]}
            msg = result.get("message") if isinstance(result, dict) else str(result)
            return {"type": "error", "message": msg or f"Error ejecutando {tool_name}", "tool": tool_name}

        logger.info("Tool ejecutada: %s", tool_name)
        return execution_result