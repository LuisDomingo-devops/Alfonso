import re
import shlex
import subprocess
from typing import Sequence
from app.utils.logger import tool_logger, error_logger

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

# FIX: ":()" nunca coincidía con ningún token real producido por shlex.split()
# de una fork bomb (":(){ :|:& };:" se tokeniza como ':(){', ':|:&', '};:',
# nunca como ':()'), así que esta protección nunca se activaba. Se detecta
# el patrón directamente sobre el string original, antes de tokenizar.
_FORK_BOMB_PATTERN = re.compile(r":\s*\(\s*\)\s*\{")


def _normalize_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return list(command)


def _is_safe(command_parts: list[str]) -> bool:
    for token in command_parts:
        if token.lower() in DANGEROUS_COMMANDS:
            return False
    return True


async def run_command(command: str | Sequence[str], cwd: str | None = None):
    if isinstance(command, str) and _FORK_BOMB_PATTERN.search(command):
        error_logger.warning("Comando bloqueado por política de seguridad (fork bomb detectada): %s", command)
        return {"status": "error", "message": "Comando no permitido"}

    command_parts = _normalize_command(command)
    tool_logger.info("Intentando ejecutar comando: %s", command_parts)

    if not command_parts:
        error_logger.warning("Comando vacío recibido")
        return {"status": "error", "message": "Comando vacío"}

    if not _is_safe(command_parts):
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


TOOLS = {
    "run_command": run_command,
}