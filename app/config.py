"""
App Configuration — Fase 3
"""

from pathlib import Path
from typing import Any, Dict
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    MODEL_NAME: str = "qwen2.5:1.5b"

    CHAT_PROMPT_PATH: str = "app/prompts/chat_system.txt"
    AUTOEVOLUTION_PROMPT_PATH: str = "app/prompts/autoevolution_promt.md"

    # ── Parámetros de inferencia ──────────────────────────────────────
    LLM_NUM_CTX_TOOL: int = 1024
    LLM_NUM_CTX_CHAT: int = 2048
    LLM_TIMEOUT: int = 300
    LLM_IS_REASONING: bool = False

    BRIDGE_HOST: str = "0.0.0.0"
    BRIDGE_PORT: int = 8765
    BRIDGE_TIMEOUT: int = 30

    TOOL_VALIDATION_MODE: str = "permissive"

    # ── Memoria Vectorial (Fase 4) ──────────────────────────────────
    CHROMA_DB_PATH: str = "data/chroma"
    EMBEDDING_MODEL_NAME: str = "nomic-embed-text"

    # ── VALIDADOR ULTRA-ROBUSTO ANTE COMENTARIOS CACHEADOS ────────────
    @model_validator(mode="before")
    @classmethod
    def clean_all_inline_comments(cls, data: Any) -> Any:
        """
        Limpia los comentarios inline de cualquier variable cargada,
        evitando que cadenas como 'true # comentario' rompan Pydantic.
        """
        if isinstance(data, dict):
            cleaned: Dict[str, Any] = {}
            for key, value in data.items():
                if isinstance(value, str):
                    # Divide por el hash y elimina espacios en blanco restantes
                    cleaned[key] = value.split("#")[0].strip()
                else:
                    cleaned[key] = value
            return cleaned
        return data

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()