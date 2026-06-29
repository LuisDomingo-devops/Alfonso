"""
cliente.py — Cliente de voz para Alfonso (versión corregida).

Cambios respecto a la versión anterior:
- --device ya NO tiene valor por defecto hardcodeado (era 28, tu USB).
  Si no lo pasas, AudioService detecta automáticamente el micrófono integrado.
- --threshold por defecto es None → se calibra automáticamente en arrange().
- Al arrancar muestra qué dispositivo y samplerate va a usar.
- El loop de silencio emite nivel en DEBUG para poder diagnósticar sin --debug.
"""



from __future__ import annotations

print("Cargando cliente de voz Alfonso…\n")

import argparse
import base64
import sys
import uuid
from typing import Optional

import numpy as np

from core.config import (
    DEFAULT_SERVER,
    CHUNK_SECONDS,
    SILENCE_THRESHOLD,
    MAX_SILENCE_SECONDS,
)
from services.audio import AudioService, auto_select_device
from core.api_client import AlfonsoAPI
from core.processor import ResponseProcessor

print("Importaciones completadas.\n")
# ---------------------------------------------------------------------------
# Calibración de umbral automática
# ---------------------------------------------------------------------------

def calibrate_threshold(audio: AudioService, device: Optional[int], seconds: float = 2.0) -> int:
    """
    Graba `seconds` segundos de silencio ambiente y calcula el umbral.
    Devuelve max(nivel_ambiente * 3, 80) para tener margen.
    """
    print("  Calibrando umbral de silencio (no hables)...", end=" ", flush=True)
    try:
        raw  = audio.record_raw(seconds, device=device)
        # Convertir a int16 para usar la misma escala que has_voice
        amp_i16 = int(np.abs(raw).mean() * 32767)
        threshold = max(amp_i16 * 3, 80)
        print(f"OK → umbral={threshold}")
        return threshold
    except Exception as exc:
        print(f"ERROR ({exc}), usando umbral por defecto {SILENCE_THRESHOLD}")
        return SILENCE_THRESHOLD


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
    threshold: Optional[int],
    debug: bool,
) -> None:
    
    print("Iniciando cliente de voz Alfonso…\n")

    session_id = str(uuid.uuid4())
    api        = AlfonsoAPI(server_url)
    processor  = ResponseProcessor()

    # AudioService con auto-detección si no se especificó dispositivo
    audio = AudioService(device=device, auto_detect=(device is None))

    # Mostrar el dispositivo que se va a usar
    import sounddevice as sd

    print("AudioService inicializado.\n")
    effective_device = audio.device
    device_name = "predeterminado del sistema"
    print(f"Dispositivo de entrada seleccionado: [{effective_device}] {device_name}\n")
    if effective_device is not None:
        try:
            print("Probando grabación para calibración de umbral…", end=" ", flush=True)
            device_name = sd.query_devices(effective_device)["name"]
        except Exception:
            print("ERROR al acceder al dispositivo, usando nombre genérico.")
            pass

    print(f"\n{'═'*60}")
    print(f"  Alfonso — Cliente de Voz")
    print(f"  Servidor      : {server_url}")
    print(f"  Wake word     : '{keyword}'")
    print(f"  Dispositivo   : [{effective_device}] {device_name}")
    print(f"  Samplerate    : {audio._native_rate}Hz → 16000Hz (Whisper)")
    print(f"  Sesión        : {session_id[:8]}…")
    print(f"{'═'*60}\n")

    print("Conectando con el servidor…", end=" ", flush=True)
    if not api.ping():
        print("ERROR")
        print(f"  No se puede conectar a {server_url}")
        print("  Arranca el servidor: uvicorn app.main:app --reload")
        sys.exit(1)
    print("OK ✓\n")

    # Calibración de umbral si no se pasó explícitamente
    if threshold is None:
        threshold = calibrate_threshold(audio, effective_device)
    print(f"  Umbral de voz activo: {threshold}\n")

    if debug:
        devs = audio.list_input_devices()
        print("Dispositivos de entrada disponibles:")
        for d in devs:
            marker = " ← EN USO" if d["index"] == effective_device else ""
            print(f"  [{d['index']:>2}] {d['name']:<45} {d['default_samplerate']:>6}Hz{marker}")
        print()

    print(f"Escuchando wake word '{keyword}'… (Ctrl+C para salir)\n")

    try:
        print("Cargando cliente de voz Alfonso…\n")
        while True:
            # ── FASE 1: esperar wake word ──────────────────────────────
            print(".", end="", flush=True)

            try:
                print("\nGrabando…", end=" ", flush=True)
                wav = audio.record_chunk(int(CHUNK_SECONDS), device=effective_device)
            except Exception as exc:
                print(f"\n[ERROR grabando] {exc}")
                continue

            # Detección de Wake Word local mediante STT local
            if not audio.has_voice(wav, threshold):
                continue
            
            print("\n[Voz] Analizando wake word localmente...", end=" ")
            wakeword_text = audio.transcribe_local(wav)
            
            if keyword.lower() not in wakeword_text.lower():
                print("skip.")
                continue
            
            # Si llegamos aquí, es que el keyword está en el texto transcrito localmente.
            # No necesitamos wakeword_res porque la validación es local.
            if not wakeword_text:
                print("  Wake word NO detectada, intentando nuevamente…")
                continue

            print(f"\n\n✓ Wake word detectada")

            # ── FASE 2: loop de conversación ───────────────────────────
            first_order = processor.extract_order(wakeword_text, keyword)
            print(f"  Primera orden extraída: '{first_order}'" if first_order else "  No se extrajo orden de la wake word, esperando a que hables…")

            while True:
                if first_order:
                    print("  Usando la orden extraída de la wake word, sin necesidad de hablar.")
                    user_text  = first_order
                    first_order = None
                    print(f"  Tú: {user_text}")
                else:
                    print("  Escuchando… (habla ahora)", end=" ", flush=True)
                    audio_buffer = []
                    silence_time = 0.0
                    chunk_dur    = 0.8

                    while True:
                        try:
                            print(f"\n[DEBUG] Grabando chunk de {chunk_dur}s para análisis de voz…", end=" ", flush=True)
                            chunk = audio.record_raw(chunk_dur, device=effective_device)
                        except Exception as exc:
                            print(f"\n[ERROR grabando orden] {exc}")
                            break

                        level = int(np.abs(chunk).mean() * 32767)
                        if level > threshold:
                            audio_buffer.append(chunk)
                            silence_time = 0.0
                            print(".", end="", flush=True)
                        else:
                            silence_time += chunk_dur
                            if audio_buffer:
                                print("_", end="", flush=True)
                                if silence_time >= MAX_SILENCE_SECONDS:
                                    break
                            elif silence_time >= 5.0:
                                break

                    if not audio_buffer:
                        print("\n  Silencio prolongado — volviendo a wake word\n")
                        break

                    print(" analizando…", end=" ", flush=True)
                    wav_order = audio.get_audio_bytes(audio_buffer)
                    print("transcribiendo…", end=" ", flush=True)

                    # Transcripción local para evitar el 404 del endpoint /stt
                    user_text = audio.transcribe_local(wav_order)

                    if not user_text:
                        print("(no entendido)")
                        continue

                    print(f"OK\n  Tú: {user_text}")

                if processor.is_exit_command(user_text):
                    print("\n  Alfonso: Hasta luego.\n")
                    print(f"Escuchando wake word '{keyword}'…\n")
                    break

                print(f"\n[CLIENTE_INFO] Enviando a /chat del servidor: '{user_text}' (session: {session_id[:8]}...)")
                chat = api.send_chat(user_text, session_id)
                
                status = chat.get("status") if isinstance(chat, dict) else "unknown"
                print(f"[CLIENTE_INFO] Respuesta del servidor recibida (Estado: {status})")

                if debug:
                    print(f"\n[debug chat] {chat}")

                if not isinstance(chat, dict) or chat.get("status") not in ("ok", "success"):
                    err_msg = chat.get('message', 'Formato de respuesta inválido') if isinstance(chat, dict) else 'Error de red/conexión'
                    print(f"[!] Chat error: {err_msg}")
                    continue

                result_data   = chat.get("result", {})
                response_text = processor.format_response(result_data)
                print(response_text + "\n")

                audio_b64 = result_data.get("audio")
                if audio_b64:
                    audio.play_audio(base64.b64decode(audio_b64), device=output_device)
                elif response_text:
                     # Si el servidor no devuelve audio, generamos el TTS localmente en el cliente
                     import asyncio
                     try:
                         # Intentar generar voz humana con Edge-TTS
                         audio_path = asyncio.run(audio.text_to_speech_human(response_text))
                         if audio_path:
                             audio.play_audio_file(audio_path)
                         else:
                             # Fallback a voz robótica local
                             audio_bytes = audio.text_to_wav_bytes(response_text)
                             if audio_bytes:
                                 audio.play_audio(audio_bytes, device=output_device)
                     except Exception as e:
                         # Silencioso en modo normal, mostrar en debug
                         if debug:
                             print(f"\n[debug] Error generando TTS local en cliente: {e}")

    except KeyboardInterrupt:
        print("\n\nHasta luego.\n")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cliente de voz Alfonso")
    p.add_argument("--url",           default=DEFAULT_SERVER)
    p.add_argument("--gui",           action="store_true", help="Lanzar la interfaz gráfica")
    p.add_argument("--keyword",       default="alfonso")
    p.add_argument("--voice",         default=None)
    p.add_argument("--device",        type=int, default=None,
                   help="Índice del micrófono (None = auto-detecta el integrado)")
    p.add_argument("--output-device", type=int, default=None,
                   help="Índice del altavoz (None = predeterminado del sistema)")
    p.add_argument("--model",         default="tiny")
    p.add_argument("--threshold",     type=int, default=None,
                   help="Umbral de silencio (None = calibración automática al arrancar)")
    p.add_argument("--debug",         action="store_true")
    p.add_argument("--list-devices",  action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(f"Argumentos recibidos: {args}\n")
    if args.list_devices:
        print("Listando dispositivos de audio disponibles…\n")
        svc = AudioService(auto_detect=False)
        print("\nDispositivos de entrada:")
        for d in svc.list_input_devices():
            auto = " ← integrado detectado" if d["index"] == auto_select_device() else ""
            print(f"  [{d['index']:>2}] {d['name']:<50} {d['default_samplerate']:>6}Hz{auto}")
        print("\nDispositivos de salida:")
        for d in svc.list_output_devices():
            print(f"  [{d['index']:>2}] {d['name']:<50} {d['default_samplerate']:>6}Hz")
        sys.exit(0)

    if args.gui:
        print("Lanzando interfaz gráfica…")
        from gui.app import launch
        config = vars(args)
        config["url"] = config["url"].rstrip("/")
        launch(config)
    else:
        print("Iniciando cliente de voz Alfonso…\n")
        run(
            server_url    = args.url.rstrip("/"),
            keyword       = args.keyword,
            voice         = args.voice,
            device        = args.device,
            output_device = getattr(args, "output_device", None),
            model         = args.model,
            threshold     = args.threshold,
            debug         = args.debug,
        )