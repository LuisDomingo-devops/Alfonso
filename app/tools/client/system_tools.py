"""
SYSTEM TOOLS — Herramientas auxiliares del sistema operativo y control interactivo.

¿QUÉ HACE?
Proporciona utilidades para controlar periféricos de entrada (mouse/teclado), realizar capturas y OCR de pantalla, 
ejecutar comandos del sistema operativo y abrir/cerrar aplicaciones de forma local o remota a través del agente.
"""

import os
import platform
import shlex
import shutil
import subprocess
import psutil
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Sequence, Optional

from app.domain.actions import Action
from app.adapters.alfonso_bridge import bridge as alfonso_bridge
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
        if _IS_WSL:
            return ["explorer.exe"]
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
            return [win_app]

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
# Tools - Sistema e Información
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


async def open_application(command: str | Sequence[str], args: Sequence[str] | None = None, client_id: str | None = None) -> dict:
    command_text = (
        command if isinstance(command, str)
        else " ".join(shlex.quote(str(part)) for part in (list(command) + list(args or [])))
    )

    if alfonso_bridge.has_clients():
        tool_logger.info("Delegando open_application al agente local: %s", command_text)
        response = await alfonso_bridge.send_command(Action.OPEN_APP, {"command": command_text}, client_id=client_id)
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


async def close_application(command: str, client_id: str | None = None) -> dict:
    target = command.strip()

    if alfonso_bridge.has_clients():
        tool_logger.info("Delegando close_application al agente local: %s", target)
        response = await alfonso_bridge.send_command(Action.CLOSE_APP, {"command": target}, client_id=client_id)
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


async def open_url(url: str, client_id: str | None = None) -> dict:
    url = url.strip()
    if not url:
        return {"status": "error", "message": "URL no especificada"}

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    if alfonso_bridge.has_clients():
        tool_logger.info("Delegando open_url al agente local: %s", url)
        response = await alfonso_bridge.send_command(Action.OPEN_URL, {"url": url}, client_id=client_id)
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
    from app.tools.client.browser_tools import browser_navigate
    return await browser_navigate(url, client_id=client_id)


# ---------------------------------------------------------------------------
# Fallbacks server-side
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


# ---------------------------------------------------------------------------
# Código Importado de computer_use_tools.py
# ---------------------------------------------------------------------------

async def _delegate_computer(action: str, params: dict, client_id: str | None = None) -> dict:
    """Envía la acción al agente local y normaliza la respuesta."""
    if not alfonso_bridge.has_clients():
        error_logger.warning(
            "computer_use: no hay agente local conectado para '%s'. "
            "Arranca ui/alfonso_agent.py en tu equipo.",
            action,
        )
        return {
            "status": "error",
            "message": (
                f"No hay agente local conectado. La acción '{action}' "
                "requiere controlar tu equipo directamente; ejecuta "
                "ui/alfonso_agent.py en tu máquina y vuelve a intentarlo."
            ),
        }

    tool_logger.info("computer_use: delegando '%s' args=%s client_id=%s", action, params, client_id)
    response = await alfonso_bridge.send_command(action, params, client_id=client_id)

    if response.get("status") == "success":
        result = response.get("result")
        if isinstance(result, dict):
            return {"status": "ok", **result}
        return {"status": "ok", "result": result}

    return {
        "status": "error",
        "message": response.get(
            "error", f"Error desconocido ejecutando '{action}' en el agente local."
        ),
    }


async def screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    save_path: Optional[str] = None,
    client_id: str | None = None,
) -> dict:
    return await _delegate_computer(Action.SCREEN_SCREENSHOT, {"region": region, "save_path": save_path}, client_id=client_id)


async def mouse_move(x: int, y: int, duration: float = 0.25, client_id: str | None = None) -> dict:
    return await _delegate_computer(Action.MOUSE_MOVE, {"x": x, "y": y, "duration": duration}, client_id=client_id)


async def mouse_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
    client_id: str | None = None,
) -> dict:
    return await _delegate_computer(
        Action.MOUSE_CLICK,
        {"x": x, "y": y, "button": button, "clicks": clicks, "interval": interval},
        client_id=client_id,
    )


async def mouse_drag(
    x1: int, y1: int,
    x2: int, y2: int,
    duration: float = 0.5,
    button: str = "left",
    client_id: str | None = None,
) -> dict:
    return await _delegate_computer(
        Action.MOUSE_DRAG,
        {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration, "button": button},
        client_id=client_id,
    )


