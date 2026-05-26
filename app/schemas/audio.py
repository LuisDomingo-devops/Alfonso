from pydantic import BaseModel, Field
from typing import Optional


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None


class STTRequest(BaseModel):
    duration: int = Field(default=5, ge=1, le=60)


class WakeWordRequest(BaseModel):
    """Para wake word local (solo desarrollo con micrófono disponible)."""
    keyword: str = "alfonso"
    max_duration: int = Field(default=30, ge=1, le=300)
    chunk_duration: int = Field(default=5, ge=1, le=30)
    model: Optional[str] = "small"


class WakeWordUploadRequest(BaseModel):
    """
    Parámetros para detección de wake word en audio subido por el cliente.
    El fichero de audio se pasa como UploadFile en el endpoint.
    """
    keyword: str = "alfonso"
    model: Optional[str] = "small"


class VoiceConversationRequest(BaseModel):
    keyword: Optional[str] = "alfonso"
    wakeword_enabled: bool = True
    max_duration: int = Field(default=30, ge=1, le=300)
    chunk_duration: int = Field(default=5, ge=1, le=30)
    stt_duration: int = Field(default=5, ge=1, le=60)
    stt_model: Optional[str] = "small"
    voice: Optional[str] = None
    session_id: Optional[str] = None