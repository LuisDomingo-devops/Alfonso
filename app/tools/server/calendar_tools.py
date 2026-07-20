"""
CALENDAR TOOLS — Herramientas para la gestión de citas de Alfonso.

¿QUÉ HACE?
Expone las funciones CRUD de base de datos de calendario para que el LLM las invoque.

¿CUÁNDO LO HACE?
Durante la ejecución del planificador para buscar, agendar o borrar eventos.

¿CÓMO LO HACE?
Mediante llamadas directas a las funciones asíncronas y síncronas de app/adapters/calendar_db.py.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/adapters/tool_registry.py (registra estas herramientas)
- app/adapters/calendar_db.py (contiene las operaciones SQLite CRUD reales)
"""

from typing import Optional
from app.adapters.calendar_db import create_event, list_events, delete_event, update_event
from app.adapters.memory import vector_memory
from app.adapters.alfonso_bridge import bridge
from app.domain.actions import Action
from app.utils.logger import tool_logger


async def calendar_create_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[str] = None,
    _session_id: str = "global",
) -> dict:
    """
    Registra una nueva cita o evento en el calendario.
    - title: Título del evento (ej. "Reunión de presupuesto")
    - start_time: Fecha y hora de inicio (Formato YYYY-MM-DD HH:MM)
    - end_time: Fecha y hora de fin (opcional, Formato YYYY-MM-DD HH:MM)
    - description: Nota o descripción detallada (opcional)
    - location: Lugar de la cita (opcional)
    - attendees: Nombres o correos de los asistentes separados por comas (opcional)
    """
    try:
        if isinstance(attendees, list):
            attendees = ", ".join([str(a) for a in attendees]) if attendees else None
            
        event_id = create_event(
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            attendees=attendees
        )
        
        # Guardar en memoria semántica para que Alfonso pueda responder preguntas sobre la cita
        fact = f"Cita agendada: '{title}' el {start_time}"
        if location:
            fact += f" en {location}"
        if attendees:
            fact += f" con {attendees}"
        if description:
            fact += f" (Detalle: {description})"
            
        vector_memory.add_fact(_session_id, fact)
        tool_logger.info(f"Cita creada con ID {event_id} y añadida a ChromaDB.")
        
        # Intentar notificar al cliente PyQt para refrescar si está abierto
        if bridge.has_clients():
            await bridge.send_command("calendar.sync", {"action": "create", "id": event_id})
            
        return {
            "status": "ok",
            "message": f"Cita registrada exitosamente con ID {event_id}.",
            "event_id": event_id
        }
    except Exception as e:
        tool_logger.exception("Error al crear cita en el calendario")
        return {"status": "error", "message": f"Error al crear la cita: {str(e)}"}


async def calendar_list_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """
    Lista las citas agendadas en un rango de fechas.
    - start_date: Fecha inicio (Formato YYYY-MM-DD)
    - end_date: Fecha fin (Formato YYYY-MM-DD)
    """
    try:
        events = list_events(start_date=start_date, end_date=end_date)
        return {
            "status": "ok",
            "events": events,
            "count": len(events)
        }
    except Exception as e:
        tool_logger.exception("Error al listar citas del calendario")
        return {"status": "error", "message": f"Error al listar citas: {str(e)}"}


async def calendar_delete_event(event_id: int) -> dict:
    """
    Elimina una cita del calendario por su ID.
    - event_id: ID numérico de la cita a eliminar.
    """
    try:
        success = delete_event(event_id)
        if success:
            if bridge.has_clients():
                await bridge.send_command("calendar.sync", {"action": "delete", "id": event_id})
            return {"status": "ok", "message": f"Cita con ID {event_id} eliminada correctamente."}
        else:
            return {"status": "error", "message": f"No se encontró ninguna cita con ID {event_id}."}
    except Exception as e:
        tool_logger.exception("Error al borrar cita del calendario")
        return {"status": "error", "message": f"Error al borrar la cita: {str(e)}"}


async def calendar_open_ui() -> dict:
    """
    Abre de forma visual la interfaz nativa del calendario en el escritorio del usuario.
    """
    try:
        if not bridge.has_clients():
            return {"status": "error", "message": "El cliente de escritorio no está conectado."}
            
        res = await bridge.send_command(Action.CALENDAR_OPEN, {})
        if res.get("status") == "success" or res.get("status") == "ok":
            return {"status": "ok", "message": "Interfaz del calendario abierta correctamente."}
        else:
            return {"status": "error", "message": f"El cliente retornó un error: {res.get('error')}"}
    except Exception as e:
        tool_logger.exception("Error al enviar comando calendar.open al cliente")
        return {"status": "error", "message": f"Error al abrir la interfaz: {str(e)}"}


async def calendar_close_ui() -> dict:
    """
    Cierra la interfaz visual del calendario en el escritorio del usuario.
    """
    try:
        if bridge.has_clients():
            await bridge.send_command("calendar.close", {})
        return {"status": "ok", "message": "Interfaz del calendario cerrada correctamente."}
    except Exception as e:
        tool_logger.exception("Error al enviar comando calendar.close al cliente")
        return {"status": "error", "message": f"Error al cerrar la interfaz: {str(e)}"}


async def calendar_update_event(
    event_id: int,
    title: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[str] = None,
) -> dict:
    """
    Modifica o actualiza una cita existente en el calendario.
    - event_id: ID numérico de la cita a modificar.
    - title: Nuevo título (opcional)
    - start_time: Nueva fecha y hora de inicio (opcional, Formato YYYY-MM-DD HH:MM)
    - end_time: Nueva fecha y hora de fin (opcional, Formato YYYY-MM-DD HH:MM)
    - description: Nueva nota o descripción (opcional)
    - location: Nuevo lugar (opcional)
    - attendees: Nuevos asistentes separados por comas (opcional)
    """
    try:
        if isinstance(attendees, list):
            attendees = ", ".join([str(a) for a in attendees]) if attendees else None

        success = update_event(
            event_id=event_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            attendees=attendees
        )
        if success:
            if bridge.has_clients():
                await bridge.send_command("calendar.sync", {"action": "update", "id": event_id})
            return {"status": "ok", "message": f"Cita con ID {event_id} modificada correctamente."}
        else:
            return {"status": "error", "message": f"No se encontró ninguna cita con ID {event_id} o no se especificaron cambios."}
    except Exception as e:
        tool_logger.exception("Error al modificar cita del calendario")
        return {"status": "error", "message": f"Error al modificar la cita: {str(e)}"}


# Registro de herramientas exportado para la carga dinámica de plugins
TOOLS = {
    "calendar_create_event": calendar_create_event,
    "calendar_list_events": calendar_list_events,
    "calendar_delete_event": calendar_delete_event,
    "calendar_open_ui": calendar_open_ui,
    "calendar_close_ui": calendar_close_ui,
    "calendar_update_event": calendar_update_event,
}
