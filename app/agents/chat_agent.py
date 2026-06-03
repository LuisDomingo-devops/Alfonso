"""
ChatAgent — gestiona respuestas conversacionales con el LLM.

Event types:
    chat.respond        → genera una respuesta de chat
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

        if self._llm is None:
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="error",
                error="LLM no inicializado",
            )

        user_message = data.get("user_message", "")
        session_id = data.get("session_id")
        request_id = data.get("request_id")

        memory_text = memory.get_summary(session_id) if session_id else None

        try:
            response = await self._llm.generate(
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