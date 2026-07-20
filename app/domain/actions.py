"""
ACTIONS — Acciones asíncronas y operaciones del orquestador.

¿QUÉ HACE?
Define tareas de utilidad y validaciones ejecutadas por el orquestador durante el ciclo de vida del plan.

¿CUÁNDO LO HACE?
Durante la ejecución del planificador para verificar el estado del cliente, resolver tareas complejas y realizar acciones genéricas.

¿CÓMO LO HACE?
Mediante funciones asíncronas de Python que interactúan con el puente WebSocket y el estado del sistema.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/domain/planner_orchestrator.py (invoca estas acciones durante su pipeline)
- app/adapters/alfonso_bridge.py (verifica el estado de las conexiones websocket activas)
"""

from __future__ import annotations


class Action:
    """Namespace de constantes. Usar Action.MOUSE_CLICK en vez de la
    cadena "mouse.click" escrita a mano en cada archivo."""

    # --- Sistema -----------------------------------------------------
    # Convención "bare" (sin punto) — ya desplegada y funcionando según
    # logs/tools.log ("Delegando open_url al agente local: ..." sin
    # errores de "Action no permitida" posteriores a la corrección).
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    OPEN_URL = "open_url"
    BROWSER_CLOSE = "browser_close"

    # --- Filesystem ----------------------------------------------------
    # Mismo motivo: convención bare ya en uso por el agente local.
    CREATE_FILE = "create_file"
    READ_FILE = "read_file"
    LIST_DIRECTORY = "list_directory"
    CREATE_DIRECTORY = "create_directory"
    APPEND_FILE = "append_file"
    DELETE_FILE = "delete_file"
    DELETE_DIRECTORY = "delete_directory"
    MOVE_FILE = "move_file"
    RENAME_FILE = "rename_file"
    REPLACE_FILE_CONTENT = "replace_file_content"

    # --- Ratón -----------------------------------------------------
    MOUSE_MOVE = "mouse.move"
    MOUSE_CLICK = "mouse.click"
    MOUSE_DRAG = "mouse.drag"

    # --- Teclado -------------------------------------------------------
    # KEYBOARD_PRESS (pulsación de una sola tecla) y KEYBOARD_HOTKEY
    # (combinación, p.ej. ctrl+c) son acciones DISTINTAS — no son el
    # mismo concepto con dos nombres, así que se mantienen separadas.
    KEYBOARD_TYPE = "keyboard.type"
    KEYBOARD_PRESS = "keyboard.press"
    KEYBOARD_HOTKEY = "keyboard.hotkey"

    # --- Pantalla / OCR --------------------------------------------
    SCREEN_SCREENSHOT = "screen.screenshot"
    SCREEN_OCR_SCREENSHOT = "screen.ocr_screenshot"
    SCREEN_OCR_IMAGE = "screen.ocr_image"
    SCREEN_FIND = "screen.find_on_screen"

    # --- Ventanas --------------------------------------------------
    WINDOW_LIST = "window.list"
    WINDOW_FOCUS = "window.focus"
    WINDOW_CLOSE = "window.close"

    # --- Calendario ------------------------------------------------
    CALENDAR_OPEN = "calendar.open"
    CALENDAR_SYNC = "calendar.sync"

    # --- Correo ----------------------------------------------------
    MAIL_OPEN = "mail.open"
    MAIL_CLOSE = "mail.close"
    MAIL_SYNC = "mail.sync"

    # --- Dev Studio ------------------------------------------------
    DEV_STUDIO_OPEN = "dev_studio.open"
    DEV_STUDIO_CLOSE = "dev_studio.close"


# Whitelist generada a partir de la clase Action — nunca se mantiene a
# mano, así que no puede desincronizarse de las constantes de arriba.
ALLOWED_ACTIONS: frozenset[str] = frozenset(
    value
    for name, value in vars(Action).items()
    if not name.startswith("_") and isinstance(value, str)
)


# Alias cortos que el LLM puede emitir en modo "tool" y que
# PlannerOrchestrator resuelve directo contra el bridge (sin pasar por
# una función Python intermedia en SERVER_TOOLS). Pensado para acciones
# de input físico sin lógica de servidor propia que valga la pena.
#
# IMPORTANTE: si una clave de aquí coincide con el nombre de una función
# registrada en SERVER_TOOLS (p.ej. "screenshot"), is_client_tool() la
# intercepta PRIMERO y la función Python correspondiente nunca se llega
# a invocar desde PlannerOrchestrator (sí se sigue pudiendo invocar
# directamente vía REST en routes_fase3.py, que llama get_tool() sin
# pasar por is_client_tool()). Ambos caminos ahora delegan al mismo
# Action.* canónico, así que el resultado final es idéntico — pero si se
# añaden alias nuevos aquí, conviene no repetir nombres de SERVER_TOOLS
# salvo que sea intencional.
CLIENT_ALIASES: dict[str, str] = {
    "open_app": Action.OPEN_APP,
    "open_application": Action.OPEN_APP,
    "close_app": Action.CLOSE_APP,
    "close_application": Action.CLOSE_APP,
    "browser_close": Action.BROWSER_CLOSE,
    "click": Action.MOUSE_CLICK,
    "move_mouse": Action.MOUSE_MOVE,
    "drag_mouse": Action.MOUSE_DRAG,
    "type_text": Action.KEYBOARD_TYPE,
    "press_key": Action.KEYBOARD_PRESS,
    "focus_window": Action.WINDOW_FOCUS,
    "close_window": Action.WINDOW_CLOSE,
    "screenshot": Action.SCREEN_SCREENSHOT,
    "open_url": Action.OPEN_URL,
    "create_file": Action.CREATE_FILE,
    "read_file": Action.READ_FILE,
    "list_directory": Action.LIST_DIRECTORY,
    "create_directory": Action.CREATE_DIRECTORY,
    "append_file": Action.APPEND_FILE,
    "delete_file": Action.DELETE_FILE,
    "delete_directory": Action.DELETE_DIRECTORY,
    "move_file": Action.MOVE_FILE,
    "rename_file": Action.RENAME_FILE,
    "replace_file_content": Action.REPLACE_FILE_CONTENT,
    "open_calendar": Action.CALENDAR_OPEN,
    "calendar_open": Action.CALENDAR_OPEN,
    "open_mail": Action.MAIL_OPEN,
    "mail_open": Action.MAIL_OPEN,
    "close_mail": Action.MAIL_CLOSE,
    "mail_close": Action.MAIL_CLOSE,
    "dev_studio_open_ui": Action.DEV_STUDIO_OPEN,
    "dev_studio_open": Action.DEV_STUDIO_OPEN,
    "dev_studio_close_ui": Action.DEV_STUDIO_CLOSE,
    "dev_studio_close": Action.DEV_STUDIO_CLOSE,
}