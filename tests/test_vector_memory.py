import pytest
from unittest.mock import MagicMock, patch
from app.core.vector_memory import VectorMemory


@pytest.fixture
def temp_vector_memory(tmp_path, monkeypatch):
    import app.config as config_module
    db_path = tmp_path / "chroma_test"
    monkeypatch.setattr(config_module.settings, "CHROMA_DB_PATH", str(db_path))
    
    # Mockear las peticiones HTTP a Ollama para que los tests corran 100% offline
    def mock_post(url, json, **kwargs):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Retornamos un vector simulado determinista de 768 dimensiones
        mock_resp.json.return_value = {"embedding": [0.1] * 768}
        return mock_resp

    with patch("httpx.Client.post", side_effect=mock_post):
        mem = VectorMemory()
        yield mem
        mem.clear()


def test_add_and_query_facts(temp_vector_memory):
    temp_vector_memory.add_fact("session_1", "Luis prefiere programar en Python.")
    temp_vector_memory.add_fact("session_1", "El color favorito de Luis es el azul.")
    
    facts = temp_vector_memory.query_facts("¿Qué lenguaje usa Luis?")
    assert len(facts) > 0
    # Como todos tienen el mismo embedding mockeado, deben retornar
    assert any("Python" in f for f in facts)


def test_vector_memory_clear(temp_vector_memory):
    temp_vector_memory.add_fact("session_1", "Dato a borrar")
    temp_vector_memory.clear()
    
    facts = temp_vector_memory.query_facts("Dato a borrar")
    assert len(facts) == 0
