"""
App Configuration — Fase 3

Nuevos parámetros para soporte multi-modelo:
    LLM_NUM_CTX_TOOL  : tokens de contexto para modo tool  (default 1024 para qwen, 4096 para R1)
    LLM_NUM_CTX_CHAT  : tokens de contexto para modo chat  (default 2048 para qwen, 8192 para R1)
    LLM_TIMEOUT       : timeout httpx en segundos           (default 300)
    LLM_IS_REASONING  : True si el modelo usa <think> tags (deepseek-r1, qwq, etc.)

Cambiar de modelo es tan simple como editar el .env:
    MODEL_NAME=deepseek-r1:7b
    LLM_NUM_CTX_TOOL=4096
    LLM_NUM_CTX_CHAT=8192
    LLM_IS_REASONING=true
    LLM_TIMEOUT=600
"""

from pydantic_settings import BaseSettings
from pathlib import Path



class Settings(BaseSettings):
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    MODEL_NAME: str = "qwen2.5:1.5b"

    CHAT_PROMPT_PATH: str = "app/prompts/chat_system.txt"
    AUTOEVOLUTION_PROMPT_PATH: str = "app/prompts/autoevolution_promt.md"

    # ── Parámetros de inferencia ──────────────────────────────────────
    # qwen2.5:1.5b  → num_ctx_tool=1024,  num_ctx_chat=2048,  timeout=300
    # deepseek-r1:7b → num_ctx_tool=4096, num_ctx_chat=8192,  timeout=600, reasoning=true
    # deepseek-r1:14b→ num_ctx_tool=8192, num_ctx_chat=16384, timeout=900, reasoning=true
    LLM_NUM_CTX_TOOL: int
    LLM_NUM_CTX_CHAT: int
    LLM_TIMEOUT: int
    LLM_IS_REASONING: bool

    BRIDGE_HOST: str = "0.0.0.0"
    BRIDGE_PORT: int = 8765
    BRIDGE_TIMEOUT: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()


def load_prompt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")
