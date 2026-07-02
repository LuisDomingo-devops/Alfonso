from typing import Optional
from core.config import EXIT_WORDS

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

            # Aceptar "ok" (de tools de servidor) o "success" (de tools de cliente)
            if status in ("ok", "success"):
                # Si no hay "message" pero hay "result"
                if not message and "result" in tool_result:
                    inner_res = tool_result["result"]
                    if isinstance(inner_res, dict):
                        message = inner_res.get("result") or inner_res.get("message") or str(inner_res)
                    else:
                        message = str(inner_res)

                # Si no hay message, extraer de campos específicos
                if not message:
                    if "human" in tool_result:
                        message = str(tool_result["human"])
                    elif "content" in tool_result:
                        message = str(tool_result["content"])
                    elif "text" in tool_result:
                        message = str(tool_result["text"])
                    elif "text_preview" in tool_result:
                        message = str(tool_result["text_preview"])
                    elif "entries" in tool_result:
                        entries = tool_result["entries"]
                        if isinstance(entries, list):
                            formatted_entries = []
                            for entry in entries:
                                name = entry.get("name", "")
                                is_dir = entry.get("is_dir", False)
                                formatted_entries.append(f"{name}/" if is_dir else name)
                            message = f"Contenido del directorio:\n" + "\n".join(formatted_entries)
                        else:
                            message = str(entries)
                    elif "system" in tool_result:
                        message = (
                            f"Sistema: {tool_result.get('system')} {tool_result.get('release')} "
                            f"({tool_result.get('version')})\n"
                            f"CPU: {tool_result.get('cpu_count')} núcleos\n"
                            f"RAM: {tool_result.get('ram_used_percent')}% usada de {tool_result.get('ram_total_gb')} GB\n"
                            f"Disco: {tool_result.get('disk_free_gb')} GB libres de {tool_result.get('disk_total_gb')} GB"
                        )

                if message and not isinstance(message, str):
                    if isinstance(message, list):
                        formatted_items = "\n".join(str(item) for item in message)
                        if tool_name == "list_directory":
                            dir_path = tool_result.get("path") or (inner_res.get("path") if isinstance(inner_res, dict) else None) or ""
                            if dir_path:
                                message = f"Contenido del directorio '{dir_path}':\n{formatted_items}"
                            else:
                                message = f"Contenido del directorio:\n{formatted_items}"
                        else:
                            message = formatted_items
                    else:
                        message = str(message)

                return message if message else f"Listo, ejecuté {tool_name} correctamente."
            else:
                # Extraer mensaje de error del bridge/cliente/servidor
                error = tool_result.get("message") or tool_result.get("error") or "error desconocido"
                if isinstance(error, dict):
                    error = error.get("error") or error.get("message") or str(error)
                return f"Error en {tool_name}: {error}"

        if result_type == "error":
            return f"Error: {result_data.get('message', 'error desconocido')}"

        return str(result_data)

    @staticmethod
    def is_exit_command(text: str) -> bool:
        return any(w in text.lower() for w in EXIT_WORDS)