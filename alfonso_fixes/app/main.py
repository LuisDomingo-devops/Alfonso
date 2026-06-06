import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agents.registry import AgentRegistry
from app.api.files import router_files
from app.api.routes import router
from app.api.routes_fase3 import router_browser, router_computer  # Fase 3
from app.core.event_bus import EventBus
from app.core.llm_client import OllamaClient
from app.core.metrics import increment_http_errors, increment_http_requests, record_http_latency
from app.core.planner_orchestrator import PlannerOrchestrator
from app.utils.logger import LOG_DIR, app_logger, attach_request_id

# ---------------------------------------------------------------------------
# Instancias globales
# ---------------------------------------------------------------------------

llm = OllamaClient()
event_bus = EventBus()
agent_registry = AgentRegistry(event_bus, llm)

# PlannerOrchestrator con EventBus — Fase 2+
planner_orchestrator = PlannerOrchestrator(event_bus)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Arranque ──────────────────────────────────────────────────────────
    app_logger.info("Los logs se escribirán en %s", LOG_DIR)
    app_logger.info("Arrancando sistema de agentes — Fase 3")

    # 1. Event bus
    await event_bus.start()
    app_logger.info("EventBus iniciado")

    # 2. Agentes
    agent_registry.set_llm(llm)
    await agent_registry.start()
    agents = agent_registry.list_agents()
    app_logger.info("Agentes registrados: %s", [a["name"] for a in agents])

    # 3. Inyectar orquestador en las rutas
    from app.api import routes as _routes
    _routes.orchestrator = planner_orchestrator

    # 4. Precalentar el modelo
    try:
        await llm.generate("ping")
        app_logger.info("Modelo precalentado")
    except Exception:
        app_logger.exception("Error precalentando el modelo")

    app_logger.info("Alfonso Fase 3 listo")

    yield  # ── La aplicación corre aquí ───────────────────────────────────

    # ── Parada limpia ─────────────────────────────────────────────────────
    await agent_registry.stop()
    await event_bus.stop()
    app_logger.info("Agentes y EventBus detenidos")


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------

app = FastAPI(title="Alfonso Core — Fase 3", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    logger = attach_request_id(app_logger, request_id)
    logger.info("HTTP request started: %s %s", request.method, request.url.path)

    start_time = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start_time

    response.headers["X-Request-ID"] = request_id
    logger.info(
        "HTTP request finished: %s %s %s",
        request.method, request.url.path, response.status_code,
    )
    increment_http_requests()
    record_http_latency(duration)
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.warning("HTTP exception: %s", exc.detail)
    increment_http_errors()
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "request_id": request_id, "detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.warning("Validation error: %s", exc.errors())
    increment_http_errors()
    return JSONResponse(
        status_code=422,
        content={"status": "error", "request_id": request_id, "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.exception("Unhandled exception")
    increment_http_errors()
    return JSONResponse(
        status_code=500,
        content={"status": "error", "request_id": request_id, "detail": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(router)
app.include_router(router_files)
app.include_router(router_browser)   # Fase 3
app.include_router(router_computer)  # Fase 3
