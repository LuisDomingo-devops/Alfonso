"""
BrowserAgent — Fase 3 (implementación real con Playwright)

Event types:
    browser.navigate        → abre una URL
    browser.click           → click en selector
    browser.fill            → rellena un campo
    browser.submit          → envía un formulario
    browser.screenshot      → captura la página
    browser.get_text        → extrae texto de la página
    browser.get_html        → devuelve el HTML
    browser.wait_for        → espera un selector
    browser.scroll          → hace scroll
    browser.evaluate        → ejecuta JavaScript
    browser.search          → busca en Google
    browser.close           → cierra el navegador
    browser.open            → alias de navigate (compat. Fase 2)
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent

_EVENT_MAP: dict[str, tuple[str, list[str]]] = {
    "browser.navigate":   ("browser_navigate",   ["url", "wait_until"]),
    "browser.click":      ("browser_click",      ["selector", "timeout", "button", "click_count"]),
    "browser.fill":       ("browser_fill",       ["selector", "value", "timeout"]),
    "browser.submit":     ("browser_submit",     ["selector", "timeout"]),
    "browser.screenshot": ("browser_screenshot", ["full_page", "save_path"]),
    "browser.get_text":   ("browser_get_text",   ["selector"]),
    "browser.get_html":   ("browser_get_html",   ["selector"]),
    "browser.wait_for":   ("browser_wait_for",   ["selector", "state", "timeout"]),
    "browser.scroll":     ("browser_scroll",     ["x", "y", "selector"]),
    "browser.evaluate":   ("browser_evaluate",   ["script"]),
    "browser.close":      ("browser_close",      []),
    "browser.search":     ("_search",            ["query"]),
    "browser.open":       ("browser_navigate",   ["url"]),
}


class BrowserAgent(BaseAgent):

    name = "browser"
    event_types = list(_EVENT_MAP.keys())

    async def handle(self, event_type: str, data: dict) -> AgentResult:
        mapping = _EVENT_MAP.get(event_type)
        if mapping is None:
            return AgentResult(
                agent=self.name,
                event_type=event_type,
                status="skipped",
                error=f"Evento no soportado: {event_type}",
            )

        tool_name, arg_keys = mapping
        raw_args = data.get("args", {})

        if tool_name == "_search":
            result = await self._do_search(raw_args.get("query", ""))
        else:
            kwargs = {k: raw_args[k] for k in arg_keys if k in raw_args}
            result = await self.run_tool(tool_name, **kwargs)

        ok = result.get("status") == "ok"
        return AgentResult(
            agent=self.name,
            event_type=event_type,
            status="success" if ok else "error",
            payload=result,
            error=result.get("message") if not ok else None,
        )

    async def _do_search(self, query: str) -> dict:
        if not query.strip():
            return {"status": "error", "message": "Búsqueda vacía"}

        import urllib.parse
        search_url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)

        nav = await self.run_tool("browser_navigate", url=search_url, wait_until="domcontentloaded")
        if nav.get("status") != "ok":
            return nav

        await self.run_tool("browser_wait_for", selector="h3", state="visible", timeout=10_000)
        text_result = await self.run_tool("browser_get_text", selector="body")
        text = text_result.get("text", "")[:3000]
        screenshot = await self.run_tool("browser_screenshot", full_page=False)

        return {
            "status": "ok",
            "query": query,
            "url": search_url,
            "text_preview": text,
            "image_base64": screenshot.get("image_base64"),
        }