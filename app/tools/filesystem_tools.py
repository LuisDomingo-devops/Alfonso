from pathlib import Path
import os
import re
from app.utils.logger import tool_logger, error_logger
from app.core.actions import Action
from app.core.alfonso_bridge import bridge as alfonso_bridge

async def _delegate(action: str, args: dict) -> dict | None:
    if alfonso_bridge.has_clients():
        # Resolver rutas para que el agente local las reciba ya normalizadas desde el contexto de WSL
        resolved_args = args.copy()
        if "path" in resolved_args:
            resolved_args["path"] = str(_resolve_path(resolved_args["path"]))
        if "src" in resolved_args:
            resolved_args["src"] = str(_resolve_path(resolved_args["src"]))
        if "dst" in resolved_args:
            # En rename_file, dst puede ser un new_name (ej: nuevo_nombre.txt), resolverlo solo si no es un nombre simple
            dst_val = resolved_args["dst"]
            if not dst_val.startswith(".") and "/" not in dst_val and "\\" not in dst_val:
                pass
            else:
                resolved_args["dst"] = str(_resolve_path(dst_val))
        if "new_name" in resolved_args:
            new_name_val = resolved_args["new_name"]
            if not new_name_val.startswith(".") and "/" not in new_name_val and "\\" not in new_name_val:
                pass
            else:
                resolved_args["new_name"] = str(_resolve_path(new_name_val))

        tool_logger.info(f"Delegando filesystem tool '{action}' al agente local")
        response = await alfonso_bridge.send_command(action, resolved_args)
        if response.get("status") == "success":
            return {
                "status": "ok",
                "message": response.get("result", "Operación exitosa en el cliente."),
                "delegate": "alfonso_agent",
                "details": response,
            }
        return {
            "status": "error",
            "message": response.get("error", "Error en la operación del cliente."),
            "delegate": "alfonso_agent",
            "details": response,
        }
    return None

# Helper to get the current user's home directory path
def get_current_user_home_path():

    return Path.home()

def _resolve_path(raw_path: str) -> Path:
    """Unifies path resolution logic to handle Windows paths in WSL, macOS hallucinations, 
    and placeholder usernames (e.g., YOUR_USERNAME)."""
    current_user_home = get_current_user_home_path()
    current_user_name = current_user_home.name
    processed_path = raw_path

    # 1. Manejar rutas de Windows (ej: C:\...) en WSL (/mnt/c/...)
    if len(processed_path) > 1 and processed_path[1] == ":":
        drive = processed_path[0].lower()
        remainder = processed_path[2:].replace("\\", "/")
        processed_path = f"/mnt/{drive}{remainder}"
        tool_logger.info(f"Ruta de Windows detectada. Corrigiendo a WSL: {processed_path}") #

        # Manejo específico para rutas de usuario de Windows dentro de WSL
        # Si la ruta es /mnt/c/Users/<some_windows_user>/...
        windows_users_path_match = re.match(r"/mnt/c/Users/([^/]+)(.*)", processed_path, re.IGNORECASE)
        if windows_users_path_match:
            windows_user_in_path = windows_users_path_match.group(1)
            rest_of_path = windows_users_path_match.group(2)
            
            # Si el usuario de Windows en la ruta no es el usuario actual de WSL,
            # asumimos que debería ser la ruta equivalente del usuario actual de WSL en Windows.
            if windows_user_in_path.lower() != current_user_name.lower():
                processed_path = f"/mnt/c/Users/{current_user_name}{rest_of_path}"
                tool_logger.info(f"Usuario de Windows en la ruta ('{windows_user_in_path}') no coincide con el usuario actual de WSL ('{current_user_name}'). Ajustando a: {processed_path}") #

    # 2. Corregir rutas de macOS y placeholders comunes (YourUsername -> luisd)
    mac_users_path_match = re.match(r"/Users/([^/]+)(.*)", processed_path)
    if mac_users_path_match:
        mac_user_in_path = mac_users_path_match.group(1)
        rest_of_path = mac_users_path_match.group(2)
        processed_path = f"/home/{current_user_name}{rest_of_path}" # Siempre convertir a /home/ para contexto WSL
        if mac_user_in_path.lower() != current_user_name.lower():
            tool_logger.info(f"Usuario de macOS en la ruta ('{mac_user_in_path}') no coincide con el usuario actual de WSL ('{current_user_name}'). Ajustando a: {processed_path}") #
        else:
            tool_logger.info(f"Ruta de macOS detectada. Corrigiendo a WSL: {processed_path}") #

    # 2b. FIX: el LLM también alucina rutas Linux genéricas tipo /home/user/...
    # o /home/luisd/... (usuario inexistente o distinto al actual). Antes este
    # caso no se corregía (a diferencia de /Users/ y /mnt/c/Users/) y producía
    # PermissionError al intentar crear /home/<usuario-inexistente>/...
    # Ver logs/errors.log: "Permission denied: '/home/user'".
    linux_users_path_match = re.match(r"/home/([^/]+)(.*)", processed_path)
    if linux_users_path_match:
        linux_user_in_path = linux_users_path_match.group(1)
        rest_of_path = linux_users_path_match.group(2)
        if linux_user_in_path.lower() != current_user_name.lower():
            processed_path = f"/home/{current_user_name}{rest_of_path}"
            tool_logger.info(f"Usuario en ruta /home/ ('{linux_user_in_path}') no coincide con el usuario actual de WSL ('{current_user_name}'). Ajustando a: {processed_path}") #

    # 2c. Corrección de alucinación común: /usr/share/applications/ para archivos normales (no-desktop)
    if "/usr/share/applications/" in processed_path and not processed_path.endswith(".desktop"):
        filename = Path(processed_path).name
        processed_path = f"~/Desktop/{filename}"
        tool_logger.info(f"Alucinación de /usr/share/applications detectada para archivo no-desktop. Redirigiendo a: {processed_path}")

    # Manejar placeholders comunes que el LLM suele inventar
    for placeholder in ["YOUR_USERNAME", "YourUsername", "your_username", "username"]:
        processed_path = processed_path.replace(placeholder, current_user_name)
    p = Path(processed_path).expanduser()
    
    if not p.is_absolute():
        parts = p.parts
        if len(parts) > 1 and parts[0].lower() in ["users", "home"] and parts[1].lower() == current_user_name.lower():
            p = current_user_home / Path(*parts[2:])
            tool_logger.info(f"Ruta relativa detectada como estructura de home del usuario actual. Ajustando a: {p}") #
        else:
            p = Path.cwd() / p
            tool_logger.info(f"Ruta relativa detectada, convirtiendo a absoluta en CWD: {p}") #
    
    tool_logger.info(f"Ruta resuelta: {p}")
    return p

