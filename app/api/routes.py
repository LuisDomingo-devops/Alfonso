import uuid

from fastapi import APIRouter, Request, UploadFile, File, WebSocket, WebSocketDisconnect, Form
from typing import Optional

from app.schemas.chat import ChatRequest
from app.schemas.audio import (
    TTSRequest,
    STTRequest,
    WakeWordRequest,
    WakeWordUploadRequest,
    VoiceConversationRequest,
)
from app.core.llm_client import OllamaClient
from app.core.orchestrator import Orchestrator
from app.core.metrics import increment_websocket_connections, increment_websocket_messages, snapshot as snapshot_metrics
from app.core.tool_registry import get_tool, list_tools
from app.utils.logger import app_logger, attach_request_id, LOG_DIR
from app.utils.timer import Timer

router = APIRouter()

llm = OllamaClient()
orchestrator = Orchestrator()


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    session_id = request.headers.get("X-Session-ID") or request_id
    logger = attach_request_id(app_logger, request_id)

    logger.info("Solicitud /chat recibida")
    logger.info("SESSION_ID: %s", session_id)
    logger.info("USER MESSAGE: %s", req.message)

    with Timer() as t:
        result = await orchestrator.run(req.message, llm, request_id=request_id, session_id=session_id)

    logger.info("Solicitud /chat procesada con estado: %s", result.get("type"))
    logger.info("LATENCY: %.2fs", t.elapsed)

    return {
        "status": "success",
        "request_id": request_id,
        "session_id": session_id,
        "result": result,
        "latency_seconds": t.elapsed,
    }


@router.get("/chat")
async def chat_get():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Health / Metrics / Tools
# ---------------------------------------------------------------------------

