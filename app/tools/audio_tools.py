"""
Herramientas de audio para Alfonso.

Diseño orientado a servidor:
- TTS: genera audio en el servidor y devuelve la ruta del fichero.
- STT: transcribe audio recibido como bytes (upload del cliente).
- Wake word: detecta la palabra clave en un fragmento de audio subido.

El micrófono local (sounddevice) se mantiene como fallback opcional
para entornos de desarrollo donde el hardware esté disponible.
"""

import asyncio
import os
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Optional

from app.utils.logger import tool_logger, error_logger

SAMPLE_RATE = 16000


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _get_sounddevice_device() -> Optional[int]:
    device_index = os.getenv("AUDIO_DEVICE_INDEX")
    if device_index is None:
        return None
    try:
        return int(device_index)
    except ValueError:
        tool_logger.warning("AUDIO_DEVICE_INDEX=%r inválido; usando dispositivo por defecto", device_index)
        return None


def _write_wav(path: Path, data: bytes, samplerate: int = SAMPLE_RATE) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(data)


def _save_bytes_to_tmp(content: bytes, filename: str = "audio.wav") -> Path:
    suffix = Path(filename).suffix or ".wav"
    path = Path(tempfile.gettempdir()) / f"stt_{uuid.uuid4().hex}{suffix}"
    path.write_bytes(content)
    return path


def _whisper_transcribe(path: Path, model_name: str = "small") -> str:
    try:
        import whisper
    except ImportError:
        raise RuntimeError("whisper no está instalado")

    model = whisper.load_model(model_name)
    result = model.transcribe(str(path), language="es")
    return result.get("text", "").strip()


def _speech_recognition_transcribe_file_sync(path: Path) -> str:
    """Fallback: transcribe con Whisper tiny (offline) en vez de Google."""
    # Usar tiny como fallback es más rápido y no necesita internet
    return _whisper_transcribe(path, model_name="tiny")


# ---------------------------------------------------------------------------
# Grabación local (solo desarrollo / entornos con hardware)
# ---------------------------------------------------------------------------

