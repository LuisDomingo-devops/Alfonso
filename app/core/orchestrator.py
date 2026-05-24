import json
from app.utils.logger import attach_request_id, orchestrator_logger, error_logger
from app.core.tool_registry import get_tool
from app.core.memory import memory


class Orchestrator:

    async def run(self, user_message: str, llm, request_id: str = None, session_id: str | None = None):

        session_id = session_id or request_id
        logger = attach_request_id(orchestrator_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        logger.info("REQUEST_ID iniciado")
        logger.info("USER MESSAGE: %s", user_message)
        logger.info("SESSION_ID: %s", session_id)

        memory_text = memory.get_summary(session_id) if session_id else None

        # -----------------------
        # DETECCIÓN SIMPLE TOOL
        # -----------------------
        tool_keywords = [
            "crea",
            "crear",
            "lee",
            "archivo",
            "escribe",
            "ejecuta",
            "run",
            "comando",
            "lista",
            "listar"
        ]

        is_tool = any(
            k in user_message.lower()
            for k in tool_keywords
        )

        mode = "tool" if is_tool else "chat"
        logger.info("LLM INPUT mode=%s", mode)

        if session_id:
            memory.add_message(session_id, "user", user_message)

        raw = await llm.generate(
            user_message,
            mode=mode,
            request_id=request_id,
            memory=memory_text
        )

        logger.debug("LLM OUTPUT: %s", raw)

        # -----------------------
        # CHAT MODE
        # -----------------------
        if mode == "chat":

            logger.info("LLM respuesta de chat completada")
            if session_id:
                memory.add_message(session_id, "assistant", raw)
            return {
                "type": "chat",
                "response": raw
            }

        # -----------------------
        # TOOL MODE
        # -----------------------
        try:
            data = json.loads(raw)

        except Exception:
            error.exception("Error parseando respuesta JSON de LLM")
            return {
                "type": "error",
                "message": "LLM no devolvió JSON válido",
                "raw": raw
            }

        # -----------------------
        # NORMALIZACIÓN FORMATOS
        # -----------------------

        tool_name = None
        args = {}

        if "tool" in data:
            logger.info("Tool detectado: %s", data.get("tool"))
            tool_name = data.get("tool")
            args = data.get("args", {})

        else:
            orchestrator_logger.debug("Intentando detectar tool en formato QWEN: %s", data.keys())
            tool_name = next(
                iter(data.keys()),
                None
            )

            if tool_name:
                nested = data.get(tool_name, {})
                if isinstance(nested, dict):
                    args = nested.get("args", {})

        if not tool_name:
            error.error("Tool no detectado en JSON: %s", data)
            return {
                "type": "error",
                "message": "No se pudo extraer tool del JSON",
                "raw": data
            }

        tool = get_tool(tool_name, request_id=request_id)

        if not tool:
            error.error("Tool no existe: %s", tool_name)
            return {
                "type": "error",
                "message": f"Tool no existe: {tool_name}"
            }

        try:
            logger.info("TOOL CALL: %s args=%s", tool_name, args)
            result = await tool(**args)
            logger.info("TOOL RESULT: %s", result)

        except Exception as e:
            error.exception("Error ejecutando tool %s", tool_name)
            return {
                "type": "error",
                "message": str(e),
                "tool": tool_name,
                "args": args
            }

        if session_id:
            memory.add_message(session_id, "assistant", f"Tool {tool_name} result: {result}")

        logger.info("Tool ejecutado exitosamente: %s", tool_name)
        return {
            "type": "tool",
            "tool": tool_name,
            "result": result
        }
