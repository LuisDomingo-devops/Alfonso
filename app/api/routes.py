"""
routes.py — Endpoints principales de Alfonso (Fase 3, fixed v2)

Fixes:
1. /audio/wakeword/upload: ahora devuelve TTS con la respuesta del orquestador.
   El cliente recibe {wake_word_detected, result, tts_audio_url} y puede
   reproducir el audio usando GET /audio/file?path=<tts_audio_url>.
2. _extract_response_text(): mejorado para cubrir todos los tipos de resultado.
3. Normalización del comando de voz antes de pasarlo al orquestador:
   se elimina puntuación final que viene del STT ("abre google." → "abre google").
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.core.metrics import snapshot
from app.core.tool_registry import list_tools
from app.tools.audio_tools import detect_wake_word_in_audio, transcribe_audio_bytes
from app.utils.logger import app_logger, attach_request_id
from app.utils.timer import Timer

router = APIRouter()

# Se inyecta desde lifespan en main.py
orchestrator: Any = None

# Puntuación final que puede generar el STT
_TRAILING_PUNCT_RE = re.compile(r"[.,;:!?¡¿\s]+$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_voice_command(text: str) -> str:
    """Elimina puntuación y espacios finales que introduce el STT."""
    return _TRAILING_PUNCT_RE.sub("", text.strip())


def _extract_response_text(result: dict) -> str:
    """Extrae el texto que el asistente debe verbalizar."""
    rtype = result.get("type", "")

    if rtype == "chat":
        return result.get("response", "")

    if rtype == "tool":
        # Si hay una respuesta sintetizada (PlannerOrchestrator la añade a veces)
        if result.get("response"):
            return result["response"]
        # Confirmaciones directas del planner
        event = result.get("event_type", "")
        _CONFIRMS = {
            "filesystem.create":  "Archivo creado.",
            "filesystem.append":  "Contenido añadido.",
            "filesystem.delete":  "Archivo eliminado.",
            "system.command":     "Comando ejecutado.",
            "system.open_app":    "Aplicación abierta.",
            "system.close_app":   "Aplicación cerrada.",
            "browser.navigate":   "Navegación completada.",
            "browser.search":     "Búsqueda completada.",
            "browser.click":      "Click realizado.",
            "browser.fill":       "Campo rellenado.",
        }
        if event in _CONFIRMS:
            return _CONFIRMS[event]
        # Fallback: mensaje del resultado interno
        inner = result.get("result", {})
        if isinstance(inner, dict) and inner.get("message"):
            return inner["message"]
        return "Hecho."

    if rtype == "error":
        msg = result.get("message", "Ha ocurrido un error.")
        # No verbalizar mensajes técnicos muy largos
        return msg[:120] if len(msg) > 120 else msg

    return str(result.get("message", "Listo."))


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


@router.post("/audio/command")
async def process_audio_command(
    file: UploadFile = File(...),
    session_id: Optional[str] = None,
    tts: bool = True,
):
    """
    Recibe audio, transcribe y ejecuta la orden en el orquestador.
    Si tts=True (por defecto), genera audio con la respuesta.
    """
    from app.main import llm
    from app.tools.audio_tools import text_to_speech

    request_id = str(uuid.uuid4())
    sid = session_id or request_id
    logger = attach_request_id(app_logger, request_id)

    logger.info("Procesando comando de voz: %s", file.filename)

    try:
        audio_bytes = await file.read()

        with Timer() as t_stt:
            stt_result = await transcribe_audio_bytes(audio_bytes)

        if stt_result.get("status") != "ok":
            raise HTTPException(status_code=422, detail="STT falló")

        raw_text = stt_result.get("text", "").strip()
        if not raw_text or len(raw_text) < 2:
            return {"status": "ignored", "message": "No se detectó texto inteligible"}

        command_text = _normalize_voice_command(raw_text)
        logger.info("Transcripción [%.2fs]: '%s' → '%s'", t_stt.elapsed, raw_text, command_text)

        with Timer() as t_exec:
            result = await orchestrator.run(command_text, llm, request_id=request_id, session_id=sid)

        response = {
            "request_id": request_id,
            "transcription": command_text,
            "result": result,
            "latency_stt": t_stt.elapsed,
            "latency_exec": t_exec.elapsed,
        }

        if tts:
            response_text = _extract_response_text(result)
            if response_text:
                tts_result = await text_to_speech(response_text)
                response["tts"] = tts_result

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error en process_audio_command: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/audio/wakeword/upload")
async def upload_wakeword(
    file: UploadFile = File(...),
    session_id: Optional[str] = None,
    tts: bool = True,
):
    """
    Recibe audio, detecta wake word.
    Si hay orden tras la wake word, la ejecuta Y genera TTS con la respuesta.

    FIX v2:
    - Normaliza puntuación del STT antes de enviar al orquestador.
    - Genera TTS con la respuesta y devuelve la ruta del audio.
    - El cliente puede reproducir el audio con GET /audio/file?path=<ruta>.
    """
    from app.main import llm
    from app.tools.audio_tools import text_to_speech

    app_logger.info("POST /audio/wakeword/upload — archivo: %s", file.filename)

    try:
        audio_bytes = await file.read()
        detected = await detect_wake_word_in_audio(audio_bytes)

        if not detected.get("wake_word_detected"):
            return detected

        # ── Wake word detectada ──────────────────────────────────────
        full_text   = detected.get("text", "")
        keyword     = detected.get("keyword", "alfonso").lower()

        # Extraer la orden (lo que viene después del nombre de wake word)
        command_raw  = re.sub(rf"^{re.escape(keyword)}[,\s]*", "", full_text, flags=re.IGNORECASE).strip()
        command_text = _normalize_voice_command(command_raw)

        detected["command_extracted"] = command_text

        if not command_text:
            # Solo se dijo el nombre; responder con saludo
            app_logger.info("Wake word sola detectada, sin orden")
            greeting = "Sí, dime."
            detected["result"] = {"type": "chat", "response": greeting}
            if tts:
                tts_result = await text_to_speech(greeting)
                detected["tts"] = tts_result
            return detected

        # ── Ejecutar orden ───────────────────────────────────────────
        app_logger.info("Orden tras wake word: '%s' → ejecutando '%s'", command_raw, command_text)

        result = await orchestrator.run(
            command_text,
            llm,
            session_id=session_id or str(uuid.uuid4()),
        )
        detected["result"] = result

        # ── TTS con la respuesta ─────────────────────────────────────
        if tts:
            response_text = _extract_response_text(result)
            app_logger.info("TTS para respuesta: '%s'", response_text[:80])
            if response_text:
                tts_result = await text_to_speech(response_text)
                detected["tts"] = tts_result

        return detected

    except Exception as e:
        app_logger.error("Error en upload_wakeword: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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