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
from app.agents.task_planner import TaskPlanner
from app.core.tool_registry import get_tool
from app.utils.logger import attach_request_id, error_logger, orchestrator_logger

_router = IntentRouter()
_planner = TaskPlanner()

_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")

_DIRECT_CONFIRM = {
    "browser.navigate": "Navegación completada.",
    "filesystem.create": "Archivo creado correctamente.",
    "filesystem.delete": "Archivo eliminado.",
    "system.datetime": "Fecha/hora obtenida.",
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

    # fallback formato raro
    key = next(iter(data.keys()), None)
    if key:
        nested = data.get(key, {})
        if isinstance(nested, dict):
            return key, nested.get("args", {})

    return None, {}


class PlannerOrchestrator:

    def __init__(self, event_bus=None):
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
            return {"type": "chat", "response": raw}

        tool_name, args = _extract_tool_and_args(data)

        if not tool_name:
            return {"type": "error", "message": "Tool no extraída"}

        # ---------------- EXECUTION (SIN EVENT BUS REAL) ----------------
        tool = get_tool(tool_name)

        if tool is None:
            return {"type": "error", "message": f"Tool no existe: {tool_name}"}

        try:
            result = await tool(**args) if asyncio.iscoroutinefunction(tool) else tool(**args)
        except Exception as e:
            error.exception("Tool error")
            return {"type": "error", "message": str(e), "tool": tool_name}

        execution_result = {
            "type": "tool",
            "tool": tool_name,
            "result": result,
        }

        # ---------------- MEMORY ----------------
        if session_id:
            memory.add_message(session_id, "assistant", json.dumps(result, ensure_ascii=False))

        # ---------------- DIRECT CONFIRM ----------------
        if tool_name in _DIRECT_CONFIRM:
            msg = _DIRECT_CONFIRM[tool_name]
            return {"type": "chat", "response": msg}

        logger.info("Tool ejecutada: %s", tool_name)

        return execution_result