"""
audio_check.py — Diagnóstico de audio para Alfonso (versión mejorada).

Detecta automáticamente el micrófono integrado del Acer Swift 314 (Realtek)
y muestra qué samplerate acepta, el nivel de señal y si Whisper puede usarlo.

Uso:
    python audio_check.py              # diagnóstico completo
    python audio_check.py --device 1   # prueba un índice específico
    python audio_check.py --live       # monitorización en tiempo real (auto-detecta)
    python audio_check.py --live --device 3
"""

from __future__ import annotations

import argparse
import sys
import time

MISSING = []
for pkg in ["sounddevice", "numpy"]:
    try:
        __import__(pkg)
    except ImportError:
        MISSING.append(pkg)

if MISSING:
    print(f"[ERROR] Instala primero: pip install {' '.join(MISSING)}")
    sys.exit(1)

import numpy as np
import sounddevice as sd

# Importamos las utilidades del AudioService nuevo
try:
    from services.audio import auto_select_device, probe_device_samplerate, TARGET_RATE
except ImportError:
    # Fallback si se ejecuta desde fuera del directorio ui/
    TARGET_RATE = 16_000
    def probe_device_samplerate(dev):
        for rate in [16_000, 44_100, 48_000]:
            try:
                sd.check_input_settings(device=dev, samplerate=rate, channels=1)
                return rate
            except Exception:
                continue
        return 44_100
    def auto_select_device():
        _INTEGRATED = [
            "realtek", "array", "intel", "sst", "integrated", "built-in",
            "amic", "dmic", "smart sound", "intel® smart", "tecnología intel",
            "varios micrófonos",
        ]
        _PENALIZE = [
            "usb", "steam", "mezcla estéreo", "altavoz", "output with",
            "speakers", "loopback", "external",
        ]
        try:
            devices = sd.query_devices()
            best, best_score = None, 0
            for i, d in enumerate(devices):
                if d["max_input_channels"] < 1:
                    continue
                name_lower = d["name"].lower()
                score  = sum(1 for kw in _INTEGRATED if kw in name_lower)
                score -= sum(3 for kw in _PENALIZE   if kw in name_lower)
                if score > best_score:
                    best_score, best = score, i
            return best
        except Exception:
            return None

CHANNELS     = 1
TEST_SECONDS = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record(device: int, samplerate: int, duration: int = TEST_SECONDS) -> np.ndarray:
    data = sd.rec(
        int(duration * samplerate),
        samplerate=samplerate,
        channels=CHANNELS,
        dtype="float32",
        device=device,
    )
    sd.wait()
    return data


def _to_int16_scale(data: np.ndarray) -> np.ndarray:
    """float32 [-1,1] → escala int16 con clip para evitar overflow."""
    return np.abs(np.clip(data.flatten(), -1.0, 1.0)) * 32767


def _amplitude(data: np.ndarray) -> int:
    return int(_to_int16_scale(data).mean())


def _peak(data: np.ndarray) -> int:
    return int(_to_int16_scale(data).max())


