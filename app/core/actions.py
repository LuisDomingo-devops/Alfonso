"""
app/core/actions.py — Vocabulario canónico de acciones cliente.

Antes de este módulo existían tres copias independientes del mismo
vocabulario de "qué string de acción cruza el bridge hacia el agente
local", y divergían entre sí:

    1. tool_registry.py::CLIENT_TOOLS     — alias cortos que el LLM puede
       emitir en modo "tool" (p.ej. "click" -> acción real)
    2. alfonso_bridge.py::ALLOWED_ACTIONS — whitelist de strings que el
       bridge acepta antes de mandarlos por websocket
    3. literales sueltos dentro de system_tools.py / computer_use_tools.py
       (las funciones Python que de verdad ejecutan la tool y delegan al
       bridge por dentro)

Confirmado por comparación directa de strings entre estos tres archivos:
las acciones de ratón/teclado/ventanas/OCR que usa computer_use_tools.py
(p.ej. "mouse_click", "keyboard_hotkey", "ocr_screenshot") usan guión bajo
y NUNCA estuvieron en ALLOWED_ACTIONS (que solo tenía "mouse.click" con
punto, y no tenía ocr_screenshot/ocr_image/find_on_screen/window_list en
ninguna forma). Toda llamada a esas funciones desde PlannerOrchestrator
(o desde el endpoint REST /computer/* en routes_fase3.py, que llama
get_tool() directamente) resulta en bridge.send_command() devolviendo
{"status": "error", "error": "Action no permitida: <nombre>"} — un fallo
silencioso porque nunca se vio ejercitado en producción, a diferencia de
open_app/close_app/open_url que sí fallaron y sí se corrigieron (ver
historial de comentarios en alfonso_bridge.py).

Las acciones de sistema (open_app, close_app, open_url) y de filesystem
(create_file, read_file, ...) SÍ están alineadas hoy entre system_tools.py
y ALLOWED_ACTIONS — se mantienen aquí tal cual, sin tocar su convención
(strings "bare", sin namespace), para no romper compatibilidad con
ui/alfonso_agent.py, que es el lado cliente del protocolo y que no está
en este repo para verificar directamente.

Las acciones de ratón/teclado/ventanas/pantalla usan namespace con punto
porque esa es la convención que CLIENT_TOOLS + ALLOWED_ACTIONS ya tenían
establecida ANTES de este módulo (p.ej. "mouse.click"), y es razonable
asumir que es la convención que el agente local ya reconoce — pero esto
no se ha verificado contra el código del agente local, que no está en
este repo. Si al probar contra el agente local real las acciones nuevas
(SCREEN_OCR_SCREENSHOT, SCREEN_OCR_IMAGE, SCREEN_FIND, WINDOW_LIST) no
responden, lo más probable es que el agente local todavía no implemente
esos handlers — no es un problema de este módulo, sino de que esa
funcionalidad nunca se completó en el lado cliente.
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
    "close_app": Action.CLOSE_APP,
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
}