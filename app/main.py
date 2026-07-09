"""
MAIN — Punto de entrada del Servidor Core de Alfonso.

¿QUÉ HACE?
Configura e inicializa la aplicación FastAPI, definiendo middlewares globales (registro de request ID, latencia HTTP) y manejadores de excepciones, y expone los servicios web.

¿CUÁNDO LO HACE?
Al arrancar el servidor web a través de comandos ASGI como uvicorn/gunicorn.

¿CÓMO LO HACE?
Crea una instancia de FastAPI, registra el router principal unificado, configura manejadores de eventos (lifespan) para iniciar y detener el bridge WebSocket y precalentar el modelo LLM.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py: Importa y registra el router principal consolidado.
- app/core/planner_orchestrator.py: Inicializa el planificador orquestador global.
- app/core/llm_client.py: Inicializa y precalienta el cliente LLM de Ollama.
- app/core/alfonso_bridge.py: Arranca/detiene la comunicación en tiempo real con el cliente.
"""

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.adapters.llm_client import OllamaClient, get_system_prompt
from app.adapters.metrics import increment_http_errors, increment_http_requests, record_http_latency
from app.domain.planner_orchestrator import PlannerOrchestrator
from app.adapters.alfonso_bridge import bridge as alfonso_bridge
from app.tools.client.browser_tools import _close as _close_playwright
from app.utils.logger import LOG_DIR, app_logger, attach_request_id

import asyncio
from app.domain.agents.security.security_agent import security_agent

# ---------------------------------------------------------------------------
# Instancias globales
# ---------------------------------------------------------------------------

llm = OllamaClient()
planner_orchestrator = PlannerOrchestrator()
_bg_security_task = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bg_security_task
    app_logger.info("Logs en %s", LOG_DIR)
    app_logger.info("Arrancando Alfonso — audio delegado al cliente local")

    import sys
    is_testing = "pytest" in sys.modules

    if not is_testing:
        await alfonso_bridge.start()
        # Iniciar monitoreo de seguridad en segundo plano
        _bg_security_task = asyncio.create_task(security_agent.start_background_monitoring())
    else:
        app_logger.info("Inicio del bridge y monitoreo de seguridad omitidos en entorno de test")

    from app.api import routes as _routes
    _routes.orchestrator = planner_orchestrator

    try:
        get_system_prompt("chat")
        get_system_prompt("tool")
        app_logger.info("Prompts de sistema precargados (chat + tool)")
    except Exception:
        app_logger.exception("Error precargando prompts de sistema")

    try:
        if not is_testing:
            await llm.generate("ping")
            app_logger.info("Modelo precalentado")
        else:
            app_logger.info("Precalentamiento de modelo omitido en entorno de test")
    except Exception:
        app_logger.exception("Error precalentando modelo")

    app_logger.info("Alfonso listo")

    yield

    if not is_testing:
        await alfonso_bridge.stop()
        if _bg_security_task:
            _bg_security_task.cancel()
    else:
        app_logger.info("Detención del bridge omitida en entorno de test")

    try:
        await _close_playwright()
        app_logger.info("Playwright cerrado limpiamente")
    except Exception:
        app_logger.exception("Error cerrando Playwright")

    app_logger.info("Alfonso detenido")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Alfonso Core — Fase 4", lifespan=lifespan)


@app.middleware("http")
async def security_waf_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "127.0.0.1"

    if security_agent.is_blocked(ip):
        return JSONResponse(
            status_code=403,
            content={"status": "error", "detail": "IP address blacklisted due to security violations."}
        )

    # Leer body de forma segura para escaneo sin interrumpir flujo
    body_bytes = b""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) < 65536:
        try:
            body_bytes = await request.body()
            async def receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            request._receive = receive
        except Exception:
            pass

    body_str = body_bytes.decode("utf-8", errors="ignore")
    path_and_query = f"{request.url.path}?{request.url.query}" if request.url.query else request.url.path
    headers_dict = dict(request.headers)

    if security_agent.inspect_request(ip, path_and_query, request.method, headers_dict, body_str):
        return JSONResponse(
            status_code=403,
            content={"status": "error", "detail": "Request rejected due to potential security threat."}
        )

    return await call_next(request)


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


app.include_router(router)