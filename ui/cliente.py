"""
Cliente de voz para Alfonso — Refactorizado y con Escucha Orgánica.
"""

from __future__ import annotations

import argparse
import base64
import sys
import uuid
import numpy as np # Se mantiene para el procesamiento de audio raw
from typing import Optional

from core.config import (
    DEFAULT_SERVER, CHUNK_SECONDS, SILENCE_THRESHOLD, 
    MAX_SILENCE_SECONDS
)
from services.audio import ( # Import AudioService from services.audio
    AudioService
)


from core.api_client import (
    AlfonsoAPI
)
from core.processor import ResponseProcessor

# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def run(
    server_url: str,
    keyword: str,
    voice: Optional[str],
    device: Optional[int],
    output_device: Optional[int],
    model: str,
    threshold: int,
    debug: bool,
) -> None:
    session_id = str(uuid.uuid4())
    api = AlfonsoAPI(server_url)
    processor = ResponseProcessor()
    audio_service = AudioService() # Instantiate AudioService

    print(f"\n{'═'*55}")
    print(f"  Alfonso — Cliente de Voz")
    print(f"  Servidor  : {server_url}")
    print(f"  Wake word : '{keyword}'")
    print(f"  Umbral    : {threshold}")
    print(f"  Sesión    : {session_id[:8]}…")
    print(f"{'═'*55}\n")

    print("Conectando con el servidor…", end=" ", flush=True)
    if not api.ping():
        print("ERROR")
        print(f"  No se puede conectar a {server_url}")
        print("  Asegúrate de que el servidor está activo:")
        print("    uvicorn app.main:app --reload")
        sys.exit(1)
    print("OK ✓\n")

    if debug:
        devs = audio_service.list_input_devices() # Use audio_service
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
            wav = audio_service.record_chunk(int(CHUNK_SECONDS), device=device) # Use audio_service

            if not audio_service.has_voice(wav, threshold): # Use audio_service
                continue

            # --- FASE 1.1: Detección de Wake Word vía API ---
            wakeword_res = api.wakeword(wav, keyword=keyword)
            wake_word_detected_locally = wakeword_res.get("status") in ("ok", "success")
            wakeword_text = wakeword_res.get("result", {}).get("text", "")

            if debug:
                print(f"\n[debug wake] {wakeword_res}")

            if not wake_word_detected_locally: # Adaptar la condición de fallo
                print(f"\n  [!] Wake word no detectada localmente.")
                continue

            print(f"\n\n✓ Wake word detectada")
            wakeword_text = "" # En modo local simple, empezamos con texto vacío

            # ────────────────────────────────────────────────────────────
            # FASE 2: loop de conversación
            # ────────────────────────────────────────────────────────────
            first_order = processor.extract_order(wakeword_text, keyword)

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
                        chunk = audio_service.record_raw(chunk_dur, device=device) # Use audio_service
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
                    wav_order = audio_service.get_audio_bytes(audio_buffer) # Use audio_service
                    print("transcribiendo…", end=" ", flush=True)
                    
                    stt_res = api.stt(wav_order)
                    user_text = stt_res.get("result", {}).get("text", "")

                    if debug:
                        print(f"\n[debug stt] {stt_res}")

                    if stt_res.get("status") not in ("ok", "success"):
                        print(f"  [!] STT error: {stt_res.get('message', '')}")
                        continue
                    if not user_text:
                        print("(no entendido)")
                        continue

                    print(f"OK\n  Tú: {user_text}")

                if processor.is_exit_command(user_text):
                    print("\n  Alfonso: Hasta luego.\n")
                    print(f"Escuchando wake word '{keyword}'…\n")
                    break

                print("  Alfonso: ", end="", flush=True)
                chat = api.send_chat(user_text, session_id)

                if debug:
                    print(f"\n[debug chat] {chat}")

                if chat.get("status") not in ("ok", "success"):
                    print(f"[!] Chat error: {chat.get('message', '')}")
                    continue

                result_data = chat.get("result", {})
                response_text = processor.format_response(result_data)
                print(response_text + "\n")

                # ADDED: Play audio from backend response
                audio_b64 = result_data.get("audio")
                if audio_b64:
                    audio_service.play_audio(base64.b64decode(audio_b64), device=output_device)

    except KeyboardInterrupt:
        print("\n\nHasta luego.\n")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cliente de voz Alfonso")
    p.add_argument("--url", default=DEFAULT_SERVER)
    p.add_argument("--gui", action="store_true", help="Lanzar la interfaz gráfica")
    p.add_argument("--keyword", default="alfonso")
    p.add_argument("--voice", default=None)
    p.add_argument("--device", type=int, default=28, help="Índice del micro integrado")
    p.add_argument("--output-device", type=int, default=21, help="Índice del altavoz integrado")
    p.add_argument("--model", default="tiny", help="Modelo Whisper para wake word")
    p.add_argument("--threshold", type=int, default=SILENCE_THRESHOLD)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--list-devices", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.list_devices:
        service = AudioService()
        print("\nDispositivos de entrada disponibles:")
        for d in service.list_input_devices():
            print(f"  [{d['index']}] IN : {d['name']} ({d['channels']} ch)")
        print("\nDispositivos de salida disponibles:")
        for d in service.list_output_devices():
            print(f"  [{d['index']}] OUT: {d['name']} ({d['channels']} ch)")
        sys.exit(0)

    if args.gui:
        from gui.app import launch
        config = vars(args)
        config['url'] = config['url'].rstrip("/")
        launch(config)
    else:
        run(
            server_url=args.url.rstrip("/"),
            keyword=args.keyword,
            voice=args.voice,
            device=args.device,
            output_device=args.output_device,
            model=args.model,
            threshold=args.threshold,
            debug=args.debug,
        )