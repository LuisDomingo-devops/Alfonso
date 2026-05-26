from typing import Optional

class ResponseProcessor:
    """Lógica de negocio: procesamiento de texto y formateo de respuestas."""

    @staticmethod
    def extract_order(wakeword_text: str, keyword: str) -> Optional[str]:
        """Extrae la orden si el usuario dijo 'Alfonso, haz X' de un tirón."""
        text = wakeword_text.lower().strip().rstrip(".,!?")
        kw = keyword.lower().strip()
        if text == kw:
            return None
        for sep in [", ", " ", ","]:
            candidate = kw + sep
            if text.startswith(candidate):
                order = wakeword_text[len(candidate):].strip()
                return order if order else None
        return None

    @staticmethod
    def format_response(result_data: dict) -> str:
        """Transforma la respuesta compleja del servidor en texto legible."""
        result_type = result_data.get("type", "")

        if result_type == "chat":
            return result_data.get("response") or "Sin respuesta."

        if result_type == "tool":
            tool_name = result_data.get("tool", "herramienta")
            tool_result = result_data.get("result", {})
            status = tool_result.get("status", "")
            message = tool_result.get("message", "")

            if status == "ok":
                return message if message else f"Listo, ejecuté {tool_name} correctamente."
            else:
                error = tool_result.get("message", "error desconocido")
                return f"Error en {tool_name}: {error}"

        if result_type == "error":
            return f"Error: {result_data.get('message', 'error desconocido')}"

        return str(result_data)

    @staticmethod
    def is_exit_command(text: str) -> bool:
        exit_words = {"adiós", "adios", "hasta luego", "para", "stop", "salir", "bye"}
        return any(w in text.lower() for w in exit_words)