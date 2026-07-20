"""
ROUTES — Endpoints HTTP del API de Alfonso.

¿QUÉ HACE?
Centraliza y expone todos los endpoints del sistema (mensajería chat, navegación de navegador, uso de computadora, calendario nativo, cliente de correo electrónico y sandbox de desarrollo).

¿CUÁNDO LO HACE?
Cuando el servidor FastAPI arranca y se inicializa la aplicación. Maneja cada petición entrante HTTP del cliente.

¿CÓMO LO HACE?
Define un router principal y routers especializados (browser, computer, calendar, mail, dev), asociándolos a sus respectivos esquemas Pydantic y delegando la lógica de negocio a los agentes de core, herramientas y bases de datos.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/main.py: Registra el router raíz.
- app/domain/planner_orchestrator.py: Procesa las consultas en el endpoint /chat.
- app/domain/agents/dev/dev_agent.py: Se comunica con el sandbox de desarrollo.
- app/domain/agents/marcos/marcos_agent.py: Asiste indirectamente en la generación de borradores inteligentes de correo.
- app/adapters/calendar_db.py y app/adapters/mail_db.py: Interactúan con las bases de datos de calendario y correo.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Depends, status
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

# Imports del núcleo
from app.adapters import mail_db
from app.adapters.calendar_db import create_event, delete_event, list_events
from app.adapters.metrics import snapshot
from app.adapters.tool_registry import get_tool, list_tools
from app.domain.agents.dev.dev_agent import dev_agent
from app.utils.logger import app_logger, attach_request_id
from app.utils.timer import Timer
from app.config import settings

# ── API Key Security ────────────────────────────────────────────────────────
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def verify_api_key(api_key: str = Depends(api_key_header)):
    if settings.ALFONSO_API_KEY:
        if not api_key or api_key != settings.ALFONSO_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Key or API Key missing"
            )
    return api_key

# Routers
router = APIRouter()
router_browser = APIRouter(prefix="/browser", tags=["browser"], dependencies=[Depends(verify_api_key)])
router_computer = APIRouter(prefix="/computer", tags=["computer"], dependencies=[Depends(verify_api_key)])
router_calendar = APIRouter(prefix="/calendar", tags=["calendar"], dependencies=[Depends(verify_api_key)])
router_mail = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(verify_api_key)])
router_dev = APIRouter(prefix="/dev", tags=["developer"], dependencies=[Depends(verify_api_key)])
router_security = APIRouter(prefix="/security", tags=["security"], dependencies=[Depends(verify_api_key)])

# Inyectado desde lifespan en main.py
orchestrator: Any = None

# Directorio del sandbox
SANDBOX_DIR = Path("data/dev_sandbox")
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Schemas: Core
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    client_info: Optional[dict] = None


# ---------------------------------------------------------------------------
# Schemas: Calendar
# ---------------------------------------------------------------------------

class EventCreate(BaseModel):
    title: str
    start_time: str
    end_time: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: Optional[str] = None


# ---------------------------------------------------------------------------
# Schemas: Dev Sandbox
# ---------------------------------------------------------------------------

class FilePayload(BaseModel):
    filename: str
    content: str


class CommandPayload(BaseModel):
    command: str


# ---------------------------------------------------------------------------
# Schemas: Browser & Computer Use
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
# Schemas: Mail
# ---------------------------------------------------------------------------

class EmailResponse(BaseModel):
    id: int
    sender: str
    recipient: str
    subject: str
    body: str
    received_at: str
    category: Optional[str]
    importance: str
    read_status: int
    summary: Optional[str]


class SendEmailRequest(BaseModel):
    recipient: str
    subject: str
    body: str


class ReplyEmailRequest(BaseModel):
    body: str
    reply_all: Optional[bool] = False


class ForwardEmailRequest(BaseModel):
    recipient: str
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers: Browser/Computer Use
# ---------------------------------------------------------------------------

def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _tool_response(request_id: str, result: dict, t: Timer) -> dict:
    status = "success" if result.get("status") == "ok" else "error"
    logger = attach_request_id(app_logger, request_id)
    logger.info("RESPUESTA TOOL DIRECTO: %s", result)
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
# Endpoints: Core
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok", "phase": "3"}


@router.get("/tools", dependencies=[Depends(verify_api_key)])
async def tools_list():
    return {"tools": list_tools()}


@router.get("/agents", dependencies=[Depends(verify_api_key)])
async def agents_list():
    return {
        "agents": [],
        "note": "Capa de agentes/EventBus retirada en Fase 4; PlannerOrchestrator es el único pipeline."
    }


@router.get("/metrics", dependencies=[Depends(verify_api_key)])
async def metrics():
    return snapshot()


@router.post("/chat", dependencies=[Depends(verify_api_key)])
async def chat_endpoint(req: ChatRequest, request: Request):
    from app.main import llm

    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    logger = attach_request_id(app_logger, request_id)

    session_id = request.headers.get("X-Session-ID") or req.session_id or request_id

    client_id = None
    if req.client_info:
        from app.adapters.alfonso_bridge import bridge
        if bridge.client_info:
            bridge.client_info.update(req.client_info)
        else:
            bridge.client_info = req.client_info
        client_id = req.client_info.get("client_id")

    logger.info("Solicitud /chat recibida")
    logger.info("SESSION_ID: %s", session_id)
    logger.info("CLIENT_ID: %s", client_id)
    logger.info("USER MESSAGE: %s", req.message)

    with Timer() as t:
        result = await orchestrator.run(
            req.message,
            llm,
            request_id=request_id,
            session_id=session_id,
            client_id=client_id,
        )

    status = result.get("type", "unknown")
    logger.info("Solicitud /chat procesada con estado: %s", status)
    if status == "chat":
        logger.info("RESPUESTA ENVIADA AL USUARIO (CHAT): %s", result.get("response"))
    elif status == "tool":
        logger.info("RESPUESTA ENVIADA AL USUARIO (TOOL %s): %s", result.get("tool"), result.get("result"))
    elif status == "multi_tool":
        logger.info("RESPUESTA ENVIADA AL USUARIO (MULTI_TOOL): %s", result.get("results"))
    else:
        logger.info("RESPUESTA ENVIADA AL USUARIO: %s", result)
    logger.info("LATENCY: %.2fs", t.elapsed)

    return {"request_id": request_id, "result": result}


@router.get("/memory/{session_id}")
async def get_memory(session_id: str):
    from app.adapters.memory import memory
    history = memory.get_history(session_id)
    return {"session_id": session_id, "messages": history, "count": len(history)}


@router.delete("/memory/{session_id}")
async def clear_memory(session_id: str):
    from app.adapters.memory import memory
    memory.clear(session_id)
    return {"status": "ok", "session_id": session_id, "message": "Historial borrado"}


@router.get("/memory")
async def list_sessions():
    from app.adapters.memory import memory
    sessions = memory.list_sessions()
    return {"sessions": sessions, "count": len(sessions)}


# ---------------------------------------------------------------------------
# Endpoints: Calendar
# ---------------------------------------------------------------------------

@router_calendar.get("/events")
async def get_events(
    start_date: Optional[str] = Query(None, description="Fecha de inicio (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Fecha de fin (YYYY-MM-DD)"),
):
    try:
        events = list_events(start_date=start_date, end_date=end_date)
        return {"status": "ok", "events": events, "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo eventos: {str(e)}")


@router_calendar.post("/events")
async def post_event(event: EventCreate):
    try:
        event_id = create_event(
            title=event.title,
            start_time=event.start_time,
            end_time=event.end_time,
            description=event.description,
            location=event.location,
            attendees=event.attendees,
        )
        
        fact = f"Cita agendada: '{event.title}' el {event.start_time}"
        if event.location:
            fact += f" en {event.location}"
        if event.attendees:
            fact += f" con {event.attendees}"
            
        from app.adapters.memory import vector_memory
        vector_memory.add_fact("global", fact)
        
        from app.adapters.alfonso_bridge import bridge
        if bridge.has_clients():
            await bridge.send_command("calendar.sync", {"action": "create", "id": event_id})
            
        return {"status": "ok", "event_id": event_id, "message": "Evento creado exitosamente."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creando evento: {str(e)}")


@router_calendar.delete("/events/{event_id}")
async def remove_event(event_id: int):
    try:
        success = delete_event(event_id)
        if not success:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
            
        from app.adapters.alfonso_bridge import bridge
        if bridge.has_clients():
            await bridge.send_command("calendar.sync", {"action": "delete", "id": event_id})
            
        return {"status": "ok", "message": f"Evento con ID {event_id} eliminado correctamente."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error eliminando evento: {str(e)}")


# ---------------------------------------------------------------------------
# Endpoints: Dev Sandbox
# ---------------------------------------------------------------------------

@router_dev.get("/files")
def list_files():
    """Lista todos los archivos presentes en el sandbox de desarrollo."""
    files = []
    for entry in os.scandir(SANDBOX_DIR):
        if entry.is_file():
            files.append({
                "name": entry.name,
                "size": entry.stat().st_size,
                "mtime": entry.stat().st_mtime
            })
    return sorted(files, key=lambda x: x["name"])


@router_dev.get("/files/{filename}")
def get_file_content(filename: str):
    """Obtiene el contenido de un archivo específico del sandbox."""
    file_path = SANDBOX_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    try:
        content = file_path.read_text(encoding="utf-8")
        return {"filename": filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_dev.post("/files")
def save_file(payload: FilePayload):
    """Guarda o actualiza un archivo en el sandbox."""
    try:
        dev_agent.write_to_sandbox(payload.filename, payload.content)
        return {"status": "ok", "message": f"Archivo '{payload.filename}' guardado correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_dev.delete("/files/{filename}")
def delete_file(filename: str):
    """Elimina un archivo del sandbox."""
    file_path = SANDBOX_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    try:
        file_path.unlink()
        return {"status": "ok", "message": f"Archivo '{filename}' eliminado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_dev.post("/execute")
def execute_command(payload: CommandPayload):
    """Ejecuta un comando dentro de la carpeta del sandbox."""
    app_logger.info("Ejecutando en sandbox: %s", payload.command)
    res = dev_agent.execute_command_in_sandbox(payload.command)
    return res


# ---------------------------------------------------------------------------
# Endpoints: Browser
# ---------------------------------------------------------------------------

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
# Endpoints: Computer Use
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Endpoints: Mail
# ---------------------------------------------------------------------------

@router_mail.get("/emails", response_model=List[EmailResponse])
async def get_emails(
    category: Optional[str] = None,
    importance: Optional[str] = None,
    read_status: Optional[int] = None,
    limit: int = 50,
):
    """Obtiene la lista de correos con filtros opcionales."""
    try:
        from app.tools.server.mail_tools import sync_emails_to_calendar
        try:
            await sync_emails_to_calendar()
        except Exception:
            pass

        emails = mail_db.list_emails(
            category=category,
            importance=importance,
            read_status=read_status,
            limit=limit
        )
        return emails
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_mail.get("/emails/{email_id}", response_model=EmailResponse)
async def get_email_detail(email_id: int):
    """Obtiene el contenido completo de un correo por su ID."""
    email = mail_db.get_email(email_id)
    if not email:
        raise HTTPException(status_code=404, detail=f"No se encontró ningún correo con ID {email_id}.")
    return email


@router_mail.post("/emails/{email_id}/read")
async def mark_email_as_read(email_id: int):
    """Marca un correo electrónico como leído."""
    success = mail_db.update_email(email_id, read_status=1)
    if not success:
        email = mail_db.get_email(email_id)
        if not email:
            raise HTTPException(status_code=404, detail=f"No se encontró ningún correo con ID {email_id}.")
        return {"status": "ok", "message": "El correo ya estaba marcado como leído."}
    return {"status": "ok", "message": f"Correo con ID {email_id} marcado como leído."}


@router_mail.post("/emails/seed")
async def seed_emails():
    """Inyecta correos de prueba simulados en la base de datos."""
    try:
        inserted = mail_db.seed_mock_emails()
        from app.tools.server.mail_tools import sync_emails_to_calendar
        try:
            await sync_emails_to_calendar()
        except Exception:
            pass
        return {
            "status": "ok",
            "message": f"Inyección completada. Se han insertado {inserted} correos de prueba.",
            "inserted_count": inserted
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router_mail.post("/send")
async def send_new_email(req: SendEmailRequest):
    """Envía un nuevo correo y lo guarda."""
    from app.tools.server.mail_tools import mail_send_email
    res = await mail_send_email(req.recipient, req.subject, req.body)
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return res


@router_mail.delete("/emails/{email_id}")
async def delete_existing_email(email_id: int):
    """Elimina un correo por su ID."""
    from app.tools.server.mail_tools import mail_delete_email
    res = await mail_delete_email(email_id)
    if res["status"] == "error":
        raise HTTPException(status_code=404, detail=res["message"])
    return res


@router_mail.post("/emails/{email_id}/reply")
async def reply_existing_email(email_id: int, req: ReplyEmailRequest):
    """Envía una respuesta a un correo por su ID."""
    from app.tools.server.mail_tools import mail_reply_email
    res = await mail_reply_email(email_id, req.body, req.reply_all)
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return res


@router_mail.post("/emails/{email_id}/forward")
async def forward_existing_email(email_id: int, req: ForwardEmailRequest):
    """Reenvía un correo por su ID."""
    from app.tools.server.mail_tools import mail_forward_email
    res = await mail_forward_email(email_id, req.recipient, req.comment)
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return res


@router_mail.get("/emails/{email_id}/draft")
async def get_smart_reply_draft(email_id: int):
    """Genera un borrador de respuesta inteligente (asistente experto si es legal)."""
    from app.tools.server.mail_tools import mail_generate_draft
    res = await mail_generate_draft(email_id)
    if res["status"] == "error":
        raise HTTPException(status_code=500, detail=res["message"])
    return res


# ── Security Endpoints ──────────────────────────────────────────────────────

@router_security.get("/status")
async def get_security_status():
    from app.domain.agents.security.security_agent import security_agent
    return {
        "status": "success",
        "active_alerts_count": len([a for a in security_agent.alerts if a["level"] in ["WARNING", "HIGH"]]),
        "total_alerts_count": len(security_agent.alerts),
        "blocked_ips_count": len(security_agent.blocked_ips),
        "last_scan_time": security_agent.last_scan_time
    }

@router_security.get("/alerts")
async def get_security_alerts():
    from app.domain.agents.security.security_agent import security_agent
    return {
        "status": "success",
        "alerts": security_agent.alerts
    }

@router_security.post("/scan")
async def trigger_security_scan():
    from app.domain.agents.security.security_agent import security_agent
    await security_agent.scan_system()
    return {
        "status": "success",
        "message": "Manual security scan completed successfully.",
        "active_alerts_count": len([a for a in security_agent.alerts if a["level"] in ["WARNING", "HIGH"]]),
        "total_alerts_count": len(security_agent.alerts)
    }


# Incluimos los sub-routers en el router principal
router.include_router(router_browser)
router.include_router(router_computer)
router.include_router(router_calendar)
router.include_router(router_mail)
router.include_router(router_dev)
router.include_router(router_security)