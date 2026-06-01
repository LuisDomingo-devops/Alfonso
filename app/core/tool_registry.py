import importlib
import inspect
from pathlib import Path
from typing import Any, Callable

from app.utils.logger import attach_request_id, tool_registry_logger


async def no_op(message: str):
    return {
        "status": "ignored",
        "message": message
    }


TOOLS: dict[str, Callable[..., Any]] = {
    "no_op": no_op,
}

_plugins_loaded = False


def register_tool(name: str, func: Callable[..., Any]) -> None:
    tool_registry_logger.info("Registrando tool: %s", name)
    TOOLS[name] = func


def _get_tools_directory() -> Path:
    return Path(__file__).resolve().parents[1] / "tools"


def load_plugins() -> None:
    global _plugins_loaded
    if _plugins_loaded:
        return

    tools_dir = _get_tools_directory()
    if not tools_dir.exists():
        tool_registry_logger.warning("No existe el directorio de herramientas: %s", tools_dir)
        _plugins_loaded = True
        return

    for module_path in tools_dir.glob("*.py"):
        if module_path.name == "__init__.py":
            continue

        module_name = module_path.stem
        full_module_name = f"app.tools.{module_name}"

        try:
            module = importlib.import_module(full_module_name)
            tool_registry_logger.info("Cargando plugin: %s", full_module_name)
        except Exception:
            tool_registry_logger.exception("Error cargando plugin %s", full_module_name)
            continue

        tools = getattr(module, "TOOLS", None)
        if isinstance(tools, dict):
            for name, func in tools.items():
                if callable(func):
                    register_tool(name, func)
                else:
                    tool_registry_logger.warning("Tool %s en %s no es callable", name, full_module_name)

        elif hasattr(module, "register_tools"):
            try:
                module.register_tools(register_tool)
            except Exception:
                tool_registry_logger.exception("Error en register_tools de %s", full_module_name)

    _plugins_loaded = True


def _ensure_plugins_loaded() -> None:
    if not _plugins_loaded:
        load_plugins()


def get_tool(name: str, request_id: str = None):
    _ensure_plugins_loaded()
    logger = attach_request_id(tool_registry_logger, request_id)
    tool = TOOLS.get(name)
    if tool is None:
        logger.warning("Tool solicitada no existe: %s", name)
    return tool


def list_tools() -> list[str]:
    _ensure_plugins_loaded()
    return list(TOOLS.keys())


def safe_get_tool(name: str):
    _ensure_plugins_loaded()
    tool = TOOLS.get(name)

    if tool is None:
        return no_op

    return tool


def get_tools_info() -> list[dict[str, Any]]:
    """
    Retorna metadatos de las herramientas para el Task Planner.
    """
    _ensure_plugins_loaded()
    info = []
    for name, func in TOOLS.items():
        if name == "no_op":
            continue
        info.append({
            "name": name,
            "description": inspect.getdoc(func) or "Sin descripción disponible."
        })
    return info
