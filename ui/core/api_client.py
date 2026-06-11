import requests
import time
import tempfile
from pathlib import Path
from typing import Optional

class AlfonsoAPI:
    """
    Cliente unificado para la API de Alfonso.
    Encapsula la URL base y maneja la lógica de reintentos.
    """
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def send_chat(self, message: str, session_id: str) -> dict:
        try:
            r = requests.post(
                f"{self.base_url}/chat",
                json={"message": message},
                headers={"X-Session-ID": session_id},
                timeout=120,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
        
    def stt(self, audio_bytes):
        """Envía audio al endpoint /stt del servidor para transcribir."""
        import requests
        files = {'file': ('audio.wav', audio_bytes, 'audio/wav')}
        try:
            response = requests.post(f"{self.base_url}/stt", files=files)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
