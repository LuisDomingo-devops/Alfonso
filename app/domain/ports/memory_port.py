from typing import Protocol, Any, Dict, List

class MemoryPort(Protocol):
    def add_message(self, session_id: str, role: str, content: str, client_id: str | None = None) -> None:
        """Adds a message to the conversation history."""
        ...

    def get_history(self, session_id: str, client_id: str | None = None) -> List[Dict[str, str]]:
        """Retrieves the full message history for a session."""
        ...

    def get_summary(self, session_id: str, client_id: str | None = None) -> str:
        """Retrieves a text summary of the session history."""
        ...

    def clear(self, session_id: str) -> None:
        """Clears all conversation history for a session."""
        ...

    def get_metadata(self, session_id: str) -> Dict[str, Any] | None:
        """Retrieves metadata associated with a session."""
        ...

    def upsert_metadata(self, session_id: str, title: str, discipline: str, project_name: str = 'default', is_persistent: bool = True) -> None:
        """Upserts metadata for a session."""
        ...

    def list_persistent_conversations(self) -> List[Dict[str, Any]]:
        """Lists all persistent conversations/projects in the system."""
        ...


class VectorMemoryPort(Protocol):
    def add_fact(self, session_id: str, fact: str, client_id: str | None = None) -> None:
        """Stores a semantically searchable fact in vector memory."""
        ...

    def query_facts(self, query: str, limit: int = 5, client_id: str | None = None) -> List[str]:
        """Searches vector memory for facts related to a query."""
        ...