@router.get("/health")
async def health(request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info("Health check")
    return {
        "status": "ok",
        "request_id": request_id,
        "logs_path": str(LOG_DIR),
    }


@router.get("/metrics")
async def metrics(request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info("Metrics requested")
    return {
        "status": "ok",
        "request_id": request_id,
        "metrics": snapshot_metrics(),
    }


@router.get("/tools")
async def tools(request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info("Tools requested")
    return {
        "status": "ok",
        "request_id": request_id,
        "tools": list_tools(),
    }


# ---------------------------------------------------------------------------
# Audio — TTS
# ---------------------------------------------------------------------------

@router.post("/audio/tts")
async def audio_tts(req: TTSRequest, request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info("Solicitud /audio/tts recibida")

    tool = get_tool("text_to_speech")
    if not tool:
        return {"status": "error", "request_id": request_id, "message": "Tool TTS no disponible"}

    with Timer() as t:
        result = await tool(req.text, voice=req.voice)

    logger.info("Solicitud /audio/tts procesada")
    return {"status": "success", "request_id": request_id, "result": result, "latency_seconds": t.elapsed}


# ---------------------------------------------------------------------------
# Audio — STT local (desarrollo)
# ---------------------------------------------------------------------------

@router.post("/audio/stt")
async def audio_stt(req: STTRequest, request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info("Solicitud /audio/stt recibida")

    tool = get_tool("speech_to_text")
    if not tool:
        return {"status": "error", "request_id": request_id, "message": "Tool STT no disponible"}

    with Timer() as t:
        result = await tool(duration=req.duration)

    logger.info("Solicitud /audio/stt procesada")
    return {"status": "success", "request_id": request_id, "result": result, "latency_seconds": t.elapsed}


# ---------------------------------------------------------------------------
# Audio — STT upload (producción)
# ---------------------------------------------------------------------------

@router.post("/audio/stt/upload")
async def audio_stt_upload(
    request: Request,
    file: UploadFile = File(...),
    model: str = "small",
):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info("Solicitud /audio/stt/upload recibida: %s", file.filename)

    tool = get_tool("transcribe_audio_bytes")
    if not tool:
        return {"status": "error", "request_id": request_id, "message": "Tool de transcripción no disponible"}

    content = await file.read()
    with Timer() as t:
        result = await tool(content=content, filename=file.filename, model=model)

    logger.info("Solicitud /audio/stt/upload procesada")
    return {"status": "success", "request_id": request_id, "result": result, "latency_seconds": t.elapsed}


# ---------------------------------------------------------------------------
# Audio — Wake word local (desarrollo)
# ---------------------------------------------------------------------------

@router.post("/audio/wakeword")
async def audio_wakeword(req: WakeWordRequest, request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info("Solicitud /audio/wakeword recibida")

    tool = get_tool("wake_word_listener")
    if not tool:
        return {"status": "error", "request_id": request_id, "message": "Tool wake word no disponible"}

    with Timer() as t:
        result = await tool(
            keyword=req.keyword,
            max_duration=req.max_duration,
            chunk_duration=req.chunk_duration,
            model=req.model or "small",
        )

    logger.info("Solicitud /audio/wakeword procesada")
    return {"status": "success", "request_id": request_id, "result": result, "latency_seconds": t.elapsed}


# ---------------------------------------------------------------------------
# Audio — Wake word upload (producción) ← NUEVO
# ---------------------------------------------------------------------------

@router.post("/audio/wakeword/upload")
async def audio_wakeword_upload(
    request: Request,
    file: UploadFile = File(...),
    keyword: str = Form(default="alfonso"),
    model: str = Form(default="small"),
):
    """
    Detecta la wake word en un fragmento de audio subido por el cliente.

    Flujo de producción:
      1. El cliente graba un chunk de audio (ej. 3-5 segundos).
      2. El cliente sube el fichero WAV/MP3 a este endpoint.
      3. El servidor transcribe y busca la palabra clave.
      4. Si wake_word_detected=true, el cliente sube el siguiente audio a /audio/stt/upload.

    Este diseño mantiene el hardware de audio en el cliente y la lógica en el servidor.
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger = attach_request_id(app_logger, request_id)
    logger.info(
        "Solicitud /audio/wakeword/upload recibida: %s (keyword=%s)",
        file.filename, keyword,
    )

    tool = get_tool("detect_wake_word_in_audio")
    if not tool:
        return {"status": "error", "request_id": request_id, "message": "Tool de wake word no disponible"}

    content = await file.read()
    with Timer() as t:
        result = await tool(content=content, filename=file.filename, keyword=keyword, model=model)

    logger.info(
        "Solicitud /audio/wakeword/upload procesada — detectada: %s",
        result.get("wake_word_detected"),
    )
    return {"status": "success", "request_id": request_id, "result": result, "latency_seconds": t.elapsed}


# ---------------------------------------------------------------------------
# Audio — Conversación completa (producción, todo por upload)
# ---------------------------------------------------------------------------

@router.post("/audio/converse")
async def audio_converse(req: VoiceConversationRequest, request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    session_id = req.session_id or request_id
    logger = attach_request_id(app_logger, request_id)
    logger.info("Solicitud /audio/converse recibida")

    wake_result = None

    with Timer() as total_timer:
        if req.wakeword_enabled:
            wake_tool = get_tool("wake_word_listener")
            if not wake_tool:
                return {"status": "error", "request_id": request_id, "message": "Tool wake word no disponible"}

            wake_result = await wake_tool(
                keyword=req.keyword or "alfonso",
                max_duration=req.max_duration,
                chunk_duration=req.chunk_duration,
                model=req.stt_model or "small",
            )

            if wake_result.get("status") != "ok":
                return {
                    "status": "error",
                    "request_id": request_id,
                    "message": wake_result.get("message", "Error en wake word"),
                    "hint": "Usa /audio/wakeword/upload + /audio/stt/upload para flujo basado en cliente.",
                    "wake_result": wake_result,
                }

            if not wake_result.get("wake_word_detected"):
                return {
                    "status": "success",
                    "request_id": request_id,
                    "message": "Wake word no detectada",
                    "wake_result": wake_result,
                }

            logger.info("Wake word detectada: %s", wake_result.get("text", ""))

        stt_tool = get_tool("speech_to_text")
        if not stt_tool:
            return {"status": "error", "request_id": request_id, "message": "Tool STT no disponible"}

        stt_result = await stt_tool(duration=req.stt_duration, model=req.stt_model or "small")

        if stt_result.get("status") != "ok":
            return {"status": "error", "request_id": request_id, "message": "STT error", "stt_result": stt_result}

        user_text = stt_result.get("text", "").strip()
        if not user_text:
            return {"status": "error", "request_id": request_id, "message": "No se detectó texto", "stt_result": stt_result}

        conversation_result = await orchestrator.run(user_text, llm, request_id=request_id, session_id=session_id)
        response_text = (
            conversation_result.get("response", "")
            if conversation_result.get("type") == "chat"
            else str(conversation_result)
        )

        tts_tool = get_tool("text_to_speech")
        if not tts_tool:
            return {
                "status": "error",
                "request_id": request_id,
                "message": "Tool TTS no disponible",
                "conversation_result": conversation_result,
            }

        tts_result = await tts_tool(response_text, voice=req.voice)

    return {
        "status": "success",
        "request_id": request_id,
        "session_id": session_id,
        "wake_result": wake_result,
        "stt_result": stt_result,
        "conversation_result": conversation_result,
        "tts_result": tts_result,
        "latency_seconds": total_timer.elapsed,
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    request_id = str(uuid.uuid4())
    logger = attach_request_id(app_logger, request_id)
    increment_websocket_connections()

    try:
        while True:
            message = await websocket.receive_text()
            logger.info("WS message received: %s", message)
            increment_websocket_messages()
            await websocket.send_text(f"Echo: {message}")
    except WebSocketDisconnect:
        logger.info("WS disconnected")
    except Exception:
        logger.exception("WS error")
        await websocket.close(code=1011)