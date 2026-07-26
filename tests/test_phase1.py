import asyncio
import sys

from app.adapters.tool_registry import get_tool
from app.adapters.memory import memory


def test_run_command_tool():
    tool = get_tool("run_command")
    assert tool is not None

    result = asyncio.run(tool([sys.executable, "-c", "print('hello')"]))

    assert result["status"] == "ok"
    assert "hello" in result["stdout"]


def test_list_directory_tool():
    tool = get_tool("list_directory")
    assert tool is not None

    result = asyncio.run(tool("app"))

    assert result["status"] == "ok"
    assert "entries" in result
    assert isinstance(result["entries"], list)


def test_session_memory_summary():
    session_id = "test-phase1-session"
    memory.clear(session_id)
    memory.add_message(session_id, "user", "hola")
    memory.add_message(session_id, "assistant", "Hola, ¿cómo puedo ayudarte?")

    summary = memory.get_summary(session_id)

    assert "user: hola" in summary
    assert "assistant: Hola, ¿cómo puedo ayudarte?" in summary
