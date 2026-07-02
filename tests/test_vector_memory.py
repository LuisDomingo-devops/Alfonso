import pytest
from app.core.vector_memory import VectorMemory


@pytest.fixture
def temp_vector_memory(tmp_path, monkeypatch):
    import app.config as config_module
    db_path = tmp_path / "chroma_test"
    monkeypatch.setattr(config_module.settings, "CHROMA_DB_PATH", str(db_path))
    
    mem = VectorMemory()
    yield mem
    mem.clear()


def test_add_and_query_facts(temp_vector_memory):
    # Agregar hechos
    id1 = temp_vector_memory.add_fact("session_1", "Luis prefiere programar en Python.")
    id2 = temp_vector_memory.add_fact("session_1", "El color favorito de Luis es el azul.")
    
    assert id1 != ""
    assert id2 != ""
    
    # Consultar hechos
    facts = temp_vector_memory.query_facts("¿Qué lenguaje de programación le gusta a Luis?")
    assert len(facts) > 0
    assert any("Python" in f for f in facts)


def test_query_facts_with_ids(temp_vector_memory):
    temp_vector_memory.add_fact("session_1", "Alfonso es un asistente virtual.")
    
    candidates = temp_vector_memory.query_facts_with_ids("asistente virtual", limit=1)
    assert len(candidates) == 1
    assert candidates[0]["text"] == "Alfonso es un asistente virtual."
    assert candidates[0]["id"] != ""
    assert candidates[0]["session_id"] == "session_1"


def test_delete_fact_by_id(temp_vector_memory):
    fact_id = temp_vector_memory.add_fact("session_1", "Frase temporal para borrar")
    
    # Asegurar que existe
    facts_before = temp_vector_memory.query_facts("Frase temporal")
    assert len(facts_before) > 0
    
    # Borrar
    success = temp_vector_memory.delete_fact_by_id(fact_id)
    assert success is True
    
    # Asegurar que se borró
    facts_after = temp_vector_memory.get_all_facts()
    assert not any(f["id"] == fact_id for f in facts_after)


def test_delete_facts_by_session(temp_vector_memory):
    temp_vector_memory.add_fact("session_a", "Hecho de la sesión A")
    temp_vector_memory.add_fact("session_b", "Hecho de la sesión B")
    
    # Borrar todos los de la sesión A
    success = temp_vector_memory.delete_facts_by_session("session_a")
    assert success is True
    
    # Comprobar
    remaining = temp_vector_memory.get_all_facts()
    assert len(remaining) == 1
    assert remaining[0]["session_id"] == "session_b"


def test_vector_memory_clear(temp_vector_memory):
    temp_vector_memory.add_fact("session_1", "Dato a borrar")
    temp_vector_memory.clear()
    
    facts = temp_vector_memory.query_facts("Dato a borrar")
    assert len(facts) == 0
