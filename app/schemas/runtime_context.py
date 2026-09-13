from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.schemas.context import (
    TenantRuntimeContext,
    TenantKind,
    BusinessTypeLiteral,
    has_capability,
)

class BusinessType(str, Enum):
    SERVICE = "FIELD_SERVICE"
    PRODUCT = "PHYSICAL"
    DIGITAL = "DIGITAL"

class TenantCapabilities(BaseModel):
    catalog: bool = True
    booking: bool = False
    schedule: bool = False
    service_area: bool = False
    variants: bool = False
    shipping: bool = False
    payment: bool = True