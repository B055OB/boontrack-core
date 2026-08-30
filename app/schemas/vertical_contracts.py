"""app/schemas/vertical_contracts.py
Standardized Vertical Contract definitions for multi-tenant BoonTrack ecosystem.
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class VerticalType(str, Enum):
    D2C_RETAIL = "D2C_RETAIL"             # Toko online fisik/digital, katalog, checkout QRIS
    GYM_FITNESS = "GYM_FITNESS"           # Membership, reservasi turnstile gate, booking sesi
    PUBLIC_SERVICE = "PUBLIC_SERVICE"     # Aspirasi & aduan warga, tracking tiket aduan
    CAREER_ATS = "CAREER_ATS"             # Review CV, polish resume, interview prep


class VerticalContract(BaseModel):
    vertical_type: VerticalType
    tenant_slug: str
    display_name: str
    primary_currency: str = "IDR"
    features_enabled: List[str]
    intent_keywords: Dict[str, List[str]]
    custom_fields_schema: Dict[str, Any] = Field(default_factory=dict)