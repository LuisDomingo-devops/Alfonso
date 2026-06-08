"""
system_tools.py — Fase 3 (fixed)

Fixes aplicados:
- get_system_info(): añadido "status": "ok" al dict de retorno para que
  SystemAgent lo reconozca como éxito (antes fallaba silenciosamente).
- open_application(): sin cambios funcionales.
- get_current_datetime(): sin cambios (ya tenía status:ok).
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
from app.utils.logger import tool_logger, error_logger


# Alias de comandos amigables → binarios reales
_APP_ALIASES: dict[str, list[str]] = {
    "internet":               ["xdg-open", "https://www.google.com"],
    "explorador":             [],  # se resuelve dinámicamente
    "explorador de archivos": [],
    "gestor de archivos":     [],
    "file manager":           [],
}

# Gestores de archivos por orden de preferencia (priorizando explorer.exe para integración con Windows/WSL)
_FILE_MANAGERS = ["explorer.exe", "nautilus", "nemo", "thunar", "dolphin", "caja", "pcmanfm", "xdg-open"]


def _find_file_manager() -> list[str] | None:
    """Devuelve el primer gestor de archivos disponible en el sistema."""
    for fm in _FILE_MANAGERS:
        if shutil.which(fm):
            tool_logger.info("Gestor de archivos detectado: %s", fm)
            if fm == "xdg-open":
                return [fm, str(Path.home())]
            if fm == "explorer.exe":
                # En WSL, explorer.exe . abre la carpeta actual de Linux en Windows
                return [fm, "."]
            return [fm]
    return None


def _normalize_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        lower = command.strip().lower()
        if lower in _APP_ALIASES:
            if not _APP_ALIASES[lower]:
                fm = _find_file_manager()
                return fm if fm else []
            return _APP_ALIASES[lower]
        if "explorad" in lower or "file manager" in lower or "gestor de archivo" in lower:
            fm = _find_file_manager()
            return fm if fm else []
        if os.name == "nt":
            return shlex.split(command, posix=False)
        return shlex.split(command)
    return list(command)


def _is_safe(command_parts: list[str]) -> bool:
    dangerous = {
        "rm", "del", "shutdown", "reboot", "poweroff",
        "format", "mkfs", "dd", ":()",
    }
    for token in command_parts:
        if token.lower() in dangerous:
            return False
    return True


async def get_system_info() -> dict:
    """
    Retorna información básica del sistema.
    FIX: ahora incluye 'status': 'ok' para que SystemAgent lo reconozca
    como éxito en lugar de error silencioso.
    """
    tool_logger.info("Obteniendo información del sistema")
    try:
        return {
            "status": "ok",
            "system": platform.system(),
            "version": platform.version(),
            "cpu": os.cpu_count(),
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
    """
    Devuelve la fecha y hora actuales del sistema operativo.
    Úsalo para responder preguntas del tipo '¿qué hora es?' o '¿qué día es hoy?'
    """
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
        command_parts.extend(list(args))

    tool_logger.info("Intentando abrir aplicación: %s", command_parts)

    if not command_parts:
        error_logger.warning("Aplicación no especificada")
        return {"status": "error", "message": "Aplicación no especificada"}

    if not _is_safe(command_parts):
        error_logger.warning("Aplicación bloqueada: %s", command_parts)
        return {"status": "error", "message": "Aplicación no permitida por política de seguridad"}

    binary = command_parts[0]
    if shutil.which(binary) is None and not Path(binary).exists():
        if shutil.which("xdg-open") and len(command_parts) == 1:
            tool_logger.info("Binario '%s' no encontrado; intentando xdg-open", binary)
            command_parts = ["xdg-open", binary]
        else:
            error_logger.warning("Aplicación no encontrada: %s", binary)
            return {
                "status": "error",
                "message": (
                    f"Aplicación no encontrada: {binary}. "
                    "En WSL asegúrate de tener el paquete instalado."
                ),
            }

    try:
        process = subprocess.Popen(
            command_parts,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        tool_logger.info("Aplicación abierta con PID %s", process.pid)
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
    """Cierra aplicaciones buscando por nombre de proceso."""
    tool_logger.info("Intentando cerrar aplicación: %s", command)
    target = command.lower()
    closed_count = 0
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # Verificamos si el nombre del proceso contiene lo que el usuario pidió
                if target in proc.info['name'].lower():
                    proc.terminate()
                    closed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        if closed_count > 0:
            tool_logger.info("Se cerraron %d procesos de %s", closed_count, command)
            return {"status": "ok", "message": f"Se han cerrado las instancias de {command}"}
        
        error_logger.warning("No se encontró ninguna aplicación abierta con el nombre: %s", command)
        return {"status": "error", "message": f"No se encontró ninguna aplicación abierta llamada {command}"}
    except Exception as exc:
        error_logger.exception("Error cerrando aplicación")
        return {"status": "error", "message": str(exc)}
    
    
TOOLS = {
    "system_info": get_system_info,
    "open_application": open_application,
    "get_current_datetime": get_current_datetime,
    "close_application": close_application,
}