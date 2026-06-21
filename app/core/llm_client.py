"""
llm_client.py — Fase 3 — Multi-modelo (FINAL CORREGIDO)
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path          
from app.config import settings, load_prompt
from app.core.http_client import client
from app.core.tool_registry import get_tool
from app.core.prompt_generator import generate_tool_prompt
from app.utils.logger import attach_request_id, llm_logger, error_logger
from app.core.prompt_generator import generate_tool_prompt

# ---------------------------------------------------------------------
# REGEX
# ---------------------------------------------------------------------

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
_TOOL_INLINE = re.compile(r"^([a-z_]+)\s+(\{.*\})$", re.DOTALL | re.IGNORECASE)
_TOOL_SPLIT_COLON = re.compile(r"^([a-zA-Z_]+)\s*:\s*(\{.*\})$", re.DOTALL | re.IGNORECASE)

# ---------------------------------------------------------------------
# UTIL
# ---------------------------------------------------------------------

def _get_current_date_str() -> str:
    now = datetime.now()
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months = [
        "enero","febrero","marzo","abril","mayo","junio",
        "julio","agosto","septiembre","octubre","noviembre","diciembre",
    ]
    return f"{days[now.weekday()]}, {now.day} de {months[now.month - 1]} de {now.year}, {now.strftime('%H:%M')}"


from functools import lru_cache

@lru_cache(maxsize=8)
def _read_prompt_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_prompt(path: str) -> str:
    try:
        return _read_prompt_file(path)
    except FileNotFoundError:
        error_logger.error("Prompt no encontrado en %s, usando fallback mínimo", path)
        return "Eres Alfonso. Responde de forma útil y concisa."


def get_system_prompt(mode: str) -> str:
    if mode == "chat":
        template = load_prompt(settings.CHAT_PROMPT_PATH)
    else:
        template = generate_tool_prompt()
    return template.replace("{current_date}", _get_current_date_str())
# ---------------------------------------------------------------------
# VALIDACIÓN TOOL
# ---------------------------------------------------------------------

def validate_tool_call(tool_call: dict) -> dict:
    if not isinstance(tool_call, dict):
        return {"tool": "no_op", "args": {"message": "Invalid tool format"}}

    tool_name = tool_call.get("tool")
    args = tool_call.get("args", {})

    tool = get_tool(tool_name)

    if tool is None:
        return {"tool": "no_op", "args": {"message": f"Tool no existe: {tool_name}"}}

    if not isinstance(args, dict):
        return {"tool": "no_op", "args": {"message": "Args inválidos"}}

    return {"tool": tool_name, "args": args}


# ---------------------------------------------------------------------
# EXTRACTOR
# ---------------------------------------------------------------------
import json
import re

def extract_json_robust(raw: str) -> dict | None:
    if not raw:
        return None

    raw = raw.strip()

    # 0. FIX CRÍTICO: JSON directo (ESTO TE FALTABA)
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 1. JSON block (fallback regex)
    m = _JSON_BLOCK.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2. remove think blocks
    clean = _THINK_BLOCK.sub("", raw).strip()

    # 3. tool: {json}
    m = _TOOL_SPLIT_COLON.match(clean)
    if m:
        try:
            return {
                "tool": m.group(1).lower(),
                "args": json.loads(m.group(2))
            }
        except json.JSONDecodeError:
            pass

    # 4. inline tool
    m = _TOOL_INLINE.match(clean)
    if m:
        try:
            return {
                "tool": m.group(1).lower(),
                "args": json.loads(m.group(2))
            }
        except json.JSONDecodeError:
            pass

    return None

# ---------------------------------------------------------------------
# CLIENTE
# ---------------------------------------------------------------------

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
        error = attach_request_id(error_logger, request_id)

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

        logger.info("MODEL=%s MODE=%s", settings.MODEL_NAME, mode)

        try:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json=payload,
            )

            if response.status_code != 200:
                raise RuntimeError(response.text)

            data = response.json()
            content = data["message"]["content"].strip()

            if not content:
                raise ValueError("Empty response")

            return content

        except Exception as e:

            if _retry < 2:
                await asyncio.sleep(2 ** _retry)
                return await self.generate(
                    message,
                    mode=mode,
                    request_id=request_id,
                    memory=memory,
                    _retry=_retry + 1,
                )

            error.exception("LLM failed permanently")

            return json.dumps({
                "tool": "no_op",
                "args": {"message": f"LLM_ERROR: {repr(e)}"}
            })