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

    def list_output_devices(self) -> list:
        devices = sd.query_devices()
        return [
            {"index": i, "name": d["name"], "channels": d["max_output_channels"]}
            for i, d in enumerate(devices)
            if d["max_output_channels"] > 0
        ]

    def record_chunk(self, duration: int, device: Optional[int] = None) -> bytes:
        kwargs = {"device": device} if device is not None else {}
        try:
            # Pequeña pausa para estabilizar el driver en Windows (evita el error -9999)
            time.sleep(0.1)
            recording = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                **kwargs,
            )
            sd.wait()
        except Exception as e:
            print(f"[!] Error de hardware de audio: {e}")
            # Devolvemos un buffer de silencio para no romper el flujo del programa
            recording = np.zeros((int(duration * self.sample_rate), self.channels), dtype="int16")
            
        return self._ndarray_to_wav_bytes(recording)

    def record_raw(self, duration: float, device: Optional[int] = None) -> np.ndarray:
        """Graba un fragmento de audio y lo devuelve como un array NumPy."""
        kwargs = {"device": device} if device is not None else {}
        recording = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            **kwargs,
        )
        try:
            sd.wait()
        except Exception:
            # Si falla el wait por error de driver, devolvemos silencio
            return np.zeros((int(duration * self.sample_rate), self.channels), dtype="int16")
            
        return recording

    def _ndarray_to_wav_bytes(self, data: np.ndarray) -> bytes:
        """Convierte un array NumPy de audio a bytes WAV."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(data.astype(np.int16).tobytes())
        return buf.getvalue()

    def get_audio_bytes(self, audio_buffer: list[np.ndarray]) -> bytes:
        """Convierte una lista de ráfagas NumPy en un WAV válido."""
        if not audio_buffer:
            return b""
        full_audio = np.concatenate(audio_buffer)
        return self._ndarray_to_wav_bytes(full_audio)

    def play_audio(self, wav_bytes: bytes, device: Optional[int] = None) -> None:
        try:
            buf = io.BytesIO(wav_bytes)
            with wave.open(buf, "rb") as wf:
                fs = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
                samples = np.frombuffer(raw, dtype=np.int16)
                sd.play(samples, fs, device=device)
                sd.wait()
        except Exception as e:
            print(f"Error en reproducción: {e}")

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
    def get_level(wav_bytes: bytes) -> int:
        """Calcula el nivel de pico (peak) del audio en bytes."""
        buf = io.BytesIO(wav_bytes)
        try:
            with wave.open(buf, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16)
            if samples.size == 0: return 0
            return int(np.abs(samples).max())
        except Exception:
            return 0

    @staticmethod
    def has_voice(wav_bytes: bytes, threshold: int) -> bool:
        buf = io.BytesIO(wav_bytes)
        try:
            with wave.open(buf, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16)
            current_vol = int(np.abs(samples).mean())
            if current_vol > 50: # Solo loguear si hay algo de ruido mínimo
                print(f"[AUDIO] Nivel detectado: {current_vol} (Umbral: {threshold})")
            return current_vol > threshold
        except Exception:
            return False