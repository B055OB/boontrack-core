from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class StandardMessagePayload(BaseModel):
    """Payload internal standar dari WebChat/WhatsApp/Telegram."""
    channel: str = Field(..., description="Channel: webchat, whatsapp, telegram")
    user_id: str = Field(..., description="ID/Nomor telepon pengguna")
    session_id: str = Field(..., description="UUID sesi percakapan")
    message: str = Field(..., min_length=1, description="Pesan pertanyaan warga")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(from_attributes=True)


class PublicServiceContext(BaseModel):
    service_slug: Optional[str] = None
    service_name: Optional[str] = None
    known_requirements: List[str] = Field(default_factory=list)
    is_escalated: bool = False
    escalation_reason: Optional[str] = None


class PublicServiceResponse(BaseModel):
    reply: str
    status: str
    session_id: str
    service_slug: Optional[str] = None
    escalation_triggered: bool = False