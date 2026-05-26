import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.api.files import router_files
from app.core.llm_client import OllamaClient
from app.core.metrics import increment_http_requests, increment_http_errors, record_http_latency
from app.utils.logger import app_logger, attach_request_id, LOG_DIR


llm = OllamaClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logger.info("Los logs se escribirán en %s", LOG_DIR)
    try:
        await llm.generate("ping")
        app_logger.info("Modelo precalentado")
    except Exception:
        app_logger.exception("Error precalentando el modelo")
    yield


app = FastAPI(title="Alfonso Core", lifespan=lifespan)


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
    logger.info("HTTP request finished: %s %s %s", request.method, request.url.path, response.status_code)
    increment_http_requests()
    record_http_latency(duration)

    return response


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


app.include_router(router)
app.include_router(router_files)