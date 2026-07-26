"""
PATHS UTILS — Utilidades para la resolución dinámica y multiplataforma de rutas.

¿QUÉ HACE?
Centraliza la lógica para determinar el sistema operativo, usuario y directorios
(Escritorio, Documentos, Home) del cliente conectado, traduciendo de forma adecuada
las rutas propuestas por el LLM sin acoplamientos al servidor.
"""

import os
import platform
import json
import re
from pathlib import Path
from app.utils.logger import tool_logger

def get_client_context(client_id: str | None = None) -> dict:
    """
    Obtiene los datos del cliente conectado consultando el bridge de Alfonso
    o leyendo la caché de data/last_client_info.json.
    Retorna un diccionario con: system, username, home, cwd.
    """
    from app.adapters.alfonso_bridge import bridge as alfonso_bridge

    client_info = None
    if client_id:
        client_info = alfonso_bridge._client_info_dict.get(client_id)
    if not client_info:
        client_info = alfonso_bridge.client_info

    if not client_info:
        try:
            info_file = Path("data/last_client_info.json")
            if info_file.exists():
                client_info = json.loads(info_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if client_info:
        return {
            "system": client_info.get("system", platform.system()),
            "username": client_info.get("username", Path.home().name),
            "home": client_info.get("home", str(Path.home().resolve())),
            "cwd": client_info.get("cwd", str(Path.cwd().resolve())),
            "release": client_info.get("release", "")
        }

    # Fallback al propio servidor
    return {
        "system": platform.system(),
        "username": Path.home().name,
        "home": str(Path.home().resolve()),
        "cwd": str(Path.cwd().resolve()),
        "release": platform.release()
    }

def get_client_desktop(client_id: str | None = None) -> str:
    """
    Obtiene la ruta del escritorio del cliente en su formato nativo (con barras inclinadas).
    """
    ctx = get_client_context(client_id)
    home = ctx["home"].replace("\\", "/")
    return f"{home}/Desktop"

def get_cv_path() -> Path:
    """Retorna la ruta absoluta del currículum en el servidor."""
    return Path(__file__).resolve().parents[2] / "data" / "cv.md"

def resolve_client_path(raw_path: str, client_id: str | None = None) -> str:
    """
    Normaliza y resuelve la ruta raw dada por el LLM en base al sistema del cliente.
    Reemplaza placeholders de usuario y formatea barras.
    """
    ctx = get_client_context(client_id)
    username = ctx["username"]
    system = ctx["system"]
    home = ctx["home"].replace("\\", "/")

    processed = raw_path.strip()

    # Reemplazar placeholders de usuario
    for placeholder in ["YOUR_USERNAME", "YourUsername", "your_username", "username"]:
        processed = processed.replace(placeholder, username)

    # Reemplazar la tilde de home
    if processed.startswith("~"):
        processed = processed.replace("~", home, 1)

    # Unificar barras
    processed = processed.replace("\\", "/")

    # Manejar corrección específica si el servidor corre en Linux/WSL y el cliente es Windows
    # Ejemplo: Si el modelo pide C:/Users/luisd/Desktop/... y estamos ejecutando localmente en WSL
    if platform.system() == "Linux" and system == "Windows":
        if len(processed) > 1 and processed[1] == ":":
            drive = processed[0].lower()
            remainder = processed[2:]
            # Solo si existe el montaje de WSL
            if os.path.exists(f"/mnt/{drive}"):
                processed = f"/mnt/{drive}{remainder}"

    return processed
