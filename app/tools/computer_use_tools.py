"""
computer_use_tools.py — Fase 3: Computer Use

Herramientas de control del ordenador:
    screenshot          → captura la pantalla completa o una región
    mouse_move          → mueve el cursor a coordenadas absolutas
    mouse_click         → click izquierdo / derecho / doble en coordenadas
    mouse_drag          → arrastra desde un punto a otro
    keyboard_type       → escribe texto en el foco actual
    keyboard_hotkey     → ejecuta una combinación de teclas (ctrl+c, alt+f4…)
    ocr_screenshot      → captura la pantalla y extrae texto con OCR
    ocr_image           → extrae texto de un fichero de imagen
    find_on_screen      → busca una imagen template en la pantalla (coordenadas)
    window_list         → lista las ventanas abiertas
    window_focus        → lleva al frente una ventana por título
    window_close        → cierra una ventana por título

Dependencias: pyautogui, pillow, pytesseract, opencv-python, psutil, pygetwindow (win) / wmctrl (linux)
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import platform
import tempfile
from pathlib import Path
from typing import Optional

from app.utils.logger import error_logger, tool_logger

_SYSTEM = platform.system()  # "Linux" | "Windows" | "Darwin"


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _require(module_name: str):
    """Importa un módulo o lanza RuntimeError descriptivo."""
    import importlib
    try:
        return importlib.import_module(module_name)
    except ImportError:
        raise RuntimeError(
            f"Módulo '{module_name}' no instalado. "
            f"Ejecuta: pip install {module_name} --break-system-packages"
        )


async def _run_sync(func, *args, **kwargs):
    """Ejecuta una función bloqueante en un thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _pil_to_base64(image) -> str:
    """Convierte una imagen PIL a base64 PNG."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# SCREENSHOT
# ---------------------------------------------------------------------------

async def screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    save_path: Optional[str] = None,
) -> dict:
    """
    Captura la pantalla.

    Args:
        region: (x, y, width, height) — None para pantalla completa
        save_path: ruta donde guardar la imagen (opcional)

    Returns:
        {status, image_base64, width, height, path?}
    """
    tool_logger.info("screenshot: region=%s", region)
    try:
        pyautogui = _require("pyautogui")

        def _capture():
            if region:
                img = pyautogui.screenshot(region=region)
            else:
                img = pyautogui.screenshot()
            return img

        img = await _run_sync(_capture)
        img_b64 = _pil_to_base64(img)

        result: dict = {
            "status": "ok",
            "image_base64": img_b64,
            "width": img.width,
            "height": img.height,
        }

        if save_path:
            p = Path(save_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(p))
            result["path"] = str(p)
            tool_logger.info("Screenshot guardado en %s", p)

        return result

    except Exception as exc:
        error_logger.exception("Error en screenshot")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# MOUSE
# ---------------------------------------------------------------------------

async def mouse_move(x: int, y: int, duration: float = 0.25) -> dict:
    """Mueve el cursor a las coordenadas (x, y)."""
    tool_logger.info("mouse_move: (%d, %d)", x, y)
    try:
        pyautogui = _require("pyautogui")
        await _run_sync(pyautogui.moveTo, x, y, duration)
        return {"status": "ok", "x": x, "y": y}
    except Exception as exc:
        error_logger.exception("Error en mouse_move")
        return {"status": "error", "message": str(exc)}


async def mouse_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
    interval: float = 0.1,
) -> dict:
    """
    Hace click en (x, y).

    Args:
        button: "left" | "right" | "middle"
        clicks: 1 = simple, 2 = doble
    """
    tool_logger.info("mouse_click: (%d, %d) button=%s clicks=%d", x, y, button, clicks)
    try:
        pyautogui = _require("pyautogui")
        await _run_sync(pyautogui.click, x, y, clicks=clicks, button=button, interval=interval)
        return {"status": "ok", "x": x, "y": y, "button": button, "clicks": clicks}
    except Exception as exc:
        error_logger.exception("Error en mouse_click")
        return {"status": "error", "message": str(exc)}


async def mouse_drag(
    x1: int, y1: int,
    x2: int, y2: int,
    duration: float = 0.5,
    button: str = "left",
) -> dict:
    """Arrastra desde (x1, y1) hasta (x2, y2)."""
    tool_logger.info("mouse_drag: (%d,%d) → (%d,%d)", x1, y1, x2, y2)
    try:
        pyautogui = _require("pyautogui")
        await _run_sync(pyautogui.moveTo, x1, y1, 0.1)
        await _run_sync(pyautogui.dragTo, x2, y2, duration, button=button)
        return {"status": "ok", "from": [x1, y1], "to": [x2, y2]}
    except Exception as exc:
        error_logger.exception("Error en mouse_drag")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# KEYBOARD
# ---------------------------------------------------------------------------

async def keyboard_type(text: str, interval: float = 0.03) -> dict:
    """Escribe texto en el elemento con foco actual."""
    tool_logger.info("keyboard_type: %d chars", len(text))
    try:
        pyautogui = _require("pyautogui")
        await _run_sync(pyautogui.typewrite, text, interval=interval)
        return {"status": "ok", "chars_typed": len(text)}
    except Exception as exc:
        error_logger.exception("Error en keyboard_type")
        return {"status": "error", "message": str(exc)}


async def keyboard_hotkey(*keys: str) -> dict:
    """
    Ejecuta una combinación de teclas.
    Ejemplos: ("ctrl", "c"), ("alt", "F4"), ("ctrl", "shift", "t")
    """
    tool_logger.info("keyboard_hotkey: %s", keys)
    try:
        pyautogui = _require("pyautogui")
        await _run_sync(pyautogui.hotkey, *keys)
        return {"status": "ok", "keys": list(keys)}
    except Exception as exc:
        error_logger.exception("Error en keyboard_hotkey")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

async def ocr_screenshot(
    region: Optional[tuple[int, int, int, int]] = None,
    lang: str = "spa+eng",
) -> dict:
    """
    Captura la pantalla y extrae texto con Tesseract OCR.

    Args:
        region: (x, y, width, height) — None para pantalla completa
        lang: idioma(s) de Tesseract, e.g. "spa", "eng", "spa+eng"
    """
    tool_logger.info("ocr_screenshot: region=%s lang=%s", region, lang)
    try:
        pyautogui  = _require("pyautogui")
        pytesseract = _require("pytesseract")

        def _do():
            img = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
            return pytesseract.image_to_string(img, lang=lang)

        text = await _run_sync(_do)
        tool_logger.info("OCR extrajo %d chars", len(text))
        return {"status": "ok", "text": text.strip(), "lang": lang}

    except Exception as exc:
        error_logger.exception("Error en ocr_screenshot")
        return {"status": "error", "message": str(exc)}


async def ocr_image(path: str, lang: str = "spa+eng") -> dict:
    """Extrae texto de un fichero de imagen existente."""
    tool_logger.info("ocr_image: %s lang=%s", path, lang)
    try:
        pytesseract = _require("pytesseract")
        PIL_Image   = _require("PIL.Image")

        p = Path(path)
        if not p.exists():
            return {"status": "error", "message": f"Imagen no encontrada: {path}"}

        def _do():
            img = PIL_Image.open(str(p))
            return pytesseract.image_to_string(img, lang=lang)

        text = await _run_sync(_do)
        return {"status": "ok", "text": text.strip(), "path": str(p), "lang": lang}

    except Exception as exc:
        error_logger.exception("Error en ocr_image")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# FIND ON SCREEN (template matching con OpenCV)
# ---------------------------------------------------------------------------

async def find_on_screen(
    template_path: str,
    threshold: float = 0.8,
    region: Optional[tuple[int, int, int, int]] = None,
) -> dict:
    """
    Busca una imagen template en la pantalla.

    Args:
        template_path: ruta a la imagen a buscar
        threshold: confianza mínima [0-1]
        region: zona de búsqueda (None = pantalla completa)

    Returns:
        {status, found, x, y, confidence} si encontrado
    """
    tool_logger.info("find_on_screen: template=%s threshold=%.2f", template_path, threshold)
    try:
        cv2       = _require("cv2")
        numpy     = _require("numpy")
        pyautogui = _require("pyautogui")
        PIL_Image = _require("PIL.Image")

        tmpl_path = Path(template_path)
        if not tmpl_path.exists():
            return {"status": "error", "message": f"Template no encontrado: {template_path}"}

        def _do():
            # Captura
            screen = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
            screen_np = numpy.array(screen.convert("RGB"))
            screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)

            # Template
            tmpl = cv2.imread(str(tmpl_path), cv2.IMREAD_GRAYSCALE)
            if tmpl is None:
                raise ValueError(f"No se pudo leer el template: {template_path}")

            h, w = tmpl.shape
            result = cv2.matchTemplate(screen_gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val >= threshold:
                cx = max_loc[0] + w // 2
                cy = max_loc[1] + h // 2
                # Ajustar si se buscó en región
                if region:
                    cx += region[0]
                    cy += region[1]
                return {"found": True, "x": cx, "y": cy, "confidence": round(float(max_val), 4)}
            return {"found": False, "confidence": round(float(max_val), 4)}

        data = await _run_sync(_do)
        return {"status": "ok", **data}

    except Exception as exc:
        error_logger.exception("Error en find_on_screen")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# WINDOW CONTROL
# ---------------------------------------------------------------------------

async def window_list() -> dict:
    """Lista las ventanas abiertas con su título."""
    tool_logger.info("window_list")
    try:
        titles = await _run_sync(_get_window_titles)
        return {"status": "ok", "windows": titles}
    except Exception as exc:
        error_logger.exception("Error en window_list")
        return {"status": "error", "message": str(exc)}


async def window_focus(title: str) -> dict:
    """Lleva al frente la primera ventana cuyo título contenga `title`."""
    tool_logger.info("window_focus: %s", title)
    try:
        result = await _run_sync(_focus_window, title)
        return result
    except Exception as exc:
        error_logger.exception("Error en window_focus")
        return {"status": "error", "message": str(exc)}


async def window_close(title: str) -> dict:
    """Cierra la primera ventana cuyo título contenga `title`."""
    tool_logger.info("window_close: %s", title)
    try:
        result = await _run_sync(_close_window, title)
        return result
    except Exception as exc:
        error_logger.exception("Error en window_close")
        return {"status": "error", "message": str(exc)}


# ── Helpers de ventanas según OS ────────────────────────────────────────────

def _get_window_titles() -> list[str]:
    if _SYSTEM == "Windows":
        import pygetwindow as gw
        return [w.title for w in gw.getAllWindows() if w.title.strip()]
    # Linux — usa wmctrl
    import subprocess
    out = subprocess.check_output(["wmctrl", "-l"], text=True)
    titles = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            titles.append(parts[3])
    return titles


def _focus_window(title: str) -> dict:
    if _SYSTEM == "Windows":
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
        if not wins:
            return {"status": "error", "message": f"Ventana no encontrada: {title}"}
        wins[0].activate()
        return {"status": "ok", "title": wins[0].title}
    # Linux
    import subprocess
    out = subprocess.check_output(["wmctrl", "-l"], text=True)
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and title.lower() in parts[3].lower():
            wid = parts[0]
            subprocess.run(["wmctrl", "-ia", wid], check=True)
            return {"status": "ok", "title": parts[3], "wid": wid}
    return {"status": "error", "message": f"Ventana no encontrada: {title}"}


def _close_window(title: str) -> dict:
    if _SYSTEM == "Windows":
        import pygetwindow as gw
        wins = [w for w in gw.getAllWindows() if title.lower() in w.title.lower()]
        if not wins:
            return {"status": "error", "message": f"Ventana no encontrada: {title}"}
        wins[0].close()
        return {"status": "ok", "title": wins[0].title}
    # Linux
    import subprocess
    out = subprocess.check_output(["wmctrl", "-l"], text=True)
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and title.lower() in parts[3].lower():
            wid = parts[0]
            subprocess.run(["wmctrl", "-ic", wid], check=True)
            return {"status": "ok", "title": parts[3], "wid": wid}
    return {"status": "error", "message": f"Ventana no encontrada: {title}"}


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