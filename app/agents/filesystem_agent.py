"""
FilesystemAgent — gestiona todas las operaciones de archivos.

Event types:
    filesystem.create   → crea un archivo
    filesystem.read     → lee un archivo
    filesystem.append   → añade contenido a un archivo
    filesystem.list     → lista un directorio
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent


class FilesystemAgent(BaseAgent):

    name = "filesystem"
    event_types = [
        "filesystem.create",
        "filesystem.read",
        "filesystem.append",
        "filesystem.list",
    ]

    async def handle(self, event_type: str, data: dict) -> AgentResult:
        args = data.get("args", {})

        if event_type == "filesystem.create":
            result = await self.run_tool(
                "create_file",
                path=args.get("path", ""),
                content=args.get("content", ""),
            )

        elif event_type == "filesystem.read":
            result = await self.run_tool(
                "read_file",
                path=args.get("path", ""),
            )

        elif event_type == "filesystem.append":
            result = await self.run_tool(
                "append_file",
                path=args.get("path", ""),
                content=args.get("content", ""),
            )

        elif event_type == "filesystem.list":
            result = await self.run_tool(
                "list_directory",
                path=args.get("path", "."),
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