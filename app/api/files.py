"""
Endpoint para servir ficheros de audio temporales generados por TTS.
Solo sirve ficheros dentro del directorio temporal del sistema.
"""

from pathlib import Path
import tempfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router_files = APIRouter()

TMP_DIR = Path(tempfile.gettempdir()).resolve()


@router_files.get("/audio/file")
async def serve_audio_file(path: str = Query(..., description="Ruta del fichero de audio")):
    """
    Sirve un fichero de audio generado por el servidor (TTS).
    Solo permite acceder a ficheros dentro del directorio temporal.
    """
    requested = Path(path).resolve()

    # Seguridad: solo servir ficheros dentro de /tmp
    if not str(requested).startswith(str(TMP_DIR)):
        raise HTTPException(status_code=403, detail="Acceso denegado")

    if not requested.exists():
        raise HTTPException(status_code=404, detail="Fichero no encontrado")

    suffix = requested.suffix.lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
    }
    media_type = media_types.get(suffix, "application/octet-stream")

    return FileResponse(path=str(requested), media_type=media_type)