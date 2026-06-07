import httpx
from app.config import settings

# El timeout se lee del .env (LLM_TIMEOUT).
# qwen2.5:1.5b  → 300s
# deepseek-r1:7b → 600s
# deepseek-r1:14b→ 900s
client = httpx.AsyncClient(timeout=settings.LLM_TIMEOUT)
