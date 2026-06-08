"""
llm_client.py — Fase 3 — Multi-modelo

Soporta qwen2.5, deepseek-r1, qwq y cualquier modelo Ollama sin cambiar código.
Solo ajustar el .env.

El extractor JSON maneja todos los formatos conocidos:
  - {"tool":"name","args":{...}}        → formato correcto
  - name {"path":"...","content":"..."}  → qwen2.5 a veces omite el wrapper
  - ```json {...} ```                    → markdown block
  - <think>...</think> {...}             → DeepSeek R1 / QwQ
"""

import asyncio
import json
import re
from datetime import datetime

from app.config import settings, load_prompt
from app.core.http_client import client
from app.utils.logger import attach_request_id, llm_logger, error_logger

# Patrones de extracción
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_BLOCK  = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON   = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", re.DOTALL)
# Formato "tool_name {args_json}" que emite qwen cuando olvida el wrapper
_TOOL_INLINE = re.compile(r"^([a-z_]+)\s+(\{.*\})$", re.DOTALL | re.IGNORECASE)

# Nombres de tools válidos (para validar el formato inline)
_VALID_TOOLS = {
    "create_file", "read_file", "append_file", "delete_file", "list_directory",
    "system_info", "get_current_datetime", "open_application", "close_application", "run_command",
    "browser_navigate", "browser_search", "browser_screenshot", "browser_get_text",
    "browser_click", "browser_fill", "browser_evaluate", "browser_close",
    "text_to_speech", "speech_to_text", "no_op",
}


def _get_current_date_str() -> str:
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
    return template.replace("{current_date}", _get_current_date_str())


def extract_json_robust(raw: str) -> dict | None:
    """
    Extrae el JSON de tool del output del LLM.

    Maneja estos formatos (en orden de prioridad):
      1. Bloque ```json {...} ```
      2. <think>...</think> + JSON al final  (R1/QwQ)
      3. 'tool_name {"args":...}'            (qwen2.5 sin wrapper)
      4. '{"tool":"name","args":{...}}'      (formato correcto)
      5. Cualquier JSON válido con campo 'tool'
    """
    raw = raw.strip()

    # 1. Bloque markdown explícito — siempre prioritario
    m = _JSON_BLOCK.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Limpiar bloque <think> de modelos de razonamiento
    clean = _THINK_BLOCK.sub("", raw).strip()

    # 3. Formato inline: 'tool_name {"args":...}'
    #    qwen2.5 a veces omite el wrapper {"tool":...,"args":...}
    m = _TOOL_INLINE.match(clean)
    if m:
        tool_name = m.group(1).lower()
        if tool_name in _VALID_TOOLS:
            try:
                args = json.loads(m.group(2))
                return {"tool": tool_name, "args": args}
            except json.JSONDecodeError:
                pass

    # 4. Buscar todos los JSON candidatos, priorizar los que tienen campo 'tool'
    candidates = list(_BARE_JSON.finditer(clean))

    # 4a. Último JSON válido con campo 'tool' (el más probable)
    for m in reversed(candidates):
        try:
            d = json.loads(m.group(0))
            if isinstance(d, dict) and "tool" in d:
                return d
        except json.JSONDecodeError:
            continue

    # 4b. Cualquier JSON válido (último)
    for m in reversed(candidates):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue

    # 5. Parsear el texto limpio completo
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return None


class OllamaClient:

    async def generate(
        self,
        message: str,
        mode: str = "chat",
        request_id: str = None,
        memory: str | None = None,
        _retry: int = 0,
    ) -> str:

        logger = attach_request_id(llm_logger, request_id)
        error  = attach_request_id(error_logger, request_id)

        system_prompt = get_system_prompt(mode)
        messages = [{"role": "system", "content": system_prompt}]
        if memory:
            messages.append({"role": "system", "content": memory})
        messages.append({"role": "user", "content": message})

        num_ctx = settings.LLM_NUM_CTX_TOOL if mode == "tool" else settings.LLM_NUM_CTX_CHAT

        payload = {
            "model": settings.MODEL_NAME,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "num_ctx": num_ctx,
                "temperature": 0.0 if mode == "tool" else 0.7,
            },
        }

        logger.info("LLM INPUT: %s", message)
        logger.info(
            "LLM MODEL: %s  MODE: %s  num_ctx=%d  reasoning=%s",
            settings.MODEL_NAME, mode, num_ctx, settings.LLM_IS_REASONING,
        )
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
            msg = data.get("message")
            if not isinstance(msg, dict):
                raise ValueError(f"Estructura inesperada: {data}")

            content = msg.get("content", "").strip()
            if not content:
                raise ValueError(f"Contenido vacío: {data}")

            logger.debug("OLLAMA RAW RESPONSE: %s", data)

            if settings.LLM_IS_REASONING and "<think>" in content:
                think_match = _THINK_BLOCK.search(content)
                if think_match:
                    logger.debug("THINK BLOCK: %s", think_match.group(0)[:500])
                logger.debug("OLLAMA CONTENT (sin think): %s", _THINK_BLOCK.sub("", content).strip())
            else:
                logger.debug("OLLAMA CONTENT: %s", content)

            logger.info("Respuesta LLM recibida correctamente")
            return content

        except Exception as e:
            if _retry < 2:
                wait = 2 ** _retry
                error.warning(
                    "LLM error (intento %d/3), reintentando en %ds: %s",
                    _retry + 1, wait, repr(e),
                )
                await asyncio.sleep(wait)
                return await self.generate(
                    message, mode=mode, request_id=request_id,
                    memory=memory, _retry=_retry + 1,
                )

            error.exception("Error al generar respuesta con Ollama (agotados reintentos)")
            return json.dumps({
                "tool": "no_op",
                "args": {"message": f"LLM_ERROR: {repr(e)}"},
            })
