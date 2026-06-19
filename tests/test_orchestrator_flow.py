import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.planner_orchestrator import PlannerOrchestrator
from app.core.event_bus import EventBus
from app.agents.base import AgentResult
from app.agents.task_planner import TaskPlan

@pytest.mark.asyncio
async def test_orchestrator_request_reply_success():
    """Prueba el ciclo de vida completo: Petición -> Bus -> Agente -> Respuesta."""
    # El mock de memoria ya se encarga el conftest.py o el mock global
    bus = EventBus()
    orchestrator = PlannerOrchestrator(bus)
    
    # Simulamos un agente que responde al evento
    async def mock_agent_behavior(data: dict):
        callback = data.get("_result_callback")
        if callback:
            # Simulamos que el agente procesó algo con éxito
            result = AgentResult(
                agent="test_agent",
                event_type="chat.respond",
                status="success",
                payload={"type": "chat", "response": "Respuesta desde el bus"}
            )
            await callback(result)

    bus.subscribe("chat.respond", mock_agent_behavior)
    await bus.start()

    # Creamos un plan de prueba
    plan = MagicMock(spec=TaskPlan)
    plan.event_type = "chat.respond"
    plan.args = {}

    # Ejecutamos el despacho
    # El fixture 'mock_memory' en conftest.py ya parchea app.core.memory.memory
    response = await orchestrator._dispatch(
        plan=plan,
        llm=None,
        session_id="test_session",
        request_id="test_req",
        memory_text=None,
        user_message="Hola"
    )
    
    assert response["type"] == "chat"
    assert response["response"] == "Respuesta desde el bus"
    await bus.stop()

@pytest.mark.asyncio
async def test_orchestrator_timeout():
    """Verifica que el orquestador no se quede colgado si un agente no responde."""
    bus = EventBus()
    orchestrator = PlannerOrchestrator(bus)
    await bus.start()

    plan = MagicMock(spec=TaskPlan)
    plan.event_type = "non.existent.event"
    plan.args = {}
    
    # Reducimos el timeout para el test (o usamos el default)
    # En el código es 30s, aquí fallará por timeout
    import app.core.planner_orchestrator as orch_module
    orch_module._AGENT_TIMEOUT = 0.1 

    response = await orchestrator._dispatch(plan, None, None, "req", None, "Hola")
    
    assert response["type"] == "error"
    assert "Agente no respondió" in response["message"]
    await bus.stop()