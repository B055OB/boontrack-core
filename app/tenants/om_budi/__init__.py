"""app/tenants/om_budi/__init__.py
Tenant Om Budi - AI Member & Customer Operations Module.
"""

from app.tenants.om_budi.service import OmBudiService, om_budi_service
from app.tenants.om_budi.router import register_om_budi_routes
from app.tenants.om_budi.config import (
    TENANT_ID,
    TENANT_NAME,
    DEFAULT_VERIFY_TOKEN,
    ESCALATION_KEYWORDS,
    MEMBER_SEGMENTS,
)

__all__ = [
    "OmBudiService",
    "om_budi_service",
    "register_om_budi_routes",
    "TENANT_ID",
    "TENANT_NAME",
    "DEFAULT_VERIFY_TOKEN",
    "ESCALATION_KEYWORDS",
    "MEMBER_SEGMENTS",
]
