"""
llm_client.py — Fase 3

Mejora: inyecta la fecha y hora reales del sistema en el prompt del sistema
mediante el placeholder {current_date}. Esto evita que el LLM invente fechas
basándose en su fecha de corte de conocimiento.
"""

import json
from datetime import datetime
from app.config import settings, load_prompt
from app.core.http_client import client
from app.utils.logger import attach_request_id, llm_logger, error_logger


def _get_current_date_str() -> str:
    """Devuelve la fecha y hora actuales como string legible para el prompt."""
    now = datetime.now()
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    return (
        f"{days[now.weekday()]}, {now.day} de {months[now.month - 1]} de {now.year}, "
        f"{now.strftime('%H:%M')}"
    )


def get_system_prompt(mode: str) -> str:
    if mode == "chat":
        template = load_prompt(settings.CHAT_PROMPT_PATH)
    else:
        template = load_prompt(settings.TOOL_PROMPT_PATH)

    # Inyectar fecha real
    current_date = _get_current_date_str()
    return template.replace("{current_date}", current_date)


class OllamaClient:

    async def generate(
        self,
        message: str,
        mode: str = "chat",
        request_id: str = None,
        memory: str | None = None,
    ) -> str:

        logger = attach_request_id(llm_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        system_prompt = get_system_prompt(mode)

        messages = [
            {"role": "system", "content": system_prompt}
        ]

        if memory:
            messages.append({"role": "system", "content": memory})

        messages.append({"role": "user", "content": message})

        payload = {
            "model": settings.MODEL_NAME,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "num_ctx": 2048,
                "temperature": 0.0 if mode == "tool" else 0.7,
            },
        }

        logger.info("LLM INPUT: %s", message)
        logger.info("LLM MODE: %s", mode)
        if memory:
            logger.debug("LLM MEMORY CONTEXT: %s", memory)

        try:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json=payload,
            )

            if response.status_code != 200:
                raise RuntimeError(f"Ollama error {response.status_code}: {response.text}")

            data = response.json()

            if not isinstance(data, dict):
                raise ValueError(f"Respuesta no válida: {data}")

            msg = data.get("message")

            if not isinstance(msg, dict):
                raise ValueError(f"Estructura inesperada: {data}")

            content = msg.get("content")

            if not content:
                raise ValueError(f"Contenido vacío: {data}")

            logger.debug("OLLAMA RAW RESPONSE: %s", data)
            logger.debug("OLLAMA CONTENT: %s", content)
            logger.info("Respuesta LLM recibida correctamente")

            return content.strip()

        except Exception as e:
            error.exception("Error al generar respuesta con Ollama")
            return json.dumps({
                "tool": "no_op",
                "args": {
                    "message": f"LLM_ERROR: {repr(e)}",
                },
            })
