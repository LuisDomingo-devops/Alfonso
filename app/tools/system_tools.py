"""
system_tools.py — Fase 3 (fixed v3)

Fixes respecto a versión anterior:
1. open_application(): acepta nombres de app cortos sin extensión
   ("firefox" funciona sin path completo en WSL).
2. _normalize_command(): normaliza nombres comunes como "google",
   "chrome" → "google-chrome" o "chromium-browser".
3. WSL display: intenta detectar DISPLAY; si no está disponible,
   usa cmd.exe /C start para apps Windows desde WSL.
4. close_application(): ahora maneja también nombres como "chromium",
   "google-chrome", "chromium-browser".
5. get_system_info(): garantiza status:ok siempre.
"""

import os
import platform
import shlex
import shutil
import subprocess
import psutil
from datetime import datetime
from pathlib import Path
from typing import Sequence

from app.core.alfonso_bridge import bridge as alfonso_bridge
from app.utils.logger import tool_logger, error_logger

# ---------------------------------------------------------------------------
# Alias y detección de entorno
# ---------------------------------------------------------------------------

_IS_WSL = "microsoft" in platform.uname().release.lower() or \
          os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")

_APP_ALIASES: dict[str, list[str]] = {
    "internet":               ["xdg-open", "https://www.google.com"],
    "google":                 ["xdg-open", "https://www.google.com"],
    "explorador":             [],   # se resuelve con _find_file_manager
    "explorador de archivos": [],
    "gestor de archivos":     [],
    "file manager":           [],
    # Alias para nombres frecuentes en voz
    "chrome":                 ["google-chrome", "chromium-browser", "chromium"],
    "chromium":               ["chromium-browser", "chromium", "google-chrome"],
    "vscode":                 ["code"],
    "visual studio code":     ["code"],
    "terminal":               ["x-terminal-emulator", "gnome-terminal", "konsole", "xterm"],
    "notepad":                ["gedit", "kate", "mousepad", "xed"],
}

_FILE_MANAGERS = ["nautilus", "nemo", "thunar", "dolphin", "caja", "pcmanfm", "xdg-open"]

_DANGEROUS = {"rm", "del", "shutdown", "reboot", "poweroff", "format", "mkfs", "dd", ":()"}


def _find_file_manager() -> list[str] | None:
    for fm in _FILE_MANAGERS:
        if shutil.which(fm):
            tool_logger.info("Gestor de archivos detectado: %s", fm)
            if fm == "xdg-open":
                return [fm, str(Path.home())]
            return [fm]
    return None


