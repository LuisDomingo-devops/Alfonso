import pytest
import sqlite3
import os
from fastapi.testclient import TestClient
from app.main import app
from app.adapters import mail_db
from app.tools.server.mail_tools import (
    mail_send_email,
    mail_delete_email,
    mail_reply_email,
    mail_forward_email,
    mail_generate_draft
)

client = TestClient(app)

class DummyConnection:
    def __init__(self, conn):
        self._conn = conn
    def __getattr__(self, name):
        return getattr(self._conn, name)
    def close(self):
        pass
    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)
    def commit(self, *args, **kwargs):
        return self._conn.commit(*args, **kwargs)

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Configura base de datos temporal en memoria para pruebas."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            recipient TEXT,
            subject TEXT,
            body TEXT,
            received_at TEXT,
            category TEXT,
            importance TEXT DEFAULT 'Media',
            read_status INTEGER DEFAULT 0,
            summary TEXT,
            processed_for_calendar INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    
    monkeypatch.setattr(mail_db, "get_connection", lambda: DummyConnection(conn))
    
    mail_db.create_email(
        sender="abogados@madrid.es",
        recipient="luisd@alfonso.dev",
        subject="Demanda arrendamiento Calle Mayor",
        body="Adjuntamos borrador de la demanda de desahucio por impago del alquiler.",
        received_at="2026-07-05 10:00",
        category="legal",
        importance="Alta"
    )
    yield conn
    conn.close()


@pytest.mark.asyncio
async def test_mail_db_delete():
    email_id = mail_db.create_email(
        sender="test@test.com",
        recipient="me@test.com",
        subject="Test subject",
        body="Test body",
        received_at="2026-07-05 12:00"
    )
    assert mail_db.get_email(email_id) is not None
    
    success = mail_db.delete_email(email_id)
    assert success is True
    assert mail_db.get_email(email_id) is None


@pytest.mark.asyncio
async def test_mail_tools_operations():
    res_send = await mail_send_email("friend@test.com", "Hello!", "This is a body.")
    assert res_send["status"] == "ok"
    assert "email_id" in res_send
    
    res_reply = await mail_reply_email(1, "Oído cocina, gracias.")
    assert res_reply["status"] == "ok"
    replied_email = mail_db.get_email(res_reply["email_id"])
    assert replied_email["recipient"] == "abogados@madrid.es"
    assert replied_email["subject"] == "Re: Demanda arrendamiento Calle Mayor"
    
    res_fwd = await mail_forward_email(1, "colleague@test.com", "Mira esto por favor.")
    assert res_fwd["status"] == "ok"
    fwd_email = mail_db.get_email(res_fwd["email_id"])
    assert fwd_email["recipient"] == "colleague@test.com"
    assert fwd_email["subject"] == "Fwd: Demanda arrendamiento Calle Mayor"
    
    res_del = await mail_delete_email(1)
    assert res_del["status"] == "ok"
    assert mail_db.get_email(1) is None


@pytest.mark.asyncio
async def test_mail_smart_reply_draft(monkeypatch):
    class MockLLM:
        async def generate(self, prompt, mode="chat"):
            return "Estimados letrados, procedemos con la revisión..."
            
    from app.tools.server import mail_tools
    monkeypatch.setattr(mail_tools, "_llm", MockLLM())
    
    res_draft = await mail_generate_draft(1)
    assert res_draft["status"] == "ok"
    assert res_draft["role"] == "[Agente Experto Abogado]"
    assert res_draft["draft"]["subject"] == "Re: Demanda arrendamiento Calle Mayor"
    assert "Estimados letrados" in res_draft["draft"]["body"]


def test_mail_api_endpoints(monkeypatch):
    async def mock_send(recipient, subject, body):
        return {"status": "ok", "email_id": 999}
        
    async def mock_delete(email_id):
        return {"status": "ok"}
        
    async def mock_reply(email_id, body, reply_all):
        return {"status": "ok", "email_id": 1000}
        
    async def mock_forward(email_id, recipient, comment):
        return {"status": "ok", "email_id": 1001}
        
    async def mock_draft(email_id):
        return {"status": "ok", "role": "[Abogado Mock]", "draft": {"recipient": "a", "subject": "b", "body": "c"}}

    import app.tools.server.mail_tools as tools
    monkeypatch.setattr(tools, "mail_send_email", mock_send)
    monkeypatch.setattr(tools, "mail_delete_email", mock_delete)
    monkeypatch.setattr(tools, "mail_reply_email", mock_reply)
    monkeypatch.setattr(tools, "mail_forward_email", mock_forward)
    monkeypatch.setattr(tools, "mail_generate_draft", mock_draft)

    r = client.post("/mail/send", json={"recipient": "x@x.com", "subject": "S", "body": "B"})
    assert r.status_code == 200
    assert r.json()["email_id"] == 999
    
    r = client.delete("/mail/emails/1")
    assert r.status_code == 200
    
    r = client.post("/mail/emails/1/reply", json={"body": "R"})
    assert r.status_code == 200
    assert r.json()["email_id"] == 1000
    
    r = client.post("/mail/emails/1/forward", json={"recipient": "y@y.com", "comment": "C"})
    assert r.status_code == 200
    assert r.json()["email_id"] == 1001
    
    r = client.get("/mail/emails/1/draft")
    assert r.status_code == 200
    assert r.json()["role"] == "[Abogado Mock]"
