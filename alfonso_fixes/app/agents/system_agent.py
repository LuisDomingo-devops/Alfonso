"""
SystemAgent — gestiona operaciones del sistema operativo.

Event types:
    system.info         → información de CPU, RAM, OS
    system.datetime     → fecha y hora actuales del sistema  ← NUEVO Fase 3
    system.command      → ejecuta un comando de terminal
    system.open_app     → abre una aplicación
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent


class SystemAgent(BaseAgent):

    name = "system"
    event_types = [
        "system.info",
        "system.datetime",
        "system.command",
        "system.open_app",
    ]

    async def handle(self, event_type: str, data: dict) -> AgentResult:
        args = data.get("args", {})

        if event_type == "system.info":
            result = await self.run_tool("system_info")

        elif event_type == "system.datetime":
            result = await self.run_tool("get_current_datetime")

        elif event_type == "system.command":
            result = await self.run_tool(
                "run_command",
                command=args.get("command", ""),
                cwd=args.get("cwd"),
            )

        elif event_type == "system.open_app":
            result = await self.run_tool(
                "open_application",
                command=args.get("command", ""),
                args=args.get("args"),
            )

        else:
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="skipped",
                error=f"Evento no soportado: {event_type}",
            )

        ok = result.get("status") == "ok"
        return AgentResult(
            agent=self.name,
            event_type=event_type,
            status="success" if ok else "error",
            payload=result,
            error=result.get("message") if not ok else None,
        )
