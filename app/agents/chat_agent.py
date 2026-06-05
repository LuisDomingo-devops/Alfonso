"""
ChatAgent — gestiona respuestas conversacionales con el LLM.

Event types:
    chat.respond        → genera una respuesta de chat

FIX Fase 2→3:
- Eliminada race condition: el LLM ahora se acepta también desde el payload del evento.
  Esto permite que el PlannerOrchestrator pase el LLM directamente en el evento,
  independientemente del orden en que lifespan llame a set_llm().
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent
from app.core.memory import memory


class ChatAgent(BaseAgent):

    name = "chat"
    event_types = ["chat.respond"]

    def __init__(self, llm=None):
        super().__init__()
        self._llm = llm

    def set_llm(self, llm) -> None:
        """Inyecta el cliente LLM (llamar desde lifespan)."""
        self._llm = llm

    async def handle(self, event_type: str, data: dict) -> AgentResult:
        if event_type != "chat.respond":
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="skipped",
                error=f"Evento no soportado: {event_type}",
            )

        # FIX: aceptar LLM desde el payload del evento como fallback
        # Esto elimina la race condition donde el modelo aún no estaba inyectado
        llm = data.get("_llm") or self._llm

        if llm is None:
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="error",
                error="LLM no inicializado. Asegúrate de que set_llm() se ha llamado desde lifespan.",
            )

        user_message = data.get("user_message", "")
        session_id = data.get("session_id")
        request_id = data.get("request_id")
        memory_text = data.get("memory_text") or (memory.get_summary(session_id) if session_id else None)

        try:
            response = await llm.generate(
                user_message,
                mode="chat",
                request_id=request_id,
                memory=memory_text,
            )
            if session_id:
                memory.add_message(session_id, "assistant", response)

            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="success",
                payload={"type": "chat", "response": response},
            )
        except Exception as exc:
            self.logger.exception("Error generando respuesta de chat")
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="error",
                error=str(exc),
            )