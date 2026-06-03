import sys
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
import os
# Deshabilita el mock global del módulo app.core.memory que causaba problemas.
# En su lugar, usaremos fixtures específicos o mocks más precisos.
# Si app.core.memory tiene una instancia global 'memory', la parchearemos.
# Forzamos a que cualquier instancia de SessionMemory use una DB en memoria durante los tests
os.environ["ALFONSO_DB_PATH"] = ":memory:"


@pytest.fixture
def session_memory_fixture():
    """
    Proporciona una instancia de SessionMemory con una base de datos SQLite en memoria
    para cada test, asegurando aislamiento.
    """
    from app.core.memory import SessionMemory
    # Usamos ':memory:' para una base de datos en memoria que se destruye al finalizar el test.
    mem = SessionMemory(db_path=":memory:")
    yield mem
    # No es necesario limpiar explícitamente, la DB en memoria se borra.

@pytest.fixture(autouse=True)
def mock_memory():
    """
    Fixture para parchear la instancia global 'memory' en app.core.memory
    y en cualquier módulo que la importe, como planner_orchestrator.
    Esto evita que los tests interactúen con la DB real.
    """
    with patch("app.core.memory.memory") as mocked:
        # Configuramos comportamientos básicos si es necesario
        mocked.get_summary.return_value = ""
        yield mocked