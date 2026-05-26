"""
Punto de entrada para el cliente Alfonso. Soporta CLI y GUI.
"""

import argparse
import sys
import uuid
from typing import Optional

# Importar módulos de la nueva arquitectura
from core.api import AlfonsoAPI
from core.processor import ResponseProcessor
from services.audio import AudioService

# ---------------------------------------------------------------------------
# Verificar dependencias antes de importar
# ---------------------------------------------------------------------------
MISSING = []
for pkg in ["sounddevice", "numpy", "requests", "PyQt6"]:
    try:
        __import__(pkg)
    except ImportError:
        MISSING.append(pkg)

if MISSING:
    print(f"[ERROR] Faltan dependencias: {', '.join(MISSING)}")
    print(f"        Instálalas con: pip install {' '.join(MISSING)} PyQt6 pygame")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
DEFAULT_SERVER = "http://localhost:8000"
CHUNK_SECONDS = 3       # segundos por chunk de escucha de wake word
ORDER_SECONDS = 5       # segundos de grabación tras detectar la wake word
SILENCE_THRESHOLD = 500 # amplitud mínima para considerar que hay voz
EXIT_WORDS_HINT = "adiós / para"

def run(
    server_url: str,
    keyword: str,
    voice: Optional[str],
    device: Optional[int],
    model: str,
    threshold: int,
    debug: bool,
) -> None:
    api = AlfonsoAPI(server_url)
    audio = AudioService()
    processor = ResponseProcessor()
    session_id = str(uuid.uuid4())

    print(f"\n{'='*55}")
    print(f"  Alfonso — Cliente de Voz")
    print(f"  Servidor  : {server_url}")
    print(f"  Wake word : '{keyword}'")
    print(f"  Umbral    : {threshold} (usa audio_check.py --live para calibrar)")
    print(f"  Sesión    : {session_id[:8]}...")
    print(f"{'='*55}\n")

    # Verificar servidor
    print("Conectando con el servidor...", end=" ", flush=True)
    if not api.ping():
        print("ERROR")
        print(f"No se puede conectar a {server_url}")
        print("Asegúrate de que el servidor está corriendo en WSL:")
        print("  cd ~/Alfonso && uvicorn app.main:app --reload")
        sys.exit(1)
    print("OK ✓")

    # Mostrar dispositivos de audio disponibles
    if debug:
        devices = audio.list_input_devices()
        print("\nDispositivios de entrada disponibles:")
        for d in devices:
            marker = " ←" if d["index"] == device else ""
            print(f"  [{d['index']}] {d['name']}{marker}")
        print()

    print(f"\\nEscuchando wake word '{keyword}'... (Ctrl+C para salir)\\n")

    STT_MODEL = "small" if model == "tiny" else model

    try:
        while True:
            # ================================================================
            # FASE 1 — Esperar wake word
            # ================================================================
            print(".", end="", flush=True)
            wav = audio.record_chunk(CHUNK_SECONDS, device=device)

            if not audio.has_voice(wav, threshold=threshold):
                continue

            if debug:
                print(f"\\n[DEBUG] Chunk con voz detectado, enviando al servidor...")

            result = api.detect_wake_word(wav, keyword=keyword, model=model)

            if debug:
                print(f"[DEBUG] Respuesta wake word: {result}")

            if result.get("status") not in ("ok", "success"):
                print(f"\\n[ERROR] {result.get('message', 'Error desconocido')}")
                continue

            inner = result.get("result", {})
            if inner.get("status") == "error":
                print(f"\\n[ERROR servidor] {inner.get('message', 'Error desconocido')}")
                continue

            if not inner.get("wake_word_detected"):
                continue

            # ================================================================
            # FASE 2 — Modo conversación: escuchar órdenes en bucle
            # hasta silencio prolongado o palabra de salida
            # ================================================================
            wakeword_text = inner.get("text", "")
            print(f"\\n\\n✓ Alfonso activado — di tu orden ('{EXIT_WORDS_HINT}' para terminar)\\n")

            order_in_wakeword = processor.extract_order(wakeword_text, keyword)
            consecutive_silence = 0
            MAX_SILENCE_CHUNKS = 2  # silencio durante 2 chunks (~6s) → vuelve a wake word

            first_order = order_in_wakeword  # puede ser None

            while True:
                if first_order:
                    user_text = first_order
                    first_order = None
                    print(f"  Tú (en wake word): {user_text}")
                else:
                    # Grabar orden
                    print("  Escuchando orden...", end=" ", flush=True)
                    wav_order = audio.record_chunk(ORDER_SECONDS, device=device)

                    if not audio.has_voice(wav_order, threshold=threshold):
                        consecutive_silence += 1
                        print(f"(silencio {consecutive_silence}/{MAX_SILENCE_CHUNKS})")
                        if consecutive_silence >= MAX_SILENCE_CHUNKS:
                            print(f"\\nSilencio prolongado — volviendo a escuchar wake word '{keyword}'...\\n")
                            break
                        continue

                    consecutive_silence = 0

                    # Transcribir orden con modelo más preciso
                    print("transcribiendo...", end=" ", flush=True)
                    stt_result = api.transcribe_audio(wav_order, model=STT_MODEL)

                    if debug:
                        print(f"\\n[DEBUG] STT: {stt_result}")

                    if stt_result.get("status") not in ("ok", "success"):
                        print(f"ERROR STT: {stt_result.get('message', '')}")
                        continue

                    stt_inner = stt_result.get("result", {})
                    if stt_inner.get("status") == "error":
                        print(f"ERROR: {stt_inner.get('message', '')}")
                        continue

                    user_text = stt_inner.get("text", "").strip()
                    if not user_text:
                        print("(no se entendió)")
                        continue

                    print(f"OK")
                    print(f"\\n  Tú: {user_text}")

                # Comprobar si el usuario quiere terminar la conversación
                if processor.is_exit_command(user_text):
                    print(f"\\n  Alfonso: Hasta luego.\\n")
                    audio_path = api.get_tts("Hasta luego.", voice)
                    if audio_path:
                        audio.play_audio_file(audio_path)
                    print(f"\\nEscuchando wake word '{keyword}'...\\n")
                    break

                # Enviar al chat
                print("  Alfonso pensando...", end=" ", flush=True)
                chat_result = api.send_chat(user_text, session_id)

                if debug:
                    print(f"\\n[DEBUG] Chat: {chat_result}")

                if chat_result.get("status") not in ("ok", "success"):
                    print(f"ERROR chat: {chat_result.get('message', '')}")
                    continue

                # Extraer respuesta — chat normal o resultado de herramienta
                result_data = chat_result.get("result", {})
                response_text = processor.format_response(result_data)

                print(f"OK")
                print(f"\\n  Alfonso: {response_text}\\n")

                # TTS
                audio_path = api.get_tts(response_text, voice)
                if audio_path:
                    audio.play_audio_file(audio_path)

    except KeyboardInterrupt:
        print("\\n\\nHasta luego.\\n")