async def create_file(path: str, content: str):
    """Crea un archivo nuevo con el contenido especificado (ej. en el Escritorio/Desktop o ruta relativa)."""
    del_res = await _delegate(Action.CREATE_FILE, {"path": path, "content": content})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando crear archivo: {path}")
    p = _resolve_path(path)
    
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
    """Lee el contenido de un archivo existente."""
    del_res = await _delegate(Action.READ_FILE, {"path": path})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando leer archivo: {path}")
    p = _resolve_path(path)

    if not p.exists():
        error_logger.warning(f"Archivo no encontrado: {p}")
        return {"status": "error", "message": "No existe"}
    
    tool_logger.info(f"Archivo leído exitosamente: {p}")
    return {
        "status": "ok",
        "content": p.read_text(encoding="utf-8")
    }


async def list_directory(path: str = "."):
    """Lista los archivos y carpetas de un directorio."""
    del_res = await _delegate(Action.LIST_DIRECTORY, {"path": path})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Listando directorio: {path}")
    p = _resolve_path(path)

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
    del_res = await _delegate(Action.APPEND_FILE, {"path": path, "content": content})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Agregando contenido al archivo: {path}")
    p = _resolve_path(path)

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
    del_res = await _delegate(Action.DELETE_FILE, {"path": path})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando eliminar archivo: {path}")
    p = _resolve_path(path)

    if not p.exists():
        error_logger.warning(f"Archivo no encontrado para eliminar: {p}")
        return {"status": "error", "message": "Archivo no encontrado"}
    
    if p.is_dir():
        error_logger.warning(f"Intento de eliminar un directorio como archivo: {p}")
        return {"status": "error", "message": "No es un archivo"}

    try:
        p.unlink()
    except Exception as e:
        error_logger.error(f"Error al eliminar {p}: {e}")
        return {"status": "error", "message": f"Error al eliminar: {e}"}

    tool_logger.info(f"Archivo eliminado exitosamente: {p}")
    return {
        "status": "ok",
        "message": f"Archivo eliminado: {p}"
    }

async def create_directory(path: str):
    del_res = await _delegate(Action.CREATE_DIRECTORY, {"path": path})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando crear directorio: {path}")
    p = _resolve_path(path)

    try:
        p.mkdir(parents=True, exist_ok=True)
    except PermissionError as e: # Catch PermissionError specifically
        error_logger.error(f"Error de permisos al crear directorio {p}: {e}")
        return {"status": "error", "message": f"Permiso denegado. No se puede crear el directorio en {p.parent}. Intenta usar una ruta dentro de {get_current_user_home_path()}/"}
    except Exception as e: # Catch any other unexpected errors
        error_logger.error(f"Error inesperado al crear directorio {p}: {e}")
        return {"status": "error", "message": f"Error inesperado al crear directorio: {e}"}

    tool_logger.info(f"Directorio creado exitosamente: {p}")
    return {
        "status": "ok",
        "message": f"Directorio creado: {p}"
    }

