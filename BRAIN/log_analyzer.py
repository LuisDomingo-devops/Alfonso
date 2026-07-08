import json
import httpx
from app.config import settings

ANALYSIS_PROMPT = """Eres un experto en Python y FastAPI analizando logs de un asistente de IA llamado Alfonso.

Basándote en el siguiente resumen de logs, identifica:

1. BUGS CRÍTICOS: errores que rompen funcionalidad (con archivo y función afectados si puedes inferirlo)
2. DEGRADACIONES: comportamiento incorrecto pero no crashea (ej: LLM responde texto cuando debería JSON)
3. MEJORAS DE RENDIMIENTO: patrones que sugieren optimización
4. MEJORAS DE PROMPTS: si el LLM confunde intenciones o genera respuestas incorrectas
5. ALUCINACIONES Y CORRECCIONES: cuando el log de 'user_corrections' o los diálogos muestren que Alfonso inventó hechos, ejecutó acciones que no debía o alucinó datos.

IMPORTANTE: Presta máxima atención a los logs etiquetados como 'user_corrections'. Indican que el usuario detectó y corrigió un error directo o alucinación de Alfonso.

Para cada problema, clasifícalo así:
- severity: critical / high / medium / low
- type: bug / degradation / performance / prompt
- location: módulo/archivo probable
- description: qué está pasando
- suggested_fix: descripción de la solución en lenguaje natural

Responde SOLO en JSON válido con esta estructura:
{{
  "issues": [
    {{
      "severity": "...",
      "type": "...",
      "location": "...",
      "description": "...",
      "suggested_fix": "..."
    }}
  ],
  "overall_health": "good/degraded/critical",
  "summary": "resumen en 2 frases"
}}

LOGS:
{log_summary}
"""

async def analyze_logs(log_summary: str) -> dict:
    payload = {
        "model": settings.MODEL_NAME,
        "messages": [
            {"role": "user", "content": ANALYSIS_PROMPT.format(log_summary=log_summary)}
        ],
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.1}
    }
    
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload
        )
    
    content = response.json()["message"]["content"].strip()
    
    # Extraer JSON si viene con markdown
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "issues": [],
            "overall_health": "unknown",
            "summary": f"Error parsing LLM response: {content[:100]}..."
        }