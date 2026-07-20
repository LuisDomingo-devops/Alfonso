import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pathlib
import tempfile
import py_compile
from app.tools.server.filesystem_tools import replace_file_content
from app.adapters.llm_client import extract_json_robust
from app.domain.planner_orchestrator import PlannerOrchestrator

# 1. Test replace_file_content tool
@pytest.mark.asyncio
async def test_replace_file_content_success():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".py") as f:
        f.write("def foo():\n    return 42\n")
        f.close()
        
        path = f.name
        
        # Test replacement
        res = await replace_file_content(path=path, target="42", replacement="100")
        assert res["status"] == "ok"
        
        content = pathlib.Path(path).read_text(encoding="utf-8")
        assert "return 100" in content
        
        # Cleanup
        pathlib.Path(path).unlink()

@pytest.mark.asyncio
async def test_replace_file_content_syntax_error():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".py") as f:
        # Valid python originally
        f.write("def foo():\n    return 42\n")
        f.close()
        
        path = f.name
        
        # We replace with invalid Python (missing indent/syntax)
        res = await replace_file_content(path=path, target="return 42", replacement="return = 42")
        assert res["status"] == "ok"
        
        content = pathlib.Path(path).read_text(encoding="utf-8")
        assert "return = 42" in content
        
        # Check syntax explicitly using py_compile to ensure our checker detects it
        with pytest.raises(py_compile.PyCompileError):
            py_compile.compile(path, doraise=True)
            
        pathlib.Path(path).unlink()

# 2. Test R1 thought block extraction
def test_extract_json_robust_with_think():
    raw_with_think = """
    <think>
    Thinking... Let's use read_file tool.
    </think>
    {"tool": "read_file", "args": {"path": "test.txt"}}
    """
    res = extract_json_robust(raw_with_think)
    assert res is not None
    assert res["tool"] == "read_file"
    assert res["args"]["path"] == "test.txt"

# 3. Test self-correction loop in PlannerOrchestrator
@pytest.mark.asyncio
async def test_orchestrator_self_correction_loop(session_memory_fixture):
    session_memory_fixture.clear("test_session")
    mock_vector = MagicMock()
    mock_vector.query_facts.return_value = []
    
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock()

    # Attempt 1: LLM returns tool with bad python code
    # Attempt 2: LLM gets the error in memory and returns corrected tool
    mock_llm.generate.side_effect = [
        '{"tool": "create_file", "args": {"path": "sandbox_temp.py", "content": "def foo() return 42"}}', # syntax error (missing colon)
        '{"tool": "create_file", "args": {"path": "sandbox_temp.py", "content": "def foo():\\n    return 42"}}'   # correct syntax
    ]

    with patch("app.domain.planner_orchestrator.memory", session_memory_fixture), \
         patch("app.domain.planner_orchestrator.vector_memory", mock_vector), \
         patch("app.domain.planner_orchestrator.is_client_tool", return_value=False):
             
        # Mock create_file to behave normally
        temp_dir = tempfile.TemporaryDirectory()
        temp_file_path = pathlib.Path(temp_dir.name) / "sandbox_temp.py"
        
        async def mock_create_file(path, content):
            temp_file_path.write_text(content, encoding="utf-8")
            return {"status": "ok", "message": "created"}
            
        with patch("app.domain.planner_orchestrator.get_tool", return_value=mock_create_file), \
             patch("app.tools.server.filesystem_tools._resolve_path", return_value=temp_file_path):
                 
            orchestrator = PlannerOrchestrator()
            result = await orchestrator.run(
                user_message="crea el archivo python",
                llm=mock_llm,
                session_id="test_session"
            )
            
            # The second attempt should succeed
            assert result["type"] == "tool"
            assert result["tool"] == "create_file"
            assert temp_file_path.read_text(encoding="utf-8") == "def foo():\n    return 42"
            
        temp_dir.cleanup()
