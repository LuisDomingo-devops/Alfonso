"""
TaskPlanner — Fase 3 completa.

Mapeo tools → event_types (acumulado Fases 1-3):

    Filesystem:
        create_file         → filesystem.create
        read_file           → filesystem.read
        append_file         → filesystem.append
        list_directory      → filesystem.list
        delete_file         → filesystem.delete

    Sistema:
        system_info         → system.info
        run_command         → system.command
        open_application    → system.open_app

    Navegador (Fase 3):
        browser_navigate    → browser.navigate
        browser_click       → browser.click
        browser_fill        → browser.fill
        browser_submit      → browser.submit
        browser_screenshot  → browser.screenshot
        browser_get_text    → browser.get_text
        browser_search      → browser.search
        browser_close       → browser.close

    Computer Use (Fase 3):
        screenshot          → computer.screenshot
        mouse_move          → computer.mouse_move
        mouse_click         → computer.mouse_click
        mouse_drag          → computer.mouse_drag
        keyboard_type       → computer.keyboard_type
        keyboard_hotkey     → computer.keyboard_hotkey
        ocr_screenshot      → computer.ocr_screenshot
        ocr_image           → computer.ocr_image
        find_on_screen      → computer.find_on_screen
        window_list         → computer.window_list
        window_focus        → computer.window_focus
        window_close        → computer.window_close

    Automatización:
        run_pipeline        → automation.run_pipeline

    Fallback:
        no_op               → chat.respond
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_TOOL_TO_EVENT: dict[str, str] = {
    # Filesystem
    "create_file":          "filesystem.create",
    "read_file":            "filesystem.read",
    "append_file":          "filesystem.append",
    "list_directory":       "filesystem.list",
    "delete_file":          "filesystem.delete",
    # Sistema
    "system_info":          "system.info",
    "run_command":          "system.command",
    "open_application":     "system.open_app",
    # Navegador
    "browser_navigate":     "browser.navigate",
    "browser_click":        "browser.click",
    "browser_fill":         "browser.fill",
    "browser_submit":       "browser.submit",
    "browser_screenshot":   "browser.screenshot",
    "browser_get_text":     "browser.get_text",
    "browser_get_html":     "browser.get_html",
    "browser_wait_for":     "browser.wait_for",
    "browser_scroll":       "browser.scroll",
    "browser_evaluate":     "browser.evaluate",
    "browser_search":       "browser.search",
    "browser_open":         "browser.open",
    "browser_close":        "browser.close",
    # Computer Use
    "screenshot":           "computer.screenshot",
    "mouse_move":           "computer.mouse_move",
    "mouse_click":          "computer.mouse_click",
    "mouse_drag":           "computer.mouse_drag",
    "keyboard_type":        "computer.keyboard_type",
    "keyboard_hotkey":      "computer.keyboard_hotkey",
    "ocr_screenshot":       "computer.ocr_screenshot",
    "ocr_image":            "computer.ocr_image",
    "find_on_screen":       "computer.find_on_screen",
    "window_list":          "computer.window_list",
    "window_focus":         "computer.window_focus",
    "window_close":         "computer.window_close",
    # Automatización
    "run_pipeline":         "automation.run_pipeline",
    # Fallback
    "no_op":                "chat.respond",
}


@dataclass
class TaskPlan:
    event_type: str
    args: dict
    tool_name: str
    is_chat: bool = False


class TaskPlanner:

    def plan(
        self,
        intent: str,
        tool_name: Optional[str],
        args: dict,
        fallback_message: str = "",
    ) -> TaskPlan:

        if intent == "chat":
            return TaskPlan(
                event_type="chat.respond",
                args={"user_message": fallback_message},
                tool_name="chat",
                is_chat=True,
            )

        if not tool_name:
            return TaskPlan(
                event_type="chat.respond",
                args={"user_message": fallback_message},
                tool_name="no_op",
                is_chat=True,
            )

        event_type = _TOOL_TO_EVENT.get(tool_name)
        if event_type:
            return TaskPlan(
                event_type=event_type,
                args=args,
                tool_name=tool_name,
                is_chat=(event_type == "chat.respond"),
            )

        return TaskPlan(
            event_type="chat.respond",
            args={"user_message": fallback_message or f"Herramienta desconocida: {tool_name}"},
            tool_name=tool_name,
            is_chat=True,
        )

    def list_supported_tools(self) -> list[str]:
        return list(_TOOL_TO_EVENT.keys())