from pathlib import Path
from app.utils.logger import tool_logger, error_logger
import os

# Helper to get the current user's home directory path
def get_current_user_home_path():
    return Path.home()

async def create_file(path: str, content: str):

    tool_logger.info(f"Intentando crear archivo: {path}")
    processed_path = path
    current_user_home = get_current_user_home_path()
    current_user_name = current_user_home.name

    # 1. Manejar rutas de Windows (ej: C:\...) en WSL (/mnt/c/...)
    if len(processed_path) > 1 and processed_path[1] == ":":
        drive = processed_path[0].lower()
        remainder = processed_path[2:].replace("\\", "/")
        processed_path = f"/mnt/{drive}{remainder}"
        tool_logger.info(f"Ruta de Windows detectada. Corrigiendo a WSL: {processed_path}")

    # 2. Corregir rutas de macOS y placeholders comunes (YourUsername -> luisd)
    if processed_path.startswith("/Users/"):
        processed_path = processed_path.replace("/Users/", "/home/", 1)

    processed_path = processed_path.replace("YourUsername", current_user_name).replace("username", current_user_name)

    p = Path(processed_path).expanduser()
    
    if not p.is_absolute():
        parts = p.parts
        # If the path starts with 'users/' or 'home/' and the *next* part matches the current user's name,
        # then resolve it relative to the current user's actual home directory.
        if len(parts) > 1 and parts[0].lower() in ["users", "home"] and parts[1].lower() == current_user_name.lower():
            p = current_user_home / Path(*parts[2:])
            tool_logger.info(f"Ruta relativa detectada como estructura de home del usuario actual. Ajustando a: {p}")
        else:
            # For any other relative path (including "users/otheruser/..." or "home/otheruser/..."),
            # resolve against the current working directory.
            tool_logger.info(f"Ruta relativa detectada, convirtiendo a absoluta en CWD: {p}")
            p = Path.cwd() / p
    
    tool_logger.info(f"Ruta absoluta final: {p}")
    
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except PermissionError as e: # Catch PermissionError specifically
        error_logger.error(f"Error de permisos al crear {p}: {e}")
        return {"status": "error", "message": f"Permiso denegado. No se puede escribir en {p.parent}. Intenta usar una ruta dentro de {get_current_user_home_path()}/"}
    except Exception as e: # Catch any other unexpected errors
        error_logger.error(f"Error inesperado al crear {p}: {e}")
        return {"status": "error", "message": f"Error inesperado al crear archivo: {e}"}

    tool_logger.info(f"Archivo creado exitosamente: {p}")
    return {
        "status": "ok",
        "message": f"Archivo creado: {p}"
    }


async def read_file(path: str):

    tool_logger.info(f"Intentando leer archivo: {path}")
    p = Path(path)

    if not p.exists():
        error_logger.warning(f"Archivo no encontrado: {p}")
        return {"status": "error", "message": "No existe"}
    
    tool_logger.info(f"Archivo leído exitosamente: {p}")
    return {
        "status": "ok",
        "content": p.read_text(encoding="utf-8")
    }


async def list_directory(path: str = "."):
    tool_logger.info(f"Listando directorio: {path}")
    p = Path(path)

    if not p.exists() or not p.is_dir():
        error_logger.warning(f"Directorio no encontrado o no es directorio: {p}")
        return {"status": "error", "message": "Directorio no encontrado"}

    entries = []
    for child in sorted(p.iterdir()):
        entries.append({
            "name": child.name,
            "is_dir": child.is_dir(),
            "size": child.stat().st_size if child.is_file() else None,
        })

    tool_logger.info(f"Directorio listado correctamente: {p}")
    return {
        "status": "ok",
        "path": str(p),
        "entries": entries
    }


async def append_file(path: str, content: str):
    tool_logger.info(f"Agregando contenido al archivo: {path}")
    processed_path = path
    current_user_home = get_current_user_home_path()
    current_user_name = current_user_home.name

    # 1. Manejar rutas de Windows en WSL
    if len(processed_path) > 1 and processed_path[1] == ":":
        drive = processed_path[0].lower()
        remainder = processed_path[2:].replace("\\", "/")
        processed_path = f"/mnt/{drive}{remainder}"
        tool_logger.info(f"Ruta de Windows detectada. Corrigiendo a WSL: {processed_path}")

    # 2. Corregir rutas de macOS y placeholders
    if processed_path.startswith("/Users/"):
        processed_path = processed_path.replace("/Users/", "/home/", 1)
    
    processed_path = processed_path.replace("YourUsername", current_user_name).replace("username", current_user_name)

    p = Path(processed_path).expanduser()
    
    if not p.is_absolute():
        parts = p.parts
        if len(parts) > 1 and parts[0].lower() in ["users", "home"] and parts[1].lower() == current_user_name.lower():
            p = current_user_home / Path(*parts[2:])
            tool_logger.info(f"Ruta relativa detectada como estructura de home del usuario actual. Ajustando a: {p}")
        else:
            tool_logger.info(f"Ruta relativa detectada, convirtiendo a absoluta en CWD: {p}")
            p = Path.cwd() / p

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as handle:
            handle.write(content)
    except PermissionError as e: # Catch PermissionError specifically
        error_logger.error(f"Error de permisos al adjuntar en {p}: {e}")
        return {"status": "error", "message": f"Permiso denegado. No se puede escribir en {p.parent}. Intenta usar una ruta dentro de {get_current_user_home_path()}/"}
    except Exception as e: # Catch any other unexpected errors
        error_logger.error(f"Error inesperado al adjuntar en {p}: {e}")
        return {"status": "error", "message": f"Error inesperado al adjuntar archivo: {e}"}

    tool_logger.info(f"Contenido agregado exitosamente: {p}")
    return {
        "status": "ok",
        "message": f"Contenido agregado a: {p}"
    }

async def delete_file(path: str):
    tool_logger.info(f"Intentando eliminar archivo: {path}")
    p = Path(path)

    if not p.exists():
        error_logger.warning(f"Archivo no encontrado para eliminar: {p}")
        return {"status": "error", "message": "Archivo no encontrado"}
    
    if p.is_dir():
        error_logger.warning(f"Intento de eliminar un directorio como archivo: {p}")
        return {"status": "error", "message": "No es un archivo"}

    p.unlink()
    '''
    esta instruccion elemina el archivo, si es un directorio se debe usar
    rmdir o shutil.rmtree para eliminarlo recursivamente
    '''
    tool_logger.info(f"Archivo eliminado exitosamente: {p}")
    return {
        "status": "ok",
        "message": f"Archivo eliminado: {p}"
    }

TOOLS = {
    "create_file": create_file,
    "read_file": read_file,
    "list_directory": list_directory,
    "append_file": append_file,
    "delete_file":delete_file,  
}