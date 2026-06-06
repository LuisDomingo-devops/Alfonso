"""
browser_tools.py — Fase 3: control real del navegador con Playwright

Herramientas:
    browser_navigate        → abre una URL
    browser_click           → hace click en un selector CSS / XPath
    browser_fill            → rellena un campo de formulario
    browser_submit          → envía un formulario
    browser_screenshot      → captura la página como imagen
    browser_get_text        → extrae el texto visible de la página
    browser_get_html        → devuelve el HTML completo
    browser_wait_for        → espera a que aparezca un selector
    browser_scroll          → hace scroll en la página
    browser_evaluate        → ejecuta JavaScript en la página
    browser_search          → busca en Google y devuelve texto + screenshot  ← NUEVO
    browser_close           → cierra el navegador

Diseño:
    - Una única instancia de Playwright por proceso (singleton lazy).
    - Chromium headless por defecto; ALFONSO_BROWSER=firefox|webkit para cambiar.
    - ALFONSO_HEADLESS=false para ver el navegador en pantalla (útil en desarrollo).
    - Thread-safe: todas las operaciones van a través de asyncio.
"""

from __future__ import annotations

import asyncio
import base64
import os
import urllib.parse
from typing import Optional

from app.utils.logger import error_logger, tool_logger

# ---------------------------------------------------------------------------
# Singleton del navegador
# ---------------------------------------------------------------------------

_playwright_instance = None
_browser_instance = None
_page_instance = None
_lock = asyncio.Lock()


async def _get_page():
    """Devuelve la página activa, arrancando Playwright si es necesario."""
    global _playwright_instance, _browser_instance, _page_instance

    async with _lock:
        if _page_instance is not None and not _page_instance.is_closed():
            return _page_instance

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright no instalado. Ejecuta: "
                "pip install playwright --break-system-packages && playwright install chromium"
            )

        browser_type = os.getenv("ALFONSO_BROWSER", "chromium").lower()
        headless = os.getenv("ALFONSO_HEADLESS", "true").lower() != "false"

        tool_logger.info("Arrancando Playwright: browser=%s headless=%s", browser_type, headless)

        _playwright_instance = await async_playwright().start()

        launcher = getattr(_playwright_instance, browser_type)
        _browser_instance = await launcher.launch(headless=headless)
        _page_instance = await _browser_instance.new_page()

        tool_logger.info("Playwright listo")
        return _page_instance


async def _close_playwright():
    global _playwright_instance, _browser_instance, _page_instance
    if _browser_instance:
        await _browser_instance.close()
    if _playwright_instance:
        await _playwright_instance.stop()
    _playwright_instance = None
    _browser_instance = None
    _page_instance = None


# ---------------------------------------------------------------------------
# Herramientas
# ---------------------------------------------------------------------------

async def browser_navigate(url: str, wait_until: str = "domcontentloaded") -> dict:
    """
    Navega a una URL.

    Args:
        url: URL completa (debe incluir https://)
        wait_until: "domcontentloaded" | "load" | "networkidle"
    """
    tool_logger.info("browser_navigate: %s", url)
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        page = await _get_page()
        response = await page.goto(url, wait_until=wait_until, timeout=30_000)

        status = response.status if response else None
        title = await page.title()

        tool_logger.info("Navegado a %s → status=%s title=%s", url, status, title)
        return {
            "status": "ok",
            "url": page.url,
            "title": title,
            "http_status": status,
        }
    except Exception as exc:
        error_logger.exception("Error en browser_navigate")
        return {"status": "error", "message": str(exc)}


