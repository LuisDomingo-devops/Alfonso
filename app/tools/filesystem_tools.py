from pathlib import Path
from app.utils.logger import tool_logger, error_logger
import os

async def create_file(path: str, content: str):

    tool_logger.info(f"Intentando crear archivo: {path}")
    # IMPORTANTE: ruta relativa segura
    p = Path(path)

    if not p.is_absolute():
        error_logger.info(f"Ruta relativa detectada, convirtiendo a absoluta: {p}")
        p = Path.cwd() / p
    
    tool_logger.info(f"Ruta absoluta final: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
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
    p = Path(path)

    if not p.is_absolute():
        p = Path.cwd() / p

    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(content)
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
    # p.rmdir()
    # shutil.rmtree(p)
    os.remove(p)
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
    "delete_file":delete_file,  # Por implementar
}