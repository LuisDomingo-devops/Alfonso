import re
from typing import Optional
from ui.config import EXIT_WORDS

def extract_order(wakeword_text: str, keyword: str) -> Optional[str]:
    """Si el usuario dijo 'Alfonso, haz X', extrae 'haz X'."""
    text = wakeword_text.lower().strip().rstrip(".,!?")
    kw = keyword.lower().strip()
    if text == kw:
        return None
    for sep in [", ", ",", " "]:
        if text.startswith(kw + sep):
            order = wakeword_text[len(kw) + len(sep):].strip()
            return order if order else None
    return None

def format_response(result_data: dict) -> str:
    """Convierte la respuesta del orchestrator en texto legible."""
    t = result_data.get("type", "")
 
    if t == "chat":
        return result_data.get("response") or "Sin respuesta."
 
    if t == "tool":
        tool_name = result_data.get("tool", "herramienta")
        tool_result = result_data.get("result", {})
        status = tool_result.get("status", "")
        message = tool_result.get("message", "")
 
        if tool_name == "no_op":
            return tool_result.get("message", "Necesito más información.")
 
        if status == "ok":
            if message:
                # Limpieza de rutas
                message = re.sub(r":\s*/[^\s]+/([^/\s]+)", r": \1", message)
            return message or f"Hecho."
 
        error_msg = tool_result.get("message", "error desconocido")
        return f"Ha ocurrido un error: {error_msg}"
 
    if t == "error":
        return f"Error: {result_data.get('message', 'error desconocido')}"
 
    if "message" in result_data:
        return result_data["message"]
 
    return "Completado."

def is_exit(text: str) -> bool:
    return any(w in text.lower() for w in EXIT_WORDS)