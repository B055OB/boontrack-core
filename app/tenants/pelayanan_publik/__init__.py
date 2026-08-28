"""app/tenants/pelayanan_publik/__init__.py
Module exports for Pelayanan Publik B2G Pilot (melayani pelayananpublik.boontrack.com).
"""

from app.tenants.pelayanan_publik.service import (
    PelayananPublikService,
    pelayanan_publik_service,
    DigiLifeIndraService,
    digilife_indra_service,
)
from app.tenants.pelayanan_publik.config import (
    TENANT_ID,
    TENANT_SLUG,
    TENANT_DOMAIN,
    TENANT_NAME,
    TENANT_ALIASES,
    DESCRIPTION,
    OPERATIONAL_HOURS,
    LOCATION,
    HOTLINE_PHONE,
    SERVICE_CATALOG,
    WELCOME_MESSAGE,
)

__all__ = [
    "PelayananPublikService",
    "pelayanan_publik_service",
    "DigiLifeIndraService",
    "digilife_indra_service",
    "TENANT_ID",
    "TENANT_SLUG",
    "TENANT_DOMAIN",
    "TENANT_NAME",
    "TENANT_ALIASES",
    "DESCRIPTION",
    "OPERATIONAL_HOURS",
    "LOCATION",
    "HOTLINE_PHONE",
    "SERVICE_CATALOG",
    "WELCOME_MESSAGE",
]
