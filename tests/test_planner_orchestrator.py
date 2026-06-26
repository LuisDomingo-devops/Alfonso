import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.planner_orchestrator import PlannerOrchestrator


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate = AsyncMock()
    return llm


@pytest.mark.asyncio
async def test_orchestrator_chat_flow(mock_llm, session_memory_fixture):
    session_memory_fixture.clear("test_session")
    mock_vector = MagicMock()
    mock_vector.query_facts.return_value = []

    with patch("app.core.planner_orchestrator.memory", session_memory_fixture), \
         patch("app.core.planner_orchestrator.vector_memory", mock_vector):
        mock_llm.generate.return_value = "Hola Luis, soy tu asistente."
        
        orchestrator = PlannerOrchestrator()
        result = await orchestrator.run(
            user_message="Hola Alfonso",
            llm=mock_llm,
            session_id="test_session"
        )
        
        assert result["type"] == "chat"
        assert result["response"] == "Hola Luis, soy tu asistente."
        
        # Debe haber guardado tanto el mensaje del usuario como el del asistente en memoria
        history = session_memory_fixture.get_history("test_session")
        assert len(history) == 2
        assert history[0]["content"] == "Hola Alfonso"
        assert history[1]["content"] == "Hola Luis, soy tu asistente."


@pytest.mark.asyncio
async def test_orchestrator_client_tool_flow(mock_llm, session_memory_fixture):
    session_memory_fixture.clear("test_session")
    mock_vector = MagicMock()
    mock_vector.query_facts.return_value = []

    with patch("app.core.planner_orchestrator.memory", session_memory_fixture), \
         patch("app.core.planner_orchestrator.vector_memory", mock_vector):
        # El LLM responde con una herramienta cliente: click
        mock_llm.generate.return_value = '{"tool": "click", "args": {"x": 100, "y": 200}}'
        
        # Mock de alfonso_bridge
        mock_bridge = AsyncMock()
        mock_bridge.send_command.return_value = {"status": "success", "result": "click exitoso"}
        
        with patch("app.core.planner_orchestrator.bridge", mock_bridge):
            orchestrator = PlannerOrchestrator()
            result = await orchestrator.run(
                user_message="haz click en la pantalla",
                llm=mock_llm,
                session_id="test_session"
            )
            
            assert result["type"] == "tool"
            assert result["execution"] == "client"
            assert result["tool"] == "click"
            assert result["result"] == {"status": "success", "result": "click exitoso"}
            
            # Verifica que llamamos al bridge con los argumentos mapeados
            mock_bridge.send_command.assert_called_once_with("mouse.click", {"x": 100, "y": 200})


@pytest.mark.asyncio
async def test_orchestrator_server_tool_flow(mock_llm, session_memory_fixture):
    session_memory_fixture.clear("test_session")
    mock_vector = MagicMock()
    mock_vector.query_facts.return_value = []

    with patch("app.core.planner_orchestrator.memory", session_memory_fixture), \
         patch("app.core.planner_orchestrator.vector_memory", mock_vector):
        # El LLM responde con una herramienta de servidor: list_directory
        mock_llm.generate.return_value = '{"tool": "list_directory", "args": {"path": "/tmp"}}'
        
        mock_tool_func = AsyncMock(return_value={"status": "ok", "entries": []})
        
        with patch("app.core.planner_orchestrator.get_tool", return_value=mock_tool_func):
            orchestrator = PlannerOrchestrator()
            result = await orchestrator.run(
                user_message="lista el directorio tmp",
                llm=mock_llm,
                session_id="test_session"
            )
            
            assert result["type"] == "tool"
            assert result["execution"] == "server"
            assert result["tool"] == "list_directory"
            assert result["result"] == {"status": "ok", "entries": []}
            mock_tool_func.assert_called_once_with(path="/tmp")