EXIT_WORDS_HINT = "adiós / para"



# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cliente de voz para Alfonso")
    p.add_argument("--url", default=DEFAULT_SERVER, help="URL del servidor Alfonso")
    p.add_argument("--keyword", default="alfonso", help="Wake word a escuchar")
    p.add_argument("--voice", default=None, help="Voz TTS (ej: es-ES-ElviraNeural)")
    p.add_argument("--device", type=int, default=None, help="Índice del dispositivo de audio")
    p.add_argument("--model", default="tiny", help="Modelo Whisper para wake word (tiny=rápido, small=preciso)")
    p.add_argument("--threshold", type=int, default=SILENCE_THRESHOLD,
                   help=f"Umbral de silencio (default: {SILENCE_THRESHOLD}). Usa audio_check.py para calibrar.")
    p.add_argument("--debug", action="store_true", help="Mostrar logs detallados")
    p.add_argument("--list-devices", action="store_true", help="Listar dispositivos de audio y salir")
    p.add_argument("--gui", action="store_true", help="Lanzar interfaz gráfica (PyQt)")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()

    if args.gui:
        from gui.app import launch
        launch(vars(args))
        sys.exit(0)

    if args.list_devices:
        audio = AudioService()
        print("\nDispositivios de entrada disponibles:")
        for d in audio.list_input_devices():
            print(f"  [{d['index']}] {d['name']} ({d['channels']} canales)")
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