import json
from app.utils.logger import attach_request_id, parser_logger, error_logger


class ResponseParser:

    def parse(self, raw_response: str, request_id: str = None):
        logger = attach_request_id(parser_logger, request_id)
        error = attach_request_id(error_logger, request_id)

        try:
            data = json.loads(raw_response)
            logger.info("Respuesta parseada correctamente")
            return {
                "status": "success",
                "data": data
            }

        except Exception:
            error.exception("Error parseando respuesta JSON")
            return {
                "status": "error",
                "message": "JSON inválido",
                "raw": raw_response
            }