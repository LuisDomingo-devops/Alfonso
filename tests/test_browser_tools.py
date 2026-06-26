import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.tools.browser_tools import (
    browser_get_text,
    browser_screenshot,
    browser_click,
    browser_close
)


@pytest.mark.asyncio
async def test_browser_get_text():
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.inner_text.return_value = "Contenido de ejemplo"
    
    with patch("app.tools.browser_tools._page", mock_page):
        res = await browser_get_text("body")
        assert res["status"] == "ok"
        assert res["text"] == "Contenido de ejemplo"
        mock_page.inner_text.assert_called_once_with("body", timeout=10000)


@pytest.mark.asyncio
async def test_browser_screenshot():
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.screenshot.return_value = b"bytes_imagen"
    
    with patch("app.tools.browser_tools._page", mock_page):
        res = await browser_screenshot()
        assert res["status"] == "ok"
        assert "image_base64" in res
        mock_page.screenshot.assert_called_once()


@pytest.mark.asyncio
async def test_browser_click():
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    
    with patch("app.tools.browser_tools._page", mock_page):
        res = await browser_click("button#enviar")
        assert res["status"] == "ok"
        mock_page.click.assert_called_once_with("button#enviar", timeout=10000)
