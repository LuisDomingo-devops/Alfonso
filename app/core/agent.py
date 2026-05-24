from app.core.intent_router import IntentRouter
from app.core.response_parser import ResponseParser
from app.core.tool_executor import ToolExecutor
from app.utils.logger import agent_logger, attach_request_id


class Agent:

    def __init__(self, llm):
        self.llm = llm
        self.router = IntentRouter()
        self.parser = ResponseParser()
        self.executor = ToolExecutor()

    async def run(self, user_message: str, request_id: str = None):

        logger = attach_request_id(agent_logger, request_id)

        intent = self.router.detect(user_message)

        logger.info("REQUEST_ID iniciado")
        logger.info("Mensaje recibido: %s", user_message)
        logger.info("Intent detectado: %s", intent)

        # CHAT
        if intent == "chat":

            response = await self.llm.generate(
                user_message,
                mode="chat",
                request_id=request_id
            )

            logger.info("Chat generado correctamente")
            return {
                "type": "chat",
                "response": response
            }

        # TOOL
        raw_response = await self.llm.generate(
            user_message,
            mode="tool",
            request_id=request_id
        )

        parsed = self.parser.parse(raw_response, request_id=request_id)

        if parsed["status"] == "error":
            logger.error("Error de parseo de respuesta de herramienta: %s", parsed)
            return parsed

        result = await self.executor.execute(parsed["data"], request_id=request_id)
        logger.info("Ejecución de herramienta finalizada")
        return result
