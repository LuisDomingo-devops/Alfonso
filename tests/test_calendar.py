import pytest
import os
from unittest.mock import AsyncMock, patch
from app.adapters.calendar_db import create_event, list_events, delete_event, get_event, update_event
from app.tools.server.calendar_tools import calendar_create_event, calendar_list_events, calendar_delete_event, calendar_open_ui

@pytest.fixture(autouse=True)
def setup_test_db():
    # Asegurar modo test
    os.environ["TESTING"] = "true"
    # Borrar eventos previos en DB de test antes de cada test
    from app.adapters.calendar_db import get_connection
    with get_connection() as conn:
        conn.execute("DELETE FROM calendar_events")
        conn.commit()
    yield

def test_db_operations():
    # 1. Crear
    event_id = create_event(
        title="Reunión Presupuesto",
        start_time="2026-07-04 10:00",
        end_time="2026-07-04 11:30",
        description="Ver números del Q3",
        location="Sala A",
        attendees="Carlos, Ana"
    )
    assert event_id > 0

    # 2. Obtener
    ev = get_event(event_id)
    assert ev is not None
    assert ev["title"] == "Reunión Presupuesto"
    assert ev["location"] == "Sala A"
    assert ev["attendees"] == "Carlos, Ana"

    # 3. Listar
    events = list_events(start_date="2026-07-04", end_date="2026-07-04")
    assert len(events) == 1
    assert events[0]["id"] == event_id

    # 4. Actualizar
    updated = update_event(event_id, title="Reunión Presupuesto Final", location="Sala B")
    assert updated is True
    ev = get_event(event_id)
    assert ev["title"] == "Reunión Presupuesto Final"
    assert ev["location"] == "Sala B"

    # 5. Eliminar
    deleted = delete_event(event_id)
    assert deleted is True
    assert get_event(event_id) is None

@pytest.mark.asyncio
async def test_calendar_tools():
    # Test crear cita con la tool
    res = await calendar_create_event(
        title="Cita Dentista",
        start_time="2026-07-05 16:00",
        description="Revisión anual",
        _session_id="test_session"
    )
    assert res["status"] == "ok"
    assert "event_id" in res
    event_id = res["event_id"]

    # Test listar con la tool
    res_list = await calendar_list_events(start_date="2026-07-05", end_date="2026-07-05")
    assert res_list["status"] == "ok"
    assert res_list["count"] == 1
    assert res_list["events"][0]["title"] == "Cita Dentista"

    # Test borrar con la tool
    res_del = await calendar_delete_event(event_id)
    assert res_del["status"] == "ok"

    # Verificar que ya no está
    res_list_empty = await calendar_list_events(start_date="2026-07-05", end_date="2026-07-05")
    assert res_list_empty["count"] == 0
