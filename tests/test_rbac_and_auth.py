import pytest
import json
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock
from app.config import Settings
from app.adapters.alfonso_bridge import AlfonsoBridge
from app.domain.planner_orchestrator import PlannerOrchestrator
from app.adapters.memory.memory import SessionMemory
from app.adapters.memory.vector_memory import VectorMemory

@pytest.fixture(autouse=True)
def mock_memory():
    # Evitar el mock de memory de conftest.py para poder probar la base de datos real
    yield

def test_settings_parsing():
    settings = Settings()
    # Test JSON parsing
    settings.ALFONSO_CLIENT_TOKENS = '{"client_1": "token_123", "client_2": "token_456"}'
    settings.ALFONSO_CLIENT_ROLES = '{"client_1": "admin", "client_2": "guest"}'
    
    assert settings.get_client_token("client_1") == "token_123"
    assert settings.get_client_token("client_2") == "token_456"
    assert settings.get_client_token("client_nonexistent") is None
    
    assert settings.get_client_role("client_1") == "admin"
    assert settings.get_client_role("client_2") == "guest"
    assert settings.get_client_role("client_nonexistent") == "guest"

    # Test comma-separated parsing fallback
    settings.ALFONSO_CLIENT_TOKENS = "client_3:token_789, client_4:token_abc"
    settings.ALFONSO_CLIENT_ROLES = "client_3:admin, client_4:limitado"
    
    assert settings.get_client_token("client_3") == "token_789"
    assert settings.get_client_token("client_4") == "token_abc"
    assert settings.get_client_role("client_3") == "admin"
    assert settings.get_client_role("client_4") == "limitado"

@pytest.mark.asyncio
async def test_bridge_handshake_authentication(monkeypatch):
    bridge = AlfonsoBridge()
    
    # Configurar settings con cliente y token
    from app.config import settings
    monkeypatch.setattr(settings, "ALFONSO_CLIENT_TOKENS", '{"test_client": "test_token"}')
    monkeypatch.setattr(settings, "ALFONSO_CLIENT_ROLES", '{"test_client": "guest"}')
    
    # Spying on bridge.register
    original_register = bridge.register
    register_called = False
    registered_metadata = {}
    async def mock_register(ws, client_id, metadata):
        nonlocal register_called, registered_metadata
        register_called = True
        registered_metadata = metadata
        await original_register(ws, client_id, metadata)
    monkeypatch.setattr(bridge, "register", mock_register)
    
    # Mocking ws y __aiter__ para evitar excepciones al iterar
    mock_ws = AsyncMock()
    mock_ws.recv.return_value = json.dumps({
        "type": "handshake",
        "client_id": "test_client",
        "token": "test_token"
    })
    
    async def empty_aiter(*args, **kwargs):
        if False:
            yield
    mock_ws.__aiter__ = empty_aiter
    
    await bridge.handler(mock_ws)
    assert register_called
    assert registered_metadata.get("role") == "guest"
    
    # Limpiar cliente registrado si quedó algo
    await bridge.unregister(mock_ws)
    
    # 2. Caso token inválido
    mock_ws_invalid = AsyncMock()
    mock_ws_invalid.recv.return_value = json.dumps({
        "type": "handshake",
        "client_id": "test_client",
        "token": "wrong_token"
    })
    mock_ws_invalid.__aiter__ = empty_aiter
    
    await bridge.handler(mock_ws_invalid)
    mock_ws_invalid.close.assert_called_with(code=4003, reason="Forbidden - Invalid Client Token")

