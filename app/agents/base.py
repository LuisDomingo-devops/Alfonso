"""
BaseAgent — clase abstracta para todos los agentes de Alfonso.

Cada agente:
- Tiene un nombre único y una lista de event_types que maneja.
- Se registra automáticamente en el EventBus al arrancar.
- Implementa `handle(event_type, data)` con su lógica específica.
- Puede acceder al ToolRegistry para ejecutar herramientas.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, List

from app.core.tool_registry import get_tool
from app.utils.logger import agent_logger


class AgentResult:
    """Resultado estándar que devuelve cualquier agente."""

    def __init__(
        self,
        agent: str,
        event_type: str,
        status: str,          # "success" | "error" | "skipped"
        payload: Any = None,
        error: str | None = None,
    ):
        self.agent = agent
        self.event_type = event_type
        self.status = status
        self.payload = payload
        self.error = error

    def to_dict(self) -> dict:
        d = {
            "agent": self.agent,
            "event_type": self.event_type,
            "status": self.status,
        }
        if self.payload is not None:
            d["payload"] = self.payload
        if self.error:
            d["error"] = self.error
        return d

    def __repr__(self) -> str:
        return f"<AgentResult agent={self.agent} status={self.status}>"


class BaseAgent(ABC):
    """
    Clase base para todos los agentes.

    Subclases deben definir:
        name        : str               — identificador único
        event_types : list[str]         — tipos de evento que acepta
        handle()    : async method      — lógica del agente
    """

    name: str = "base"
    event_types: List[str] = []

    def __init__(self):
        self.logger = logging.getLogger(f"agent.{self.name}")

    # ------------------------------------------------------------------
    # Registro en EventBus
    # ------------------------------------------------------------------

    def register(self, event_bus) -> None:
        """
        Registra este agente en el EventBus para todos sus event_types.
        Llamar desde el lifespan de FastAPI.
        """
        for event_type in self.event_types:
            event_bus.subscribe(event_type, self._dispatch)
            self.logger.info("Registrado en EventBus para evento: %s", event_type)

    async def _dispatch(self, data: dict) -> None:
        """Wrapper que captura errores y loguea el resultado."""
        event_type = data.get("event_type", "unknown")
        try:
            result = await self.handle(event_type, data)
            if isinstance(result, AgentResult):
                self.logger.info("Resultado: %s", result)
                # Si el data tiene un callback de resultado, llamarlo
                callback = data.get("_result_callback")
                if callback:
                    await callback(result)
        except Exception:
            self.logger.exception("Error en agente %s procesando evento %s", self.name, event_type)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @abstractmethod
    async def handle(self, event_type: str, data: dict) -> AgentResult:
        """
        Lógica principal del agente.

        Args:
            event_type: tipo de evento recibido
            data: payload del evento (incluye 'user_message', 'session_id', etc.)

        Returns:
            AgentResult con el resultado de la operación
        """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def run_tool(self, tool_name: str, **kwargs) -> dict:
        """Ejecuta una herramienta del ToolRegistry de forma segura."""
        tool = get_tool(tool_name)
        if tool is None:
            return {"status": "error", "message": f"Tool no encontrada: {tool_name}"}
        try:
            return await tool(**kwargs)
        except Exception as exc:
            self.logger.exception("Error ejecutando tool %s", tool_name)
            return {"status": "error", "message": str(exc)}