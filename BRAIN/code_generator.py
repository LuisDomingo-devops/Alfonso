import logging
import os
from datetime import datetime
from BRAIN.config import CONFIG

def _load_system_prompt() -> str:
    """
    Carga el prompt del sistema utilizando las rutas definidas en el archivo de configuración.
    """
    path = os.path.join(CONFIG.PROMPTS_PATH, CONFIG.SYSTEM_PROMPT_FILE)
    
    try:
        if not os.path.exists(path):
             logging.warning(f"Prompt no encontrado en {path}. Usando fallback.")
             return "Eres un experto en Python. Soluciona: {issue_description}"
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Error cargando prompt desde {path}: {e}")
        return "Eres un experto en Python. Soluciona: {issue_description}"

async def generate_fix(issue: dict, codebase_context: dict) -> dict:
    """
    issue: dict con severity, type, location, description, suggested_fix
    codebase_context: {filename: content} de los archivos relevantes

    Retorna un objeto 'EvolutionProposal' con el contenido técnico para el informe.
    """
    # Simulación de generación local pausada
    description = issue.get("description", "Sin descripción")
    location = issue.get("location", "Ubicación desconocida")
    suggested_fix = issue.get("suggested_fix", "Revisión de lógica")
    
    # Carga dinámica del prompt basado en el archivo config
    system_prompt_template = _load_system_prompt()

    # 1. El Diff Crudo: Esto es lo que se usará para el "despliegue" real una vez validado.
    raw_diff = (
        f"--- {location}\n"
        f"+++ {location}\n"
        f"@@ -1,1 +1,2 @@\n"
        f"-# Código antiguo\n"
        f"+# Propuesta de mejora validada y desplegada por Alfonso\n"
        f"@@ -10,4 +10,5 @@\n"
        f" # {suggested_fix}\n"
        f"-pass\n"
        f"+await improved_logic_v2()\n"
    )

    # 2. El Informe (Markdown): Lo que tú leerás por la mañana.
    proposal_text = (
        f"### INFORME DE AUTO-EVOLUCIÓN NOCTURNA\n\n"
        f"**Análisis del problema:** {description}\n"
        f"**Ubicación identificada:** {location}\n\n"
        f"**Sugerencia de mejora:**\n"
        f"> {suggested_fix}\n\n"
        f"**Boceto de cambio (Diff propuesto):**\n"
        f"```diff\n{raw_diff}```"
    )
    
    return {
        "id": f"report_{datetime.now().strftime('%Y%m%d_%H%M')}_{location.replace('/', '_')}",
        "content": proposal_text,
        "status": "pending_validation",
        "patch_data": {
            "raw_diff": raw_diff,
            "target_file": location,
            "deployment_ready": True
        },
        "metadata": {
            "severity": issue.get("severity"),
            "timestamp": "nightly_run",
            "requires_manual_apply": True,
            "can_auto_deploy": True
        }
    }