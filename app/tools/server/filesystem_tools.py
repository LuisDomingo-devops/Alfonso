"""
FILESYSTEM TOOLS — Manipulación del sistema de archivos local.

¿QUÉ HACE?
Permite listar directorios, buscar texto en archivos, leer y escribir datos en disco.

¿CUÁNDO LO HACE?
Cuando el planificador requiere explorar archivos locales, crear scripts o modificar la base de código.

¿CÓMO LO HACE?
Encapsulando llamadas estándar de Python como `os`, `shutil` y `pathlib`.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/adapters/tool_registry.py (registra estas herramientas)
"""

from pathlib import Path
import os
import re
from app.utils.logger import tool_logger, error_logger
from app.utils.paths import resolve_client_path, get_client_context
from app.domain.actions import Action
from app.adapters.alfonso_bridge import bridge as alfonso_bridge

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
    ctx = get_client_context()
    return Path(ctx["home"])

def _resolve_path(raw_path: str) -> Path:
    """Unifies path resolution logic to handle Windows paths in WSL, macOS hallucinations, 
    and placeholder usernames (e.g., YOUR_USERNAME)."""
    resolved_str = resolve_client_path(raw_path)
    return Path(resolved_str)

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
    del_res = await _delegate(Action.MOVE_FILE, {
        "old_path": old_path,
        "new_path": new_path,
        "src": old_path,
        "dst": new_path
    })
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

async def replace_file_content(path: str, target: str, replacement: str):
    """Reemplaza un bloque de texto exacto (target) por otro (replacement) en el archivo especificado."""
    del_res = await _delegate(Action.REPLACE_FILE_CONTENT, {"path": path, "target": target, "replacement": replacement})
    if del_res is not None:
        return del_res

    tool_logger.info(f"Intentando reemplazar contenido en archivo: {path}")
    p = _resolve_path(path)

    if not p.exists():
        error_logger.warning(f"Archivo no encontrado para reemplazar: {p}")
        return {"status": "error", "message": "Archivo no encontrado"}

    try:
        content = p.read_text(encoding="utf-8")
        if target not in content:
            error_logger.warning(f"Texto objetivo no encontrado en el archivo: {p}")
            return {
                "status": "error",
                "message": f"Texto objetivo no encontrado en el archivo. Asegúrate de especificar las líneas exactas a reemplazar (incluyendo espacios e indentaciones)."
            }
        
        new_content = content.replace(target, replacement, 1)
        p.write_text(new_content, encoding="utf-8")
    except PermissionError as e:
        error_logger.error(f"Error de permisos al reemplazar en {p}: {e}")
        return {"status": "error", "message": f"Permiso denegado al escribir en {p}"}
    except Exception as e:
        error_logger.error(f"Error inesperado al reemplazar en {p}: {e}")
        return {"status": "error", "message": f"Error inesperado al reemplazar contenido: {e}"}

    tool_logger.info(f"Reemplazo de contenido exitoso en: {p}")
    return {
        "status": "ok",
        "message": f"Contenido reemplazado exitosamente en: {p}"
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
    "replace_file_content": replace_file_content,
}


# ---------------------------------------------------------------------------
# Fase 1 (BaseTool + Pydantic) — esquemas permisivos
# ---------------------------------------------------------------------------
# Este es el módulo donde se vio el error real en producción
# (logs/errors.log: "create_file() got an unexpected keyword argument
# 'file_path'"). Los alias de abajo cubren las variantes que el modelo
# qwen2.5:1.5b ha mandado realmente; campos no listados aquí simplemente
# se ignoran en modo permisivo en vez de romper la llamada.

from app.adapters.tool_base import ToolArgsModel  # noqa: E402  (al final a propósito)

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


class ReplaceFileContentArgs(ToolArgsModel):
    path: str
    target: str
    replacement: str


_TARGET_ALIASES = {
    "old_text": "target",
    "buscar": "target",
    "original": "target",
}

_REPLACEMENT_ALIASES = {
    "new_text": "replacement",
    "reemplazo": "replacement",
    "nuevo": "replacement",
}


ARGS_SCHEMAS = {
    "create_file": (CreateFileArgs, {**_PATH_ALIASES, **_CONTENT_ALIASES}),
    "read_file": (ReadFileArgs, dict(_PATH_ALIASES)),
    "append_file": (AppendFileArgs, {**_PATH_ALIASES, **_CONTENT_ALIASES}),
    "delete_file": (DeleteFileArgs, dict(_PATH_ALIASES)),
    "list_directory": (ListDirectoryArgs, dict(_PATH_ALIASES)),
    "replace_file_content": (ReplaceFileContentArgs, {**_PATH_ALIASES, **_TARGET_ALIASES, **_REPLACEMENT_ALIASES}),
}