"""
AgentRegistry — inicializa y registra todos los agentes de Alfonso.

Uso desde el lifespan de FastAPI:
    from app.agents.registry import AgentRegistry

    registry = AgentRegistry(event_bus, llm)
    await registry.start()
    # ... app runs ...
    await registry.stop()

Añadir un agente nuevo: instanciarlo aquí y añadirlo a self._agents.
"""

from __future__ import annotations

import logging
from typing import List

from app.agents.base import BaseAgent
from app.agents.chat_agent import ChatAgent
from app.agents.filesystem_agent import FilesystemAgent
from app.agents.system_agent import SystemAgent

logger = logging.getLogger("agent.registry")


class AgentRegistry:

    def __init__(self, event_bus, llm=None):
        self._bus = event_bus
        self._llm = llm

        # Instanciar agentes
        self._chat_agent = ChatAgent()
        self._agents: List[BaseAgent] = [
            FilesystemAgent(),
            SystemAgent(),
            self._chat_agent,
        ]

    def set_llm(self, llm) -> None:
        """Inyectar el LLM después de inicializar (por si aún no existe en __init__)."""
        self._llm = llm
        self._chat_agent.set_llm(llm)

    async def start(self) -> None:
        """Registra todos los agentes en el EventBus."""
        if self._llm:
            self._chat_agent.set_llm(self._llm)

        for agent in self._agents:
            agent.register(self._bus)
            logger.info("Agente iniciado: %s (eventos: %s)", agent.name, agent.event_types)

        logger.info("AgentRegistry: %d agentes registrados", len(self._agents))

    async def stop(self) -> None:
        """Limpieza de recursos de agentes (si alguno los tiene)."""
        logger.info("AgentRegistry detenido")

    def list_agents(self) -> list[dict]:
        return [
            {"name": a.name, "event_types": a.event_types}
            for a in self._agents
        ]