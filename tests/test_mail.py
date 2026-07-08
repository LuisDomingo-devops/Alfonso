import pytest
import os
import sqlite3
from unittest.mock import AsyncMock, patch, MagicMock
from app.adapters.mail_db import (
    create_email,
    list_emails,
    get_email,
    update_email,
    seed_mock_emails,
)
from app.tools.server.mail_tools import (
    mail_receive_mock_emails,
    mail_classify_emails,
    mail_get_unread_summary,
    mail_list_emails,
    mail_get_email,
)

# Conexión compartida en memoria para tests
_test_conn = None

class DummyConnection:
    def __init__(self, conn):
        self._conn = conn
    def __getattr__(self, name):
        return getattr(self._conn, name)
    def close(self):
        # no-op
        pass
    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)
    def commit(self, *args, **kwargs):
        return self._conn.commit(*args, **kwargs)

@pytest.fixture(autouse=True)
def setup_test_db():
    global _test_conn
    os.environ["TESTING"] = "true"
    
    if _test_conn is None:
        _test_conn = sqlite3.connect(":memory:", check_same_thread=False)
        _test_conn.row_factory = sqlite3.Row
    
    # Asegurar esquema limpio antes de cada test
    try:
        _test_conn.execute("DROP TABLE IF EXISTS emails")
        _test_conn.commit()
    except Exception:
        pass
        
    from app.adapters.mail_db import _init_mail_schema
    _init_mail_schema(_test_conn)
    
    dummy = DummyConnection(_test_conn)
    
    with patch("app.adapters.mail_db.get_connection", return_value=dummy):
        yield

def test_mail_db_operations():
    # 1. Crear
    email_id = create_email(
        sender="test@sender.com",
        recipient="luisd@alfonso.dev",
        subject="Reunión urgente",
        body="Por favor asiste a la reunión de las 12:00",
        received_at="2026-07-04 10:00",
        importance="Alta"
    )
    assert email_id > 0

    # 2. Obtener
    email = get_email(email_id)
    assert email is not None
    assert email["sender"] == "test@sender.com"
    assert email["subject"] == "Reunión urgente"
    assert email["importance"] == "Alta"
    assert email["read_status"] == 0

    # 3. Listar
    emails = list_emails(importance="Alta")
    assert len(emails) == 1
    assert emails[0]["id"] == email_id

    # 4. Actualizar
    updated = update_email(email_id, category="personal", importance="Baja", read_status=1, summary="Reunión importante")
    assert updated is True
    email = get_email(email_id)
    assert email["category"] == "personal"
    assert email["importance"] == "Baja"
    assert email["read_status"] == 1
    assert email["summary"] == "Reunión importante"


@pytest.mark.anyio
async def test_mail_tools_and_mock_seeding():
    # Test inyectar mock emails con tool
    res = await mail_receive_mock_emails()
    assert res["status"] == "ok"
    assert res["inserted_count"] > 0

    # Test listar con tool
    res_list = await mail_list_emails()
    assert res_list["status"] == "ok"
    assert res_list["count"] > 0

    # Test clasificar con tool (mocking LLM response to avoid network call in pytest)
    with patch("app.tools.server.mail_tools._llm.generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = '{"category": "legal", "importance": "Alta", "summary": "Notificacion urgente judicial"}'
        res_class = await mail_classify_emails()
        assert res_class["status"] == "ok"
        assert res_class["classified_count"] > 0

    # Verificar que al menos uno quedó clasificado como legal/Alta/con resumen
    emails = list_emails()
    assert any(e["category"] == "legal" for e in emails)

    # Verificar que el email con la cita dental se sincronizó al calendario
    from app.adapters.calendar_db import list_events
    events = list_events(start_date="2026-07-10", end_date="2026-07-10")
    assert len(events) > 0
    assert any("dental" in ev["title"].lower() for ev in events)

    # Test get email con tool
    target_id = emails[0]["id"]
    res_get = await mail_get_email(target_id)
    assert res_get["status"] == "ok"
    assert res_get["email"]["read_status"] == 1  # Debe marcarse como leído

    # Test obtener resumen con tool (mocking LLM response)
    with patch("app.tools.server.mail_tools._llm.generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = "Buenos días Luis, aquí tienes tu resumen..."
        res_sum = await mail_get_unread_summary()
        assert res_sum["status"] == "ok"
        assert "unread_count" in res_sum
        assert "resumen" in res_sum["summary"].lower()
        assert "resumen" in res_sum["message"].lower()
