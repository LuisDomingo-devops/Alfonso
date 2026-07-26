import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from unittest.mock import patch, MagicMock
from app.utils.paths import get_client_context, get_client_desktop, resolve_client_path, get_cv_path

def test_get_cv_path():
    cv_p = get_cv_path()
    assert isinstance(cv_p, Path)
    assert cv_p.name == "cv.md"

def test_get_client_context_fallback_and_mock():
    # Mockear alfonso_bridge para simular cliente Windows conectado
    mock_bridge = MagicMock()
    mock_bridge.client_info = {
        "system": "Windows",
        "username": "testuser",
        "home": "C:\\Users\\testuser",
        "cwd": "C:\\Users\\testuser\\project"
    }
    mock_bridge._client_info_dict = {}

    with patch("app.adapters.alfonso_bridge.bridge", mock_bridge):
        ctx = get_client_context()
        assert ctx["system"] == "Windows"
        assert ctx["username"] == "testuser"
        assert ctx["home"] == "C:\\Users\\testuser"
        assert ctx["cwd"] == "C:\\Users\\testuser\\project"

def test_get_client_desktop():
    # Simular cliente Mac
    mock_bridge = MagicMock()
    mock_bridge.client_info = {
        "system": "Darwin",
        "username": "macuser",
        "home": "/Users/macuser",
        "cwd": "/Users/macuser/cwd"
    }
    mock_bridge._client_info_dict = {}

    with patch("app.adapters.alfonso_bridge.bridge", mock_bridge):
        desktop = get_client_desktop()
        assert desktop == "/Users/macuser/Desktop"

@patch("platform.system", return_value="Windows")
def test_resolve_client_path_placeholders(mock_platform):
    # Simular cliente
    mock_bridge = MagicMock()
    mock_bridge.client_info = {
        "system": "Windows",
        "username": "luisd",
        "home": "C:\\Users\\luisd",
        "cwd": "C:\\Users\\luisd\\cwd"
    }
    mock_bridge._client_info_dict = {}

    with patch("app.adapters.alfonso_bridge.bridge", mock_bridge):
        # Probar reemplazo de placeholders
        res = resolve_client_path("C:\\Users\\YOUR_USERNAME\\Desktop\\docs")
        assert res == "C:/Users/luisd/Desktop/docs"

        # Probar reemplazo de tilde (home)
        res_tilde = resolve_client_path("~/Desktop/notas.txt")
        assert res_tilde == "C:/Users/luisd/Desktop/notas.txt"

@patch("platform.system", return_value="Linux")
def test_resolve_client_path_wsl_translation(mock_platform):
    # Simular que el servidor está en Linux y el cliente es Windows
    mock_bridge = MagicMock()
    mock_bridge.client_info = {
        "system": "Windows",
        "username": "luisd",
        "home": "C:\\Users\\luisd",
        "cwd": "C:\\Users\\luisd\\cwd"
    }
    mock_bridge._client_info_dict = {}

    with patch("app.adapters.alfonso_bridge.bridge", mock_bridge):
        # Simulamos que existe la carpeta en WSL para forzar traducción
        with patch("os.path.exists", return_value=True):
            res = resolve_client_path("C:/Users/luisd/Desktop/file.txt")
            assert res == "/mnt/c/Users/luisd/Desktop/file.txt"
