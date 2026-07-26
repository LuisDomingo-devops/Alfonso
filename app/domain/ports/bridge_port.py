from typing import Protocol, Any, Dict

class BridgePort(Protocol):
    async def send_command(self, action: str, data: Dict[str, Any]) -> None:
        """Sends a command to all connected WebSocket clients."""
        ...

    def has_clients(self) -> bool:
        """Returns True if there are active WebSocket connections."""
        ...

    @property
    def client_info(self) -> Dict[str, Any] | None:
        """Returns client info dictionary."""
        ...
