"""
TaskPlanner — Fase 2.

Recibe la intención detectada y el JSON de tool que produjo el LLM
y los convierte en un (event_type, args) que se publica en el EventBus.

Esto desacopla el orquestador de los agentes: el orquestador no sabe
qué agente va a manejar el evento, solo publica el tipo correcto.

Mapeo de tools → event_types:
    create_file     → filesystem.create
    read_file       → filesystem.read
    append_file     → filesystem.append
    list_directory  → filesystem.list
    system_info     → system.info
    run_command     → system.command
    open_application→ system.open_app
    no_op           → chat.respond  (fallback a chat)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_TOOL_TO_EVENT: dict[str, str] = {
    "create_file":      "filesystem.create",
    "read_file":        "filesystem.read",
    "append_file":      "filesystem.append",
    "list_directory":   "filesystem.list",
    "system_info":      "system.info",
    "run_command":      "system.command",
    "open_application": "system.open_app",
    "no_op":            "chat.respond",
}


@dataclass
class TaskPlan:
    event_type: str
    args: dict
    tool_name: str          # para logging / trazabilidad
    is_chat: bool = False   # True si el plan es solo responder con texto


class TaskPlanner:
    """
    Convierte un resultado del LLM en un TaskPlan publicable.

    Uso:
        planner = TaskPlanner()
        plan = planner.plan(intent="tool", tool_name="create_file", args={...})
    """

    def plan(
        self,
        intent: str,
        tool_name: Optional[str],
        args: dict,
        fallback_message: str = "",
    ) -> TaskPlan:
        """
        Genera un TaskPlan a partir del intent y tool.

        Args:
            intent:           "chat" o "tool"
            tool_name:        nombre de la herramienta extraído del JSON del LLM
            args:             argumentos para la herramienta
            fallback_message: mensaje del LLM si no hay JSON válido

        Returns:
            TaskPlan con event_type y args listos para publicar.
        """

        # 1. Intent chat directo
        if intent == "chat":
            return TaskPlan(
                event_type="chat.respond",
                args={"user_message": fallback_message},
                tool_name="chat",
                is_chat=True,
            )

        # 2. Intent tool pero sin nombre válido → chat fallback
        if not tool_name:
            return TaskPlan(
                event_type="chat.respond",
                args={"user_message": fallback_message},
                tool_name="no_op",
                is_chat=True,
            )

        # 3. Tool conocida → evento del agente correspondiente
        event_type = _TOOL_TO_EVENT.get(tool_name)
        if event_type:
            is_chat = (event_type == "chat.respond")
            return TaskPlan(
                event_type=event_type,
                args=args,
                tool_name=tool_name,
                is_chat=is_chat,
            )

        # 4. Tool desconocida → log y chat fallback
        return TaskPlan(
            event_type="chat.respond",
            args={"user_message": fallback_message or f"Herramienta desconocida: {tool_name}"},
            tool_name=tool_name,
            is_chat=True,
        )

    def list_supported_tools(self) -> list[str]:
        return list(_TOOL_TO_EVENT.keys())