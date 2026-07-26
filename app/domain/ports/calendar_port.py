from typing import Protocol, Any, List, Dict

class CalendarPort(Protocol):
    def list_events(self, date_str: str | None = None) -> List[Dict[str, Any]]:
        """Lists events on the calendar, optionally filtered by date."""
        ...

    def delete_event(self, event_id: int) -> bool:
        """Deletes an event from the calendar database by ID."""
        ...