async def browser_click(
    selector: str,
    timeout: int = 10_000,
    button: str = "left",
    click_count: int = 1,
) -> dict:
    """
    Hace click en el elemento identificado por `selector` (CSS o XPath).

    Args:
        selector: CSS selector o XPath (prefijo "xpath=")
        timeout: ms máximos esperando al elemento
        button: "left" | "right" | "middle"
        click_count: 1 = simple, 2 = doble
    """
    tool_logger.info("browser_click: selector=%s", selector)
    try:
        page = await _get_page()
        await page.click(
            selector,
            timeout=timeout,
            button=button,
            click_count=click_count,
        )
        return {"status": "ok", "selector": selector}
    except Exception as exc:
        error_logger.exception("Error en browser_click")
        return {"status": "error", "message": str(exc), "selector": selector}


async def browser_fill(
    selector: str,
    value: str,
    timeout: int = 10_000,
) -> dict:
    """
    Rellena un campo de texto (input, textarea) con `value`.
    Limpia el campo antes de escribir.
    """
    tool_logger.info("browser_fill: selector=%s value_len=%d", selector, len(value))
    try:
        page = await _get_page()
        await page.fill(selector, value, timeout=timeout)
        return {"status": "ok", "selector": selector, "value_length": len(value)}
    except Exception as exc:
        error_logger.exception("Error en browser_fill")
        return {"status": "error", "message": str(exc), "selector": selector}


async def browser_submit(selector: str, timeout: int = 10_000) -> dict:
    """
    Envía el formulario que contiene el selector dado
    (pulsa Enter o hace click en el botón submit).
    """
    tool_logger.info("browser_submit: selector=%s", selector)
    try:
        page = await _get_page()
        try:
            await page.locator(selector).evaluate("el => el.form && el.form.submit()")
        except Exception:
            await page.press(selector, "Enter", timeout=timeout)
        return {"status": "ok", "selector": selector}
    except Exception as exc:
        error_logger.exception("Error en browser_submit")
        return {"status": "error", "message": str(exc)}


