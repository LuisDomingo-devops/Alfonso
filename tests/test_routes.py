"""
Tests para las rutas principales de la API (Fase 3).
"""
import pytest
from fastapi.testclient import TestClient
import app.api.routes as routes
from app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["phase"] == "3"

def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "http_requests" in body
    assert "http_errors" in body

def test_chat_endpoint_with_mocked_orchestrator(client, monkeypatch):
    async def fake_run(message, llm, request_id=None, session_id=None):
        return {"type": "chat", "response": "simulado"}
    monkeypatch.setattr(routes.orchestrator, "run", fake_run)
    response = client.post("/chat", json={"message": "hola", "session_id": "test_sess"})
    assert response.status_code == 200
    body = response.json()
    assert "request_id" in body
    assert body["result"]["type"] == "chat"
    assert body["result"]["response"] == "simulado"

def test_chat_validation_error(client):
    response = client.post("/chat", json={})
    assert response.status_code == 422

def test_tools_endpoint(client):
    response = client.get("/tools")
    assert response.status_code == 200
    body = response.json()
    assert "create_file" in body["tools"]

def test_memory_endpoints(client):
    resp1 = client.get("/memory")
    assert resp1.status_code == 200
    resp2 = client.get("/memory/test_session")
    assert resp2.status_code == 200
    resp3 = client.delete("/memory/test_session")
    assert resp3.status_code == 200
