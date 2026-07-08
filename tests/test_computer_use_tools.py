import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.tools.client.system_tools import (
    mouse_click,
    keyboard_type,
    screenshot,
    window_list
)


@pytest.mark.asyncio
async def test_mouse_click_delegation():
    mock_bridge = AsyncMock()
    mock_bridge.has_clients = MagicMock(return_value=True)
    mock_bridge.send_command.return_value = {"status": "success", "result": "click_ok"}
    
    with patch("app.tools.client.system_tools.alfonso_bridge", mock_bridge):
        res = await mouse_click(x=10, y=20)
        assert res["status"] == "ok"
        mock_bridge.send_command.assert_called_once_with(
            "mouse.click",
            {"x": 10, "y": 20, "button": "left", "clicks": 1, "interval": 0.1}
        )


@pytest.mark.asyncio
async def test_keyboard_type_delegation():
    mock_bridge = AsyncMock()
    mock_bridge.has_clients = MagicMock(return_value=True)
    mock_bridge.send_command.return_value = {"status": "success", "result": "type_ok"}
    
    with patch("app.tools.client.system_tools.alfonso_bridge", mock_bridge):
        res = await keyboard_type("hola")
        assert res["status"] == "ok"
        mock_bridge.send_command.assert_called_once_with(
            "keyboard.type",
            {"text": "hola", "interval": 0.03}
        )
