"""
HTTP CLIENT — Cliente HTTP asíncrono global.

¿QUÉ HACE?
Expone un pool único de conexiones HTTP asíncronas reutilizables por toda la aplicación.

¿CUÁNDO LO HACE?
Al realizar llamadas externas hacia la API de Ollama o cualquier servicio HTTP de terceros.

¿CÓMO LO HACE?
Instanciando un objeto httpx.AsyncClient global y manejando timeouts para prevenir bloqueos.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/adapters/llm_client.py (utiliza este cliente para comunicarse con Ollama)
- app/domain/agents/dev/dev_agent.py (utiliza este cliente para realizar llamadas API directas)
"""

import httpx
from app.config import settings

# El timeout se lee del .env (LLM_TIMEOUT).
# qwen2.5:1.5b  → 300s
# deepseek-r1:7b → 600s
# deepseek-r1:14b→ 900s
client = httpx.AsyncClient(timeout=settings.LLM_TIMEOUT)
