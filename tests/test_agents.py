import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agents.chat_agent import ChatAgent
from app.agents.filesystem_agent import FilesystemAgent
from app.agents.system_agent import SystemAgent

@pytest.mark.asyncio
async def test_chat_agent_logic():
    """Verifica que el ChatAgent use el LLM y devuelva un AgentResult exitoso."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "Respuesta de prueba"
    
    agent = ChatAgent(llm=mock_llm)
    data = {"user_message": "Hola Alfonso", "request_id": "123"}
    
    result = await agent.handle("chat.respond", data)
    
    assert result.status == "success"
    assert result.payload["response"] == "Respuesta de prueba"
    mock_llm.generate.assert_called_once()

@pytest.mark.asyncio
async def test_filesystem_agent_mapping():
    """Verifica que el agente de archivos mapee eventos a herramientas correctamente."""
    agent = FilesystemAgent()
    # Mockeamos run_tool para no tocar el disco real
    agent.run_tool = AsyncMock(return_value={"status": "ok", "message": "Creado"})
    
    data = {
        "event_type": "filesystem.create",
        "args": {"path": "nota.txt", "content": "test content"}
    }
    
    result = await agent.handle("filesystem.create", data)
    
    assert result.status == "success"
    agent.run_tool.assert_called_with("create_file", path="nota.txt", content="test content")

@pytest.mark.asyncio
async def test_system_agent_info():
    """Verifica que el SystemAgent maneje correctamente la petición de info."""
    agent = SystemAgent()
    agent.run_tool = AsyncMock(return_value={"status": "ok", "cpu": "i9"})
    
    result = await agent.handle("system.info", {"args": {}})
    
    assert result.status == "success"
    assert result.payload["cpu"] == "i9"
    agent.run_tool.assert_called_with("system_info")

if __name__ == "__main__":
    pytest.main([__file__])