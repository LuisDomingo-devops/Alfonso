"""
Cliente de voz para Alfonso — corre en Windows.

Flujo completo:
  1. Escucha el micrófono en chunks buscando la wake word "alfonso"
  2. Al detectarla, graba la orden del usuario
  3. Sube el audio al servidor (WSL) para transcripción
  4. Recibe la respuesta de texto
  5. Convierte la respuesta a audio (TTS en el servidor)
  6. Descarga y reproduce el MP3

Requisitos (instalar en Python de Windows):
    pip install sounddevice soundfile requests pygame numpy

Uso:
    python cliente_voz.py
    python cliente_voz.py --url http://localhost:8000   # URL del servidor
    python cliente_voz.py --keyword jarvis              # otra wake word
    python cliente_voz.py --debug                       # más logs
"""

import argparse
import io
import sys
import tempfile
import time
import uuid
import wave
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Verificar dependencias antes de importar
# ---------------------------------------------------------------------------
MISSING = []
for pkg in ["sounddevice", "numpy", "requests"]:
    try:
        __import__(pkg)
    except ImportError:
        MISSING.append(pkg)

if MISSING:
    print(f"[ERROR] Faltan dependencias: {', '.join(MISSING)}")
    print(f"        Instálalas con: pip install {' '.join(MISSING)} pygame soundfile")
    sys.exit(1)

import numpy as np
import requests
import sounddevice as sd

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DEFAULT_SERVER = "http://localhost:8000"
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
CHUNK_SECONDS = 3       # segundos por chunk de escucha de wake word
ORDER_SECONDS = 5       # segundos de grabación tras detectar la wake word
SILENCE_THRESHOLD = 500 # amplitud mínima para considerar que hay voz


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def list_input_devices() -> list:
    devices = sd.query_devices()
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]


def record_chunk(duration: int, device: Optional[int] = None) -> bytes:
    """Graba `duration` segundos y devuelve bytes WAV."""
    kwargs = {"device": device} if device is not None else {}
    recording = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        **kwargs,
    )
    sd.wait()
    return _ndarray_to_wav_bytes(recording)


