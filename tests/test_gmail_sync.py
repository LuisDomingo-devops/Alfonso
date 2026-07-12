import pytest
import os
import sqlite3
from unittest.mock import MagicMock, patch
from app.core import gmail_sync
from app.adapters import mail_db

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

@pytest.fixture
def setup_test_db(monkeypatch):
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
    
    # Mockear get_connection en ambos espacios de nombre para mayor seguridad
    monkeypatch.setattr(mail_db, "get_connection", lambda: DummyConnection(conn))
    monkeypatch.setattr(gmail_sync, "get_connection", lambda: DummyConnection(conn))
    yield conn
    conn.close()

@pytest.mark.asyncio
async def test_sync_from_gmail_no_env(setup_test_db, monkeypatch):
    monkeypatch.setenv("GMAIL_EMAIL", "")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "")
    
    count = await gmail_sync.sync_from_gmail()
    assert count == 0

@pytest.mark.asyncio
async def test_sync_from_gmail_mock(setup_test_db, monkeypatch):
    monkeypatch.setenv("GMAIL_EMAIL", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    
    # Mock IMAP
    mock_imap = MagicMock()
    mock_imap.search.return_value = ("OK", [b"1 2"])
    
    # Email mock payload
    email_bytes = b"""From: sender@gmail.com
To: recipient@gmail.com
Subject: Test subject from Gmail
Date: Sun, 12 Jul 2026 10:00:00 +0200
MIME-Version: 1.0
Content-Type: text/plain

This is a test gmail message.
"""
    
    def side_effect(e_id, query):
        print(f"FETCH CALLED WITH: e_id={e_id}, query={query}")
        if query == "(RFC822)":
            return ("OK", [(None, email_bytes)])
        elif query == "(FLAGS)":
            if e_id == b"1":
                return ("OK", [b"FLAGS (\\Seen)"])
            else:
                return ("OK", [b"FLAGS ()"])
        return ("OK", [])

    mock_imap.fetch.side_effect = side_effect
    
    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        count = await gmail_sync.sync_from_gmail()
        
    assert count > 0
    # Verificar inserción
    emails = mail_db.list_emails()
    assert len(emails) > 0
    assert emails[0]["subject"] == "Test subject from Gmail"
    assert emails[0]["sender"] == "sender@gmail.com"
