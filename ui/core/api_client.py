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
        except Exception as e:
            print("[DEBUG PING ERROR]:", e)
            import traceback
            traceback.print_exc()
            return False

    def send_chat(self, message: str, session_id: str) -> dict:
        # Obtener estructura fresca del escritorio en tiempo real
        desktop_structure = []
        try:
            import os
            desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.exists(desktop_dir):
                desktop_dir = os.path.join(os.path.expanduser("~"), "Escritorio")
            if os.path.exists(desktop_dir):
                for entry in os.scandir(desktop_dir):
                    if not entry.name.startswith(".") and not entry.name.startswith("desktop.ini"):
                        marker = " (Carpeta)" if entry.is_dir() else ""
                        desktop_structure.append(f"{entry.name}{marker}")
                desktop_structure = sorted(desktop_structure)[:30]
        except Exception:
            pass

        try:
            r = requests.post(
                f"{self.base_url}/chat",
                json={
                    "message": message,
                    "client_info": {
                        "desktop_structure": desktop_structure
                    }
                },
                headers={"X-Session-ID": session_id},
                timeout=300,
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
