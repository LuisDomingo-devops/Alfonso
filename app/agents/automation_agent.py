"""
AutomationAgent — Fase 2 (stub).

Gestiona flujos de automatización: secuencias de acciones, tareas
programadas y pipelines multi-paso.
La implementación completa evoluciona en Fase 7 (Agentic OS).

Event types:
    automation.run_pipeline     → ejecuta una secuencia de eventos en orden
    automation.schedule         → registra una tarea para ejecución futura (stub)
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import AgentResult, BaseAgent


class AutomationAgent(BaseAgent):

    name = "automation"
    event_types = [
        "automation.run_pipeline",
        "automation.schedule",
    ]

    def __init__(self, event_bus=None):
        super().__init__()
        self._bus = event_bus

    def set_event_bus(self, event_bus) -> None:
        self._bus = event_bus

    async def handle(self, event_type: str, data: dict) -> AgentResult:

        if event_type == "automation.run_pipeline":
            return await self._run_pipeline(data)

        if event_type == "automation.schedule":
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="error",
                error="Tareas programadas pendientes de implementación (Fase 7).",
                payload={"not_implemented": True, "planned_phase": 7},
            )

        return AgentResult(
            agent=self.name,
            event_type=event_type,
            status="skipped",
            error=f"Evento no soportado: {event_type}",
        )

    # ------------------------------------------------------------------
    # Pipeline: lista de pasos [ {event_type, args}, ... ]
    # ------------------------------------------------------------------

    async def _run_pipeline(self, data: dict) -> AgentResult:
        """
        Ejecuta una lista de steps secuencialmente publicando cada uno
        en el EventBus.

        Payload esperado:
            {
                "args": {
                    "steps": [
                        {"event_type": "filesystem.create", "args": {...}},
                        {"event_type": "system.command",    "args": {...}},
                    ]
                }
            }
        """
        if self._bus is None:
            return AgentResult(
                agent=self.name,
                event_type="automation.run_pipeline",
                status="error",
                error="EventBus no disponible para ejecutar pipeline.",
            )

        steps: list[dict[str, Any]] = data.get("args", {}).get("steps", [])
        if not steps:
            return AgentResult(
                agent=self.name,
                event_type="automation.run_pipeline",
                status="error",
                error="El pipeline no tiene steps definidos.",
            )

        results = []
        for i, step in enumerate(steps):
            step_event = step.get("event_type")
            step_args = step.get("args", {})

            if not step_event:
                results.append({"step": i, "status": "skipped", "reason": "sin event_type"})
                continue

            loop = asyncio.get_running_loop()
            future: asyncio.Future = loop.create_future()

            async def _cb(agent_result, _f=future):
                if not _f.done():
                    _f.set_result(agent_result)

            await self._bus.publish(step_event, {
                "event_type": step_event,
                "args": step_args,
                "_result_callback": _cb,
            })

            try:
                agent_result = await asyncio.wait_for(future, timeout=30.0)
                results.append({
                    "step": i,
                    "event_type": step_event,
                    "status": agent_result.status,
                    "payload": agent_result.payload,
                    "error": agent_result.error,
                })
                # Si un paso falla, abortamos el pipeline
                if agent_result.status == "error":
                    self.logger.warning("Pipeline abortado en step %d: %s", i, agent_result.error)
                    break
            except asyncio.TimeoutError:
                results.append({"step": i, "event_type": step_event, "status": "timeout"})
                break

        all_ok = all(r.get("status") == "success" for r in results)
        return AgentResult(
            agent=self.name,
            event_type="automation.run_pipeline",
            status="success" if all_ok else "error",
            payload={"steps_executed": len(results), "results": results},
            error=None if all_ok else "Uno o más steps fallaron.",
        )