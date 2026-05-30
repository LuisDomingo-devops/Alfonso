"""
Cliente de voz para Alfonso — Fase 1 completa.

- Retry automático en wake word con backoff exponencial.
- Silencio prolongado vuelve al loop de wake word sin crashear.
- Manejo correcto de respuestas tipo "tool" (no intenta hacer TTS del dict).
- Variables de entorno para configurar sin tocar código.
- Logging más limpio en consola.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import uuid
import wave
from typing import Optional

MISSING = []
for pkg in ["sounddevice", "numpy", "requests"]:
    try:
        __import__(pkg)
    except ImportError:
        MISSING.append(pkg)

if MISSING:
    print(f"[ERROR] Faltan dependencias: {', '.join(MISSING)}")
    print(f"        Instálalas con: pip install {' '.join(MISSING)}")
    sys.exit(1)

import numpy as np
import requests
import sounddevice as sd

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
DEFAULT_SERVER   = os.getenv("ALFONSO_SERVER", "http://localhost:8000")
SAMPLE_RATE      = 16000
CHANNELS         = 1
CHUNK_SECONDS    = int(os.getenv("CHUNK_SECONDS", "3"))
ORDER_SECONDS    = int(os.getenv("ORDER_SECONDS", "5"))
SILENCE_THRESHOLD = int(os.getenv("SILENCE_THRESHOLD", "500"))
MAX_SILENCE_CHUNKS = 3          # chunks de silencio antes de volver a wake word
WAKE_WORD_RETRIES  = 3          # reintentos si el servidor no responde
EXIT_WORDS = {"adiós", "adios", "hasta luego", "para", "stop", "salir", "bye", "terminar"}


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def ping_server(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def detect_wake_word(
    base_url: str,
    wav_bytes: bytes,
    keyword: str,
    model: str = "tiny",
) -> dict:
    for attempt in range(1, WAKE_WORD_RETRIES + 1):
        try:
            r = requests.post(
                f"{base_url}/audio/wakeword/upload",
                files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
                data={"keyword": keyword, "model": model},
                timeout=90,
            )
            r.raise_for_status()
            return r.json()
        except requests.Timeout:
            if attempt < WAKE_WORD_RETRIES:
                time.sleep(2 ** attempt)
                continue
            return {"status": "error", "message": "timed out after retries"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "max retries exceeded"}


def transcribe_audio(base_url: str, wav_bytes: bytes, model: str = "small") -> dict:
    try:
        r = requests.post(
            f"{base_url}/audio/stt/upload",
            files={"file": ("orden.wav", wav_bytes, "audio/wav")},
            params={"model": model},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def send_chat(base_url: str, message: str, session_id: str) -> dict:
    try:
        r = requests.post(
            f"{base_url}/chat",
            json={"message": message},
            headers={"X-Session-ID": session_id},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_tts(base_url: str, text: str, voice: Optional[str] = None) -> Optional[str]:
    import tempfile
    from pathlib import Path

    try:
        payload = {"text": text}
        if voice:
            payload["voice"] = voice
        r = requests.post(f"{base_url}/audio/tts", json=payload, timeout=30)
        r.raise_for_status()
        audio_file = r.json().get("result", {}).get("audio_file")
        if not audio_file:
            return None
        file_r = requests.get(f"{base_url}/audio/file", params={"path": audio_file}, timeout=10)
        if file_r.status_code == 200:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(file_r.content)
            tmp.close()
            return tmp.name
        return audio_file if Path(audio_file).exists() else None
    except Exception:
        return None


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


# ---------------------------------------------------------------------------
# Procesamiento de respuestas
# ---------------------------------------------------------------------------

def _extract_order(wakeword_text: str, keyword: str) -> Optional[str]:
    """Si el usuario dijo 'Alfonso, haz X', extrae 'haz X'."""
    text = wakeword_text.lower().strip().rstrip(".,!?")
    kw = keyword.lower().strip()
    if text == kw:
        return None
    for sep in [", ", ",", " "]:
        if text.startswith(kw + sep):
            order = wakeword_text[len(kw) + len(sep):].strip()
            return order if order else None
    return None


def _format_response(result_data: dict) -> str:
    """
    Convierte la respuesta del orchestrator en texto legible para TTS y consola.
    """
    t = result_data.get("type", "")
 
    if t == "chat":
        return result_data.get("response") or "Sin respuesta."
 
    if t == "tool":
        tool_name = result_data.get("tool", "herramienta")
        tool_result = result_data.get("result", {})
        status = tool_result.get("status", "")
        message = tool_result.get("message", "")
 
        # no_op: el modelo pidió más información
        if tool_name == "no_op":
            return tool_result.get("message", "Necesito más información.")
 
        if status == "ok":
            # Mensaje limpio: quitar la ruta absoluta larga si está presente
            if message:
                # "Archivo creado: /home/luisd/Alfonso/ruta/archivo.txt" → "Archivo creado: archivo.txt"
                import re
                message = re.sub(r":\s*/[^\s]+/([^/\s]+)", r": \1", message)
            return message or f"Hecho."
 
        # status == error
        error_msg = tool_result.get("message", "error desconocido")
        return f"Ha ocurrido un error: {error_msg}"
 
    if t == "error":
        return f"Error: {result_data.get('message', 'error desconocido')}"
 
    # Fallback: si el resultado tiene message directo
    if "message" in result_data:
        return result_data["message"]
 
    return "Completado."


def _is_exit(text: str) -> bool:
    return any(w in text.lower() for w in EXIT_WORDS)


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def run(
    server_url: str,
    keyword: str,
    voice: Optional[str],
    device: Optional[int],
    model: str,
    threshold: int,
    debug: bool,
) -> None:
    session_id = str(uuid.uuid4())
    stt_model = "small" if model == "tiny" else model

    print(f"\n{'═'*55}")
    print(f"  Alfonso — Cliente de Voz")
    print(f"  Servidor  : {server_url}")
    print(f"  Wake word : '{keyword}'")
    print(f"  Umbral    : {threshold}")
    print(f"  Sesión    : {session_id[:8]}…")
    print(f"{'═'*55}\n")

    print("Conectando con el servidor…", end=" ", flush=True)
    if not ping_server(server_url):
        print("ERROR")
        print(f"  No se puede conectar a {server_url}")
        print("  Asegúrate de que el servidor está activo:")
        print("    uvicorn app.main:app --reload")
        sys.exit(1)
    print("OK ✓\n")

    if debug:
        devs = list_input_devices()
        print("Dispositivos de entrada:")
        for d in devs:
            marker = " ←" if d["index"] == device else ""
            print(f"  [{d['index']}] {d['name']}{marker}")
        print()

    print(f"Escuchando wake word '{keyword}'… (Ctrl+C para salir)\n")

    try:
        while True:
            # ────────────────────────────────────────────────────────────
            # FASE 1: esperar wake word
            # ────────────────────────────────────────────────────────────
            print(".", end="", flush=True)
            wav = record_chunk(CHUNK_SECONDS, device=device)

            if not has_voice(wav, threshold):
                continue

            result = detect_wake_word(server_url, wav, keyword=keyword, model=model)

            if debug:
                print(f"\n[debug wake] {result}")

            if result.get("status") not in ("ok", "success"):
                print(f"\n  [!] Error wake word: {result.get('message', '')}")
                continue

            inner = result.get("result", result)
            if not inner.get("wake_word_detected"):
                continue

            wakeword_text = inner.get("text", "")
            print(f"\n\n✓ '{keyword}' detectado\n")

            # ────────────────────────────────────────────────────────────
            # FASE 2: loop de conversación
            # ────────────────────────────────────────────────────────────
            silence_count = 0
            first_order = _extract_order(wakeword_text, keyword)

            while True:
                if first_order:
                    user_text = first_order
                    first_order = None
                    print(f"  Tú (en wake word): {user_text}")
                else:
                    print("  Escuchando…", end=" ", flush=True)
                    wav_order = record_chunk(ORDER_SECONDS, device=device)

                    if not has_voice(wav_order, threshold):
                        silence_count += 1
                        print(f"(silencio {silence_count}/{MAX_SILENCE_CHUNKS})")
                        if silence_count >= MAX_SILENCE_CHUNKS:
                            print(f"\n  Silencio prolongado — volviendo a wake word\n")
                            break
                        continue

                    silence_count = 0
                    print("transcribiendo…", end=" ", flush=True)
                    stt = transcribe_audio(server_url, wav_order, model=stt_model)

                    if debug:
                        print(f"\n[debug stt] {stt}")

                    if stt.get("status") not in ("ok", "success"):
                        print(f"  [!] STT error: {stt.get('message', '')}")
                        continue

                    stt_inner = stt.get("result", stt)
                    user_text = stt_inner.get("text", "").strip()
                    if not user_text:
                        print("(no entendido)")
                        continue

                    print(f"OK\n  Tú: {user_text}")

                if _is_exit(user_text):
                    print("\n  Alfonso: Hasta luego.\n")
                    path = get_tts(server_url, "Hasta luego.", voice)
                    if path:
                        play_audio(path)
                    print(f"Escuchando wake word '{keyword}'…\n")
                    break

                print("  Alfonso: ", end="", flush=True)
                chat = send_chat(server_url, user_text, session_id)

                if debug:
                    print(f"\n[debug chat] {chat}")

                if chat.get("status") not in ("ok", "success"):
                    print(f"[!] Chat error: {chat.get('message', '')}")
                    continue

                result_data = chat.get("result", {})
                response_text = _format_response(result_data)
                print(response_text + "\n")

                path = get_tts(server_url, response_text, voice)
                if path:
                    play_audio(path)

    except KeyboardInterrupt:
        print("\n\nHasta luego.\n")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cliente de voz Alfonso")
    p.add_argument("--url", default=DEFAULT_SERVER)
    p.add_argument("--keyword", default="alfonso")
    p.add_argument("--voice", default=None)
    p.add_argument("--device", type=int, default=None)
    p.add_argument("--model", default="tiny", help="Modelo Whisper para wake word")
    p.add_argument("--threshold", type=int, default=SILENCE_THRESHOLD)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--list-devices", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.list_devices:
        print("\nDispositivos de entrada disponibles:")
        for d in list_input_devices():
            print(f"  [{d['index']}] {d['name']} ({d['channels']} ch)")
        sys.exit(0)

    run(
        server_url=args.url.rstrip("/"),
        keyword=args.keyword,
        voice=args.voice,
        device=args.device,
        model=args.model,
        threshold=args.threshold,
        debug=args.debug,
    )