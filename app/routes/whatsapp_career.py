"""BoonTrack Career Assistant Router (Backward compatibility wrapper).

Logika domain utama telah dimodularisasi ke package `app.tenants.career`.
"""

from app.tenants.career.router import (
    career_routes,
    verify_webhook,
    handle_incoming_whatsapp,
    register_career_routes as register_whatsapp_career_routes
)
from app.tenants.career.service import (
    career_service,
    GLOBAL_USER_STATES
)
from app.tenants.career.config import (
    TENANT_ID as CAREER_TENANT_ID,
    VERIFY_TOKEN
)

__all__ = [
    "career_routes",
    "verify_webhook",
    "handle_incoming_whatsapp",
    "register_whatsapp_career_routes",
    "career_service",
    "GLOBAL_USER_STATES",
    "CAREER_TENANT_ID",
    "VERIFY_TOKEN"
]
