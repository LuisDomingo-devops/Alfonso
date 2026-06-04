"""
MailAgent — Fase 2 (stub).

Gestiona operaciones de correo electrónico.
La integración real con Gmail / Outlook llega en Fase 5.

Event types:
    mail.send       → envía un correo (stub: loguea y devuelve not_implemented)
    mail.read       → lee el buzón  (stub)
    mail.search     → busca correos (stub)
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent


_NOT_IMPLEMENTED_MSG = (
    "La integración de correo llegará en Fase 5. "
    "Por ahora este agente actúa como placeholder."
)


class MailAgent(BaseAgent):

    name = "mail"
    event_types = [
        "mail.send",
        "mail.read",
        "mail.search",
    ]

    async def handle(self, event_type: str, data: dict) -> AgentResult:
        self.logger.info(
            "MailAgent recibió evento '%s' — stub Fase 2, pendiente Fase 5.",
            event_type,
        )

        if event_type not in self.event_types:
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="skipped",
                error=f"Evento no soportado: {event_type}",
            )

        return AgentResult(
            agent=self.name,
            event_type=event_type,
            status="error",
            error=_NOT_IMPLEMENTED_MSG,
            payload={"not_implemented": True, "planned_phase": 5},
        )