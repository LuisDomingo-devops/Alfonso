"""
BROWSER TOOLS — Herramientas de navegación web basadas en Playwright.

¿QUÉ HACE?
Implementa herramientas para interactuar con sitios web (navegación, clics, búsquedas, rellenar formularios, scroll y screenshots).

¿CUÁNDO LO HACE?
Cuando el orquestador ejecuta tareas de investigación en la web en nombre del usuario.

¿CÓMO LO HACE?
Inicializando una sesión interactiva en segundo plano con Playwright y exponiendo llamadas asíncronas.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/core/tool_registry.py (registra estas herramientas)
- app/api/routes.py (expone endpoints directos de control de navegador)
"""

from __future__ import annotations

import asyncio
import base64
import os
import urllib.parse
from typing import Optional, Dict, Any

from dotenv import load_dotenv

load_dotenv()

from app.utils.logger import error_logger, tool_logger


# =========================================================
# Estado global (singleton controlado)
# =========================================================

_playwright = None
_browser = None
_context = None
_page = None

_lock = asyncio.Lock()


# =========================================================
# Helpers de error estructurado
# =========================================================

def _error(error_type: str, message: str, **extra) -> dict:
    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
        **extra
    }


def _ok(**data) -> dict:
    return {
        "status": "ok",
        **data
    }


# =========================================================
# Inicialización segura
# =========================================================

async def _get_page():
    global _playwright, _browser, _context, _page

    async with _lock:
        if _page and not _page.is_closed():
            return _page

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright no instalado. Instala con: "
                "pip install playwright && playwright install chromium"
            )

        browser_type = os.getenv("ALFONSO_BROWSER", "chromium").lower()
        headless = os.getenv("ALFONSO_HEADLESS", "true").lower() != "false"

        tool_logger.info("Iniciando browser: %s headless=%s", browser_type, headless)

        try:
            _playwright = await async_playwright().start()
            launcher = getattr(_playwright, browser_type)

            _browser = await launcher.launch(headless=headless)
            _context = await _browser.new_context()
            _page = await _context.new_page()

        except Exception as e:
            await _close()
            return _error("browser_startup_failed", str(e))

        tool_logger.info("Browser listo")
        return _page


async def _close():
    global _playwright, _browser, _context, _page

    try:
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
        if _playwright:
            await _playwright.stop()
    finally:
        _playwright = None
        _browser = None
        _context = None
        _page = None


# =========================================================
# PRIMITIVAS (nivel bajo)
# =========================================================

async def browser_navigate(url: str, wait_until: str = "domcontentloaded"):
    try:
        page = await _get_page()
        if isinstance(page, dict):
            return page

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        response = await page.goto(url, wait_until=wait_until, timeout=30000)

        return _ok(
            url=page.url,
            title=await page.title(),
            http_status=response.status if response else None
        )

    except Exception as e:
        error_logger.exception("browser_navigate error")
        return _error("navigation_error", str(e), url=url)


async def browser_click(selector: str):
    try:
        page = await _get_page()
        if isinstance(page, dict):
            return page

        await page.click(selector, timeout=10000)
        return _ok(selector=selector)

    except Exception as e:
        return _error("click_failed", str(e), selector=selector)


async def browser_fill(selector: str, value: str):
    try:
        page = await _get_page()
        if isinstance(page, dict):
            return page

        await page.fill(selector, value, timeout=10000)
        return _ok(selector=selector, length=len(value))

    except Exception as e:
        return _error("fill_failed", str(e), selector=selector)


async def browser_screenshot(full_page: bool = False):
    try:
        page = await _get_page()
        if isinstance(page, dict):
            return page

        img = await page.screenshot(full_page=full_page)
        return _ok(
            image_base64=base64.b64encode(img).decode(),
            url=page.url
        )

    except Exception as e:
        return _error("screenshot_failed", str(e))


async def browser_get_text(selector: str = "body"):
    try:
        page = await _get_page()
        if isinstance(page, dict):
            return page

        text = await page.inner_text(selector, timeout=10000)
        return _ok(text=text.strip())

    except Exception as e:
        return _error("text_extraction_failed", str(e), selector=selector)


# =========================================================
# INSPECCIÓN (CLAVE PARA AGENTE)
# =========================================================

async def browser_inspect():
    """
    Devuelve estado estructurado de la página.
    Esto es lo que permite que Alfonso "entienda UI".
    """
    try:
        page = await _get_page()
        if isinstance(page, dict):
            return page

        title = await page.title()
        url = page.url

        links = await page.eval_on_selector_all(
            "a",
            "els => els.slice(0, 30).map(e => ({text: e.innerText, href: e.href}))"
        )

        inputs = await page.eval_on_selector_all(
            "input, textarea",
            "els => els.slice(0, 30).map(e => ({type: e.type, name: e.name, placeholder: e.placeholder}))"
        )

        buttons = await page.eval_on_selector_all(
            "button",
            "els => els.slice(0, 30).map(e => e.innerText)"
        )

        return _ok(
            url=url,
            title=title,
            links=links,
            inputs=inputs,
            buttons=buttons
        )

    except Exception as e:
        return _error("inspect_failed", str(e))


# =========================================================
# COMPUESTAS (nivel alto)
# =========================================================

async def browser_search(query: str, max_text_chars: int = 3000):
    try:
        if not query.strip():
            return _error("invalid_query", "Query vacía")

        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)

        nav = await browser_navigate(url)
        if nav.get("status") != "ok":
            return nav

        # fallback robusto (Google cambia DOM)
        await asyncio.sleep(2)

        text = await browser_get_text("body")
        shot = await browser_screenshot()

        return _ok(
            query=query,
            url=url,
            text_preview=text.get("text", "")[:max_text_chars],
            image_base64=shot.get("image_base64")
        )

    except Exception as e:
        return _error("search_failed", str(e), query=query)


async def browser_close():
    """Cierra el navegador. Si hay un cliente conectado, delega el cierre cerrando los navegadores comunes (chrome, firefox, msedge)."""
    from app.adapters.alfonso_bridge import bridge as alfonso_bridge
    if alfonso_bridge.has_clients():
        from app.tools.client.system_tools import close_application
        tool_logger.info("Delegando browser_close al cliente")
        results = []
        for browser_name in ["chrome", "firefox", "msedge"]:
            res = await close_application(browser_name)
            results.append(res)
        return _ok(message="Comandos de cierre de navegador delegados al cliente", results=results)

    try:
        await _close()
        return _ok(message="Browser cerrado en el servidor")
    except Exception as e:
        return _error("close_failed", str(e))


# =========================================================
# REGISTRO
# =========================================================

TOOLS = {
    # primitivas
    "browser_navigate": browser_navigate,
    "browser_click": browser_click,
    "browser_fill": browser_fill,
    "browser_screenshot": browser_screenshot,
    "browser_get_text": browser_get_text,

    # nueva clave
    "browser_inspect": browser_inspect,

    # compuestas
    "browser_search": browser_search,

    # control
    "browser_close": browser_close,
}