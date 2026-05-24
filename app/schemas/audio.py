from pydantic import BaseModel
from typing import Optional


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None


class STTRequest(BaseModel):
    duration: int = 5


class WakeWordRequest(BaseModel):
    keyword: str = "alfonso"
    max_duration: int = 30
    chunk_duration: int = 5
    model: Optional[str] = "small"


class VoiceConversationRequest(BaseModel):
    keyword: Optional[str] = "alfonso"
    wakeword_enabled: bool = True
    max_duration: int = 30
    chunk_duration: int = 5
    stt_duration: int = 5
    stt_model: Optional[str] = "small"
    voice: Optional[str] = None
    session_id: Optional[str] = None
