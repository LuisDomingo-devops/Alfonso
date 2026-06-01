"""
Cliente de voz para Alfonso — Refactorizado y con Escucha Orgánica.
"""

from __future__ import annotations

import argparse
import sys
import uuid
import numpy as np
from typing import Optional

from ui.config import (
    DEFAULT_SERVER, CHUNK_SECONDS, SILENCE_THRESHOLD, 
    MAX_SILENCE_SECONDS
)
from ui.audio_utils import (
    record_chunk, record_raw, has_voice, list_input_devices, 
    play_audio, get_audio_bytes
)
from ui.api_client import (
    ping_server, detect_wake_word, transcribe_audio, send_chat, get_tts
)
from ui.formatter import extract_order, format_response, is_exit


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
            wav = record_chunk(int(CHUNK_SECONDS), device=device)

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
            first_order = extract_order(wakeword_text, keyword)

            while True:
                if first_order:
                    user_text = first_order
                    first_order = None
                    print(f"  Tú: {user_text}")
                else:
                    print("  Escuchando… (habla ahora)", end=" ", flush=True)
                    audio_buffer = []
                    silence_time = 0
                    chunk_dur = 0.8

                    while True:
                        chunk = record_raw(chunk_dur, device=device)
                        if np.abs(chunk).mean() > threshold:
                            audio_buffer.append(chunk)
                            silence_time = 0
                            print(".", end="", flush=True)
                        else:
                            silence_time += chunk_dur
                            if audio_buffer:
                                print("_", end="", flush=True)
                                if silence_time >= MAX_SILENCE_SECONDS:
                                    break
                            elif silence_time >= 5.0: # Timeout inicial
                                break

                    if not audio_buffer:
                        print("\n  Silencio prolongado — volviendo a wake word\n")
                        break

                    print(" analizando…", end=" ", flush=True)
                    wav_order = get_audio_bytes(audio_buffer)
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

                if is_exit(user_text):
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
                response_text = format_response(result_data)
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