from app.core.tool_registry import get_tool, prepare_tool_args
from app.utils.logger import attach_request_id, tool_logger, error_logger


class ToolExecutor:

    async def execute(self, data: dict, request_id: str = None):

        logger = attach_request_id(tool_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        tool_name = data.get("tool")
        args = data.get("args", {})

        tool = get_tool(tool_name, request_id=request_id)

        if not tool:
            error.warning("Tool no encontrada: %s", tool_name)
            return {
                "type": "error",
                "message": f"Tool no encontrada: {tool_name}"
            }

        # Fase 1 (BaseTool + Pydantic), modo permisivo por defecto:
        # ver app/core/tool_base.py para el razonamiento completo.
        validated = prepare_tool_args(tool_name, args, request_id)

        if not validated.ok:
            error.warning("Args inválidos para tool %s: %s", tool_name, validated.error)
            return {
                "type": "error",
                "message": validated.error,
            }

        if validated.warnings:
            logger.info(
                "Args de %s corregidos en modo permisivo: %s",
                tool_name,
                "; ".join(validated.warnings),
            )

        args = validated.args

        try:
            logger.info("TOOL CALL: %s args=%s", tool_name, args)
            result = await tool(**args)
            logger.info("TOOL RESULT: %s", result)
            return {
                "type": "tool",
                "tool": tool_name,
                "result": result
            }

        except Exception as e:
            error.exception("Error ejecutando tool: %s", tool_name)
            return {
                "type": "error",
                "message": str(e)
            }