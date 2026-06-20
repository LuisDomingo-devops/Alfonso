"""
computer_use_tools.py — FIX arquitectura: delegación pura al agente local.

ANTES: estas funciones importaban pyautogui/cv2/pytesseract y ejecutaban
TODO dentro del contenedor/WSL del servidor. El servidor no tiene acceso al
framebuffer, ratón ni teclado reales del usuario, así que nunca controlaban
el equipo real, sólo (si acaso) una sesión X virtual dentro de WSL.

AHORA: cada función empaqueta sus argumentos y los envía vía
`alfonso_bridge.send_command(action, params)` al agente local
(ui/alfonso_agent.py, corriendo en la máquina del usuario). Si no hay agente
conectado, se devuelve un error explícito — nunca un fallback silencioso
que actúe sobre el servidor.
"""

from __future__ import annotations

from typing import Optional

from app.core.alfonso_bridge import bridge as alfonso_bridge
from app.utils.logger import error_logger, tool_logger


async def _delegate(action: str, params: dict) -> dict:
    """Envía la acción al agente local y normaliza la respuesta."""
    if not alfonso_bridge.has_clients():
        error_logger.warning(
            "computer_use: no hay agente local conectado para '%s'. "
            "Arranca ui/alfonso_agent.py en tu equipo.",
            action,
        )
        return {
            "status": "error",
            "message": (
                f"No hay agente local conectado. La acción '{action}' "
                "requiere controlar tu equipo directamente; ejecuta "
                "ui/alfonso_agent.py en tu máquina y vuelve a intentarlo."
            ),
        }

    tool_logger.info("computer_use: delegando '%s' args=%s", action, params)
    response = await alfonso_bridge.send_command(action, params)

    if response.get("status") == "success":
        result = response.get("result")
        if isinstance(result, dict):
            return {"status": "ok", **result}
        return {"status": "ok", "result": result}

    return {
        "status": "error",
        "message": response.get(
            "error", f"Error desconocido ejecutando '{action}' en el agente local."
        ),
    }


# ---------------------------------------------------------------------------
# SCREENSHOT
# ---------------------------------------------------------------------------

async def screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    save_path: Optional[str] = None,
) -> dict:
    return await _delegate("screenshot", {"region": region, "save_path": save_path})


# ---------------------------------------------------------------------------
# MOUSE
# ---------------------------------------------------------------------------

async def mouse_move(x: int, y: int, duration: float = 0.25) -> dict:
    return await _delegate("mouse_move", {"x": x, "y": y, "duration": duration})


async def mouse_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> dict:
    return await _delegate(
        "mouse_click",
        {"x": x, "y": y, "button": button, "clicks": clicks, "interval": interval},
    )


async def mouse_drag(
    x1: int, y1: int,
    x2: int, y2: int,
    duration: float = 0.5,
    button: str = "left",
) -> dict:
    return await _delegate(
        "mouse_drag",
        {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration, "button": button},
    )


# ---------------------------------------------------------------------------
# KEYBOARD
# ---------------------------------------------------------------------------

async def keyboard_type(text: str, interval: float = 0.03) -> dict:
    return await _delegate("keyboard_type", {"text": text, "interval": interval})


async def keyboard_hotkey(*keys: str) -> dict:
    # ComputerAgent llama a esta tool con *keys posicionales (ver computer_agent.py)
    return await _delegate("keyboard_hotkey", {"keys": list(keys)})


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

async def ocr_screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    lang: str = "spa+eng",
) -> dict:
    return await _delegate("ocr_screenshot", {"region": region, "lang": lang})


async def ocr_image(path: str, lang: str = "spa+eng") -> dict:
    # NOTA: `path` se resuelve en el filesystem del AGENTE LOCAL, no del servidor.
    return await _delegate("ocr_image", {"path": path, "lang": lang})


# ---------------------------------------------------------------------------
# FIND ON SCREEN
# ---------------------------------------------------------------------------

async def find_on_screen(
    template_path: str,
    threshold: float = 0.8,
    region: Optional[tuple[int, int, int, int]] = None,
) -> dict:
    return await _delegate(
        "find_on_screen",
        {"template_path": template_path, "threshold": threshold, "region": region},
    )


# ---------------------------------------------------------------------------
# WINDOW CONTROL
# ---------------------------------------------------------------------------

async def window_list() -> dict:
    return await _delegate("window_list", {})


async def window_focus(title: str) -> dict:
    return await _delegate("window_focus", {"title": title})


async def window_close(title: str) -> dict:
    return await _delegate("window_close", {"title": title})


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

TOOLS = {
    "screenshot":       screenshot,
    "mouse_move":       mouse_move,
    "mouse_click":      mouse_click,
    "mouse_drag":       mouse_drag,
    "keyboard_type":    keyboard_type,
    "keyboard_hotkey":  keyboard_hotkey,
    "ocr_screenshot":   ocr_screenshot,
    "ocr_image":        ocr_image,
    "find_on_screen":   find_on_screen,
    "window_list":      window_list,
    "window_focus":     window_focus,
    "window_close":     window_close,
}