"""
CALENDAR DB — Abstracción de base de datos SQLite para calendario nativo.

¿QUÉ HACE?
Proporciona funciones CRUD para almacenar y gestionar los eventos de la agenda local.

¿CUÁNDO LO HACE?
Al listar, crear, actualizar o eliminar citas a través de las herramientas del planificador o endpoints REST.

¿CÓMO LO HACE?
Ejecutando consultas SQL directas en una base de datos SQLite persistente local.

¿CON QUÉ OTROS SCRIPTS ESTÁ RELACIONADO?
- app/api/routes.py (expone endpoints REST para interactuar con esta base de datos)
- app/tools/calendar_tools.py (expone estas funciones en forma de herramientas para el LLM)
"""

import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

IS_TESTING = "pytest" in sys.modules or os.getenv("TESTING") == "true"

if IS_TESTING:
    DB_PATH = Path(__file__).resolve().parents[2] / "data" / "memory_test.db"
else:
    DB_PATH = Path(__file__).resolve().parents[2] / "data" / "memory.db"

_db_initialized = False


def _init_calendar_schema(conn: sqlite3.Connection) -> None:
    """Crea la tabla de eventos de calendario e índices si no existen."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            start_time  TEXT    NOT NULL, -- Formato ISO: YYYY-MM-DD HH:MM
            end_time    TEXT,             -- Formato ISO: YYYY-MM-DD HH:MM
            description TEXT,
            location    TEXT,
            attendees   TEXT,             -- Lista de nombres/correos separada por comas
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_calendar_start_time
        ON calendar_events (start_time)
    """)
    conn.commit()


def get_connection() -> sqlite3.Connection:
    global _db_initialized
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if not _db_initialized:
        _init_calendar_schema(conn)
        _db_initialized = True
    return conn


def create_event(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[str] = None,
) -> int:
    """Inserta un nuevo evento de calendario y devuelve su ID."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO calendar_events (title, start_time, end_time, description, location, attendees)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, start_time, end_time, description, location, attendees),
        )
        conn.commit()
        return cursor.lastrowid


def list_events(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict]:
    """
    Lista eventos dentro de un rango de fechas (YYYY-MM-DD).
    Si no se especifican, devuelve todos los eventos.
    """
    query = "SELECT * FROM calendar_events"
    params = []
    
    if start_date and end_date:
        query += " WHERE start_time >= ? AND start_time <= ?"
        params.extend([f"{start_date} 00:00", f"{end_date} 23:59"])
    elif start_date:
        query += " WHERE start_time >= ?"
        params.append(f"{start_date} 00:00")
    elif end_date:
        query += " WHERE start_time <= ?"
        params.append(f"{end_date} 23:59")
        
    query += " ORDER BY start_time ASC"
    
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_event(event_id: int) -> Optional[Dict]:
    """Obtiene un evento por su ID."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None


def update_event(
    event_id: int,
    title: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[str] = None,
) -> bool:
    """Actualiza campos específicos de un evento existente."""
    fields = []
    params = []
    
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    if start_time is not None:
        fields.append("start_time = ?")
        params.append(start_time)
    if end_time is not None:
        fields.append("end_time = ?")
        params.append(end_time)
    if description is not None:
        fields.append("description = ?")
        params.append(description)
    if location is not None:
        fields.append("location = ?")
        params.append(location)
    if attendees is not None:
        fields.append("attendees = ?")
        params.append(attendees)
        
    if not fields:
        return False
        
    query = f"UPDATE calendar_events SET {', '.join(fields)} WHERE id = ?"
    params.append(event_id)
    
    with get_connection() as conn:
        cursor = conn.execute(query, params)
        conn.commit()
        return cursor.rowcount > 0


def delete_event(event_id: int) -> bool:
    """Elimina un evento por su ID."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
        conn.commit()
        return cursor.rowcount > 0


from typing import Any
from app.domain.ports.calendar_port import CalendarPort

class SQLiteCalendarAdapter(CalendarPort):
    def list_events(self, date_str: str | None = None) -> list[dict[str, Any]]:
        return list_events(date_str)

    def delete_event(self, event_id: int) -> bool:
        return delete_event(event_id)

