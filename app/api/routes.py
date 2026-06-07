"""
routes.py — Endpoints principales de Alfonso (Fase 3)

Endpoints:
    POST /chat          → mensaje de usuario → orquestador → respuesta
    GET  /health        → estado del servidor
    GET  /tools         → lista de tools registradas
    GET  /agents        → lista de agentes activos
    GET  /metrics       → métricas HTTP
    GET  /memory/{id}   → historial de sesión
    DELETE /memory/{id} → borrar historial de sesión
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.metrics import snapshot
from app.core.tool_registry import list_tools
from app.utils.logger import app_logger, attach_request_id
from app.utils.timer import Timer

router = APIRouter()

# Se inyecta desde lifespan en main.py
orchestrator: Any = None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok", "phase": "3"}


@router.get("/tools")
async def tools_list():
    return {"tools": list_tools()}


@router.get("/agents")
async def agents_list(request: Request):
    from app.main import agent_registry
    return {"agents": agent_registry.list_agents()}


@router.get("/metrics")
async def metrics():
    return snapshot()


@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    from app.main import llm

    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    logger = attach_request_id(app_logger, request_id)

    logger.info("Solicitud /chat recibida")
    logger.info("SESSION_ID: %s", req.session_id or request_id)
    logger.info("USER MESSAGE: %s", req.message)

    with Timer() as t:
        result = await orchestrator.run(
            req.message,
            llm,
            request_id=request_id,
            session_id=req.session_id or request_id,
        )

    status = result.get("type", "unknown")
    logger.info("Solicitud /chat procesada con estado: %s", status)
    logger.info("LATENCY: %.2fs", t.elapsed)

    return {"request_id": request_id, "result": result}


@router.get("/memory/{session_id}")
async def get_memory(session_id: str):
    from app.core.memory import memory
    history = memory.get_history(session_id)
    return {"session_id": session_id, "messages": history, "count": len(history)}


@router.delete("/memory/{session_id}")
async def clear_memory(session_id: str):
    from app.core.memory import memory
    memory.clear(session_id)
    return {"status": "ok", "session_id": session_id, "message": "Historial borrado"}


@router.get("/memory")
async def list_sessions():
    from app.core.memory import memory
    sessions = memory.list_sessions()
    return {"sessions": sessions, "count": len(sessions)}