def _record_audio_local(duration: int = 5) -> Path:
    """
    Graba audio desde el micrófono local.
    Lanza RuntimeError si sounddevice no está disponible o no hay dispositivo.
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError("sounddevice no está disponible")

    path = Path(tempfile.gettempdir()) / f"stt_{uuid.uuid4().hex}.wav"
    tool_logger.info("Grabando audio local durante %s segundos → %s", duration, path)

    device = _get_sounddevice_device()
    kwargs = {"device": device} if device is not None else {}

    recording = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        **kwargs,
    )
    sd.wait()
    _write_wav(path, recording.astype("int16").tobytes())
    return path


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

async def text_to_speech(text: str, voice: Optional[str] = None) -> dict:
    """
    Convierte texto a audio MP3 usando edge-tts.
    Fallback a pyttsx3 si edge-tts no está disponible.
    Devuelve la ruta al fichero generado.
    """
    tool_logger.info("TTS solicitado: %s", text)

    try:
        import edge_tts
    except ImportError:
        tool_logger.warning("edge-tts no disponible, usando pyttsx3")
        return await _tts_pyttsx3(text, voice=voice)

    voice_name = voice or "es-ES-AlvaroNeural"
    output_path = Path(tempfile.gettempdir()) / f"tts_{uuid.uuid4().hex}.mp3"

    try:
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(str(output_path))
        tool_logger.info("TTS generado en %s", output_path)
        return {"status": "ok", "audio_file": str(output_path)}
    except Exception as exc:
        error_logger.exception("Error en edge-tts")
        return {"status": "error", "message": str(exc)}


async def _tts_pyttsx3(text: str, voice: Optional[str] = None) -> dict:
    try:
        import pyttsx3
    except ImportError:
        error_logger.warning("pyttsx3 no disponible")
        return {"status": "error", "message": "No hay backend TTS disponible"}

    try:
        engine = pyttsx3.init()
        if voice:
            for v in engine.getProperty("voices"):
                if voice.lower() in v.name.lower():
                    engine.setProperty("voice", v.id)
                    break
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: engine.say(text) or engine.runAndWait())
        tool_logger.info("TTS completado con pyttsx3")
        return {"status": "ok", "message": "spoken"}
    except Exception as exc:
        error_logger.exception("Error en pyttsx3")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# STT — principal: transcripción de bytes subidos por el cliente
# ---------------------------------------------------------------------------

async def transcribe_audio_bytes(
    content: bytes,
    filename: str = "audio.wav",
    model: str = "small",
) -> dict:
    """
    Transcribe audio recibido como bytes.
    Intenta Whisper primero; si falla, usa SpeechRecognition.
    Este es el método principal para producción (cliente sube el audio).
    """
    tool_logger.info("Transcribiendo audio subido: %s (%d bytes)", filename, len(content))

    try:
        audio_path = _save_bytes_to_tmp(content, filename)
    except Exception as exc:
        error_logger.exception("Error guardando audio subido")
        return {"status": "error", "message": str(exc)}

    # Intentar Whisper
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _whisper_transcribe, audio_path, model)
        tool_logger.info("Transcripción Whisper: %s", text)
        return {"status": "ok", "text": text}
    except Exception as exc:
        tool_logger.warning("Whisper falló (%s), intentando SpeechRecognition", exc)

    # Fallback SpeechRecognition
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _speech_recognition_transcribe_file_sync, audio_path)
        tool_logger.info("Transcripción SpeechRecognition: %s", text)
        return {"status": "ok", "text": text}
    except Exception as exc:
        error_logger.exception("Fallback STT también falló")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# STT — local (solo desarrollo)
# ---------------------------------------------------------------------------

async def speech_to_text(duration: int = 5, model: str = "small") -> dict:
    """
    Graba desde el micrófono local y transcribe.
    Solo para entornos de desarrollo con hardware disponible.
    En producción usa transcribe_audio_bytes + el cliente graba.
    """
    tool_logger.info("STT local solicitado (duration=%s, model=%s)", duration, model)

    try:
        audio_path = _record_audio_local(duration)
    except RuntimeError as exc:
        tool_logger.warning("Grabación local no disponible: %s", exc)
        return {
            "status": "error",
            "message": str(exc),
            "hint": "En producción usa el endpoint /audio/stt/upload para subir el audio desde el cliente.",
        }
    except Exception as exc:
        error_logger.exception("Error inesperado grabando audio local")
        return {"status": "error", "message": str(exc)}

    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _whisper_transcribe, audio_path, model)
        tool_logger.info("STT local resultado: %s", text)
        return {"status": "ok", "text": text}
    except Exception as exc:
        tool_logger.warning("Whisper falló en STT local: %s", exc)
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Wake word — principal: detecta la palabra clave en audio subido
# ---------------------------------------------------------------------------

async def detect_wake_word_in_audio(
    content: bytes,
    filename: str = "audio.wav",
    keyword: str = "alfonso",
    model: str = "small",
) -> dict:
    """
    Detecta si un fragmento de audio subido por el cliente contiene la wake word.

    El cliente graba un chunk de audio, lo sube a este endpoint, y el servidor
    transcribe y busca la palabra clave. Esto es correcto para producción:
    el hardware de audio vive en el cliente, no en el servidor.

    Returns:
        {
            "status": "ok",
            "wake_word_detected": bool,
            "text": str,          # transcripción completa del chunk
            "keyword": str
        }
    """
    tool_logger.info(
        "Detectando wake word '%s' en audio subido: %s (%d bytes)",
        keyword, filename, len(content),
    )

    result = await transcribe_audio_bytes(content, filename=filename, model=model)

    if result.get("status") != "ok":
        return result

    text = result.get("text", "").lower().strip()
    detected = keyword.lower() in text

    tool_logger.info(
        "Wake word '%s' %s en: '%s'",
        keyword,
        "DETECTADA" if detected else "no detectada",
        text,
    )

    return {
        "status": "ok",
        "wake_word_detected": detected,
        "text": text,
        "keyword": keyword,
    }


# ---------------------------------------------------------------------------
# Wake word — local (solo desarrollo, mantiene compatibilidad)
# ---------------------------------------------------------------------------

async def wake_word_listener(
    keyword: str = "alfonso",
    max_duration: int = 30,
    chunk_duration: int = 5,
    model: str = "small",
) -> dict:
    """
    Escucha el micrófono local en bucle buscando la wake word.
    Solo para desarrollo local con hardware disponible.
    En producción usa detect_wake_word_in_audio.
    """
    tool_logger.info("Wake word listener local iniciado (keyword=%s)", keyword)
    elapsed = 0

    while elapsed < max_duration:
        result = await speech_to_text(duration=chunk_duration, model=model)

        if result.get("status") != "ok":
            # En producción esto es esperado: devolvemos info útil en vez de crash
            return {
                "status": "error",
                "message": result.get("message", "STT no disponible"),
                "hint": (
                    "El micrófono local no está disponible. "
                    "Usa POST /audio/wakeword/upload para enviar audio desde el cliente."
                ),
            }

        text = result.get("text", "").lower()
        tool_logger.info("Wake word chunk: '%s'", text)

        if keyword.lower() in text:
            return {"status": "ok", "wake_word_detected": True, "text": text}

        elapsed += chunk_duration

    return {"status": "ok", "wake_word_detected": False, "text": ""}


# ---------------------------------------------------------------------------
# Registro de tools
# ---------------------------------------------------------------------------

TOOLS = {
    "text_to_speech": text_to_speech,
    "speech_to_text": speech_to_text,
    "wake_word_listener": wake_word_listener,
    "transcribe_audio_bytes": transcribe_audio_bytes,
    "detect_wake_word_in_audio": detect_wake_word_in_audio,
}