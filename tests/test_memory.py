"""
Tests para la memoria persistente con SQLite.
"""
import pytest
from app.core.memory import SessionMemory


@pytest.fixture
def mem(tmp_path, monkeypatch):
    """
    Crea una instancia de SessionMemory con una base de datos temporal
    para que los tests no interfieran con la base de datos real.
    """
    import app.core.memory as memory_module
    db_path = tmp_path / "test_memory.db"
    monkeypatch.setattr(memory_module, "DB_PATH", db_path)
    # Re-inicializar la base de datos en la ruta temporal
    memory_module._db_initialized = False
    with memory_module._get_connection() as conn:
        pass
    return SessionMemory(max_messages=5)


def test_add_and_get_history(mem):
    mem.add_message("session-1", "user", "hola")
    mem.add_message("session-1", "assistant", "hola, ¿en qué puedo ayudarte?")

    history = mem.get_history("session-1")
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "hola"}
    assert history[1] == {"role": "assistant", "content": "hola, ¿en qué puedo ayudarte?"}


def test_get_summary(mem):
    mem.add_message("session-2", "user", "hola")
    mem.add_message("session-2", "assistant", "hola!")

    summary = mem.get_summary("session-2")
    assert "user: hola" in summary
    assert "assistant: hola!" in summary


def test_empty_session_returns_empty(mem):
    assert mem.get_history("session-inexistente") == []
    assert mem.get_summary("session-inexistente") == ""


def test_max_messages_limit(mem):
    """Con max_messages=5, solo se conservan los 5 más recientes."""
    for i in range(10):
        mem.add_message("session-3", "user", f"mensaje {i}")

    history = mem.get_history("session-3")
    assert len(history) == 5
    # Deben ser los 5 últimos
    assert history[-1]["content"] == "mensaje 9"
    assert history[0]["content"] == "mensaje 5"


def test_clear_session(mem):
    mem.add_message("session-4", "user", "hola")
    mem.clear("session-4")

    assert mem.get_history("session-4") == []


def test_persistence_across_instances(tmp_path, monkeypatch):
    """
    Verifica que los datos sobreviven al crear una nueva instancia de SessionMemory,
    simulando un reinicio del servidor.
    """
    import app.core.memory as memory_module
    db_path = tmp_path / "persist_test.db"
    monkeypatch.setattr(memory_module, "DB_PATH", db_path)
    memory_module._db_initialized = False
    with memory_module._get_connection() as conn:
        pass

    # Primera instancia: escribe datos
    mem1 = SessionMemory(max_messages=10)
    mem1.add_message("session-5", "user", "mensaje persistente")
    mem1.add_message("session-5", "assistant", "respuesta persistente")

    # Segunda instancia (simula reinicio): debe leer los datos del disco
    mem2 = SessionMemory(max_messages=10)
    history = mem2.get_history("session-5")

    assert len(history) == 2
    assert history[0]["content"] == "mensaje persistente"
    assert history[1]["content"] == "respuesta persistente"


def test_multiple_sessions_isolated(mem):
    """Las sesiones no se mezclan entre sí."""
    mem.add_message("session-a", "user", "mensaje de a")
    mem.add_message("session-b", "user", "mensaje de b")

    history_a = mem.get_history("session-a")
    history_b = mem.get_history("session-b")

    assert len(history_a) == 1
    assert history_a[0]["content"] == "mensaje de a"
    assert len(history_b) == 1
    assert history_b[0]["content"] == "mensaje de b"


def test_list_sessions(mem):
    mem.add_message("session-x", "user", "x")
    mem.add_message("session-y", "user", "y")

    sessions = mem.list_sessions()
    assert "session-x" in sessions
    assert "session-y" in sessions


def test_empty_session_id_ignored(mem):
    """session_id vacío no debe guardar nada."""
    mem.add_message("", "user", "esto no debería guardarse")
    assert mem.get_history("") == []