async def browser_screenshot(
    full_page: bool = False,
    save_path: Optional[str] = None,
) -> dict:
    """
    Captura la página actual como PNG.

    Args:
        full_page: True para capturar la página completa (con scroll)
        save_path: ruta donde guardar (opcional)

    Returns:
        {status, image_base64, url, path?}
    """
    tool_logger.info("browser_screenshot: full_page=%s", full_page)
    try:
        page = await _get_page()
        data = await page.screenshot(full_page=full_page)
        b64 = base64.b64encode(data).decode()

        result: dict = {"status": "ok", "image_base64": b64, "url": page.url}

        if save_path:
            from pathlib import Path
            p = Path(save_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            result["path"] = str(p)
            tool_logger.info("Browser screenshot guardado en %s", p)

        return result
    except Exception as exc:
        error_logger.exception("Error en browser_screenshot")
        return {"status": "error", "message": str(exc)}


async def browser_get_text(selector: str = "body") -> dict:
    """
    Extrae el texto visible del elemento identificado por `selector`.
    Por defecto extrae todo el texto de la página (body).
    """
    tool_logger.info("browser_get_text: selector=%s", selector)
    try:
        page = await _get_page()
        text = await page.inner_text(selector, timeout=10_000)
        return {"status": "ok", "text": text.strip(), "selector": selector}
    except Exception as exc:
        error_logger.exception("Error en browser_get_text")
        return {"status": "error", "message": str(exc)}


async def browser_get_html(selector: str = "html") -> dict:
    """Devuelve el HTML del elemento (por defecto el documento completo)."""
    tool_logger.info("browser_get_html: selector=%s", selector)
    try:
        page = await _get_page()
        html = await page.inner_html(selector, timeout=10_000)
        return {"status": "ok", "html_length": len(html), "html": html}
    except Exception as exc:
        error_logger.exception("Error en browser_get_html")
        return {"status": "error", "message": str(exc)}


async def browser_wait_for(
    selector: str,
    state: str = "visible",
    timeout: int = 15_000,
) -> dict:
    """
    Espera a que el elemento cambie a `state`.

    Args:
        state: "visible" | "hidden" | "attached" | "detached"
        timeout: ms máximos de espera
    """
    tool_logger.info("browser_wait_for: selector=%s state=%s", selector, state)
    try:
        page = await _get_page()
        await page.wait_for_selector(selector, state=state, timeout=timeout)
        return {"status": "ok", "selector": selector, "state": state}
    except Exception as exc:
        error_logger.exception("Error en browser_wait_for")
        return {"status": "error", "message": str(exc)}


async def browser_scroll(
    x: int = 0,
    y: int = 500,
    selector: Optional[str] = None,
) -> dict:
    """
    Hace scroll en la página o dentro de un elemento.

    Args:
        x: desplazamiento horizontal en píxeles
        y: desplazamiento vertical en píxeles (positivo = hacia abajo)
        selector: elemento en el que hacer scroll (None = ventana)
    """
    tool_logger.info("browser_scroll: x=%d y=%d selector=%s", x, y, selector)
    try:
        page = await _get_page()
        if selector:
            await page.eval_on_selector(
                selector,
                f"el => el.scrollBy({x}, {y})",
            )
        else:
            await page.evaluate(f"window.scrollBy({x}, {y})")
        return {"status": "ok", "x": x, "y": y}
    except Exception as exc:
        error_logger.exception("Error en browser_scroll")
        return {"status": "error", "message": str(exc)}


async def browser_evaluate(script: str) -> dict:
    """
    Ejecuta JavaScript arbitrario en el contexto de la página.

    Args:
        script: código JS a ejecutar (debe ser una expresión o función)

    Returns:
        {status, result} donde result es el valor devuelto por el script
    """
    tool_logger.info("browser_evaluate: script_len=%d", len(script))
    try:
        page = await _get_page()
        result = await page.evaluate(script)
        return {"status": "ok", "result": result}
    except Exception as exc:
        error_logger.exception("Error en browser_evaluate")
        return {"status": "error", "message": str(exc)}


async def browser_search(query: str, max_text_chars: int = 3000) -> dict:
    """
    Busca en Google la query dada y devuelve el texto extraído más un screenshot.

    Flujo:
        1. Navega a google.com/search?q=<query>
        2. Espera los resultados (selector h3)
        3. Extrae texto del body (truncado a max_text_chars)
        4. Captura screenshot

    Args:
        query: términos de búsqueda
        max_text_chars: máximo de caracteres de texto a devolver

    Returns:
        {status, query, url, text_preview, image_base64}
    """
    tool_logger.info("browser_search: query=%s", query)

    if not query.strip():
        return {"status": "error", "message": "Query vacía"}

    search_url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)

    nav = await browser_navigate(search_url, wait_until="domcontentloaded")
    if nav.get("status") != "ok":
        return nav

    # Esperar resultados
    wait = await browser_wait_for("h3", state="visible", timeout=10_000)
    if wait.get("status") != "ok":
        tool_logger.warning("browser_search: h3 no apareció, continuando de todas formas")

    text_result = await browser_get_text("body")
    text = text_result.get("text", "")[:max_text_chars]

    screenshot = await browser_screenshot(full_page=False)

    return {
        "status": "ok",
        "query": query,
        "url": search_url,
        "text_preview": text,
        "image_base64": screenshot.get("image_base64"),
    }


async def browser_close() -> dict:
    """Cierra el navegador y libera recursos de Playwright."""
    tool_logger.info("browser_close")
    try:
        await _close_playwright()
        return {"status": "ok", "message": "Navegador cerrado"}
    except Exception as exc:
        error_logger.exception("Error en browser_close")
        return {"status": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

TOOLS = {
    "browser_navigate":   browser_navigate,
    "browser_click":      browser_click,
    "browser_fill":       browser_fill,
    "browser_submit":     browser_submit,
    "browser_screenshot": browser_screenshot,
    "browser_get_text":   browser_get_text,
    "browser_get_html":   browser_get_html,
    "browser_wait_for":   browser_wait_for,
    "browser_scroll":     browser_scroll,
    "browser_evaluate":   browser_evaluate,
    "browser_search":     browser_search,
    "browser_close":      browser_close,
}
