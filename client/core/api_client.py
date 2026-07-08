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
        max_retries = 30
        retry_delay = 3
        print(f"[INFO] Verificando conexión con el backend ({self.base_url})...")
        for i in range(max_retries):
            try:
                r = requests.get(f"{self.base_url}/health", timeout=5)
                if r.status_code == 200:
                    return True
            except Exception:
                if i < max_retries - 1:
                    print(f"[INFO] Servidor calentándose o iniciándose... Reintento {i+1}/{max_retries} en {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print("[ERROR] No se pudo conectar al servidor tras varios intentos.")
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

    def get_calendar_events(self, start_date=None, end_date=None) -> dict:
        """Obtiene la lista de eventos del calendario en el rango de fechas."""
        try:
            params = {}
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date
            r = requests.get(f"{self.base_url}/calendar/events", params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_emails(self, category=None, importance=None, read_status=None) -> list:
        """Obtiene la lista de correos con filtros opcionales."""
        try:
            params = {}
            if category is not None:
                params["category"] = category
            if importance is not None:
                params["importance"] = importance
            if read_status is not None:
                params["read_status"] = read_status
            r = requests.get(f"{self.base_url}/mail/emails", params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[ERROR] get_emails falló: {e}")
            return []

    def get_email(self, email_id: int) -> dict:
        """Obtiene el contenido completo de un correo por su ID."""
        try:
            r = requests.get(f"{self.base_url}/mail/emails/{email_id}", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def mark_email_as_read(self, email_id: int) -> dict:
        """Marca un correo como leído."""
        try:
            r = requests.post(f"{self.base_url}/mail/emails/{email_id}/read", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def seed_emails(self) -> dict:
        """Inyecta correos de prueba simulados."""
        try:
            r = requests.post(f"{self.base_url}/mail/emails/seed", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def send_email(self, recipient: str, subject: str, body: str) -> dict:
        """Envía un nuevo correo electrónico."""
        try:
            r = requests.post(
                f"{self.base_url}/mail/send",
                json={"recipient": recipient, "subject": subject, "body": body},
                timeout=10
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_email(self, email_id: int) -> dict:
        """Elimina un correo electrónico."""
        try:
            r = requests.delete(f"{self.base_url}/mail/emails/{email_id}", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def reply_email(self, email_id: int, body: str, reply_all: bool = False) -> dict:
        """Envía una respuesta a un correo electrónico."""
        try:
            r = requests.post(
                f"{self.base_url}/mail/emails/{email_id}/reply",
                json={"body": body, "reply_all": reply_all},
                timeout=10
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def forward_email(self, email_id: int, recipient: str, comment: str = None) -> dict:
        """Reenvía un correo electrónico."""
        try:
            r = requests.post(
                f"{self.base_url}/mail/emails/{email_id}/forward",
                json={"recipient": recipient, "comment": comment},
                timeout=10
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_reply_draft(self, email_id: int) -> dict:
        """Obtiene un borrador de respuesta inteligente (asistente experto si es legal)."""
        try:
            r = requests.get(f"{self.base_url}/mail/emails/{email_id}/draft", timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_dev_files(self) -> list:
        """Obtiene la lista de archivos del sandbox de desarrollo."""
        try:
            r = requests.get(f"{self.base_url}/dev/files", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[ERROR] get_dev_files falló: {e}")
            return []

    def get_dev_file(self, filename: str) -> dict:
        """Obtiene el contenido de un archivo del sandbox."""
        try:
            r = requests.get(f"{self.base_url}/dev/files/{filename}", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def save_dev_file(self, filename: str, content: str) -> dict:
        """Guarda o actualiza un archivo en el sandbox."""
        try:
            r = requests.post(
                f"{self.base_url}/dev/files",
                json={"filename": filename, "content": content},
                timeout=10
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_dev_file(self, filename: str) -> dict:
        """Elimina un archivo del sandbox."""
        try:
            r = requests.delete(f"{self.base_url}/dev/files/{filename}", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def execute_dev_command(self, command: str) -> dict:
        """Ejecuta un comando en el sandbox."""
        try:
            r = requests.post(
                f"{self.base_url}/dev/execute",
                json={"command": command},
                timeout=20
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"status": "error", "exit_code": -1, "stdout": "", "stderr": str(e)}



