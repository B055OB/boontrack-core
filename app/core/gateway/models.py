from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class GatewayCapabilities(BaseModel):
    qr_pairing: bool = True
    pairing_code: bool = True
    multi_agent: bool = False

class GatewayStatusResponse(BaseModel):
    success: bool
    plan_tier: str
    gateway_type: str = "QR_SESSION" # QR_SESSION atau META_CLOUD
    status: str # CONNECTED, DEGRADED, DISCONNECTED
    phone_number: Optional[str] = None
    last_heartbeat: Optional[str] = None
    pending_messages: int = 0
    disconnect_reason: Optional[str] = None
    capabilities: GatewayCapabilities