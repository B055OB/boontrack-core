from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StandardMessagePayload(BaseModel):
    channel: str = Field(default="webchat", description="Channel asal: webchat, whatsapp, telegram")
    user_id: str = Field(..., description="Identifier unik warga / sender")
    session_id: str = Field(..., description="Session ID obrolan")
    message: str = Field(..., max_length=1000, description="Pesan / pertanyaan warga")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class PublicServiceContext(BaseModel):
    service_slug: Optional[str] = None
    is_escalated: bool = False
    escalation_reason: Optional[str] = None
    extracted_data: Dict[str, Any] = Field(default_factory=dict)


class PublicServiceResponse(BaseModel):
    reply: str
    status: str = "ACTIVE"
    session_id: str
    service_slug: Optional[str] = None
    escalation_triggered: bool = False
    metadata: Optional[Dict[str, Any]] = None
