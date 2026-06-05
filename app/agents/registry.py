"""
AgentRegistry — Fase 3 completa.

Agentes registrados:
    - FilesystemAgent       (filesystem.*)
    - SystemAgent           (system.*)          ← incluye system.datetime
    - ChatAgent             (chat.respond)
    - BrowserAgent          (browser.*)         Fase 3 — Playwright real
    - ComputerAgent         (computer.*)        Fase 3 — PyAutoGUI / OCR / ventanas
    - MailAgent             (mail.*)            stub → Fase 5
    - AutomationAgent       (automation.*)      pipeline multi-step
"""

from __future__ import annotations

import logging
from typing import List

from app.agents.automation_agent import AutomationAgent
from app.agents.base import BaseAgent
from app.agents.browser_agent import BrowserAgent
from app.agents.chat_agent import ChatAgent
from app.agents.computer_agent import ComputerAgent
from app.agents.filesystem_agent import FilesystemAgent
from app.agents.mail_agent import MailAgent
from app.agents.system_agent import SystemAgent

logger = logging.getLogger("agent.registry")


class AgentRegistry:

    def __init__(self, event_bus, llm=None):
        self._bus = event_bus
        self._llm = llm

        self._chat_agent = ChatAgent()
        self._automation_agent = AutomationAgent(event_bus=event_bus)

        self._agents: List[BaseAgent] = [
            FilesystemAgent(),
            SystemAgent(),
            BrowserAgent(),
            ComputerAgent(),
            MailAgent(),
            self._automation_agent,
            self._chat_agent,
        ]

    def set_llm(self, llm) -> None:
        self._llm = llm
        self._chat_agent.set_llm(llm)

    async def start(self) -> None:
        # Inyectar LLM ANTES de registrar en el bus
        if self._llm:
            self._chat_agent.set_llm(self._llm)

        self._automation_agent.set_event_bus(self._bus)

        for agent in self._agents:
            agent.register(self._bus)
            logger.info(
                "Agente iniciado: %s (eventos: %s)",
                agent.name,
                agent.event_types,
            )

        logger.info("AgentRegistry: %d agentes registrados", len(self._agents))

    async def stop(self) -> None:
        try:
            from app.tools.browser_tools import _close_playwright
            await _close_playwright()
            logger.info("Playwright cerrado limpiamente")
        except Exception:
            pass
        logger.info("AgentRegistry detenido")

    def list_agents(self) -> list[dict]:
        return [
            {"name": a.name, "event_types": a.event_types}
            for a in self._agents
        ]