"""
ComputerAgent — Fase 3: Computer Use

Gestiona el control del ordenador a bajo nivel:
    - Ratón y teclado (PyAutoGUI)
    - OCR y detección de imágenes en pantalla (Tesseract + OpenCV)
    - Control de ventanas (wmctrl / pygetwindow)
    - Screenshots

Event types:
    computer.screenshot         → captura de pantalla
    computer.mouse_move         → mover ratón
    computer.mouse_click        → click
    computer.mouse_drag         → arrastrar
    computer.keyboard_type      → escribir texto
    computer.keyboard_hotkey    → combinación de teclas
    computer.ocr_screenshot     → OCR de la pantalla
    computer.ocr_image          → OCR de un fichero
    computer.find_on_screen     → buscar imagen en pantalla
    computer.window_list        → listar ventanas
    computer.window_focus       → traer ventana al frente
    computer.window_close       → cerrar ventana
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent

# Mapa event_type → (tool_name, arg_keys)
# arg_keys: campos que se extraen de data["args"] y se pasan como kwargs
_EVENT_MAP: dict[str, tuple[str, list[str]]] = {
    "computer.screenshot":      ("screenshot",      ["region", "save_path"]),
    "computer.mouse_move":      ("mouse_move",       ["x", "y", "duration"]),
    "computer.mouse_click":     ("mouse_click",      ["x", "y", "button", "clicks", "interval"]),
    "computer.mouse_drag":      ("mouse_drag",       ["x1", "y1", "x2", "y2", "duration", "button"]),
    "computer.keyboard_type":   ("keyboard_type",    ["text", "interval"]),
    "computer.keyboard_hotkey": ("keyboard_hotkey",  ["keys"]),
    "computer.ocr_screenshot":  ("ocr_screenshot",   ["region", "lang"]),
    "computer.ocr_image":       ("ocr_image",        ["path", "lang"]),
    "computer.find_on_screen":  ("find_on_screen",   ["template_path", "threshold", "region"]),
    "computer.window_list":     ("window_list",      []),
    "computer.window_focus":    ("window_focus",     ["title"]),
    "computer.window_close":    ("window_close",     ["title"]),
}


class ComputerAgent(BaseAgent):

    name = "computer"
    event_types = list(_EVENT_MAP.keys())

    async def handle(self, event_type: str, data: dict) -> AgentResult:

        mapping = _EVENT_MAP.get(event_type)
        if mapping is None:
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="skipped",
                error=f"Evento no soportado: {event_type}",
            )

        tool_name, arg_keys = mapping
        raw_args = data.get("args", {})

        # Caso especial: keyboard_hotkey recibe una lista "keys"
        if tool_name == "keyboard_hotkey":
            keys = raw_args.get("keys", [])
            if isinstance(keys, str):
                # Permitir pasar como string "ctrl+c"
                keys = [k.strip() for k in keys.replace("+", " ").split()]
            result = await self.run_tool(tool_name, *keys)
        else:
            # Filtrar solo los args conocidos para esta tool
            kwargs = {k: raw_args[k] for k in arg_keys if k in raw_args}
            result = await self.run_tool(tool_name, **kwargs)

        ok = result.get("status") == "ok"
        return AgentResult(
            agent=self.name,
            event_type=event_type,
            status="success" if ok else "error",
            payload=result,
            error=result.get("message") if not ok else None,
        )