import requests
import time
import tempfile
from pathlib import Path
from typing import Optional
from ui.config import WAKE_WORD_RETRIES

def ping_server(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        return r.status_code == 200
    except Exception:
        return False

def detect_wake_word(
    base_url: str,
    wav_bytes: bytes,
    keyword: str,
    model: str = "tiny",
) -> dict:
    for attempt in range(1, WAKE_WORD_RETRIES + 1):
        try:
            r = requests.post(
                f"{base_url}/audio/wakeword/upload",
                files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
                data={"keyword": keyword, "model": model},
                timeout=90,
            )
            r.raise_for_status()
            return r.json()
        except requests.Timeout:
            if attempt < WAKE_WORD_RETRIES:
                time.sleep(2 ** attempt)
                continue
            return {"status": "error", "message": "timed out after retries"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "max retries exceeded"}

def transcribe_audio(base_url: str, wav_bytes: bytes, model: str = "small") -> dict:
    try:
        r = requests.post(
            f"{base_url}/audio/stt/upload",
            files={"file": ("orden.wav", wav_bytes, "audio/wav")},
            params={"model": model},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def send_chat(base_url: str, message: str, session_id: str) -> dict:
    try:
        r = requests.post(
            f"{base_url}/chat",
            json={"message": message},
            headers={"X-Session-ID": session_id},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_tts(base_url: str, text: str, voice: Optional[str] = None) -> Optional[str]:
    try:
        payload = {"text": text}
        if voice:
            payload["voice"] = voice
        r = requests.post(f"{base_url}/audio/tts", json=payload, timeout=30)
        r.raise_for_status()
        audio_file = r.json().get("result", {}).get("audio_file")
        if not audio_file:
            return None
        file_r = requests.get(f"{base_url}/audio/file", params={"path": audio_file}, timeout=10)
        if file_r.status_code == 200:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(file_r.content)
            tmp.close()
            return tmp.name
        return audio_file if Path(audio_file).exists() else None
    except Exception:
        return None