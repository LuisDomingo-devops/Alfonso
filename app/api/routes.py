"""
routes_fase3.py — Endpoints de Fase 3: Browser y Computer Use

Añadir estos routers a app/main.py:
    from app.api.routes_fase3 import router_browser, router_computer
    app.include_router(router_browser)
    app.include_router(router_computer)
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.tool_registry import get_tool
from app.core.metrics import increment_http_errors
from app.utils.logger import app_logger, attach_request_id
from app.utils.timer import Timer


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BrowserNavigateRequest(BaseModel):
    url: str
    wait_until: str = "domcontentloaded"


class BrowserSearchRequest(BaseModel):
    query: str
    max_text_chars: int = Field(default=3000, ge=100, le=10000)


class BrowserClickRequest(BaseModel):
    selector: str
    button: str = "left"
    click_count: int = Field(default=1, ge=1, le=3)


class BrowserFillRequest(BaseModel):
    selector: str
    value: str


class BrowserScrollRequest(BaseModel):
    x: int = 0
    y: int = Field(default=500)
    selector: Optional[str] = None


class BrowserEvaluateRequest(BaseModel):
    script: str


class BrowserScreenshotRequest(BaseModel):
    full_page: bool = False
    save_path: Optional[str] = None


class ComputerMouseMoveRequest(BaseModel):
    x: int
    y: int
    duration: float = Field(default=0.25, ge=0.0, le=5.0)


class ComputerMouseClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"
    clicks: int = Field(default=1, ge=1, le=3)


class ComputerMouseDragRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    duration: float = Field(default=0.5, ge=0.0, le=5.0)
    button: str = "left"


class ComputerKeyboardTypeRequest(BaseModel):
    text: str
    interval: float = Field(default=0.03, ge=0.0, le=1.0)


class ComputerKeyboardHotkeyRequest(BaseModel):
    keys: list[str] = Field(description="Lista de teclas, e.g. ['ctrl', 'c']")


class ComputerOCRScreenshotRequest(BaseModel):
    region: Optional[list[int]] = Field(
        default=None,
        description="[x, y, width, height] o null para pantalla completa"
    )
    lang: str = "spa+eng"


class ComputerOCRImageRequest(BaseModel):
    path: str
    lang: str = "spa+eng"


class ComputerFindOnScreenRequest(BaseModel):
    template_path: str
    threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    region: Optional[list[int]] = None


class ComputerWindowFocusRequest(BaseModel):
    title: str


class ComputerWindowCloseRequest(BaseModel):
    title: str


class ComputerScreenshotRequest(BaseModel):
    region: Optional[list[int]] = None
    save_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _tool_response(request_id: str, result: dict, t: Timer) -> dict:
    status = "success" if result.get("status") == "ok" else "error"
    return {
        "status": status,
        "request_id": request_id,
        "result": result,
        "latency_seconds": t.elapsed,
    }


async def _call_tool(tool_name: str, request_id: str, **kwargs) -> dict:
    tool = get_tool(tool_name, request_id=request_id)
    if not tool:
        return {"status": "error", "message": f"Tool no disponible: {tool_name}"}
    return await tool(**kwargs)


# ---------------------------------------------------------------------------
# Router: Browser
# ---------------------------------------------------------------------------

router_browser = APIRouter(prefix="/browser", tags=["browser"])


@router_browser.post("/navigate")
async def browser_navigate_endpoint(req: BrowserNavigateRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_navigate", rid, url=req.url, wait_until=req.wait_until)
    return _tool_response(rid, result, t)


@router_browser.post("/search")
async def browser_search_endpoint(req: BrowserSearchRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_search", rid, query=req.query, max_text_chars=req.max_text_chars)
    return _tool_response(rid, result, t)


@router_browser.post("/click")
async def browser_click_endpoint(req: BrowserClickRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool(
            "browser_click", rid,
            selector=req.selector,
            button=req.button,
            click_count=req.click_count,
        )
    return _tool_response(rid, result, t)


@router_browser.post("/fill")
async def browser_fill_endpoint(req: BrowserFillRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_fill", rid, selector=req.selector, value=req.value)
    return _tool_response(rid, result, t)


@router_browser.post("/submit")
async def browser_submit_endpoint(request: Request, selector: str):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_submit", rid, selector=selector)
    return _tool_response(rid, result, t)


@router_browser.post("/scroll")
async def browser_scroll_endpoint(req: BrowserScrollRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_scroll", rid, x=req.x, y=req.y, selector=req.selector)
    return _tool_response(rid, result, t)


@router_browser.post("/evaluate")
async def browser_evaluate_endpoint(req: BrowserEvaluateRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_evaluate", rid, script=req.script)
    return _tool_response(rid, result, t)


@router_browser.post("/screenshot")
async def browser_screenshot_endpoint(req: BrowserScreenshotRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool(
            "browser_screenshot", rid,
            full_page=req.full_page,
            save_path=req.save_path,
        )
    return _tool_response(rid, result, t)


@router_browser.get("/text")
async def browser_get_text_endpoint(request: Request, selector: str = "body"):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_get_text", rid, selector=selector)
    return _tool_response(rid, result, t)


@router_browser.delete("/close")
async def browser_close_endpoint(request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("browser_close", rid)
    return _tool_response(rid, result, t)


# ---------------------------------------------------------------------------
# Router: Computer Use
# ---------------------------------------------------------------------------

router_computer = APIRouter(prefix="/computer", tags=["computer"])


@router_computer.post("/screenshot")
async def computer_screenshot_endpoint(req: ComputerScreenshotRequest, request: Request):
    rid = _request_id(request)
    region = tuple(req.region) if req.region and len(req.region) == 4 else None
    with Timer() as t:
        result = await _call_tool("screenshot", rid, region=region, save_path=req.save_path)
    return _tool_response(rid, result, t)


@router_computer.post("/mouse/move")
async def mouse_move_endpoint(req: ComputerMouseMoveRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("mouse_move", rid, x=req.x, y=req.y, duration=req.duration)
    return _tool_response(rid, result, t)


@router_computer.post("/mouse/click")
async def mouse_click_endpoint(req: ComputerMouseClickRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool(
            "mouse_click", rid,
            x=req.x, y=req.y,
            button=req.button,
            clicks=req.clicks,
        )
    return _tool_response(rid, result, t)


@router_computer.post("/mouse/drag")
async def mouse_drag_endpoint(req: ComputerMouseDragRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool(
            "mouse_drag", rid,
            x1=req.x1, y1=req.y1,
            x2=req.x2, y2=req.y2,
            duration=req.duration,
            button=req.button,
        )
    return _tool_response(rid, result, t)


@router_computer.post("/keyboard/type")
async def keyboard_type_endpoint(req: ComputerKeyboardTypeRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("keyboard_type", rid, text=req.text, interval=req.interval)
    return _tool_response(rid, result, t)


@router_computer.post("/keyboard/hotkey")
async def keyboard_hotkey_endpoint(req: ComputerKeyboardHotkeyRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        tool = get_tool("keyboard_hotkey", request_id=rid)
        if not tool:
            result = {"status": "error", "message": "Tool no disponible: keyboard_hotkey"}
        else:
            result = await tool(*req.keys)
    return _tool_response(rid, result, t)


@router_computer.post("/ocr/screenshot")
async def ocr_screenshot_endpoint(req: ComputerOCRScreenshotRequest, request: Request):
    rid = _request_id(request)
    region = tuple(req.region) if req.region and len(req.region) == 4 else None
    with Timer() as t:
        result = await _call_tool("ocr_screenshot", rid, region=region, lang=req.lang)
    return _tool_response(rid, result, t)


@router_computer.post("/ocr/image")
async def ocr_image_endpoint(req: ComputerOCRImageRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("ocr_image", rid, path=req.path, lang=req.lang)
    return _tool_response(rid, result, t)


@router_computer.post("/find")
async def find_on_screen_endpoint(req: ComputerFindOnScreenRequest, request: Request):
    rid = _request_id(request)
    region = tuple(req.region) if req.region and len(req.region) == 4 else None
    with Timer() as t:
        result = await _call_tool(
            "find_on_screen", rid,
            template_path=req.template_path,
            threshold=req.threshold,
            region=region,
        )
    return _tool_response(rid, result, t)


@router_computer.get("/windows")
async def window_list_endpoint(request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("window_list", rid)
    return _tool_response(rid, result, t)


@router_computer.post("/windows/focus")
async def window_focus_endpoint(req: ComputerWindowFocusRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("window_focus", rid, title=req.title)
    return _tool_response(rid, result, t)


@router_computer.post("/windows/close")
async def window_close_endpoint(req: ComputerWindowCloseRequest, request: Request):
    rid = _request_id(request)
    with Timer() as t:
        result = await _call_tool("window_close", rid, title=req.title)
    return _tool_response(rid, result, t)
