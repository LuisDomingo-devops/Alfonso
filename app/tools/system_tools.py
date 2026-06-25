"""
system_tools.py — Fase 3 (fixed v4)

Fixes respecto a versión anterior (v3):
1. open_application(): acepta nombres de app cortos sin extensión
   ("firefox" funciona sin path completo en WSL).
2. _normalize_command(): normaliza nombres comunes como "google",
   "chrome" → "google-chrome" o "chromium-browser".
3. WSL display: intenta detectar DISPLAY; si no está disponible,
   usa cmd.exe /C start para apps Windows desde WSL.
4. close_application(): ahora maneja también nombres como "chromium",
   "google-chrome", "chromium-browser".
5. get_system_info(): garantiza status:ok siempre.
6. FIX (revisión escaneo de apps host): cuando no hay agente local
   conectado vía alfonso_bridge, se emite un warning explícito indicando
   que la app se abrirá en WSL y NO en el host Windows, para evitar
   confusión cuando el usuario espera ver la app en su escritorio Windows
   pero el agente local (ui/alfonso_agent.py) no está corriendo.
7. FIX (unificación de tablas de acciones): los literales "open_app",
   "close_app", "open_url" que se mandaban al bridge ahora vienen de
   app.core.actions.Action — mismo valor exacto, pero ya no son una copia
   independiente que pueda divergir de ALLOWED_ACTIONS.
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

from app.core.actions import Action
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
    "terminal":               ["x-terminal-emulator", "gnome-terminal", "konsole", "xterm", "terminal", "bash", "sh", "cmd", "powershell"],
    "notepad":                ["gedit", "kate", "mousepad", "xed", "leafpad", "notepad"],
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
    """
    Abre una aplicación EN EL EQUIPO DEL USUARIO, siempre vía el agente local.

    FIX: antes, si no había agente conectado, esta función caía en un
    fallback que abría el binario dentro del contenedor/WSL del servidor
    (logs/tools.log: "se intentará abrir dentro de WSL, NO en el host
    Windows"). Esto violaba la separación cliente/servidor: el usuario
    pedía abrir Firefox en SU escritorio y obtenía un proceso fantasma en
    WSL. Ahora se delega siempre; si no hay agente, se devuelve un error
    explícito en vez de actuar sobre el servidor.

    Excepción opt-in: si ALFONSO_ALLOW_SERVER_EXEC_FALLBACK=true está en el
    entorno (uso explícito y consciente, p. ej. servidor Linux de escritorio
    sin WSL), se permite el viejo comportamiento local como último recurso.
    """
    command_text = (
        command if isinstance(command, str)
        else " ".join(shlex.quote(str(part)) for part in (list(command) + list(args or [])))
    )

    if alfonso_bridge.has_clients():
        tool_logger.info("Delegando open_application al agente local: %s", command_text)
        response = await alfonso_bridge.send_command(Action.OPEN_APP, {"command": command_text})
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

    error_logger.warning(
        "No hay agente local conectado (alfonso_bridge.has_clients()=False). "
        "No se puede abrir '%s' en el equipo del usuario.",
        command_text,
    )

    if os.getenv("ALFONSO_ALLOW_SERVER_EXEC_FALLBACK", "false").lower() == "true":
        return await _open_application_server_fallback(command, args)

    return {
        "status": "error",
        "message": (
            f"No hay agente local conectado. No puedo abrir '{command_text}' en tu "
            "equipo. Arranca ui/alfonso_agent.py en tu máquina (Windows/Linux) y "
            "vuelve a intentarlo."
        ),
    }


async def close_application(command: str) -> dict:
    """
    Cierra una aplicación EN EL EQUIPO DEL USUARIO, siempre vía el agente local.

    FIX: antes esta función NUNCA delegaba — solo mataba procesos con
    `psutil` dentro del contenedor WSL del servidor. Por eso "cierra
    firefox" podía reportar éxito ("Cerrados 1 procesos") sin afectar al
    Firefox real del usuario en Windows. Ahora se delega siempre.
    """
    target = command.strip()

    if alfonso_bridge.has_clients():
        tool_logger.info("Delegando close_application al agente local: %s", target)
        response = await alfonso_bridge.send_command(Action.CLOSE_APP, {"command": target})
        if response.get("status") == "success":
            return {
                "status": "ok",
                "message": response.get("result"),
                "delegate": "alfonso_agent",
                "command": target,
            }
        return {
            "status": "error",
            "message": response.get("error", "Error delegando al agente local."),
            "delegate": "alfonso_agent",
            "details": response,
        }

    error_logger.warning(
        "No hay agente local conectado (alfonso_bridge.has_clients()=False). "
        "No se puede cerrar '%s' en el equipo del usuario.",
        target,
    )

    if os.getenv("ALFONSO_ALLOW_SERVER_EXEC_FALLBACK", "false").lower() == "true":
        return await _close_application_server_fallback(target)

    return {
        "status": "error",
        "message": (
            f"No hay agente local conectado. No puedo cerrar '{target}' en tu "
            "equipo. Arranca ui/alfonso_agent.py en tu máquina y vuelve a intentarlo."
        ),
    }
async def open_url(url: str) -> dict:
    """
    Abre una URL en el navegador predeterminado del CLIENTE conectado
    (vía alfonso_bridge). Si no hay agente local conectado, cae a
    Playwright en el servidor como fallback (modo automatización/scraping,
    NO visible para el usuario — solo para cuando Alfonso opera solo).
    """
    url = url.strip()
    if not url:
        return {"status": "error", "message": "URL no especificada"}

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if alfonso_bridge.has_clients():
        tool_logger.info("Delegando open_url al agente local: %s", url)
        response = await alfonso_bridge.send_command(Action.OPEN_URL, {"url": url})
        if response.get("status") == "success":
            return {
                "status": "ok",
                "message": response.get("result"),
                "delegate": "alfonso_agent",
                "url": url,
            }
        return {
            "status": "error",
            "message": response.get("error", "Error abriendo la URL en el cliente."),
            "delegate": "alfonso_agent",
        }

    tool_logger.warning(
        "No hay agente local conectado; '%s' se abrirá en Playwright en el "
        "servidor y NO se verá en pantalla del cliente. Arranca "
        "ui/alfonso_agent.py para delegar correctamente.",
        url,
    )
    from app.tools.browser_tools import browser_navigate
    return await browser_navigate(url)


# ---------------------------------------------------------------------------
# Fallbacks server-side (SOLO si ALFONSO_ALLOW_SERVER_EXEC_FALLBACK=true)
# Conservan la lógica original — útil únicamente si el servidor corre con
# acceso directo a un escritorio real (no WSL) y se quiere usar como agente
# de sí mismo conscientemente.
# ---------------------------------------------------------------------------

async def _open_application_server_fallback(command, args):
    command_parts = _normalize_command(command)
    if args:
        command_parts = list(command_parts) + list(args)

    tool_logger.warning(
        "ALFONSO_ALLOW_SERVER_EXEC_FALLBACK activo: abriendo '%s' en el SERVIDOR, no en el cliente.",
        command_parts,
    )

    if not command_parts:
        return {"status": "error", "message": "Aplicación no especificada"}
    if not _is_safe(command_parts):
        return {"status": "error", "message": "Aplicación no permitida por política de seguridad"}

    binary = command_parts[0]
    if shutil.which(binary) is None and not Path(binary).exists():
        if shutil.which("xdg-open") and len(command_parts) == 1:
            command_parts = ["xdg-open", binary]
        else:
            return {"status": "error", "message": f"Aplicación no encontrada en el servidor: {binary}"}

    try:
        process = subprocess.Popen(
            command_parts,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "status": "ok",
            "pid": process.pid,
            "command": command_parts,
            "message": f"[SERVIDOR] Aplicación iniciada: {command_parts[0]}",
            "delegate": "server_fallback",
        }
    except Exception as exc:
        error_logger.exception("Error en fallback server-side de open_application")
        return {"status": "error", "message": str(exc)}


async def _close_application_server_fallback(target: str):
    tool_logger.warning(
        "ALFONSO_ALLOW_SERVER_EXEC_FALLBACK activo: cerrando '%s' en el SERVIDOR, no en el cliente.",
        target,
    )
    _CLOSE_ALIASES = {
        "chrome": ["chrome", "google-chrome", "chromium", "chromium-browser"],
        "firefox": ["firefox", "firefox-esr"],
        "vscode": ["code", "vscode"],
        "terminal": ["gnome-terminal", "konsole", "xterm", "bash", "sh"],
    }
    targets = _CLOSE_ALIASES.get(target.lower(), [target.lower()])

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
        return {
            "status": "ok",
            "message": f"[SERVIDOR] Cerradas {len(closed)} instancias de {target}.",
            "pids": closed,
            "delegate": "server_fallback",
        }
    return {"status": "error", "message": f"No hay ninguna aplicación abierta llamada '{target}' en el servidor."}


TOOLS = {
    "system_info":          get_system_info,
    "open_application":     open_application,
    "close_application":    close_application,
    "get_current_datetime": get_current_datetime,
    "open_url":             open_url,
}