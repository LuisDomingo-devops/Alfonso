"""
LLM CLIENT — Cliente del modelo de lenguaje (Ollama).

¿QUÉ HACE?
Gestiona la comunicación con el servidor Ollama local para generar texto, completar chats, estructurar JSON y precalentar el modelo.

¿CUÁNDO LO HACE?
Siempre que el orquestador, router o agentes requieran capacidades cognitivas de inferencia del LLM.

¿CÓMO LO HACE?
Formateando payloads HTTP compatibles con la API `/api/chat` de Ollama y llamándolos con app/core/http_client.py.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/core/http_client.py (provee el cliente HTTP subyacente para las peticiones)
- app/core/planner_orchestrator.py (usa este cliente para planificar y responder en el chat)
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path          
from app.config import settings
from app.adapters.http_client import client
from app.adapters.tool_registry import get_tool
from app.domain.prompt_generator import generate_tool_prompt
from app.utils.logger import attach_request_id, llm_logger, error_logger

# ---------------------------------------------------------------------
# REGEX
# ---------------------------------------------------------------------

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
_TOOL_INLINE = re.compile(r"^([a-z_]+)\s+(\{.*\})$", re.DOTALL | re.IGNORECASE)
_TOOL_SPLIT_COLON = re.compile(r"^([a-zA-Z_]+)\s*:\s*(\{.*\})$", re.DOTALL | re.IGNORECASE)
_TOOL_PLAIN_COLON = re.compile(r"^([a-zA-Z0-9_-]+)\s*:\s*(.+)$", re.DOTALL)
_TOOL_PLAIN_SPACE = re.compile(r"^([a-zA-Z0-9_-]+)\s+(.+)$", re.DOTALL)

# ---------------------------------------------------------------------
# UTIL
# ---------------------------------------------------------------------

def _get_current_date_str() -> str:
    ''' Esta función devuelve la fecha y hora actual en español, 
    en el formato: "lunes, 1 de enero de 2024, 14:30" '''

    now = datetime.now()
    days = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months = [
        "enero","febrero","marzo","abril","mayo","junio",
        "julio","agosto","septiembre","octubre","noviembre","diciembre",
    ]
    return f"{days[now.weekday()]}, {now.day} de {months[now.month - 1]} de {now.year}, {now.strftime('%H:%M')}"


from functools import lru_cache

@lru_cache(maxsize=8) # Este decorador almacena en caché los prompts generados para evitar recalcularlos repetidamente'''
def _read_prompt_file(path: str) -> str:
    ''' Lee el contenido de un archivo de prompt y lo devuelve como cadena.'''
    return Path(path).read_text(encoding="utf-8")


def load_prompt(path: str) -> str:
    ''' Carga un prompt desde un archivo y devuelve su contenido.'''
    try:
        return _read_prompt_file(path)
    except FileNotFoundError:
        error_logger.error("Prompt no encontrado en %s, usando fallback mínimo", path)
        return "Eres Alfonso. Responde de forma útil y concisa."


def get_system_prompt(mode: str) -> str:
    ''' Devuelve el prompt de sistema correspondiente al modo 
    especificado ("chat" o "tool"). '''
    if mode == "chat":
        template = load_prompt(settings.CHAT_PROMPT_PATH)
        try:
            from app.domain.prompt_generator import get_client_context_str
            client_ctx = get_client_context_str()
            template = template + "\n\n" + client_ctx
        except Exception:
            pass
    else:
        template = generate_tool_prompt()
    return template.replace("{current_date}", _get_current_date_str())
# ---------------------------------------------------------------------
# VALIDACIÓN TOOL
# ---------------------------------------------------------------------

def validate_tool_call(tool_call: dict) -> dict:
    ''' Valida la estructura de la llamada a la herramienta y
    devuelve un diccionario con el nombre de la herramienta y sus 
    argumentos. '''
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
    ''' Extrae un bloque JSON de una cadena de texto, manejando 
    varios formatos y casos especiales.
    Devuelve un diccionario con la herramienta y sus argumentos,'''
    if not raw:
        return None

    raw = raw.strip()

    # 0. FIX CRÍTICO: JSON directo (ESTO TE FALTABA)
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 0.5. Si hay múltiples líneas (ej. múltiples herramientas generadas), probar línea por línea
    if "\n" in raw:
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if isinstance(data, dict) and "tool" in data:
                        return data
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

    try:
        return json.loads(clean)
    except Exception:
        pass

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

    # 5. Fallback para formatos planos sin JSON: "tool_name: value" o "tool_name value"
    for regex in [_TOOL_PLAIN_COLON, _TOOL_PLAIN_SPACE]:
        m = regex.match(clean)
        if m:
            t_name = m.group(1).lower().strip()
            val = m.group(2).strip()
            if not val.startswith("{"):
                # Quitar comillas si las hay
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1].strip()
                
                # Intentar mapear al primer parámetro de la función del registry
                try:
                    from app.adapters.tool_registry import safe_get_tool, list_tools
                    import inspect
                    if t_name in list_tools():
                        func = safe_get_tool(t_name)
                        if func:
                            sig = inspect.signature(func)
                            params = [p for p in sig.parameters.keys() if p not in ("self", "session_id")]
                            if params:
                                return {
                                    "tool": t_name,
                                    "args": {params[0]: val}
                                }
                except Exception:
                    pass

                # Mapeo manual alternativo para herramientas comunes
                CLIENT_ARGS_MAPPING = {
                    "open_url": "url",
                    "open_application": "command",
                    "open_app": "command",
                    "close_application": "command",
                    "close_app": "command",
                    "create_file": "path",
                    "delete_file": "path",
                    "read_file": "path",
                    "list_directory": "path",
                    "create_directory": "path",
                    "delete_directory": "path",
                    "keyboard_type": "text",
                    "keyboard_press": "key",
                    "press_key": "key",
                }
                if t_name in CLIENT_ARGS_MAPPING:
                    return {
                        "tool": t_name,
                        "args": {CLIENT_ARGS_MAPPING[t_name]: val}
                    }

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
        options: dict | None = None,
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

        options_payload = {
            "num_ctx": num_ctx,
            "temperature": 0.0 if mode == "tool" else 0.7,
        }
        if options:
            options_payload.update(options)

        payload = {
            "model": settings.MODEL_NAME,
            "messages": messages,
            "stream": False,
            "keep_alive": -1,
            "options": options_payload,
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
                    options=options,
                    _retry=_retry + 1,
                )

            error.exception("LLM failed permanently")

            if mode == "chat":
                return "Estoy teniendo problemas técnicos para responderte. Por favor, inténtalo de nuevo en unos instantes."

            return json.dumps({
                "tool": "no_op",
                "args": {"message": f"LLM_ERROR: {repr(e)}"}
            })