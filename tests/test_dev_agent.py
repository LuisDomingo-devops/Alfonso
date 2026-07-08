import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.domain.agents.dev.dev_agent import dev_agent
from app.domain.planner_orchestrator import PlannerOrchestrator

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_dev_agent_sandbox_write_and_execute():
    # Probar escritura en sandbox
    filename = "test_run.py"
    content = "print('Hello DevAgent Sandbox')"
    path = dev_agent.write_to_sandbox(filename, content)
    assert filename in path
    
    # Probar ejecución de comando
    res = dev_agent.execute_command_in_sandbox("python3 test_run.py")
    assert res["exit_code"] == 0
    assert "Hello DevAgent Sandbox" in res["stdout"]

def test_dev_endpoints(client):
    # 1. Guardar archivo
    resp_save = client.post("/dev/files", json={"filename": "test_api.py", "content": "print('API Test')"})
    assert resp_save.status_code == 200
    assert resp_save.json()["status"] == "ok"

    # 2. Listar archivos
    resp_list = client.get("/dev/files")
    assert resp_list.status_code == 200
    filenames = [f["name"] for f in resp_list.json()]
    assert "test_api.py" in filenames

    # 3. Leer archivo
    resp_get = client.get("/dev/files/test_api.py")
    assert resp_get.status_code == 200
    assert resp_get.json()["content"] == "print('API Test')"

    # 4. Ejecutar comando
    resp_exec = client.post("/dev/execute", json={"command": "python3 test_api.py"})
    assert resp_exec.status_code == 200
    assert resp_exec.json()["exit_code"] == 0
    assert "API Test" in resp_exec.json()["stdout"]

    # 5. Eliminar archivo
    resp_del = client.delete("/dev/files/test_api.py")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_orchestrator_delegation_to_dev_agent(monkeypatch):
    orchestrator = PlannerOrchestrator()
    
    async def mock_generate_response(query):
        return "Simulated DevAgent response for " + query

    monkeypatch.setattr(dev_agent, "generate_response", mock_generate_response)
    
    # Simular una llamada con un query que coincida con el intent de desarrollo
    res = await orchestrator.run("Alfonso crea una app para restaurar archivos en Python", None, request_id="req_test", session_id="sess_test")
    assert res["type"] == "chat"
    assert "Simulated DevAgent" in res["response"]
