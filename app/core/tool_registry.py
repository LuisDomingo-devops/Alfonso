import importlib
from pathlib import Path
from typing import Any, Callable, Type

from app.config import settings
from app.core.tool_base import ToolArgsModel, ValidatedArgs, coerce_and_validate
from app.utils.logger import (
    attach_request_id,
    tool_registry_logger
)


async def no_op(message: str):
    return {
        "status": "ignored",
        "message": message
    }


SERVER_TOOLS: dict[str, Callable[..., Any]] = {
    "no_op": no_op,
}

# Fase 1 (BaseTool + Pydantic): esquema opcional por tool.
# Cada entrada: nombre_tool -> (ModeloPydantic, alias_map)
# Si una tool no aparece aquí, se ejecuta exactamente igual que antes
# (sin ninguna validación) — la migración es incremental, módulo a módulo.
ARGS_SCHEMAS: dict[str, tuple[Type[ToolArgsModel], dict[str, str]]] = {}

CLIENT_TOOLS: dict[str, str] = {

    "open_app": "system.open_app",
    "close_app": "system.close_app",

    "click": "mouse.click",
    "move_mouse": "mouse.move",
    "drag_mouse": "mouse.drag",

    "type_text": "keyboard.type",
    "press_key": "keyboard.press",

    "focus_window": "window.focus",
    "close_window": "window.close",

    "screenshot": "screen.screenshot",
}


_plugins_loaded = False



def register_tool(
    name: str,
    func: Callable[..., Any]
):

    tool_registry_logger.info(
        "Registrando tool servidor: %s",
        name
    )

    SERVER_TOOLS[name] = func




def _get_tools_directory() -> Path:

    return (
        Path(__file__)
        .resolve()
        .parents[1]
        /
        "tools"
    )




def load_plugins():

    global _plugins_loaded


    if _plugins_loaded:
        return


    tools_dir = _get_tools_directory()


    if not tools_dir.exists():

        tool_registry_logger.warning(
            "No existe tools directory %s",
            tools_dir
        )

        _plugins_loaded = True
        return



    for module_path in tools_dir.glob("*.py"):


        if module_path.name == "__init__.py":
            continue


        module_name = module_path.stem

        full_module_name = (
            f"app.tools.{module_name}"
        )


        try:

            module = importlib.import_module(
                full_module_name
            )

            tool_registry_logger.info(
                "Cargando plugin %s",
                full_module_name
            )


        except Exception:

            tool_registry_logger.exception(
                "Error cargando %s",
                full_module_name
            )

            continue



        tools = getattr(
            module,
            "TOOLS",
            None
        )


        if isinstance(tools, dict):

            for name, func in tools.items():

                if callable(func):

                    register_tool(
                        name,
                        func
                    )




        elif hasattr(
            module,
            "register_tools"
        ):

            module.register_tools(
                register_tool
            )


        # Fase 1 (BaseTool + Pydantic): esquemas opcionales de args.
        # Convención: cada módulo de tools puede exponer un diccionario
        # ARGS_SCHEMAS = {"nombre_tool": (PydanticModel, alias_map)}.
        # Es opcional a propósito — no migrar un módulo no rompe nada.
        module_schemas = getattr(module, "ARGS_SCHEMAS", None)

        if isinstance(module_schemas, dict):

            for tool_name, schema_entry in module_schemas.items():

                ARGS_SCHEMAS[tool_name] = schema_entry

                tool_registry_logger.info(
                    "Registrando esquema de args (Fase 1): %s",
                    tool_name
                )


    _plugins_loaded = True




def _ensure_plugins_loaded():

    if not _plugins_loaded:
        load_plugins()




def get_tool(
    name: str,
    request_id: str = None
):

    _ensure_plugins_loaded()


    logger = attach_request_id(
        tool_registry_logger,
        request_id
    )


    tool = SERVER_TOOLS.get(
        name
    )


    if tool is None:

        logger.warning(
            "Tool servidor inexistente %s",
            name
        )


    return tool




def is_client_tool(
    name: str
):

    return name in CLIENT_TOOLS




def get_client_action(
    name: str
):

    return CLIENT_TOOLS.get(
        name
    )




def list_tools():

    _ensure_plugins_loaded()

    return list(
        SERVER_TOOLS.keys()
    )




def list_client_tools():

    return list(
        CLIENT_TOOLS.keys()
    )




def safe_get_tool(name: str):

    _ensure_plugins_loaded()

    return SERVER_TOOLS.get(
        name,
        no_op
    )




def get_args_schema(
    name: str
):
    """Devuelve (ModeloPydantic, alias_map) registrado para esta tool,
    o None si la tool todavía no tiene esquema (sigue sin validar, igual
    que antes de la Fase 1)."""

    _ensure_plugins_loaded()

    return ARGS_SCHEMAS.get(name)




def prepare_tool_args(
    name: str,
    raw_args: dict,
    request_id: str = None
) -> ValidatedArgs:
    """
    Punto único de entrada para validar/corregir args antes de ejecutar
    una tool (Fase 1). Usar esto en vez de llamar a `tool(**raw_args)`
    directamente evita que un TypeError crudo de Python (p.ej. "got an
    unexpected keyword argument 'file_path'") se propague tal cual al
    usuario, y permite recuperar args casi-correctos en modo permisivo.

    Si la tool no tiene esquema registrado, devuelve raw_args sin tocar
    (comportamiento idéntico al actual).
    """

    schema_entry = get_args_schema(name)

    schema, aliases = schema_entry if schema_entry else (None, None)

    return coerce_and_validate(
        tool_name=name,
        raw_args=raw_args or {},
        schema=schema,
        aliases=aliases,
        mode=settings.TOOL_VALIDATION_MODE,
        request_id=request_id,
    )




def get_callable_tool_function(
    name: str
):

    return safe_get_tool(
        name
    )