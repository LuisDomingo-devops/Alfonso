"""
main.py — Alfonso Core Fase 3 (sin audio server-side)

El audio (STT/TTS/wake word) se gestiona completamente en el cliente local (ui/).
El servidor solo expone /chat y las rutas de herramientas.
"""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agents.registry import AgentRegistry
from app.api.routes import router
from app.api.routes_fase3 import router_browser, router_computer
from app.core.event_bus import EventBus
from app.core.llm_client import OllamaClient
from app.core.metrics import increment_http_errors, increment_http_requests, record_http_latency
from app.core.planner_orchestrator import PlannerOrchestrator
from app.core.alfonso_bridge import bridge as alfonso_bridge
from app.utils.logger import LOG_DIR, app_logger, attach_request_id

# ---------------------------------------------------------------------------
# Instancias globales
# ---------------------------------------------------------------------------

llm              = OllamaClient()
event_bus        = EventBus()
agent_registry   = AgentRegistry(event_bus, llm)
planner_orchestrator = PlannerOrchestrator(event_bus)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logger.info("Logs en %s", LOG_DIR)
    app_logger.info("Arrancando Alfonso — audio delegado al cliente local")

    await event_bus.start()

    agent_registry.set_llm(llm)
    await agent_registry.start()
    await alfonso_bridge.start()
    app_logger.info("Agentes: %s", [a["name"] for a in agent_registry.list_agents()])

    from app.api import routes as _routes
    _routes.orchestrator = planner_orchestrator

    try:
        await llm.generate("ping")
        app_logger.info("Modelo precalentado")
    except Exception:
        app_logger.exception("Error precalentando modelo")

    app_logger.info("Alfonso listo")

    yield

    await alfonso_bridge.stop()
    await agent_registry.stop()
    await event_bus.stop()
    app_logger.info("Alfonso detenido")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Alfonso Core — Fase 3", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    logger = attach_request_id(app_logger, request_id)
    logger.info("HTTP %s %s", request.method, request.url.path)

    start_time = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start_time

    response.headers["X-Request-ID"] = request_id
    increment_http_requests()
    record_http_latency(duration)
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    increment_http_errors()
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "request_id": request_id, "detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    increment_http_errors()
    return JSONResponse(
        status_code=422,
        content={"status": "error", "request_id": request_id, "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    attach_request_id(app_logger, request_id).exception("Unhandled exception")
    increment_http_errors()
    return JSONResponse(
        status_code=500,
        content={"status": "error", "request_id": request_id, "detail": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(router)
app.include_router(router_browser)
app.include_router(router_computer)