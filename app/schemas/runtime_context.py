from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class BusinessType(str, Enum):
    SERVICE = "SERVICE"
    PRODUCT = "PRODUCT"
    DIGITAL = "DIGITAL"

class TenantCapabilities(BaseModel):
    catalog: bool = True
    booking: bool = False
    schedule: bool = False
    service_area: bool = False
    variants: bool = False
    shipping: bool = False
    payment: bool = True

class TenantRuntimeContext(BaseModel):
    tenant_id: str
    tenant_slug: str
    template_code: str
    business_type: BusinessType
    capabilities: TenantCapabilities
    allowed_buyer_actions: List[str]
    disallowed_actions: List[str] = Field(default_factory=lambda: [
        "Tambah Produk", "Setup WhatsApp", "Bikin Landing Page", 
        "Atur Toko", "Hubungkan Domain", "Kelola Staff"
    ])
    persona_system_hint: str