"""app/tenants/digilife_indra/__init__.py
Module exports for DigiLife Indra B2G Pilot (Kelurahan Kebon Melati).
"""

from app.tenants.digilife_indra.service import (
    DigiLifeIndraService,
    digilife_indra_service,
)
from app.tenants.digilife_indra.config import (
    TENANT_ID,
    TENANT_SLUG,
    TENANT_NAME,
    DESCRIPTION,
    OPERATIONAL_HOURS,
    LOCATION,
    SERVICE_CATALOG,
    WELCOME_MESSAGE,
)

__all__ = [
    "DigiLifeIndraService",
    "digilife_indra_service",
    "TENANT_ID",
    "TENANT_SLUG",
    "TENANT_NAME",
    "DESCRIPTION",
    "OPERATIONAL_HOURS",
    "LOCATION",
    "SERVICE_CATALOG",
    "WELCOME_MESSAGE",
]