@pytest.mark.asyncio
async def test_rbac_orchestrator_permissions(tmp_path, monkeypatch):
    orchestrator = PlannerOrchestrator()
    
    # Configurar base de datos temporal limpia
    memory_module = sys.modules["app.adapters.memory.memory"]
    db_path = tmp_path / "test_rbac_orch_memory.db"
    monkeypatch.setattr(memory_module, "DB_PATH", db_path)
    memory_module._db_initialized = False
    
    # Simular rol de cliente en el bridge
    from app.adapters.alfonso_bridge import bridge
    bridge._client_info_dict["guest_client"] = {"role": "guest"}
    bridge._client_info_dict["admin_client"] = {"role": "admin"}
    
    # Mocking tool de servidor
    mock_tool = AsyncMock()
    mock_tool.return_value = {"status": "ok"}
    monkeypatch.setattr("app.domain.planner_orchestrator.get_tool", lambda name, req_id: mock_tool)
    monkeypatch.setattr("app.domain.planner_orchestrator.prepare_tool_args", lambda name, args, req_id: MagicMock(ok=True, args=args))
    
    # Mocking vector memory
    monkeypatch.setattr("app.domain.planner_orchestrator.vector_memory.query_facts", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.domain.planner_orchestrator._check_and_store_fact", lambda *args, **kwargs: False)
    
    # Mocking intent router to force tool execution
    monkeypatch.setattr("app.domain.planner_orchestrator._router.detect_with_detail", lambda msg: {"intent": "tool"})
    
    # Mocking LLM
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"tool": "read_emails", "args": {}}'
    
    # 1. Ejecución de guest sobre tool de servidor -> Debería ser bloqueada (Acceso denegado)
    res_guest = await orchestrator.run("consulta", llm=mock_llm, client_id="guest_client", session_id="test_sess_guest")
    assert res_guest["type"] == "error"
    assert "Acceso denegado" in res_guest["message"]
    
    # 2. Ejecución de admin sobre tool de servidor -> Debería permitirse
    res_admin = await orchestrator.run("consulta", llm=mock_llm, client_id="admin_client", session_id="test_sess_admin")
    assert res_admin["type"] == "tool"

def test_sqlite_memory_isolation(tmp_path, monkeypatch):
    memory_module = sys.modules["app.adapters.memory.memory"]
    db_path = tmp_path / "test_rbac_memory.db"
    monkeypatch.setattr(memory_module, "DB_PATH", db_path)
    memory_module._db_initialized = False
    
    mem = SessionMemory(max_messages=10)
    
    # Guardar mensajes en la misma session_id pero para diferentes client_ids
    mem.add_message("session_x", "user", "mensaje admin", client_id="client_admin")
    mem.add_message("session_x", "user", "mensaje guest", client_id="client_guest")
    
    history_admin = mem.get_history("session_x", client_id="client_admin")
    history_guest = mem.get_history("session_x", client_id="client_guest")
    
    assert len(history_admin) == 1
    assert history_admin[0]["content"] == "mensaje admin"
    
    assert len(history_guest) == 1
    assert history_guest[0]["content"] == "mensaje guest"

def test_vector_memory_isolation(tmp_path, monkeypatch):
    import chromadb
    client = chromadb.EphemeralClient()
    
    # Mocking VectorMemory initialization to use EphemeralClient
    vm = VectorMemory()
    vm.client = client
    vm._refresh_collection()
    
    # Añadir hechos para diferentes clientes
    vm.add_fact("session_y", "El admin vive en Madrid", client_id="client_admin")
    vm.add_fact("session_y", "El guest vive en Barcelona", client_id="client_guest")
    
    facts_admin = vm.query_facts("¿Dónde vive?", limit=5, client_id="client_admin")
    facts_guest = vm.query_facts("¿Dónde vive?", limit=5, client_id="client_guest")
    
    assert len(facts_admin) == 1
    assert "Madrid" in facts_admin[0]
    
    assert len(facts_guest) == 1
    assert "Barcelona" in facts_guest[0]

@pytest.mark.asyncio
async def test_verify_api_key(monkeypatch):
    from app.api.routes import verify_api_key
    from app.config import settings
    from fastapi import HTTPException
    
    # Caso 1: Sin API Key configurada
    monkeypatch.setattr(settings, "ALFONSO_API_KEY", "")
    res = await verify_api_key("cualquier_key")
    assert res == "cualquier_key"
    
    # Caso 2: API Key configurada y válida
    monkeypatch.setattr(settings, "ALFONSO_API_KEY", "secret_key_123")
    res = await verify_api_key("secret_key_123")
    assert res == "secret_key_123"
    
    # Caso 3: API Key configurada e inválida
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key("wrong_key")
    assert exc_info.value.status_code == 401
