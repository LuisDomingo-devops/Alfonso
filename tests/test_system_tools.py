import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.tools.client.system_tools import open_application, open_url, close_application

@pytest.mark.asyncio
async def test_open_application_delegation():
    mock_bridge = AsyncMock()
    mock_bridge.has_clients = MagicMock(return_value=True)
    mock_bridge.send_command.return_value = {"status": "success", "result": "app_opened"}
    
    with patch("app.tools.client.system_tools.alfonso_bridge", mock_bridge):
        res = await open_application("notepad")
        assert res["status"] == "ok"
        mock_bridge.send_command.assert_called_once_with(
            "open_app",
            {"command": "notepad"}
        )

@pytest.mark.asyncio
async def test_open_url_delegation():
    mock_bridge = AsyncMock()
    mock_bridge.has_clients = MagicMock(return_value=True)
    mock_bridge.send_command.return_value = {"status": "success", "result": "https://google.com"}
    
    with patch("app.tools.client.system_tools.alfonso_bridge", mock_bridge):
        res = await open_url("https://google.com")
        assert res["status"] == "ok"
        mock_bridge.send_command.assert_called_once_with(
            "open_url",
            {"url": "https://google.com"}
        )

@pytest.mark.asyncio
async def test_close_application_delegation():
    mock_bridge = AsyncMock()
    mock_bridge.has_clients = MagicMock(return_value=True)
    mock_bridge.send_command.return_value = {"status": "success", "result": "app_closed"}
    
    with patch("app.tools.client.system_tools.alfonso_bridge", mock_bridge):
        res = await close_application("notepad")
        assert res["status"] == "ok"
        mock_bridge.send_command.assert_called_once_with(
            "close_app",
            {"command": "notepad"}
        )