def _ndarray_to_wav_bytes(data: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16 = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(data.astype(np.int16).tobytes())
    return buf.getvalue()


def has_voice(wav_bytes: bytes, threshold: int = SILENCE_THRESHOLD) -> bool:
    """Devuelve True si el audio tiene energía suficiente (no es silencio)."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16)
    return int(np.abs(samples).mean()) > threshold


def play_audio_file(path: str) -> None:
    """Reproduce un fichero de audio MP3/WAV."""
    try:
        import pygame
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        pygame.mixer.quit()
        return
    except ImportError:
        pass

    # Fallback: playsound o simplemente avisar
    try:
        import playsound
        playsound.playsound(path)
        return
    except ImportError:
        pass

    print(f"  [AUDIO] Respuesta guardada en: {path}")
    print("  [AUDIO] Instala pygame para reproducción automática: pip install pygame")


# ---------------------------------------------------------------------------
# Comunicación con el servidor
# ---------------------------------------------------------------------------

def ping_server(url: str) -> bool:
    try:
        r = requests.get(f"{url}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def detect_wake_word(url: str, wav_bytes: bytes, keyword: str, model: str = "small") -> dict:
    """Sube un chunk de audio y pregunta al servidor si contiene la wake word."""
    try:
        r = requests.post(
            f"{url}/audio/wakeword/upload",
            files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
            data={"keyword": keyword, "model": model},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"status": "error", "message": str(e)}


def transcribe_audio(url: str, wav_bytes: bytes, model: str = "small") -> dict:
    """Sube audio y obtiene la transcripción."""
    try:
        r = requests.post(
            f"{url}/audio/stt/upload",
            files={"file": ("orden.wav", wav_bytes, "audio/wav")},
            params={"model": model},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"status": "error", "message": str(e)}


def send_chat(url: str, message: str, session_id: str) -> dict:
    """Envía un mensaje de texto al chat y obtiene la respuesta."""
    try:
        r = requests.post(
            f"{url}/chat",
            json={"message": message},
            headers={"X-Session-ID": session_id},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        return {"status": "error", "message": str(e)}


def get_tts(url: str, text: str, voice: Optional[str] = None) -> Optional[str]:
    """
    Pide al servidor que convierta texto a audio.
    Descarga el fichero MP3 y devuelve la ruta local temporal.
    """
    try:
        payload = {"text": text}
        if voice:
            payload["voice"] = voice
        r = requests.post(f"{url}/audio/tts", json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()

        audio_file = data.get("result", {}).get("audio_file")
        if not audio_file:
            return None

        # Descargar el fichero desde el servidor
        file_r = requests.get(
            f"{url}/audio/file",
            params={"path": audio_file},
            timeout=10,
        )
        if file_r.status_code == 200:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(file_r.content)
            tmp.close()
            return tmp.name

        # Si no hay endpoint de descarga, intentar leer el fichero directamente
        # (solo funciona si cliente y servidor están en el mismo equipo)
        if Path(audio_file).exists():
            return audio_file

        return None

    except Exception as e:
        print(f"  [TTS] Error obteniendo audio: {e}")
        return None


# ---------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------

def run(
    server_url: str,
    keyword: str,
    voice: Optional[str],
    device: Optional[int],
    model: str,
    debug: bool,
) -> None:

    session_id = str(uuid.uuid4())
    print(f"\n{'='*55}")
    print(f"  Alfonso — Cliente de Voz")
    print(f"  Servidor : {server_url}")
    print(f"  Wake word: '{keyword}'")
    print(f"  Sesión   : {session_id[:8]}...")
    print(f"{'='*55}\n")

    # Verificar servidor
    print("Conectando con el servidor...", end=" ", flush=True)
    if not ping_server(server_url):
        print("ERROR")
        print(f"No se puede conectar a {server_url}")
        print("Asegúrate de que el servidor está corriendo en WSL:")
        print("  cd ~/Alfonso && uvicorn app.main:app --reload")
        sys.exit(1)
    print("OK ✓")

    # Mostrar dispositivos de audio disponibles
    if debug:
        devices = list_input_devices()
        print("\nDispositivios de entrada disponibles:")
        for d in devices:
            marker = " ←" if d["index"] == device else ""
            print(f"  [{d['index']}] {d['name']}{marker}")
        print()

    print(f"\nEscuchando wake word '{keyword}'... (Ctrl+C para salir)\n")

    try:
        while True:
            # --- Fase 1: escuchar wake word ---
            print(".", end="", flush=True)
            wav = record_chunk(CHUNK_SECONDS, device=device)

            # Saltar chunks de silencio para no gastar llamadas al servidor
            if not has_voice(wav):
                continue

            if debug:
                print(f"\n[DEBUG] Chunk con voz detectado, enviando al servidor...")

            result = detect_wake_word(server_url, wav, keyword=keyword, model=model)

            if debug:
                print(f"[DEBUG] Respuesta wake word: {result}")

            if result.get("status") != "ok":
                print(f"\n[ERROR] {result.get('message', 'Error desconocido')}")
                continue

            if not result.get("result", {}).get("wake_word_detected"):
                continue

            # --- Wake word detectada ---
            print(f"\n\n✓ Wake word detectada: '{result['result'].get('text', '')}'")
            print("  Grabando orden... (habla ahora)")

            # --- Fase 2: grabar la orden ---
            wav_order = record_chunk(ORDER_SECONDS, device=device)

            if not has_voice(wav_order):
                print("  No se detectó voz en la orden.")
                print(f"\nEscuchando wake word '{keyword}'...\n")
                continue

            # --- Fase 3: transcribir la orden ---
            print("  Transcribiendo...", end=" ", flush=True)
            stt_result = transcribe_audio(server_url, wav_order, model=model)

            if debug:
                print(f"\n[DEBUG] STT: {stt_result}")

            if stt_result.get("status") != "ok":
                print(f"ERROR: {stt_result.get('result', {}).get('message', 'STT falló')}")
                continue

            user_text = stt_result.get("result", {}).get("text", "").strip()
            if not user_text:
                print("(no se entendió nada)")
                continue

            print(f"OK")
            print(f"\n  Tú: {user_text}")

            # --- Fase 4: enviar al chat ---
            print("  Alfonso pensando...", end=" ", flush=True)
            chat_result = send_chat(server_url, user_text, session_id)

            if debug:
                print(f"\n[DEBUG] Chat: {chat_result}")

            if chat_result.get("status") != "ok" and chat_result.get("status") != "success":
                print(f"ERROR: {chat_result.get('message', 'Chat falló')}")
                continue

            response_text = chat_result.get("result", {}).get("response", "")
            if not response_text:
                response_text = str(chat_result.get("result", ""))

            print(f"OK")
            print(f"\n  Alfonso: {response_text}\n")

            # --- Fase 5: TTS y reproducción ---
            audio_path = get_tts(server_url, response_text, voice=voice)
            if audio_path:
                print("  Reproduciendo respuesta...")
                play_audio_file(audio_path)
            else:
                print("  (TTS no disponible — respuesta solo en texto)")

            print(f"\nEscuchando wake word '{keyword}'...\n")

    except KeyboardInterrupt:
        print("\n\nHasta luego.\n")


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cliente de voz para Alfonso")
    p.add_argument("--url", default=DEFAULT_SERVER, help="URL del servidor Alfonso")
    p.add_argument("--keyword", default="alfonso", help="Wake word a escuchar")
    p.add_argument("--voice", default=None, help="Voz TTS (ej: es-ES-ElviraNeural)")
    p.add_argument("--device", type=int, default=None, help="Índice del dispositivo de audio")
    p.add_argument("--model", default="small", help="Modelo Whisper (tiny/base/small)")
    p.add_argument("--debug", action="store_true", help="Mostrar logs detallados")
    p.add_argument("--list-devices", action="store_true", help="Listar dispositivos de audio y salir")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.list_devices:
        print("\nDispositivios de entrada disponibles:")
        for d in list_input_devices():
            print(f"  [{d['index']}] {d['name']} ({d['channels']} canales)")
        sys.exit(0)

    run(
        server_url=args.url.rstrip("/"),
        keyword=args.keyword,
        voice=args.voice,
        device=args.device,
        model=args.model,
        debug=args.debug,
    )