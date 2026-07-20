import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from app.adapters.tool_registry import get_tool_schemas
from app.adapters.llm_client import OllamaClient

def test_get_tool_schemas():
    schemas = get_tool_schemas()
    assert isinstance(schemas, list)
    assert len(schemas) > 0
    
    # Cada esquema debe tener la estructura esperada de Ollama/OpenAI
    for schema in schemas:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        assert schema["function"]["parameters"]["type"] == "object"

@pytest.mark.asyncio
async def test_native_tool_call_parsing():
    client = OllamaClient()
    
    # Mocking http client response with native tool calls
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "create_file",
                        "arguments": {
                            "path": "/test/path.txt",
                            "content": "test content"
                        }
                    }
                }
            ]
        }
    }
    
    with patch("app.adapters.llm_client.client.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        
        result_str = await client.generate("crea un archivo de prueba", mode="tool")
        result = json.loads(result_str)
        
        # Debe haber inyectado tools en el payload de envío
        sent_payload = mock_post.call_args[1]["json"]
        assert "tools" in sent_payload
        assert len(sent_payload["tools"]) > 0
        
        # La respuesta debe ser el JSON formateado de llamada a tool esperado por Alfonso
        assert result["tool"] == "create_file"
        assert result["args"]["path"] == "/test/path.txt"
        assert result["args"]["content"] == "test content"

@pytest.mark.asyncio
async def test_native_tool_call_fallback_to_text():
    client = OllamaClient()
    
    # Mocking response with no tool calls, just raw text JSON
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": '{"tool": "read_file", "args": {"path": "/test/read.txt"}}'
        }
    }
    
    with patch("app.adapters.llm_client.client.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        
        result_str = await client.generate("lee el archivo de prueba", mode="tool")
        result = json.loads(result_str)
        
        # Verifica que se procesó el content de texto plano
        assert result["tool"] == "read_file"
        assert result["args"]["path"] == "/test/read.txt"