def _has_display() -> bool:
    """Comprueba si hay un servidor X disponible."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _wsl_open(app_name: str) -> list[str] | None:
    """
    En WSL, intenta abrir una app Windows mediante PowerShell.
    Útil para firefox.exe, explorer.exe, etc.
    """
    if not _IS_WSL:
        return None
    # Intentar con powershell.exe Start-Process
    return ["powershell.exe", "-Command", f"Start-Process '{app_name}'"]


def _resolve_app(name: str) -> list[str] | None:
    """
    Resuelve el nombre de una aplicación a una lista de argumentos ejecutables.
    Devuelve None si no se puede resolver.
    """
    lower = name.strip().lower()

    # 1. Alias explícitos
    if lower in _APP_ALIASES:
        candidates = _APP_ALIASES[lower]
        if not candidates:
            return _find_file_manager()
        # Buscar el primero disponible
        for candidate in candidates:
            if shutil.which(candidate):
                return [candidate]
        return None

    # 2. Explorador de archivos por keywords
    if any(k in lower for k in ("explorad", "file manager", "gestor de archivo")):
        return _find_file_manager()

    # 3. Binario disponible directamente
    if shutil.which(name):
        return [name]

    # 4. En WSL: intentar via PowerShell
    if _IS_WSL:
        # Nombres comunes que pueden existir en Windows
        windows_apps = {
            "firefox": "firefox.exe",
            "chrome": "chrome.exe",
            "notepad": "notepad.exe",
            "explorer": "explorer.exe",
        }
        win_app = windows_apps.get(lower)
        if win_app:
            return _wsl_open(win_app)

    return None


def _normalize_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, (list, tuple)):
        return list(command)

    command = command.strip()
    resolved = _resolve_app(command)
    if resolved:
        return resolved

    # Parsear como línea de comando normal
    try:
        if os.name == "nt":
            return shlex.split(command, posix=False)
        return shlex.split(command)
    except ValueError:
        return [command]


def _is_safe(command_parts: list[str]) -> bool:
    for token in command_parts:
        if token.lower() in _DANGEROUS:
            return False
    return True


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

async def get_system_info() -> dict:
    tool_logger.info("Obteniendo información del sistema")
    try:
        return {
            "status": "ok",
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "is_wsl": _IS_WSL,
            "cpu_count": os.cpu_count(),
            "ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 2),
            "ram_available_gb": round(psutil.virtual_memory().available / 1024**3, 2),
            "ram_used_percent": psutil.virtual_memory().percent,
            "disk_total_gb": round(psutil.disk_usage("/").total / 1024**3, 2),
            "disk_free_gb": round(psutil.disk_usage("/").free / 1024**3, 2),
        }
    except Exception as exc:
        error_logger.exception("Error obteniendo info del sistema")
        return {"status": "error", "message": str(exc)}


async def get_current_datetime() -> dict:
    tool_logger.info("Obteniendo fecha y hora del sistema")
    now = datetime.now()
    days_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months_es = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    return {
        "status": "ok",
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": days_es[now.weekday()],
        "day": now.day,
        "month": months_es[now.month - 1],
        "year": now.year,
        "human": (
            f"{days_es[now.weekday()]}, {now.day} de {months_es[now.month - 1]}"
            f" de {now.year}, {now.strftime('%H:%M')}"
        ),
    }


async def open_application(command: str | Sequence[str], args: Sequence[str] | None = None) -> dict:
    command_parts = _normalize_command(command)
    if args:
        command_parts = list(command_parts) + list(args)

    if alfonso_bridge.has_clients():
        command_text = (
            command if isinstance(command, str)
            else " ".join(shlex.quote(str(part)) for part in command_parts)
        )
        tool_logger.info("Delegando open_application al agente local: %s", command_text)
        response = await alfonso_bridge.send_command(
            "open_app",
            {"command": command_text},
        )
        if response.get("status") == "success":
            return {
                "status": "ok",
                "message": response.get("result"),
                "delegate": "alfonso_agent",
                "command": command_text,
            }
        return {
            "status": "error",
            "message": response.get("error", "Error delegando al agente local."),
            "delegate": "alfonso_agent",
            "details": response,
        }

    tool_logger.info("Intentando abrir aplicación: %s (wsl=%s, display=%s)",
                     command_parts, _IS_WSL, _has_display())

    if not command_parts:
        return {"status": "error", "message": "Aplicación no especificada"}

    if not _is_safe(command_parts):
        return {"status": "error", "message": "Aplicación no permitida por política de seguridad"}

    binary = command_parts[0]

    # Verificar binario disponible
    if shutil.which(binary) is None and not Path(binary).exists():
        # Último intento en WSL: PowerShell
        if _IS_WSL:
            wsl_cmd = _wsl_open(str(command) if isinstance(command, str) else command_parts[0])
            if wsl_cmd:
                tool_logger.info("Intentando apertura via WSL PowerShell: %s", wsl_cmd)
                command_parts = wsl_cmd
                binary = command_parts[0]
        
        if shutil.which(binary) is None and not Path(binary).exists():
            # Intentar con xdg-open como último recurso
            if shutil.which("xdg-open") and len(command_parts) == 1:
                tool_logger.info("Binario '%s' no encontrado; usando xdg-open", binary)
                command_parts = ["xdg-open", binary]
            else:
                error_logger.warning("Aplicación no encontrada: %s", binary)
                hint = (
                    "En WSL, asegúrate de tener DISPLAY configurado o usa la versión .exe de la app."
                    if _IS_WSL else "Asegúrate de tener el paquete instalado."
                )
                return {
                    "status": "error",
                    "message": f"Aplicación no encontrada: {binary}. {hint}",
                }

    # Advertir si no hay display pero la app probablemente lo necesite
    if not _has_display() and _IS_WSL and binary not in ("powershell.exe", "cmd.exe"):
        tool_logger.warning("No se detectó DISPLAY. La app gráfica puede no abrirse visualmente.")

    try:
        env = os.environ.copy()
        # En WSL, intentar heredar DISPLAY si está disponible
        if _IS_WSL and not env.get("DISPLAY"):
            env["DISPLAY"] = ":0"

        process = subprocess.Popen(
            command_parts,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        tool_logger.info("Aplicación abierta con PID %s: %s", process.pid, command_parts)
        return {
            "status": "ok",
            "pid": process.pid,
            "command": command_parts,
            "message": f"Aplicación iniciada: {command_parts[0]}",
        }
    except Exception as exc:
        error_logger.exception("Error abriendo aplicación")
        return {"status": "error", "message": str(exc)}


async def close_application(command: str) -> dict:
    """
    Cierra procesos por nombre.
    Maneja aliases: 'chrome' cierra también 'google-chrome', 'chromium-browser', etc.
    """
    tool_logger.info("Intentando cerrar aplicación: %s", command)
    target = command.strip().lower()

    # Expandir con aliases conocidos
    _CLOSE_ALIASES: dict[str, list[str]] = {
        "chrome": ["chrome", "google-chrome", "chromium", "chromium-browser"],
        "firefox": ["firefox", "firefox-esr"],
        "vscode": ["code", "vscode"],
        "terminal": ["gnome-terminal", "konsole", "xterm", "bash", "sh"],
    }
    targets = _CLOSE_ALIASES.get(target, [target])

    closed: list[int] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            proc_name = proc.info["name"].lower()
            if any(t in proc_name for t in targets):
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
                closed.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if closed:
        tool_logger.info("Cerrados %d procesos de '%s': pids=%s", len(closed), command, closed)
        return {
            "status": "ok",
            "message": f"Cerradas {len(closed)} instancias de {command}.",
            "pids": closed,
        }

    error_logger.warning("No se encontró proceso con nombre: %s", command)
    return {
        "status": "error",
        "message": f"No hay ninguna aplicación abierta llamada '{command}'.",
    }


TOOLS = {
    "system_info":          get_system_info,
    "open_application":     open_application,
    "close_application":    close_application,
    "get_current_datetime": get_current_datetime,
}