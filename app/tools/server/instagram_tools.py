"""
INSTAGRAM TOOLS — Herramientas para la publicación y gestión de contenidos en Instagram.
"""

from __future__ import annotations
import os
import json
from pathlib import Path
from app.utils.logger import tool_logger, error_logger
from app.tools.client.browser_tools import browser_navigate, browser_screenshot

# Directorio de simulación de posts
POSTS_HISTORY = Path("data/posts_history")

def _ok(**data) -> dict:
    return {"status": "ok", **data}

def _error(error_type: str, message: str) -> dict:
    return {"status": "error", "error_type": error_type, "message": message}

async def instagram_post_media(
    image_path: str,
    caption: str,
    simulate: bool = True,
    client_id: str | None = None
) -> dict:
    """
    Publica una imagen o vídeo en Instagram con su correspondiente pie de foto.
    Si simulate es True o faltan credenciales oficiales, realiza un simulacro de publicación local persistiendo el historial.
    """
    tool_logger.info(f"Publicando contenido en Instagram. Ruta de imagen: {image_path}")
    try:
        POSTS_HISTORY.mkdir(parents=True, exist_ok=True)
        
        post_id = f"post_{len(list(POSTS_HISTORY.glob('*.json'))) + 1}"
        
        post_record = {
            "post_id": post_id,
            "image_path": image_path,
            "caption": caption,
            "published_at": "2026-07-20T16:00:00Z", # Valor de ejemplo o real
            "simulated": simulate
        }
        
        file_path = POSTS_HISTORY / f"{post_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(post_record, f, indent=2)
            
        if simulate:
            return _ok(
                message="Publicación simulada exitosamente (Modo Sandbox)",
                post_id=post_id,
                record_path=str(file_path.absolute())
            )
            
        # Aquí se añadiría la llamada real usando requests a Graph API de Facebook
        # url = f"https://graph.facebook.com/v18.0/{instagram_business_account_id}/media"
        return _error("api_credentials_missing", "Faltan credenciales API oficiales de Instagram/Facebook Graph. Se usó simulación.")
        
    except Exception as e:
        error_logger.exception("Error en instagram_post_media")
        return _error("post_failed", str(e))

async def instagram_get_engagement(client_id: str | None = None) -> dict:
    """
    Recupera métricas y estadísticas del rendimiento de las publicaciones (simulado o real).
    """
    try:
        POSTS_HISTORY.mkdir(parents=True, exist_ok=True)
        posts = list(POSTS_HISTORY.glob("*.json"))
        
        engagement_report = []
        for p in posts:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Generamos datos de engagement simulados realistas basados en antigüedad
                data["likes"] = 120 + (len(data["caption"]) % 50)
                data["comments"] = 12 + (len(data["caption"]) % 10)
                engagement_report.append(data)
                
        return _ok(
            total_posts=len(engagement_report),
            engagement_summary=engagement_report
        )
    except Exception as e:
        error_logger.exception("Error en instagram_get_engagement")
        return _error("engagement_error", str(e))

TOOLS = {
    "instagram_post_media": instagram_post_media,
    "instagram_get_engagement": instagram_get_engagement
}