async def delete_directory(path: str):
    del_res = await _delegate(Action.DELETE_DIRECTORY, {"path": path})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando eliminar directorio: {path}")
    p = _resolve_path(path)

    if not p.exists():
        error_logger.warning(f"Directorio no encontrado para eliminar: {p}")
        return {"status": "error", "message": "Directorio no encontrado"}
    
    if not p.is_dir():
        error_logger.warning(f"Intento de eliminar un archivo como directorio: {p}")
        return {"status": "error", "message": "No es un directorio"}

    try:
        p.rmdir()
    except Exception as e:
        error_logger.error(f"Error al eliminar directorio {p}: {e}")
        return {"status": "error", "message": f"Error al eliminar directorio: {e}"}

    tool_logger.info(f"Directorio eliminado exitosamente: {p}")
    return {
        "status": "ok",
        "message": f"Directorio eliminado: {p}"
    }

async def move_file(old_path: str, new_path: str):
    del_res = await _delegate(Action.MOVE_FILE, {"old_path": old_path, "new_path": new_path})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando mover archivo: {old_path} -> {new_path}")
    old_p = _resolve_path(old_path)
    new_p = _resolve_path(new_path)

    if not old_p.exists():
        error_logger.warning(f"Archivo no encontrado para mover: {old_p}")
        return {"status": "error", "message": "Archivo no encontrado"}

    try:
        old_p.rename(new_p)
    except Exception as e:
        error_logger.error(f"Error al mover archivo {old_p}: {e}")
        return {"status": "error", "message": f"Error al mover archivo: {e}"}

    tool_logger.info(f"Archivo movido exitosamente: {old_p} -> {new_p}")
    return {
        "status": "ok",
        "message": f"Archivo movido: {old_p} -> {new_p}"
    }

async def rename_file(path: str, new_name: str):
    del_res = await _delegate(Action.RENAME_FILE, {"path": path, "new_name": new_name})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando renombrar archivo: {path} -> {new_name}")
    p = _resolve_path(path)
    new_p = p.with_name(new_name)

    if not p.exists():
        error_logger.warning(f"Archivo no encontrado para renombrar: {p}")
        return {"status": "error", "message": "Archivo no encontrado"}

    try:
        p.rename(new_p)
    except Exception as e:
        error_logger.error(f"Error al renombrar archivo {p}: {e}")
        return {"status": "error", "message": f"Error al renombrar archivo: {e}"}

    tool_logger.info(f"Archivo renombrado exitosamente: {p} -> {new_p}")
    return {
        "status": "ok",
        "message": f"Archivo renombrado: {p} -> {new_p}"
    }

TOOLS = {
    "create_file": create_file,
    "read_file": read_file,
    "list_directory": list_directory,
    "create_directory": create_directory,
    "append_file": append_file,
    "delete_file":delete_file,
    "delete_directory": delete_directory,
    "move_file": move_file,
    "rename_file": rename_file,
}


# ---------------------------------------------------------------------------
# Fase 1 (BaseTool + Pydantic) — esquemas permisivos
# ---------------------------------------------------------------------------
# Este es el módulo donde se vio el error real en producción
# (logs/errors.log: "create_file() got an unexpected keyword argument
# 'file_path'"). Los alias de abajo cubren las variantes que el modelo
# qwen2.5:1.5b ha mandado realmente; campos no listados aquí simplemente
# se ignoran en modo permisivo en vez de romper la llamada.

from app.core.tool_base import ToolArgsModel  # noqa: E402  (al final a propósito)

_PATH_ALIASES = {
    "file_path": "path",
    "filename": "path",
    "file_name": "path",
    "ruta": "path",
    "nombre": "path",
    "nombre_archivo": "path",
}

_CONTENT_ALIASES = {
    "contenido": "content",
    "text": "content",
    "texto": "content",
    "data": "content",
}


class CreateFileArgs(ToolArgsModel):
    path: str
    content: str = ""


class ReadFileArgs(ToolArgsModel):
    path: str


class AppendFileArgs(ToolArgsModel):
    path: str
    content: str = ""


class DeleteFileArgs(ToolArgsModel):
    path: str


class ListDirectoryArgs(ToolArgsModel):
    path: str = "."


ARGS_SCHEMAS = {
    "create_file": (CreateFileArgs, {**_PATH_ALIASES, **_CONTENT_ALIASES}),
    "read_file": (ReadFileArgs, dict(_PATH_ALIASES)),
    "append_file": (AppendFileArgs, {**_PATH_ALIASES, **_CONTENT_ALIASES}),
    "delete_file": (DeleteFileArgs, dict(_PATH_ALIASES)),
    "list_directory": (ListDirectoryArgs, dict(_PATH_ALIASES)),
}