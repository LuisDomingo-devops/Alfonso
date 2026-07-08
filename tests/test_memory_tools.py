import pytest
from app.adapters.memory import vector_memory
from app.tools.server.memory_tools import save_user_preference, forget_user_fact, get_user_profile


@pytest.fixture(autouse=True)
def clean_memory_db():
    # Limpiar antes y después de cada test
    vector_memory.clear()
    yield
    vector_memory.clear()


@pytest.mark.anyio
async def test_save_user_preference_tool():
    # Guardar
    res = await save_user_preference("Prefiero la interfaz oscura", "session_123")
    assert res["status"] == "ok"
    assert "fact_id" in res
    assert res["fact"] == "Prefiero la interfaz oscura"
    
    # Comprobar que está en base de datos
    facts = vector_memory.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["text"] == "Prefiero la interfaz oscura"
    assert facts[0]["session_id"] == "session_123"


@pytest.mark.anyio
async def test_get_user_profile_tool():
    # Guardar dos hechos de diferentes sesiones
    vector_memory.add_fact("session_abc", "Me gusta la pizza")
    vector_memory.add_fact("session_def", "Me gusta el sushi")
    
    # Obtener perfil para session_abc
    res = await get_user_profile("session_abc")
    assert res["status"] == "ok"
    assert res["count"] == 1
    assert "Me gusta la pizza" in res["facts"]
    
    # Obtener perfil global (incluye todo)
    res_global = await get_user_profile("global")
    assert res_global["status"] == "ok"
    assert res_global["count"] == 2


@pytest.mark.anyio
async def test_forget_user_fact_tool():
    # Guardar
    vector_memory.add_fact("session_123", "Mi perro se llama Rex")
    vector_memory.add_fact("session_123", "Mi gato se llama Félix")
    
    # Olvidar perro
    res = await forget_user_fact("Rex", "session_123")
    assert res["status"] == "ok"
    assert res["deleted_facts"] == ["Mi perro se llama Rex"]
    
    # Comprobar que solo queda el gato
    remaining = vector_memory.get_all_facts()
    assert len(remaining) == 1
    assert remaining[0]["text"] == "Mi gato se llama Félix"
