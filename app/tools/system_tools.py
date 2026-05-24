import os
import platform
import shlex
import shutil
import subprocess
import psutil
from pathlib import Path
from typing import Sequence
from app.utils.logger import tool_logger, error_logger


def _normalize_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        if os.name == "nt":
            return shlex.split(command, posix=False)
        return shlex.split(command)
    return list(command)


def _is_safe(command_parts: list[str]) -> bool:
    for token in command_parts:
        if token.lower() in {
            "rm",
            "del",
            "shutdown",
            "reboot",
            "poweroff",
            "format",
            "mkfs",
            "dd",
            ":()",
        }:
            return False
    return True


async def get_system_info():
    tool_logger.info("Obteniendo información del sistema")

    return {
        "system": platform.system(),
        "version": platform.version(),
        "cpu": os.cpu_count(),
        "ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 2),
        "ram_available_gb": round(psutil.virtual_memory().available / 1024**3, 2),
    }


async def open_application(command: str | Sequence[str], args: Sequence[str] | None = None):
    command_parts = _normalize_command(command)
    if args:
        command_parts.extend(list(args))

    tool_logger.info("Intentando abrir aplicación: %s", command_parts)

    if not command_parts:
        error_logger.warning("Aplicación no especificada")
        return {"status": "error", "message": "Aplicación no especificada"}

    if not _is_safe(command_parts):
        error_logger.warning("Aplicación bloqueada por política de seguridad: %s", command_parts)
        return {"status": "error", "message": "Aplicación no permitida"}

    if shutil.which(command_parts[0]) is None and not Path(command_parts[0]).exists():
        error_logger.warning("Aplicación no encontrada: %s", command_parts[0])
        return {"status": "error", "message": "Aplicación no encontrada"}

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

TOOLS = {
    "system_info": get_system_info,
    "open_application": open_application,
}