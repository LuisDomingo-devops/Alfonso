"""
LOGGER — Configuración del registro de logs.

¿QUÉ HACE?
Define e inicializa la configuración de logs con rotación diaria para la app, el planificador y los errores.

¿CUÁNDO LO HACE?
Al inicio de la aplicación y a lo largo de toda la ejecución de cualquier script del servidor.

¿CÓMO LO HACE?
Configurando handlers de la biblioteca estándar `logging` e inyectando request IDs.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/main.py (middleware HTTP utiliza el logger para registrar peticiones entrantes)
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

FORMAT = "%(asctime)s | %(levelname)s | %(name)s | [%(request_id)s] %(message)s"
DEFAULT_REQUEST_ID = "----------"


class RequestIdFormatter(logging.Formatter):
    def format(self, record):
        if getattr(record, "request_id", None) is None:
            record.request_id = DEFAULT_REQUEST_ID
        return super().format(record)


class ColorFormatter(RequestIdFormatter):
    COLOR_MAP = {
        logging.DEBUG: "\033[94m",
        logging.INFO: "\033[92m",
        logging.WARNING: "\033[93m",
        logging.ERROR: "\033[91m",
        logging.CRITICAL: "\033[95m",
    }
    RESET = "\033[0m"

    def format(self, record):
        message = super().format(record)
        color = self.COLOR_MAP.get(record.levelno, self.RESET)
        return f"{color}{message}{self.RESET}"


formatter = RequestIdFormatter(FORMAT)
console_formatter = ColorFormatter(FORMAT)


def attach_request_id(logger: logging.Logger, request_id: str | None = None):
    if request_id is None:
        request_id = DEFAULT_REQUEST_ID
    return logging.LoggerAdapter(logger, {"request_id": request_id})


def build_logger(name: str, filename: str, log_to_console: bool = True):
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    file_handler = RotatingFileHandler(
        LOG_DIR / filename,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )

    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger


app_logger = build_logger("app", "app.log")
tool_logger = build_logger("tools", "tools.log")
error_logger = build_logger("errors", "errors.log")
orchestrator_logger = build_logger("planner_orchestrator", "planner_orchestrator.log")
agent_logger = build_logger("agent", "agent.log")
llm_logger = build_logger("llm", "llm.log")
tool_registry_logger = build_logger("tool_registry", "tool_registry.log")
parser_logger = build_logger("parser", "parser.log")
http_logger = build_logger("http", "http.log")