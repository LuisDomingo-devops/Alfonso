import sys
from pathlib import Path
import pytest

# Add ui/ directory to sys.path so we can import core.processor
ui_path = str(Path(__file__).resolve().parents[1] / "ui")
if ui_path not in sys.path:
    sys.path.insert(0, ui_path)

from core.processor import ResponseProcessor

def test_format_response_chat():
    data = {"type": "chat", "response": "Hola de prueba"}
    assert ResponseProcessor.format_response(data) == "Hola de prueba"

def test_format_response_chat_empty():
    data = {"type": "chat"}
    assert ResponseProcessor.format_response(data) == "Sin respuesta."

def test_format_response_tool_datetime():
    data = {
        "type": "tool",
        "tool": "get_current_datetime",
        "result": {
            "status": "ok",
            "human": "martes, 30 de junio de 2026, 12:26"
        }
    }
    assert ResponseProcessor.format_response(data) == "martes, 30 de junio de 2026, 12:26"

def test_format_response_tool_read_file():
    data = {
        "type": "tool",
        "tool": "read_file",
        "result": {
            "status": "ok",
            "content": "contenido del archivo"
        }
    }
    assert ResponseProcessor.format_response(data) == "contenido del archivo"

def test_format_response_tool_list_directory():
    data = {
        "type": "tool",
        "tool": "list_directory",
        "result": {
            "status": "ok",
            "entries": [
                {"name": "file.txt", "is_dir": False},
                {"name": "folder", "is_dir": True}
            ]
        }
    }
    expected = "Contenido del directorio:\nfile.txt\nfolder/"
    assert ResponseProcessor.format_response(data) == expected

def test_format_response_tool_system_info():
    data = {
        "type": "tool",
        "tool": "get_system_info",
        "result": {
            "status": "ok",
            "system": "Linux",
            "release": "Ubuntu",
            "version": "24.04",
            "cpu_count": 8,
            "ram_total_gb": 16.0,
            "ram_used_percent": 50.0,
            "disk_total_gb": 100.0,
            "disk_free_gb": 30.0
        }
    }
    expected = (
        "Sistema: Linux Ubuntu (24.04)\n"
        "CPU: 8 núcleos\n"
        "RAM: 50.0% usada de 16.0 GB\n"
        "Disco: 30.0 GB libres de 100.0 GB"
    )
    assert ResponseProcessor.format_response(data) == expected

def test_format_response_tool_generic_success():
    data = {
        "type": "tool",
        "tool": "some_other_tool",
        "result": {
            "status": "ok"
        }
    }
    assert ResponseProcessor.format_response(data) == "Listo, ejecuté some_other_tool correctamente."

def test_format_response_client_list_directory():
    data = {
        "type": "tool",
        "execution": "client",
        "tool": "list_directory",
        "result": {
            "status": "success",
            "result": {
                "path": "C:\\Users\\luisd\\Desktop",
                "result": ["Alfonso", "credentials", "ui"]
            }
        }
    }
    expected = "Contenido del directorio 'C:\\Users\\luisd\\Desktop':\nAlfonso\ncredentials\nui"
    assert ResponseProcessor.format_response(data) == expected

def test_format_response_client_list_directory_no_path():
    data = {
        "type": "tool",
        "execution": "client",
        "tool": "list_directory",
        "result": {
            "status": "success",
            "result": {
                "result": ["Alfonso", "credentials", "ui"]
            }
        }
    }
    expected = "Contenido del directorio:\nAlfonso\ncredentials\nui"
    assert ResponseProcessor.format_response(data) == expected