async def keyboard_type(text: str, interval: float = 0.03, client_id: str | None = None) -> dict:
    return await _delegate_computer(Action.KEYBOARD_TYPE, {"text": text, "interval": interval}, client_id=client_id)


async def keyboard_hotkey(*args_keys: str, keys: list[str] | None = None, client_id: str | None = None) -> dict:
    final_keys = list(args_keys) if args_keys else (keys or [])
    return await _delegate_computer(Action.KEYBOARD_HOTKEY, {"keys": final_keys}, client_id=client_id)


async def ocr_screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    lang: str = "spa+eng",
    client_id: str | None = None,
) -> dict:
    return await _delegate_computer(Action.SCREEN_OCR_SCREENSHOT, {"region": region, "lang": lang}, client_id=client_id)


async def ocr_image(path: str, lang: str = "spa+eng", client_id: str | None = None) -> dict:
    return await _delegate_computer(Action.SCREEN_OCR_IMAGE, {"path": path, "lang": lang}, client_id=client_id)


async def find_on_screen(
    template_path: str,
    threshold: float = 0.8,
    region: Optional[tuple[int, int, int, int]] = None,
    client_id: str | None = None,
) -> dict:
    return await _delegate_computer(
        Action.SCREEN_FIND,
        {"template_path": template_path, "threshold": threshold, "region": region},
        client_id=client_id,
    )


async def window_list(client_id: str | None = None) -> dict:
    return await _delegate_computer(Action.WINDOW_LIST, {}, client_id=client_id)


async def window_focus(title: str, client_id: str | None = None) -> dict:
    return await _delegate_computer(Action.WINDOW_FOCUS, {"title": title}, client_id=client_id)


async def window_close(title: str, client_id: str | None = None) -> dict:
    return await _delegate_computer(Action.WINDOW_CLOSE, {"title": title}, client_id=client_id)


# ---------------------------------------------------------------------------
# Código Importado de command_executor.py
# ---------------------------------------------------------------------------

DANGEROUS_COMMANDS = {
    "rm",
    "del",
    "shutdown",
    "reboot",
    "poweroff",
    "format",
    "mkfs",
    "dd",
}

_FORK_BOMB_PATTERN = re.compile(r":\s*\(\s*\)\s*\{")


def _normalize_terminal_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return list(command)


def _is_safe_command(command_parts: list[str]) -> bool:
    for token in command_parts:
        if token.lower() in DANGEROUS_COMMANDS:
            return False
    return True


async def run_command(command: str | Sequence[str], cwd: str | None = None):
    if isinstance(command, str) and _FORK_BOMB_PATTERN.search(command):
        error_logger.warning("Comando bloqueado por política de seguridad (fork bomb detectada): %s", command)
        return {"status": "error", "message": "Comando no permitido"}

    command_parts = _normalize_terminal_command(command)
    tool_logger.info("Intentando ejecutar comando: %s", command_parts)

    if not command_parts:
        error_logger.warning("Comando vacío recibido")
        return {"status": "error", "message": "Comando vacío"}

    if not _is_safe_command(command_parts):
        error_logger.warning("Comando bloqueado por política de seguridad: %s", command_parts)
        return {"status": "error", "message": "Comando no permitido"}

    try:
        result = subprocess.run(
            command_parts,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )

        tool_logger.info("Comando ejecutado con código %s", result.returncode)
        return {
            "status": "ok",
            "command": command_parts,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    except Exception as exc:
        error_logger.exception("Error ejecutando comando")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Registro Unificado de Herramientas (TOOLS)
# ---------------------------------------------------------------------------

TOOLS = {
    # system_info / apps / url / date
    "system_info":          get_system_info,
    "open_application":     open_application,
    "close_application":    close_application,
    "get_current_datetime": get_current_datetime,
    "open_url":             open_url,
    
    # computer_use
    "screenshot":           screenshot,
    "mouse_move":           mouse_move,
    "mouse_click":          mouse_click,
    "mouse_drag":           mouse_drag,
    "keyboard_type":        keyboard_type,
    "keyboard_hotkey":      keyboard_hotkey,
    "ocr_screenshot":       ocr_screenshot,
    "ocr_image":            ocr_image,
    "find_on_screen":       find_on_screen,
    "window_list":          window_list,
    "window_focus":         window_focus,
    "window_close":         window_close,
    
    # command_executor
    "run_command":          run_command,
}