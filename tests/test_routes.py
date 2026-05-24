from fastapi.testclient import TestClient
import app.api.routes as routes
from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "request_id" in body
    assert "logs_path" in body


def test_metrics_endpoint():
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "metrics" in body


def test_chat_endpoint_with_mocked_orchestrator(monkeypatch):
    async def fake_run(message, llm, request_id=None, session_id=None):
        return {"type": "chat", "response": "simulado"}

    monkeypatch.setattr(routes.orchestrator, "run", fake_run)

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hola"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["type"] == "chat"
    assert body["result"]["response"] == "simulado"


def test_chat_validation_error():
    with TestClient(app) as client:
        response = client.post("/chat", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["status"] == "error"
    assert "request_id" in body


def test_websocket_echo():
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_text("hola")
            assert ws.receive_text() == "Echo: hola"


def test_tools_endpoint():
    with TestClient(app) as client:
        response = client.get("/tools")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "request_id" in body
    assert "tools" in body
    assert "create_file" in body["tools"]
    assert "read_file" in body["tools"]
    assert "system_info" in body["tools"]
    assert "text_to_speech" in body["tools"]
    assert "speech_to_text" in body["tools"]
    assert "wake_word_listener" in body["tools"]


def test_audio_tts_endpoint_with_mocked_tool(monkeypatch):
    async def fake_tts(text, voice=None):
        return {"status": "ok", "message": "spoken"}

    monkeypatch.setattr(routes, "get_tool", lambda name: fake_tts if name == "text_to_speech" else None)

    with TestClient(app) as client:
        response = client.post("/audio/tts", json={"text": "hola", "voice": "mujer"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["status"] == "ok"
    assert body["result"]["message"] == "spoken"


def test_audio_stt_endpoint_with_mocked_tool(monkeypatch):
    async def fake_stt(duration=5):
        return {"status": "ok", "text": "hola"}

    monkeypatch.setattr(routes, "get_tool", lambda name: fake_stt if name == "speech_to_text" else None)

    with TestClient(app) as client:
        response = client.post("/audio/stt", json={"duration": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["status"] == "ok"
    assert body["result"]["text"] == "hola"


def test_audio_wakeword_endpoint_with_mocked_tool(monkeypatch):
    async def fake_wakeword(keyword="alfonso", max_duration=30, chunk_duration=5, model="small"):
        return {"status": "ok", "wake_word_detected": True, "text": "alfonso"}

    monkeypatch.setattr(routes, "get_tool", lambda name: fake_wakeword if name == "wake_word_listener" else None)

    with TestClient(app) as client:
        response = client.post("/audio/wakeword", json={"keyword": "alfonso", "max_duration": 10, "chunk_duration": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["wake_word_detected"] is True
    assert body["result"]["text"] == "alfonso"


def test_audio_converse_endpoint_with_mocked_tools(monkeypatch):
    async def fake_wakeword(keyword="alfonso", max_duration=30, chunk_duration=5, model="small"):
        return {"status": "ok", "wake_word_detected": True, "text": "alfonso"}

    async def fake_stt(duration=5, model="small"):
        return {"status": "ok", "text": "hola"}

    async def fake_run(message, llm, request_id=None, session_id=None):
        return {"type": "chat", "response": "respuesta hablada"}

    async def fake_tts(text, voice=None):
        return {"status": "ok", "audio_file": "/tmp/response.mp3"}

    def fake_get_tool(name):
        return {
            "wake_word_listener": fake_wakeword,
            "speech_to_text": fake_stt,
            "text_to_speech": fake_tts,
        }.get(name)

    monkeypatch.setattr(routes, "get_tool", fake_get_tool)
    monkeypatch.setattr(routes.orchestrator, "run", fake_run)

    with TestClient(app) as client:
        response = client.post(
            "/audio/converse",
            json={
                "keyword": "alfonso",
                "wakeword_enabled": True,
                "max_duration": 10,
                "chunk_duration": 2,
                "stt_duration": 5,
                "stt_model": "small",
                "voice": "mujer",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["wake_result"]["wake_word_detected"] is True
    assert body["stt_result"]["text"] == "hola"
    assert body["conversation_result"]["response"] == "respuesta hablada"
    assert body["tts_result"]["audio_file"] == "/tmp/response.mp3"


def test_audio_stt_upload_endpoint_with_mocked_tool(monkeypatch):
    async def fake_transcribe(content=b"", filename="audio.wav", model="small"):
        return {"status": "ok", "text": "hola desde upload"}

    monkeypatch.setattr(routes, "get_tool", lambda name: fake_transcribe if name == "transcribe_audio_bytes" else None)

    with TestClient(app) as client:
        response = client.post(
            "/audio/stt/upload",
            files={"file": ("test.wav", b"RIFF....", "audio/wav")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["status"] == "ok"
    assert body["result"]["text"] == "hola desde upload"
