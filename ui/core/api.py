import requests
import tempfile
from pathlib import Path
from typing import Optional

class AlfonsoAPI:
    """Maneja la comunicación REST con el servidor Alfonso."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def detect_wake_word(self, wav_bytes: bytes, keyword: str, model: str = "tiny") -> dict:
        try:
            r = requests.post(
                f"{self.base_url}/audio/wakeword/upload",
                files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
                data={"keyword": keyword, "model": model},
                timeout=90,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"status": "error", "message": str(e)}

    def transcribe_audio(self, wav_bytes: bytes, model: str = "small") -> dict:
        try:
            r = requests.post(
                f"{self.base_url}/audio/stt/upload",
                files={"file": ("orden.wav", wav_bytes, "audio/wav")},
                params={"model": model},
                timeout=120,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"status": "error", "message": str(e)}

    def send_chat(self, message: str, session_id: str) -> dict:
        try:
            r = requests.post(
                f"{self.base_url}/chat",
                json={"message": message},
                headers={"X-Session-ID": session_id},
                timeout=60,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            return {"status": "error", "message": str(e)}

    def get_tts(self, text: str, voice: Optional[str] = None) -> Optional[str]:
        try:
            payload = {"text": text}
            if voice:
                payload["voice"] = voice
            r = requests.post(f"{self.base_url}/audio/tts", json=payload, timeout=30)
            r.raise_for_status()
            data = r.json()

            audio_file = data.get("result", {}).get("audio_file")
            if not audio_file:
                return None

            file_r = requests.get(f"{self.base_url}/audio/file", params={"path": audio_file}, timeout=10)
            if file_r.status_code == 200:
                tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                tmp.write(file_r.content)
                tmp.close()
                return tmp.name
            return audio_file if Path(audio_file).exists() else None
        except Exception:
            return None