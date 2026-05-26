"""
Diagnóstico de audio para Alfonso.
Te ayuda a encontrar el micrófono correcto y el umbral de silencio adecuado.

Uso:
    python audio_check.py                    # prueba todos los micrófonos
    python audio_check.py --device 1         # prueba solo el dispositivo 1
    python audio_check.py --device 1 --live  # monitorización en tiempo real
"""

import argparse
import io
import sys
import time
import wave

MISSING = []
for pkg in ["sounddevice", "numpy"]:
    try:
        __import__(pkg)
    except ImportError:
        MISSING.append(pkg)

if MISSING:
    print(f"[ERROR] Instala: pip install {' '.join(MISSING)}")
    sys.exit(1)

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHANNELS = 1
TEST_DURATION = 2  # segundos por prueba


def record(duration: int, device: int) -> np.ndarray:
    recording = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        device=device,
    )
    sd.wait()
    return recording


def amplitude(data: np.ndarray) -> int:
    return int(np.abs(data).mean())


def bar(value: int, max_val: int = 3000, width: int = 40) -> str:
    filled = int((value / max_val) * width)
    filled = min(filled, width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {value:5d}"


def test_device(device_index: int, device_name: str) -> dict:
    """Graba 2 segundos del dispositivo y devuelve estadísticas."""
    try:
        data = record(TEST_DURATION, device_index)
        amp = amplitude(data)
        peak = int(np.abs(data).max())
        return {
            "ok": True,
            "amplitude_mean": amp,
            "amplitude_peak": peak,
            "has_signal": amp > 50,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def live_monitor(device: int, device_name: str) -> None:
    """Monitorización en tiempo real del nivel de audio."""
    print(f"\nMonitorización en tiempo real — dispositivo [{device}] {device_name}")
    print("Habla al micrófono para ver el nivel. Ctrl+C para salir.\n")
    print("Nivel  0   500  1000  1500  2000  2500  3000+")
    print("       |    |    |    |    |    |    |")

    try:
        while True:
            try:
                data = record(1, device)
                amp = amplitude(data)
                peak = int(np.abs(data).max())
                status = "SILENCIO" if amp < 200 else "BAJO" if amp < 500 else "BIEN"
                print(f"\r  {bar(amp)}  pico:{peak:5d}  {status}    ", end="", flush=True)
            except Exception as e:
                print(f"\r  [ERROR: {e}]", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n")


def run_full_test() -> None:
    devices = sd.query_devices()
    input_devices = [
        (i, d) for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]

    if not input_devices:
        print("No se encontraron dispositivos de entrada.")
        return

    print("\n" + "="*60)
    print("  DIAGNÓSTICO DE AUDIO — Alfonso")
    print("="*60)
    print(f"\nProbando {len(input_devices)} dispositivos de entrada...")
    print("(Habla durante las grabaciones para ver qué capta cada uno)\n")

    results = []
    for idx, device in input_devices:
        name = device["name"][:45]
        print(f"  [{idx:2d}] {name:<45}", end=" ", flush=True)

        result = test_device(idx, name)

        if not result["ok"]:
            print(f"  ERROR: {result['error'][:40]}")
        else:
            amp = result["amplitude_mean"]
            peak = result["amplitude_peak"]
            signal = "✓ SEÑAL" if result["has_signal"] else "  silencio"
            print(f"  media:{amp:5d}  pico:{peak:5d}  {signal}")
            if result["has_signal"]:
                results.append((idx, name, amp))

    print("\n" + "-"*60)

    if results:
        best = max(results, key=lambda x: x[2])
        print(f"\n✓ Dispositivos con señal detectada:")
        for idx, name, amp in sorted(results, key=lambda x: x[2], reverse=True):
            marker = " ← RECOMENDADO" if idx == best[0] else ""
            print(f"    [{idx}] {name[:45]}  (media: {amp}){marker}")

        print(f"\nPara usar el recomendado:")
        print(f"    python cliente.py --device {best[0]} --debug")
        print(f"\nPara monitorizar en tiempo real:")
        print(f"    python audio_check.py --device {best[0]} --live")

        # Calcular umbral sugerido
        suggested_threshold = max(100, best[2] // 3)
        print(f"\nUmbral de silencio sugerido: {suggested_threshold}")
        print(f"    python cliente.py --device {best[0]} --threshold {suggested_threshold} --debug")
    else:
        print("\n⚠ Ningún dispositivo captó señal.")
        print("  Asegúrate de hablar durante la grabación o prueba --live con cada índice.")
        print("\n  Prueba manualmente:")
        for idx, device in input_devices[:5]:
            print(f"    python audio_check.py --device {idx} --live")

    print()


def parse_args():
    p = argparse.ArgumentParser(description="Diagnóstico de audio para Alfonso")
    p.add_argument("--device", type=int, default=None, help="Índice del dispositivo a probar")
    p.add_argument("--live", action="store_true", help="Monitorización en tiempo real")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.device is not None:
        devices = sd.query_devices()
        name = devices[args.device]["name"] if args.device < len(devices) else f"device {args.device}"

        if args.live:
            live_monitor(args.device, name)
        else:
            print(f"\nProbando dispositivo [{args.device}] {name}...")
            print("Habla ahora durante 2 segundos...", end=" ", flush=True)
            result = test_device(args.device, name)
            if result["ok"]:
                print(f"\n  Media: {result['amplitude_mean']}")
                print(f"  Pico : {result['amplitude_peak']}")
                print(f"  Señal: {'SÍ ✓' if result['has_signal'] else 'NO — silencio'}")
                print(f"\nPara monitorización continua:")
                print(f"  python audio_check.py --device {args.device} --live")
            else:
                print(f"ERROR: {result['error']}")
    else:
        run_full_test()