from app.core.tool_registry import get_tool, list_tools


def test_tool_registry_loads_plugins():
    tools = list_tools()

    assert "create_file" in tools
    assert "read_file" in tools
    assert "system_info" in tools
    assert "run_command" in tools
    assert "list_directory" in tools
    assert "open_application" in tools
    assert "text_to_speech" in tools
    assert "speech_to_text" in tools
    assert "wake_word_listener" in tools

    assert get_tool("create_file") is not None
    assert get_tool("read_file") is not None
    assert get_tool("system_info") is not None
    assert get_tool("run_command") is not None
    assert get_tool("list_directory") is not None
    assert get_tool("open_application") is not None
    assert get_tool("close_application") is not None
    assert get_tool("text_to_speech") is not None
    assert get_tool("speech_to_text") is not None
    assert get_tool("wake_word_listener") is not None


def test_tool_registry_unknown_tool_returns_none():
    assert get_tool("missing_tool") is None