def _bar(value: int, max_val: int = 3000, width: int = 40) -> str:
    filled = min(int((value / max_val) * width), width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {value:5d}"


# ---------------------------------------------------------------------------
# Diagnóstico completo
# ---------------------------------------------------------------------------

def run_full_test(auto_device: Optional[int] = None) -> None:
    devices     = sd.query_devices()
    input_devs  = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]

    print("\n" + "="*65)
    print("  DIAGNÓSTICO DE AUDIO — Alfonso / Acer Swift 314")
    print("="*65)

    if auto_device is not None:
        name = devices[auto_device]["name"] if auto_device < len(devices) else "?"
        print(f"\n  Micrófono integrado detectado automáticamente: [{auto_device}] {name}")
    else:
        print("\n  No se detectó micrófono integrado automáticamente.")

    print(f"\n  Probando {len(input_devs)} dispositivos de entrada...\n")
    print(f"  {'IDX':>3}  {'NOMBRE':<40}  {'RATE':>6}  {'MEDIA':>5}  {'PICO':>5}  STATUS")
    print("  " + "-"*75)

    results = []
    for idx, device in input_devs:
        name = device["name"][:38]
        rate = probe_device_samplerate(idx)
        try:
            data   = _record(idx, rate, TEST_SECONDS)
            amp    = _amplitude(data)
            pk     = _peak(data)
            signal = "✓ SEÑAL" if amp > 50 else "  silencio"
            print(f"  [{idx:>2}]  {name:<40}  {rate:>6}  {amp:>5}  {pk:>5}  {signal}")
            if amp > 50:
                results.append((idx, device["name"], amp, rate))
        except Exception as exc:
            print(f"  [{idx:>2}]  {name:<40}  {rate:>6}  ERROR: {str(exc)[:25]}")

    print("\n" + "-"*65)

    if not results:
        print("\n⚠  Ningún dispositivo captó señal.")
        print("   Posibles causas en Windows:")
        print("   1. Privacidad → Micrófono → permitir acceso a apps de escritorio")
        print("   2. El micrófono integrado está muteado en el mezclador de Windows")
        print("   3. Prueba hablar más cerca del micrófono durante los 2 segundos")
        print("\n   Prueba monitorización en tiempo real:")
        if auto_device is not None:
            print(f"       python audio_check.py --live --device {auto_device}")
        else:
            for idx, _ in input_devs[:3]:
                print(f"       python audio_check.py --live --device {idx}")
        return

    best_idx, best_name, best_amp, best_rate = max(results, key=lambda x: x[2])
    print(f"\n✓  Dispositivos con señal:")
    for idx, name, amp, rate in sorted(results, key=lambda x: x[2], reverse=True):
        marker = " ← RECOMENDADO" if idx == best_idx else ""
        print(f"     [{idx}] {name[:45]}  (media: {amp}, rate: {rate}Hz){marker}")

    threshold = max(80, best_amp // 4)
    print(f"\n   Umbral de silencio sugerido: {threshold}")
    print(f"\n   Para usar en Alfonso:")
    print(f"       python cliente.py --device {best_idx} --threshold {threshold}")
    print(f"\n   Para monitorizar en tiempo real:")
    print(f"       python audio_check.py --live --device {best_idx}")

    if best_rate != TARGET_RATE:
        print(f"\n⚠  El micrófono [{best_idx}] graba a {best_rate}Hz.")
        print(f"   Alfonso remuestreará automáticamente a {TARGET_RATE}Hz para Whisper.")
        print(f"   No necesitas hacer nada — el nuevo AudioService lo gestiona solo.")

    print()


# ---------------------------------------------------------------------------
# Monitorización en tiempo real
# ---------------------------------------------------------------------------

def live_monitor(device: int) -> None:
    devices = sd.query_devices()
    name    = devices[device]["name"] if device < len(devices) else f"device {device}"
    rate    = probe_device_samplerate(device)

    print(f"\n  Monitorización — [{device}] {name} @ {rate}Hz")
    print("  Habla para ver el nivel. Ctrl+C para salir.\n")
    print("  Nivel  0    500   1000  1500  2000  2500  3000+")
    print("         |     |     |     |     |     |     |")

    try:
        while True:
            try:
                data = _record(device, rate, 1)
                amp  = _amplitude(data)
                pk   = _peak(data)
                if amp < 80:
                    status = "SILENCIO"
                elif amp < 500:
                    status = "BAJO"
                else:
                    status = "BIEN ✓"
                print(f"\r  {_bar(amp)}  pico:{pk:5d}  {status}    ", end="", flush=True)
            except Exception as exc:
                print(f"\r  [ERROR: {exc}]", end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnóstico de audio para Alfonso")
    p.add_argument("--device", type=int, default=None, help="Índice del dispositivo a probar")
    p.add_argument("--live",   action="store_true",    help="Monitorización en tiempo real")
    return p.parse_args()


# typing Optional no importado arriba en el fallback
try:
    from typing import Optional
except ImportError:
    pass


if __name__ == "__main__":
    args       = parse_args()
    auto_dev   = auto_select_device()

    device = args.device if args.device is not None else auto_dev

    if args.live:
        if device is None:
            print("[!] No se detectó micrófono automáticamente. Usa --device N")
            sys.exit(1)
        live_monitor(device)
    else:
        run_full_test(auto_dev)