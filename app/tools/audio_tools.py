import asyncio
import os
import tempfile
import uuid
import wave
from pathlib import Path
from typing import Optional
from app.utils.logger import tool_logger, error_logger

SAMPLE_RATE = 16000


def _write_wav(path: Path, data, samplerate: int = SAMPLE_RATE):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(data)


def _get_sounddevice_device() -> Optional[int]:
    device_index = os.getenv("AUDIO_DEVICE_INDEX")
    if device_index is None:
        return None

    try:
        return int(device_index)
    except ValueError:
        tool_logger.warning("Invalid AUDIO_DEVICE_INDEX=%r; using default device", device_index)
        return None


def _record_audio(duration: int = 5) -> Path:
    try:
        import sounddevice as sd
    except Exception:
        raise RuntimeError("sounddevice not available")

    path = Path(tempfile.gettempdir()) / f"stt_{uuid.uuid4().hex}.wav"
    tool_logger.info("Recording audio for %s seconds to %s", duration, path)

    device = _get_sounddevice_device()
    kwargs = {}
    if device is not None:
        kwargs["device"] = device

    recording = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16", **kwargs)
    sd.wait()
    audio_data = recording.astype("int16").tobytes()
    _write_wav(path, audio_data)
    return path


def _whisper_transcribe(path: Path, model_name: str = "small") -> str:
    try:
        import whisper
    except Exception:
        raise RuntimeError("whisper not available")

    model = whisper.load_model(model_name)
    result = model.transcribe(str(path), language="es")
    return result.get("text", "").strip()


def _save_audio_bytes(content: bytes, filename: str = "audio.wav") -> Path:
    suffix = Path(filename).suffix or ".wav"
    path = Path(tempfile.gettempdir()) / f"stt_upload_{uuid.uuid4().hex}{suffix}"
    path.write_bytes(content)
    return path


async def transcribe_audio_bytes(content: bytes, filename: str = "audio.wav", model: str = "small"):
    tool_logger.info("Transcribing uploaded audio: %s", filename)

    try:
        audio_path = _save_audio_bytes(content, filename)
    except Exception as exc:
        error_logger.exception("Error saving uploaded audio")
        return {"status": "error", "message": str(exc)}

    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _whisper_transcribe, audio_path, model)
        tool_logger.info("Uploaded audio transcribed: %s", text)
        return {"status": "ok", "text": text}
    except Exception as exc:
        tool_logger.warning("Whisper transcription failed for uploaded audio: %s", exc)
        return await _speech_recognition_transcribe_file(audio_path)


async def _speech_recognition_transcribe_file(path: Path):
    try:
        import speech_recognition as sr
    except Exception:
        error_logger.warning("speech_recognition no disponible para STT fallback")
        return {"status": "error", "message": "STT backend not available"}

    recognizer = sr.Recognizer()

    try:
        with sr.AudioFile(str(path)) as source:
            audio = recognizer.record(source)

        text = recognizer.recognize_google(audio, language="es-ES")
        tool_logger.info("STT result from speech_recognition file: %s", text)
        return {"status": "ok", "text": text}
    except Exception as exc:
        error_logger.exception("STT fallback error on uploaded file")
        return {"status": "error", "message": str(exc)}


async def text_to_speech(text: str, voice: Optional[str] = None):
    tool_logger.info("TTS requested: %s", text)

    try:
        import edge_tts
    except Exception:
        tool_logger.info("edge-tts not disponible, fallback a pyttsx3")
        return await _pyttsx3_speak(text, voice=voice)

    voice_name = voice or "es-ES-AlvaroNeural"
    output_path = Path(tempfile.gettempdir()) / f"tts_{uuid.uuid4().hex}.mp3"

    try:
        communicate = edge_tts.Communicate(text, voice_name)
        await communicate.save(str(output_path))
        tool_logger.info("TTS generado en %s", output_path)
        return {"status": "ok", "audio_file": str(output_path)}
    except Exception as exc:
        error_logger.exception("Edge TTS error")
        return {"status": "error", "message": str(exc)}


async def _pyttsx3_speak(text: str, voice: Optional[str] = None):
    try:
        import pyttsx3
    except Exception:
        error_logger.warning("pyttsx3 no disponible para TTS fallback")
        return {"status": "error", "message": "TTS backend not available"}

    try:
        engine = pyttsx3.init()
        if voice:
            for v in engine.getProperty("voices"):
                if voice.lower() in v.name.lower():
                    engine.setProperty("voice", v.id)
                    break

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: engine.say(text) or engine.runAndWait())
        tool_logger.info("TTS completed with pyttsx3")
        return {"status": "ok", "message": "spoken"}
    except Exception as exc:
        error_logger.exception("TTS error")
        return {"status": "error", "message": str(exc)}


async def speech_to_text(duration: int = 5, model: str = "small"):
    tool_logger.info("STT requested duration=%s model=%s", duration, model)

    try:
        audio_path = _record_audio(duration)
    except Exception as exc:
        tool_logger.warning("Falling back to SpeechRecognition due to audio capture error: %s", exc)
        return await _speech_recognition_transcribe(duration)

    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _whisper_transcribe, audio_path, model)
        tool_logger.info("STT result: %s", text)
        return {"status": "ok", "text": text}
    except Exception as exc:
        tool_logger.warning("Whisper transcription failed: %s", exc)
        return await _speech_recognition_transcribe(duration)


async def _speech_recognition_transcribe(duration: int = 5):
    try:
        import speech_recognition as sr
    except Exception:
        error_logger.warning("speech_recognition no disponible para STT fallback")
        return {"status": "error", "message": "STT backend not available"}

    recognizer = sr.Recognizer()

    try:
        device_index = _get_sounddevice_device()
        with sr.Microphone(device_index=device_index) as source:
            recognizer.adjust_for_ambient_noise(source)
            audio = recognizer.listen(source, timeout=duration)

        text = recognizer.recognize_google(audio, language="es-ES")
        tool_logger.info("STT result from speech_recognition: %s", text)
        return {"status": "ok", "text": text}
    except Exception as exc:
        error_logger.exception("STT fallback error")
        return {"status": "error", "message": str(exc)}


async def wake_word_listener(keyword: str = "alfonso", max_duration: int = 30, chunk_duration: int = 5, model: str = "small"):
    tool_logger.info("Wake word listener started for keyword=%s", keyword)
    elapsed = 0

    while elapsed < max_duration:
        result = await speech_to_text(duration=chunk_duration, model=model)
        if result.get("status") != "ok":
            return result

        text = result.get("text", "").lower()
        tool_logger.info("Wake word chunk transcript: %s", text)
        if keyword.lower() in text:
            return {"status": "ok", "wake_word_detected": True, "text": text}

        elapsed += chunk_duration

    return {"status": "ok", "wake_word_detected": False, "text": ""}


TOOLS = {
    "text_to_speech": text_to_speech,
    "speech_to_text": speech_to_text,
    "wake_word_listener": wake_word_listener,
    "transcribe_audio_bytes": transcribe_audio_bytes,
}
