import io
import wave
import time
import numpy as np
import sounddevice as sd
from typing import Optional

class AudioService:
    """Encargado de la grabación y reproducción de audio local."""
    
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

    def list_input_devices(self) -> list:
        devices = sd.query_devices()
        return [
            {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
            for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        ]

    def record_chunk(self, duration: int, device: Optional[int] = None) -> bytes:
        kwargs = {"device": device} if device is not None else {}
        recording = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            **kwargs,
        )
        sd.wait()
        return self._ndarray_to_wav_bytes(recording)

    def _ndarray_to_wav_bytes(self, data: np.ndarray) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(data.astype(np.int16).tobytes())
        return buf.getvalue()

    def play_audio_file(self, path: str) -> None:
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            pygame.mixer.quit()
        except Exception as e:
            print(f"Error en reproducción: {e}")

    @staticmethod
    def has_voice(wav_bytes: bytes, threshold: int) -> bool:
        buf = io.BytesIO(wav_bytes)
        try:
            with wave.open(buf, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16)
            return int(np.abs(samples).mean()) > threshold
        except Exception:
            return False