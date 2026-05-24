from collections import deque
from typing import Deque, Dict, List


class SessionMemory:
    def __init__(self, max_messages: int = 10):
        self._sessions: Dict[str, Deque[Dict[str, str]]] = {}
        self.max_messages = max_messages

    def add_message(self, session_id: str, role: str, content: str) -> None:
        if not session_id:
            return
        if session_id not in self._sessions:
            self._sessions[session_id] = deque(maxlen=self.max_messages)
        self._sessions[session_id].append({"role": role, "content": content})

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        return list(self._sessions.get(session_id, []))

    def get_summary(self, session_id: str) -> str:
        history = self.get_history(session_id)
        if not history:
            return ""
        return "\n".join(f"{entry['role']}: {entry['content']}" for entry in history)

    def clear(self, session_id: str) -> None:
        if session_id in self._sessions:
            del self._sessions[session_id]


memory = SessionMemory()
