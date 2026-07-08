import pytest
from unittest.mock import AsyncMock, MagicMock
from app.domain.planner_orchestrator import PlannerOrchestrator
from app.adapters.memory import memory, vector_memory


@pytest.fixture(autouse=True)
def clean_databases():
    # Limpiar memoria de sesión y vectorial
    vector_memory.clear()
    # Limpiar SQLite
    sessions = memory.list_sessions()
    for s in sessions:
        memory.clear(s)
    yield
    vector_memory.clear()
    for s in memory.list_sessions():
        memory.clear(s)


@pytest.mark.anyio
async def test_orchestrator_memory_lifecycle():
    orchestrator = PlannerOrchestrator()
    session_id = "test_e2e_session"

    # --- FASE 1: Guardar preferencia a través de la simulación del LLM ---
    # El usuario da una orden que no activa el analizador estático pero sí al LLM en modo tool.
    mock_llm = MagicMock()
    # Forzar una llamada a la tool save_user_preference
    mock_llm.generate = AsyncMock(return_value='{"tool": "save_user_preference", "args": {"fact": "El perro del usuario se llama Toby."}}')

    # Ejecutar en el orquestador (forzamos que vaya a la tool usando una keyword)
    result = await orchestrator.run(
        user_message="crea un registro indicando que mi perro se llama Toby.",
        llm=mock_llm,
        session_id=session_id
    )

    # Verificar que el hecho se guardó en ChromaDB mediante la tool
    facts = vector_memory.get_all_facts()
    assert len(facts) == 1
    assert facts[0]["text"] == "El perro del usuario se llama Toby."
    assert facts[0]["session_id"] == session_id

    # --- FASE 2: Recuperación del contexto semántico en el siguiente turno ---
    # El usuario pregunta cómo se llama su perro.
    mock_llm.generate = AsyncMock(return_value='{"tool": "no_op", "args": {"message": "Buscando..."}}')

    await orchestrator.run(
        user_message="¿Cómo se llama mi perro?",
        llm=mock_llm,
        session_id=session_id
    )

    # Verificar que mock_llm.generate fue llamado con el contexto de la memoria recuperada
    args, kwargs = mock_llm.generate.call_args
    memory_context = kwargs.get("memory")
    assert memory_context is not None
    assert "El perro del usuario se llama Toby." in memory_context

    # --- FASE 3: Borrar el recuerdo a través del LLM ---
    # Petición para olvidar. Usamos una palabra clave explícita para la coincidencia de substring
    mock_llm.generate = AsyncMock(return_value='{"tool": "forget_user_fact", "args": {"query": "Toby"}}')

    await orchestrator.run(
        user_message="elimina de mi perfil el nombre de mi perro",
        llm=mock_llm,
        session_id=session_id
    )

    # Verificar que ya no queden recuerdos en la base de datos vectorial
    facts_after = vector_memory.get_all_facts()
    assert len(facts_after) == 0


@pytest.mark.anyio
async def test_orchestrator_style_injection():
    orchestrator = PlannerOrchestrator()
    session_id = "test_style_session"

    # Insertar una directriz de estilo en ChromaDB
    vector_memory.add_fact(session_id, "Responder siempre de forma muy concisa y usando viñetas.")

    # Simular una consulta del usuario
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value='{"tool": "no_op", "args": {"message": "Listo"}}')

    await orchestrator.run(
        user_message="Dame el estado del servidor",
        llm=mock_llm,
        session_id=session_id
    )

    # Verificar que la directriz se recuperó e inyectó bajo el bloque de estilo
    args, kwargs = mock_llm.generate.call_args
    memory_context = kwargs.get("memory")
    assert memory_context is not None
    assert "[Directrices de estilo preferidas por el usuario:]" in memory_context
    assert "Responder siempre de forma muy concisa y usando viñetas." in memory_context

