import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domain.planner_orchestrator import PlannerOrchestrator
from app.domain.ports.llm_port import LLMPort
from app.domain.ports.memory_port import MemoryPort, VectorMemoryPort
from app.domain.ports.bridge_port import BridgePort
from app.domain.ports.calendar_port import CalendarPort

@pytest.mark.asyncio
async def test_orchestrator_dependency_injection_with_mocks():
    # 1. Crear mocks que implementen formalmente las interfaces de los Puertos
    mock_llm = MagicMock(spec=LLMPort)
    mock_memory = MagicMock(spec=MemoryPort)
    mock_vector_memory = MagicMock(spec=VectorMemoryPort)
    mock_bridge = MagicMock(spec=BridgePort)
    mock_calendar = MagicMock(spec=CalendarPort)

    # Configurar respuestas esperadas en los mocks
    mock_memory.get_metadata.return_value = {"is_persistent": False}
    mock_memory.get_history.return_value = []
    mock_memory.get_summary.return_value = ""
    mock_vector_memory.query_facts.return_value = []
    mock_bridge.client_info = {"client_id": "mock_client"}
    
    # Simular una respuesta directa de chat del LLM
    mock_llm.generate = AsyncMock(return_value="Hola, soy un mock inyectado.")
    
    # 2. Instanciar el orquestador inyectando los mocks (Arquitectura Hexagonal limpia)
    orchestrator = PlannerOrchestrator(
        llm=mock_llm,
        memory=mock_memory,
        vector_memory=mock_vector_memory,
        bridge=mock_bridge,
        calendar=mock_calendar
    )

    # 3. Ejecutar el orquestador y verificar que delega a las dependencias inyectadas
    result = await orchestrator.run(
        user_message="Hola Alfonso",
        session_id="session-test-di"
    )

    # 4. Aseveraciones (Assertions)
    assert result["type"] == "chat"
    assert result["response"] == "Hola, soy un mock inyectado."
    
    # Verificar que se interactuó con el mock de memoria corta y no con la BD real
    mock_memory.add_message.assert_any_call("session-test-di", "user", "Hola Alfonso", client_id=None)
    mock_memory.add_message.assert_any_call("session-test-di", "assistant", "Hola, soy un mock inyectado.", client_id=None)
    mock_llm.generate.assert_called_once()
