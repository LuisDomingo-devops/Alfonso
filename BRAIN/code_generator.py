import logging
import httpx
from pathlib import Path
from datetime import datetime
from app.config import settings

def _load_system_prompt() -> str:
    """
    Carga el prompt de auto-evolución utilizando las rutas de la configuración centralizada.
    """
    path = Path(settings.AUTOEVOLUTION_PROMPT_PATH)
    
    try:
        if not path.exists():
             logging.warning(f"Prompt no encontrado en {path}. Usando fallback.")
             return "Eres un experto en Python. Soluciona el problema indicado en el código fuente proporcionando un Git Diff limpio."
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logging.error(f"Error cargando prompt desde {path}: {e}")
        return "Eres un experto en Python. Soluciona el problema indicado en el código fuente proporcionando un Git Diff limpio."

async def generate_fix(issue: dict, codebase_context: dict) -> dict:
    """
    issue: dict con severity, type, location, description, suggested_fix
    codebase_context: {filename: content} de los archivos relevantes

    Retorna un objeto 'EvolutionProposal' con el contenido técnico real generado por el LLM.
    """
    description = issue.get("description", "Sin descripción")
    location = issue.get("location", "Ubicación desconocida")
    suggested_fix = issue.get("suggested_fix", "Revisión de lógica")
    
    # Carga dinámica del prompt basado en el archivo config
    system_prompt_template = _load_system_prompt()
    
    # Buscar el código fuente original
    original_code = codebase_context.get(location, "")
    
    if original_code:
        user_prompt = (
            f"El siguiente archivo tiene un problema o alucinación reportada:\n"
            f"Archivo: {location}\n"
            f"Descripción del problema: {description}\n"
            f"Solución sugerida: {suggested_fix}\n\n"
            f"Código fuente original:\n"
            f"```python\n{original_code}\n```\n\n"
            f"Genera un Git Diff con la corrección propuesta. Devuelve ÚNICAMENTE el bloque de Git Diff. No agregues explicaciones adicionales de ningún tipo."
        )
        
        payload = {
            "model": settings.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt_template},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {"num_ctx": 4096, "temperature": 0.2}
        }
        
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                response = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json=payload
                )
            
            raw_diff = response.json()["message"]["content"].strip()
            # Extraer diff si viene envuelto en markdown
            if "```diff" in raw_diff:
                raw_diff = raw_diff.split("```diff")[1].split("```")[0].strip()
            elif "```" in raw_diff:
                raw_diff = raw_diff.split("```")[1].split("```")[0].strip()
        except Exception as e:
            logging.error(f"Error llamando a Ollama para generar fix en {location}: {e}")
            raw_diff = (
                f"--- {location}\n"
                f"+++ {location}\n"
                f"@@ -1,1 +1,1 @@\n"
                f"-# Error llamando a Ollama: {str(e)}\n"
                f"+# Error llamando a Ollama: {str(e)}\n"
            )
    else:
        raw_diff = (
            f"--- {location}\n"
            f"+++ {location}\n"
            f"@@ -1,1 +1,1 @@\n"
            f"-# Código fuente original no disponible en el contexto para {location}\n"
            f"+# Código fuente original no disponible en el contexto para {location}\n"
        )

    # El Informe (Markdown): Lo que tú leerás por la mañana.
    proposal_text = (
        f"### INFORME DE AUTO-EVOLUCIÓN Y CORRECCIÓN DE ALUCINACIONES\n\n"
        f"**Análisis del problema:** {description}\n"
        f"**Ubicación identificada:** {location}\n\n"
        f"**Propuesta de mejora:**\n"
        f"> {suggested_fix}\n\n"
        f"**Cambio propuesto (Git Diff):**\n"
        f"```diff\n{raw_diff}\n```"
    )
    
    proposal_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{location.replace('/', '_').replace('.', '_')}"
    
    return {
        "id": proposal_id,
        "content": proposal_text,
        "status": "pending_validation",
        "patch_data": {
            "raw_diff": raw_diff,
            "target_file": location,
            "deployment_ready": True
        },
        "metadata": {
            "severity": issue.get("severity"),
            "timestamp": datetime.now().isoformat(),
            "requires_manual_apply": True,
            "can_auto_deploy": True
        }
    }