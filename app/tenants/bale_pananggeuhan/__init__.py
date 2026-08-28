"""app/tenants/bale_pananggeuhan/__init__.py
Module exports for Balé Pananggeuhan B2G Pilot (Setda Pemprov Jawa Barat).
"""

from app.tenants.bale_pananggeuhan.service import (
    BalePananggeuhanService,
    bale_pananggeuhan_service,
)
from app.tenants.bale_pananggeuhan.config import (
    TENANT_ID,
    TENANT_SLUG,
    TENANT_NAME,
    DESCRIPTION,
    LOCATION,
    OPERATIONAL_HOURS,
    HOTLINE_PHONE,
    DISPATCH_DEPARTMENTS,
    ESCALATION_KEYWORDS,
    WELCOME_MESSAGE,
)

__all__ = [
    "BalePananggeuhanService",
    "bale_pananggeuhan_service",
    "TENANT_ID",
    "TENANT_SLUG",
    "TENANT_NAME",
    "DESCRIPTION",
    "LOCATION",
    "OPERATIONAL_HOURS",
    "HOTLINE_PHONE",
    "DISPATCH_DEPARTMENTS",
    "ESCALATION_KEYWORDS",
    "WELCOME_MESSAGE",
]
