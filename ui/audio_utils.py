import io
import time
import wave
import numpy as np
import sounddevice as sd
from typing import Optional
from ui.config import SAMPLE_RATE, CHANNELS, SILENCE_THRESHOLD

def _ndarray_to_wav_bytes(data: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data.astype(np.int16).tobytes())
    return buf.getvalue()

def record_chunk(duration: int, device: Optional[int] = None) -> bytes:
    kwargs = {"device": device} if device is not None else {}
    recording = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        **kwargs,
    )
    sd.wait()
    return _ndarray_to_wav_bytes(recording)

def record_raw(duration: float, device: Optional[int] = None) -> np.ndarray:
    kwargs = {"device": device} if device is not None else {}
    recording = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        **kwargs,
    )
    sd.wait()
    return recording

def has_voice(wav_bytes: bytes, threshold: int = SILENCE_THRESHOLD) -> bool:
    buf = io.BytesIO(wav_bytes)
    try:
        with wave.open(buf, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16)
        return int(np.abs(samples).mean()) > threshold
    except Exception:
        return False

def list_input_devices() -> list[dict]:
    devices = sd.query_devices()
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]

def play_audio(path: str) -> None:
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        pygame.mixer.quit()
    except Exception as e:
        print(f"  [audio] Error reproduciendo: {e}")

def get_audio_bytes(audio_buffer: list[np.ndarray]) -> bytes:
    """Convierte una lista de ráfagas NumPy en un WAV válido."""
    if not audio_buffer:
        return b""
    full_audio = np.concatenate(audio_buffer)
    return _ndarray_to_wav_bytes(full_audio)