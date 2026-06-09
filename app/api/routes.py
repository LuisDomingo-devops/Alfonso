"""
routes.py — Endpoints principales de Alfonso (Fase 3)

Endpoints:
    POST /chat          → mensaje de usuario → orquestador → respuesta
    GET  /health        → estado del servidor
    POST /audio/wakeword/upload → sube audio para detección de wakeword
    GET  /tools         → lista de tools registradas
    GET  /agents        → lista de agentes activos
    GET  /metrics       → métricas HTTP
    GET  /memory/{id}   → historial de sesión
    DELETE /memory/{id} → borrar historial de sesión
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Request, UploadFile, File, HTTPException

from app.tools.audio_tools import detect_wake_word_in_audio, transcribe_audio_bytes
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
    session_id: Optional[str] = None


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

def _extract_response_text(result: dict) -> str:
    """Extrae el texto que el asistente debe decir."""
    if result.get("type") == "chat":
        return result.get("response", "")
    elif result.get("type") == "tool":
        # Devolvemos el resumen de la ejecución de la herramienta
        return result.get("summary", "Operación completada.")
    return str(result.get("message", "Hecho"))


@router.post("/audio/command")
async def process_audio_command(file: UploadFile = File(...), session_id: Optional[str] = None):
    """
    Recibe audio, lo transcribe y ejecuta la orden resultante en el orquestador.
    """
    from app.main import llm
    request_id = str(uuid.uuid4())
    sid = session_id or request_id
    logger = attach_request_id(app_logger, request_id)

    logger.info("Procesando comando de voz desde archivo: %s", file.filename)

    try:
        audio_bytes = await file.read()
        
        # 1. Transcripción (STT)
        with Timer() as t_stt:
            text = await transcribe_audio_bytes(audio_bytes)
        
        if not text or len(text.strip()) < 2:
            return {"status": "ignored", "message": "No se detectó texto inteligible"}

        logger.info("Transcripción exitosa [%.2fs]: %s", t_stt.elapsed, text)

        # 2. Ejecución en Orquestador
        with Timer() as t_exec:
            result = await orchestrator.run(
                text,
                llm,
                request_id=request_id,
                session_id=sid,
            )

        return {
            "request_id": request_id,
            "transcription": text,
            "result": result,
            "latency_stt": t_stt.elapsed,
            "latency_exec": t_exec.elapsed
        }
    except Exception as e:
        logger.error("Error en process_audio_command: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/audio/wakeword/upload")
async def upload_wakeword(file: UploadFile = File(...), session_id: Optional[str] = None):
    """
    Recibe un archivo de audio y lo procesa para detectar una palabra de activación (wakeword).
    Si detecta la palabra y hay una orden adjunta, la ejecuta inmediatamente.
    """
    app_logger.info("Solicitud POST /audio/wakeword/upload recibida para archivo: %s", file.filename)
    try:
        audio_bytes = await file.read()
        detected = await detect_wake_word_in_audio(audio_bytes)
        
        if detected.get("wake_word_detected"):
            full_text = detected.get("text", "")
            keyword = detected.get("keyword", "alfonso").lower()
            
            # Extraemos la orden (lo que viene después del nombre)
            import re
            command_text = re.sub(rf"^{keyword}[,\s]*", "", full_text, flags=re.IGNORECASE).strip()
            
            if command_text:
                from app.main import llm
                app_logger.info("Orden detectada tras wakeword: '%s'. Ejecutando...", command_text)
                result = await orchestrator.run(
                    command_text,
                    llm,
                    session_id=session_id or str(uuid.uuid4())
                )
                detected["result"] = result

        return detected
    except Exception as e:
        error_message = f"Error procesando el archivo de wakeword: {e}"
        app_logger.error(error_message, exc_info=True)
        raise HTTPException(status_code=500, detail=error_message)

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
