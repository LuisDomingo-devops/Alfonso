"""
AudioService — soporte correcto para micrófono integrado Realtek/Intel SST.

Cambios clave respecto a la versión original:
- auto_select_device(): detecta el integrado con keywords en inglés Y español
  (necesario para Windows en español: "Varios micrófonos", "Tecnología Intel").
- probe_device_samplerate(): el dispositivo [20] graba a 48000Hz; se detecta
  automáticamente y resample() lo convierte a 16000Hz antes de pasarlo a Whisper.
- _to_int16_scale(): clip previo a la conversión. Sin él valores fuera de [-1,1]
  producen overflow y números de 26 dígitos como los que aparecieron en el diagnóstico.
- record_chunk() loguea errores en lugar de fallar en silencio.
"""

from __future__ import annotations

import io
import logging
import time
import wave
from typing import Optional
import pyttsx3 # Import for local TTS
import edge_tts
import asyncio
from core.config import SILENCE_THRESHOLD
import tempfile
import os

import numpy as np
import sounddevice as sd

logger = logging.getLogger("audio_service")

TARGET_RATE = 16_000    # frecuencia que espera Whisper
CHANNELS    = 1
DTYPE       = "float32" # más compatible que int16 en micros integrados

# ---------------------------------------------------------------------------
# Keywords de detección de dispositivo
# ---------------------------------------------------------------------------

# Integrado — inglés y español (Windows en español renombra los dispositivos)
_INTEGRATED_KEYWORDS = [
    # Inglés
    "realtek", "array", "intel", "sst", "hda", "integrated",
    "internal", "built-in", "builtin", "laptop", "notebook",
    "amic", "dmic",
    # Intel Smart Sound Technology (Acer Swift, Asus, Lenovo…)
    "smart sound", "intel® smart", "tecnología intel",
    # Windows en español: nombre del array de micrófonos Intel SST
    "varios micrófonos",
    # Realtek en español
    "mic input", "micrófono",
]

# Penalizar: periféricos externos, loopback, Steam
_USB_KEYWORDS = [
    "usb", "external", "headset", "gaming", "blue", "yeti", "rode",
    "steam",            # Steam Streaming Microphone — siempre falso positivo
    "mezcla estéreo",   # Stereo Mix / loopback
    "altavoz",          # Altavoz de PC usado como entrada — loopback
    "output with",      # Realtek HD Audio output with S/PDIF
    "speakers",
    "loopback",
]


# ---------------------------------------------------------------------------
# Funciones de utilidad
# ---------------------------------------------------------------------------

def auto_select_device() -> Optional[int]:
    """
    Devuelve el índice del micrófono integrado con mayor puntuación.
    None si no encuentra ninguno (sounddevice usará el predeterminado).
    """
    try:
        devices    = sd.query_devices()
        candidates = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] < 1:
                continue
            name_lower = d["name"].lower()
            score  = sum(1 for kw in _INTEGRATED_KEYWORDS if kw in name_lower)
            score -= sum(3 for kw in _USB_KEYWORDS        if kw in name_lower)
            if score > 0:
                candidates.append((score, i, d["name"]))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        _, best_idx, best_name = candidates[0]
        logger.info("Micrófono integrado detectado: [%d] %s", best_idx, best_name)
        return best_idx

    except Exception as exc:
        logger.warning("Error en auto_select_device: %s", exc)
        return None


# Caché para evitar consultas repetitivas al hardware que pueden causar latencia
_samplerate_cache = {}

