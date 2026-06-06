"""
test_fase3.py — Tests de integración para Fase 3

Ejecutar:
    python test_fase3.py                     # todos los tests
    python test_fase3.py --only intent       # solo el IntentRouter
    python test_fase3.py --only datetime     # solo la tool de fecha
    python test_fase3.py --only browser      # solo el navegador (requiere Playwright)
    python test_fase3.py --only computer     # solo Computer Use (requiere display)
    python test_fase3.py --only api          # contra la API en vivo

El script NO requiere el servidor corriendo salvo --only api.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Colores para output
# ─────────────────────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"
SKIP = f"{YELLOW}SKIP{RESET}"

results: list[tuple[str, str, str]] = []  # (suite, name, status)


def ok(suite: str, name: str, detail: str = "") -> None:
    results.append((suite, name, "PASS"))
    print(f"  {PASS}  {name}" + (f"  ({detail})" if detail else ""))


def fail(suite: str, name: str, detail: str = "") -> None:
    results.append((suite, name, "FAIL"))
    print(f"  {FAIL}  {name}" + (f"  → {detail}" if detail else ""))


def skip(suite: str, name: str, reason: str = "") -> None:
    results.append((suite, name, "SKIP"))
    print(f"  {SKIP}  {name}" + (f"  ({reason})" if reason else ""))


# ─────────────────────────────────────────────────────────────────────────────
# Suite 1: IntentRouter
# ─────────────────────────────────────────────────────────────────────────────

def test_intent_router() -> None:
    suite = "IntentRouter"
    print(f"\n{'─'*50}")
    print(f" {suite}")
    print(f"{'─'*50}")

    try:
        from app.core.intent_router import IntentRouter
        router = IntentRouter()
    except ImportError as e:
        skip(suite, "import", str(e))
        return

    cases = [
        # (mensaje, intent_esperado, descripción)
        ("hola, buenos días",                        "chat",  "saludo puro"),
        ("qué hora es",                              "tool",  "hora → datetime_tool"),
        ("que dia es hoy",                           "tool",  "fecha → datetime_tool"),
        ("buenos dias Alfonso que hora es",          "tool",  "saludo + hora"),
        ("crea un archivo llamado notas.txt",        "tool",  "crear archivo con nombre"),
        ("crea un archivo de texto",                 "tool",  "crear archivo genérico"),
        ("elimina el archivo notas.txt",             "tool",  "eliminar archivo"),
        ("abre el explorador de archivos",           "tool",  "explorador"),
        ("abre exploraddor de archivos",             "tool",  "explorador con typo"),
        ("buenos dias, abre exploraddor de archivos","tool",  "saludo + explorador"),
        ("navega a https://github.com",              "tool",  "navegar URL"),
        ("busca en internet noticias de hoy",        "tool",  "búsqueda web"),
        ("abre firefox",                             "tool",  "abrir app"),
        ("cuánta RAM tiene el sistema",              "tool",  "system info"),
        ("explica cómo funciona Python",             "chat",  "pregunta teórica"),
    ]

    for message, expected_intent, desc in cases:
        detail = router.detect_with_detail(message)
        got = detail["intent"]
        if got == expected_intent:
            ok(suite, desc, f"score={detail['score']}")
        else:
            fail(suite, desc, f"esperado={expected_intent} obtenido={got} score={detail['score']} reglas={detail['fired_rules']}")


# ─────────────────────────────────────────────────────────────────────────────
# Suite 2: Tool datetime
# ─────────────────────────────────────────────────────────────────────────────

async def test_datetime_tool() -> None:
    suite = "DatetimeTool"
    print(f"\n{'─'*50}")
    print(f" {suite}")
    print(f"{'─'*50}")

    try:
        from app.tools.system_tools import get_current_datetime
    except ImportError as e:
        skip(suite, "import", str(e))
        return

    result = await get_current_datetime()
    suite_name = suite

    if result.get("status") == "ok":
        ok(suite_name, "get_current_datetime devuelve status ok")
    else:
        fail(suite_name, "get_current_datetime devuelve status ok", str(result))

    required_keys = {"iso", "date", "time", "day_of_week", "day", "month", "year", "human"}
    missing = required_keys - set(result.keys())
    if not missing:
        ok(suite_name, "todos los campos presentes")
    else:
        fail(suite_name, "todos los campos presentes", f"faltan: {missing}")

    if result.get("day_of_week") in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]:
        ok(suite_name, f"day_of_week válido: {result['day_of_week']}")
    else:
        fail(suite_name, "day_of_week válido", f"obtenido: {result.get('day_of_week')}")

    print(f"       → Fecha actual: {result.get('human', '?')}")


# ─────────────────────────────────────────────────────────────────────────────
# Suite 3: Filesystem tools
# ─────────────────────────────────────────────────────────────────────────────

async def test_filesystem() -> None:
    suite = "Filesystem"
    print(f"\n{'─'*50}")
    print(f" {suite}")
    print(f"{'─'*50}")

    try:
        from app.tools.filesystem_tools import (
            create_file, read_file, append_file, list_directory, delete_file
        )
    except ImportError as e:
        skip(suite, "import", str(e))
        return

    test_path = "/tmp/alfonso_test_fase3.txt"

    # create
    r = await create_file(test_path, "linea 1\n")
    if r.get("status") == "ok":
        ok(suite, "create_file")
    else:
        fail(suite, "create_file", str(r))
        return

    # read
    r = await read_file(test_path)
    if r.get("status") == "ok" and "linea 1" in r.get("content", ""):
        ok(suite, "read_file")
    else:
        fail(suite, "read_file", str(r))

    # append
    r = await append_file(test_path, "linea 2\n")
    if r.get("status") == "ok":
        ok(suite, "append_file")
    else:
        fail(suite, "append_file", str(r))

    # read after append
    r = await read_file(test_path)
    if "linea 2" in r.get("content", ""):
        ok(suite, "append persistió en read")
    else:
        fail(suite, "append persistió en read", str(r))

    # list
    r = await list_directory("/tmp")
    if r.get("status") == "ok":
        ok(suite, "list_directory", f"{len(r.get('entries', []))} entries")
    else:
        fail(suite, "list_directory", str(r))

    # delete
    r = await delete_file(test_path)
    if r.get("status") == "ok":
        ok(suite, "delete_file")
    else:
        fail(suite, "delete_file", str(r))

    # read after delete
    r = await read_file(test_path)
    if r.get("status") == "error":
        ok(suite, "read retorna error tras delete")
    else:
        fail(suite, "read retorna error tras delete", str(r))


# ─────────────────────────────────────────────────────────────────────────────
# Suite 4: Browser (requiere Playwright)
# ─────────────────────────────────────────────────────────────────────────────

async def test_browser() -> None:
    suite = "Browser"
    print(f"\n{'─'*50}")
    print(f" {suite}")
    print(f"{'─'*50}")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        skip(suite, "playwright import", "instala: pip install playwright && playwright install chromium")
        return

    try:
        from app.tools.browser_tools import (
            browser_navigate, browser_get_text, browser_screenshot,
            browser_search, browser_close,
        )
    except ImportError as e:
        skip(suite, "browser_tools import", str(e))
        return

    # navigate
    r = await browser_navigate("https://example.com")
    if r.get("status") == "ok":
        ok(suite, "browser_navigate example.com", f"title={r.get('title', '?')}")
    else:
        fail(suite, "browser_navigate example.com", str(r))
        await browser_close()
        return

    # get_text
    r = await browser_get_text("h1")
    if r.get("status") == "ok":
        ok(suite, "browser_get_text h1", r.get("text", "")[:40])
    else:
        fail(suite, "browser_get_text h1", str(r))

    # screenshot
    r = await browser_screenshot()
    if r.get("status") == "ok" and r.get("image_base64"):
        b64_len = len(r["image_base64"])
        ok(suite, "browser_screenshot", f"base64 len={b64_len}")
    else:
        fail(suite, "browser_screenshot", str(r))

    # search
    r = await browser_search("python asyncio tutorial", max_text_chars=500)
    if r.get("status") == "ok" and r.get("text_preview"):
        ok(suite, "browser_search", f"text_len={len(r['text_preview'])}")
    else:
        fail(suite, "browser_search", str(r))

    # close
    r = await browser_close()
    if r.get("status") == "ok":
        ok(suite, "browser_close")
    else:
        fail(suite, "browser_close", str(r))


# ─────────────────────────────────────────────────────────────────────────────
# Suite 5: Computer Use (requiere display)
# ─────────────────────────────────────────────────────────────────────────────

async def test_computer() -> None:
    suite = "ComputerUse"
    print(f"\n{'─'*50}")
    print(f" {suite}")
    print(f"{'─'*50}")

    try:
        import pyautogui  # noqa
    except ImportError:
        skip(suite, "pyautogui import", "instala: pip install pyautogui")
        return

    try:
        from app.tools.computer_use_tools import screenshot, window_list
    except ImportError as e:
        skip(suite, "computer_use_tools import", str(e))
        return

    # screenshot
    try:
        r = await screenshot()
        if r.get("status") == "ok" and r.get("image_base64"):
            ok(suite, "screenshot pantalla completa", f"w={r.get('width')} h={r.get('height')}")
        else:
            fail(suite, "screenshot", str(r))
    except Exception as e:
        skip(suite, "screenshot", f"sin display: {e}")

    # window_list
    try:
        r = await window_list()
        if r.get("status") == "ok":
            ok(suite, "window_list", f"{len(r.get('windows', []))} ventanas")
        else:
            fail(suite, "window_list", str(r))
    except Exception as e:
        skip(suite, "window_list", f"wmctrl no disponible: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Suite 6: API en vivo
# ─────────────────────────────────────────────────────────────────────────────

async def test_api(base_url: str = "http://localhost:8000") -> None:
    suite = "API"
    print(f"\n{'─'*50}")
    print(f" {suite}  ({base_url})")
    print(f"{'─'*50}")

    try:
        import httpx
    except ImportError:
        skip(suite, "httpx import", "instala: pip install httpx")
        return

    async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:

        # health
        try:
            r = await client.get("/health")
            if r.status_code == 200 and r.json().get("status") == "ok":
                ok(suite, "GET /health", f"phase={r.json().get('phase', '?')}")
            else:
                fail(suite, "GET /health", f"status={r.status_code}")
        except Exception as e:
            fail(suite, "GET /health", f"servidor no disponible: {e}")
            return

        # tools list
        r = await client.get("/tools")
        tools_list = r.json().get("tools", [])
        for expected_tool in ["get_current_datetime", "browser_navigate", "browser_search", "delete_file"]:
            if expected_tool in tools_list:
                ok(suite, f"tool registrada: {expected_tool}")
            else:
                fail(suite, f"tool registrada: {expected_tool}", "no aparece en /tools")

        # agents list
        r = await client.get("/agents")
        agent_names = [a["name"] for a in r.json().get("agents", [])]
        for expected in ["filesystem", "system", "browser", "computer", "chat"]:
            if expected in agent_names:
                ok(suite, f"agente activo: {expected}")
            else:
                fail(suite, f"agente activo: {expected}", f"solo hay: {agent_names}")

        # chat datetime
        r = await client.post("/chat", json={"message": "buenos dias Alfonso que hora es"})
        if r.status_code == 200:
            body = r.json()
            result_type = body.get("result", {}).get("type")
            if result_type == "tool":
                ok(suite, "POST /chat datetime → tipo tool")
            else:
                fail(suite, "POST /chat datetime → tipo tool", f"type={result_type}")
        else:
            fail(suite, "POST /chat datetime", f"status={r.status_code}")

        # browser navigate
        r = await client.post("/browser/navigate", json={"url": "https://example.com"})
        if r.status_code == 200 and r.json().get("status") == "success":
            ok(suite, "POST /browser/navigate")
        else:
            fail(suite, "POST /browser/navigate", f"status={r.status_code} body={r.text[:100]}")

        # browser search
        r = await client.post("/browser/search", json={"query": "python asyncio"}, timeout=30.0)
        if r.status_code == 200:
            ok(suite, "POST /browser/search")
        else:
            fail(suite, "POST /browser/search", f"status={r.status_code}")

        # browser screenshot
        r = await client.post("/browser/screenshot", json={})
        if r.status_code == 200:
            ok(suite, "POST /browser/screenshot")
        else:
            fail(suite, "POST /browser/screenshot", f"status={r.status_code}")

        # browser close
        r = await client.delete("/browser/close")
        if r.status_code == 200:
            ok(suite, "DELETE /browser/close")
        else:
            fail(suite, "DELETE /browser/close", f"status={r.status_code}")

        # computer windows
        r = await client.get("/computer/windows")
        if r.status_code == 200:
            ok(suite, "GET /computer/windows")
        else:
            fail(suite, "GET /computer/windows", f"status={r.status_code}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def run(only: str | None, api_url: str) -> None:
    suites = {
        "intent":   lambda: asyncio.coroutine(test_intent_router)() if asyncio.iscoroutinefunction(test_intent_router) else test_intent_router(),
        "datetime": test_datetime_tool,
        "filesystem": test_filesystem,
        "browser":  test_browser,
        "computer": test_computer,
        "api":      lambda: test_api(api_url),
    }

    # test_intent_router es síncrono
    sync_suites = {"intent"}

    to_run = [only] if only else list(suites.keys())

    for name in to_run:
        if name not in suites:
            print(f"Suite desconocida: {name}. Opciones: {list(suites.keys())}")
            continue
        if name in sync_suites:
            test_intent_router()
        else:
            await suites[name]()

    # Resumen
    total = len(results)
    passed = sum(1 for _, _, s in results if s == "PASS")
    failed = sum(1 for _, _, s in results if s == "FAIL")
    skipped = sum(1 for _, _, s in results if s == "SKIP")

    print(f"\n{'═'*50}")
    print(f" RESUMEN: {passed}/{total} PASS  |  {failed} FAIL  |  {skipped} SKIP")
    print(f"{'═'*50}\n")

    if failed > 0:
        print(f"{RED}Tests fallidos:{RESET}")
        for suite, name, status in results:
            if status == "FAIL":
                print(f"  ✗ [{suite}] {name}")
        print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tests de integración Fase 3")
    parser.add_argument("--only", choices=["intent", "datetime", "filesystem", "browser", "computer", "api"])
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    asyncio.run(run(args.only, args.api_url))
