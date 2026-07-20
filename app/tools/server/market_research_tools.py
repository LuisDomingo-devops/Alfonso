"""
MARKET RESEARCH TOOLS — Herramientas de análisis de mercado y propuestas de negocio.
"""

from __future__ import annotations
import os
import json
from pathlib import Path
from app.utils.logger import tool_logger, error_logger
from app.tools.client.browser_tools import browser_search

# Ruta para guardar las propuestas generadas
PROPOSALS_DIR = Path("data/proposals")

def _ok(**data) -> dict:
    return {"status": "ok", **data}

def _error(error_type: str, message: str) -> dict:
    return {"status": "error", "error_type": error_type, "message": message}

async def market_analyze_niche(keyword: str, client_id: str | None = None) -> dict:
    """
    Busca tendencias, hashtags populares y cuentas competidoras en un nicho específico usando el navegador.
    """
    tool_logger.info(f"Iniciando análisis de mercado para el nicho: {keyword}")
    try:
        # Hacemos una búsqueda para identificar competidores y tendencias del nicho en Instagram
        search_query = f"site:instagram.com {keyword} influencer virtual"
        search_res = await browser_search(query=search_query, client_id=client_id)
        
        if search_res.get("status") != "ok":
            return _error("search_failed", f"No se pudo buscar en la web: {search_res.get('message')}")
            
        text_preview = search_res.get("text_preview", "")
        
        # Analizar tendencias básicas (este análisis lo expandirá el LLM usando la información de esta herramienta)
        analysis_data = {
            "niche": keyword,
            "raw_insights": text_preview,
            "source_url": search_res.get("url")
        }
        
        return _ok(analysis=analysis_data)
    except Exception as e:
        error_logger.exception("Error en market_analyze_niche")
        return _error("analysis_error", str(e))

async def market_generate_proposal(
    niche: str,
    avatar_concept: str,
    target_audience: str,
    monetization_strategy: str,
    client_id: str | None = None
) -> dict:
    """
    Genera un documento formal de propuesta de negocio para el dueño del sistema.
    """
    tool_logger.info(f"Generando propuesta de negocio para el nicho: {niche}")
    try:
        PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
        
        proposal_content = f"""# Propuesta de Negocio: Personaje Virtual en {niche}

Este documento ha sido generado de forma autónoma por Alfonso para la aprobación del dueño de la empresa.

## 1. Definición del Proyecto
* **Nicho:** {niche}
* **Concepto de Avatar (Instagram):** {avatar_concept}

## 2. Público Objetivo
{target_audience}

## 3. Estrategia de Monetización
{monetization_strategy}

## 4. Plan de Acción Recomendado
1. Configurar y ajustar workflow de ComfyUI para mantener la consistencia del rostro del avatar.
2. Generar el set de las primeras 9 publicaciones de lanzamiento.
3. Automatizar la subida y programación de posts.
4. Interactuar diariamente con cuentas afines del nicho para acelerar el crecimiento orgánico.

---
*Para proceder con esta propuesta, aprueba esta ejecución o indícame las modificaciones deseadas.*
"""
        
        safe_filename = niche.lower().replace(" ", "_").replace("/", "_")
        file_path = PROPOSALS_DIR / f"propuesta_{safe_filename}.md"
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(proposal_content)
            
        return _ok(
            message=f"Propuesta comercial generada y guardada en {file_path}",
            file_path=str(file_path.absolute()),
            preview=proposal_content[:300] + "..."
        )
    except Exception as e:
        error_logger.exception("Error en market_generate_proposal")
        return _error("proposal_generation_error", str(e))

TOOLS = {
    "market_analyze_niche": market_analyze_niche,
    "market_generate_proposal": market_generate_proposal
}