def probe_device_samplerate(device_index: Optional[int]) -> int:
    """
    Devuelve el primer samplerate que acepta el dispositivo.
    Prueba 16000, 44100, 48000 en ese orden.
    """
    global _samplerate_cache
    if device_index in _samplerate_cache:
        return _samplerate_cache[device_index]

    for rate in [TARGET_RATE, 44_100, 48_000, 22_050]:
        try:
            sd.check_input_settings(
                device=device_index, samplerate=rate, channels=CHANNELS
            )
            if rate != TARGET_RATE:
                logger.info(
                    "Dispositivo [%s] no acepta %dHz, usando %dHz (se remuestreará)",
                    device_index, TARGET_RATE, rate,
                )
            _samplerate_cache[device_index] = rate
            return rate
        except Exception:
            continue

    logger.warning("Samplerate no determinado para [%s], usando 44100", device_index)
    _samplerate_cache[device_index] = 44_100
    return 44_100


def resample(data: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
    """
    Remuestreo por interpolación lineal: convierte 48000Hz → 16000Hz.
    Para mayor calidad en producción usa scipy.signal.resample o librosa.
    """
    if orig_rate == target_rate:
        return data
    n_target = int(len(data) * target_rate / orig_rate)
    resampled = np.interp(
        np.linspace(0, len(data) - 1, n_target),
        np.arange(len(data)),
        data.flatten(),
    )
    return resampled.reshape(-1, 1)


def _to_int16_scale(data: np.ndarray) -> np.ndarray:
    """
    float32 [-1.0, 1.0] → escala int16 [0, 32767].
    El np.clip es obligatorio: sin él, valores fuera de rango producen overflow
    (los números de 26 dígitos que aparecieron en el primer diagnóstico).
    """
    return np.abs(np.clip(data.flatten(), -1.0, 1.0)) * 32767


def ndarray_to_wav_bytes(data: np.ndarray, samplerate: int = TARGET_RATE) -> bytes:
    """Convierte array float32 o int16 a bytes WAV mono 16-bit."""
    if data.dtype != np.int16:
        data_i16 = np.clip(data.flatten() * 32767, -32768, 32767).astype(np.int16)
    else:
        data_i16 = data.flatten()

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(data_i16.tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class AudioService:
    """
    Servicio de audio del cliente Alfonso.

    Ejemplo:
        svc = AudioService()           # auto-detecta el integrado
        wav = svc.record_chunk(3)      # 3 segundos → bytes WAV 16kHz
        if svc.has_voice(wav, 125):
            api.stt(wav)
    """

    def __init__(self, device: Optional[int] = None, auto_detect: bool = True):
        logger.info("Inicializando AudioService…")
        if device is None and auto_detect:
            device = auto_select_device()

        self.device       = device
        self._native_rate = probe_device_samplerate(device)

        name = "predeterminado del sistema"
        if device is not None:
            try:
                name = sd.query_devices(device)["name"]
            except Exception:
                pass
        logger.info(
            "AudioService listo -> [%s] '%s' @ %dHz (target %dHz)",
            device, name, self._native_rate, TARGET_RATE,
        )
        self._tts_engine = None # Initialize pyttsx3 engine lazily

    def _init_tts_engine(self):
        """Initializes the pyttsx3 engine if not already initialized."""
        if self._tts_engine is None:
            try:
                self._tts_engine = pyttsx3.init()
                # Optional: Set properties like voice, rate, volume
                # voices = self._tts_engine.getProperty('voices')
                # self._tts_engine.setProperty('voice', voices[0].id)
                # self._tts_engine.setProperty('rate', 150)
            except Exception as e:
                logger.error(f"Error initializing pyttsx3 engine: {e}")
                self._tts_engine = None

    # ------------------------------------------------------------------
    # Listado de dispositivos
    # ------------------------------------------------------------------

    def list_input_devices(self) -> list:
        logger.info("Listando dispositivos de entrada (micrófonos)…")
        return [
            {
                "index": i,
                "name": d["name"],
                "channels": d["max_input_channels"],
                "default_samplerate": int(d["default_samplerate"]),
            }
            for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0
        ]

    def list_output_devices(self) -> list:
        logger.info("Listando dispositivos de salida (altavoces)…")
        return [
            {
                "index": i,
                "name": d["name"],
                "channels": d["max_output_channels"],
                "default_samplerate": int(d["default_samplerate"]),
            }
            for i, d in enumerate(sd.query_devices())
            if d["max_output_channels"] > 0
        ]

    # ------------------------------------------------------------------
    # Grabación
    # ------------------------------------------------------------------

    def record_raw(self, duration: float, device: Optional[int] = None) -> np.ndarray:
        logger.debug(f"Grabando {duration} segundos de audio desde dispositivo [{device}]…")
        """
        Graba `duration` segundos y devuelve array float32 mono a TARGET_RATE.
        Si el dispositivo graba a otro samplerate lo remuestrea automáticamente.
        Lanza excepción en caso de error (no silencio silencioso).
        """
        dev  = device if device is not None else self.device
        rate = probe_device_samplerate(dev) if device is not None else self._native_rate

        time.sleep(0.05)  # margen para que WASAPI inicialice el stream

        try:
            recording = sd.rec(
                int(duration * rate),
                samplerate=rate,
                channels=CHANNELS,
                dtype=DTYPE,
                device=dev,
            )
            sd.wait()
        except Exception as exc:
            logger.error("Error grabando [device=%s, rate=%d]: %s", dev, rate, exc)
            raise

        if rate != TARGET_RATE:
            recording = resample(recording, rate, TARGET_RATE)

        # Verificación de "Silencio absoluto" (problema de drivers o permisos)
        if np.max(np.abs(recording)) < 1e-6:
            logger.warning("¡ATENCIÓN! El dispositivo [%s] ha devuelto silencio absoluto. Revisa los permisos de Windows o si el micro está muteado físicamente.", dev)

        return recording

    def record_chunk(self, duration: int, device: Optional[int] = None) -> bytes:
        """
        Graba `duration` segundos y devuelve bytes WAV 16kHz mono.
        En caso de error devuelve silencio y loguea el problema.
        """
        print(f"Grabando chunk de {duration} segundos…", end=" ", flush=True)
        try:
            raw = self.record_raw(float(duration), device=device)
            return ndarray_to_wav_bytes(raw, TARGET_RATE)
        except Exception as exc:
            logger.error("record_chunk falló: %s — devolviendo silencio", exc)
            silence = np.zeros((int(duration * TARGET_RATE), 1), dtype=DTYPE)
            return ndarray_to_wav_bytes(silence, TARGET_RATE)

    def get_audio_bytes(self, audio_buffer: list) -> bytes:
        logger.debug("Concatenando buffers de audio y convirtiendo a bytes WAV…")
        """Concatena lista de arrays grabados con record_raw y devuelve WAV."""
        if not audio_buffer:
            return b""
        full = np.concatenate(audio_buffer)
        return ndarray_to_wav_bytes(full, TARGET_RATE)

    # ------------------------------------------------------------------
    # Reproducción
    # ------------------------------------------------------------------

    def play_audio(self, wav_bytes: bytes, device: Optional[int] = None) -> None:
        logger.debug("Reproduciendo audio…")
        try:
            buf = io.BytesIO(wav_bytes)
            with wave.open(buf, "rb") as wf:
                fs   = wf.getframerate()
                raw  = wf.readframes(wf.getnframes())
                data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
            sd.play(data, fs, device=device)
            sd.wait()
        except Exception as exc:
            logger.error("Error reproduciendo audio: %s", exc)

    async def text_to_speech_human(self, text: str) -> Optional[str]:
        """
        Genera audio con voces neuronales humanas usando edge-tts.
        Devuelve la ruta al archivo temporal generado.
        """
        try:
            # Usamos una voz masculina española muy natural (Alvaro)
            # Para femenina podrías usar "es-ES-ElviraNeural"
            voice = "es-ES-AlvaroNeural"
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_path = temp_file.name
            temp_file.close()

            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(temp_path)
            
            logger.info(f"Audio humano generado exitosamente en {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"Error generando voz humana (edge-tts): {e}")
            return None

    def text_to_wav_bytes(self, text: str) -> bytes:
        """
        Convierte texto a bytes WAV usando pyttsx3.
        Requiere: pip install pyttsx3
        """
        self._init_tts_engine()
        if self._tts_engine is None:
            logger.error("pyttsx3 engine not initialized. Cannot perform TTS.")
            return b""

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        temp_file.close()
        temp_path = temp_file.name

        try:
            self._tts_engine.save_to_file(text, temp_path)
            self._tts_engine.runAndWait()

            with open(temp_path, "rb") as f:
                wav_bytes = f.read()
            return wav_bytes
        except Exception as e:
            logger.error("Error reproduciendo audio: %s", exc)

    def calibrate_threshold(self, device: Optional[int], seconds: float = 2.0) -> int:
        """
        Graba `seconds` segundos de silencio ambiente y calcula el umbral.
        Devuelve max(nivel_ambiente * 3, 80) para tener margen.
        """
        logger.info("Calibrando umbral de silencio (no hables)...")
        try:
            raw  = self.record_raw(seconds, device=device)
            # Convertir a int16 para usar la misma escala que has_voice
            amp_i16 = int(_to_int16_scale(raw).mean())
            threshold = max(amp_i16 * 3, 80)
            logger.info(f"Calibración OK → umbral={threshold}")
            return threshold
        except Exception as exc:
            logger.error(f"ERROR calibrando umbral ({exc}), usando umbral por defecto {SILENCE_THRESHOLD}")
            return SILENCE_THRESHOLD

    def play_audio_file(self, path: str) -> None:
        print(f"Reproduciendo fichero de audio: {path}")
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            pygame.mixer.quit()
        except Exception as exc:
            logger.error("Error reproduciendo fichero: %s", exc)

    # ------------------------------------------------------------------
    # Detección de voz
    # ------------------------------------------------------------------

    @staticmethod
    def get_level(wav_bytes: bytes) -> int: # Changed to staticmethod
        logger.debug("Calculando nivel de audio…")
        """Nivel pico en escala 0-32767."""
        buf = io.BytesIO(wav_bytes)
        try:
            with wave.open(buf, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16)
            return int(np.abs(samples).max()) if samples.size else 0
        except Exception:
            return 0

    @staticmethod
    def has_voice(wav_bytes: bytes, threshold: int) -> bool:
        """True si el nivel medio supera el umbral (escala int16 0-32767)."""
        buf = io.BytesIO(wav_bytes)
        try:
            with wave.open(buf, "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            samples = np.frombuffer(raw, dtype=np.int16)
            level   = int(np.abs(samples).mean())
            
            # Feedback visual para que el usuario sepa si el micro está llegando al nivel
            # Mostramos el estado actual para diagnosticar si el ruido ambiente es muy alto
            if level > 5:
                 status = "VOZ" if level > threshold else "RUIDO"
                 # Limpiamos con espacios al final para evitar restos visuales en consola
                 print(f" [Audio] Nivel: {level:4d} | Umbral: {threshold:3d} | Estado: {status}    ", end="\r")

            return level > threshold
        except Exception:
            return False

    def transcribe_local(self, wav_bytes: bytes) -> str:
        """
        Realiza la transcripción de audio a texto localmente para evitar 404 en el servidor.
        Requiere: pip install SpeechRecognition
        """
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            
            # Escribir bytes a un archivo temporal que sr pueda leer
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(wav_bytes)
                tmp_path = tmp.name
            
            try:
                with sr.AudioFile(tmp_path) as source:
                    audio = r.record(source)
                # Usamos el motor de Google (gratis, requiere internet pero no modelos locales pesados)
                text = r.recognize_google(audio, language="es-ES")
                return text.strip()
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                    
        except ImportError:
            logger.error("Librería 'speech_recognition' no encontrada. Ejecuta: pip install SpeechRecognition")
            return ""
        except Exception as e:
            logger.debug(f"STT local no detectó palabras: {e}")
            return ""