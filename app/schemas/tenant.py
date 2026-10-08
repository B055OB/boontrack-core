"""app/schemas/tenant.py
Pydantic Schemas for Tenant Onboarding & Global Isolation.

Provides:
- TenantCreateRequest: Validates payload for new tenant creation (name, slug regex, business_category, optional waba_phone_number_id).
- TenantResponse: Standard response model with id, slug, status, created_at, and metadata.
"""

import re
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


SLUG_REGEX = r"^[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*$"


class TenantCreateRequest(BaseModel):
    """Payload schema untuk registrasi tenant baru."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(
        ...,
        min_length=3,
        max_length=128,
        description="Nama resmi tenant / bisnis (minimal 3 karakter)",
    )
    slug: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Slug unik tenant (alphanumeric + hyphen, e.g. 'little-bite', 'klinik-anak')",
    )
    business_category: str = Field(
        ...,
        min_length=2,
        max_length=64,
        description="Kategori bisnis (misal: 'fnb', 'clinical_consultation', 'retail')",
    )
    waba_phone_number_id: Optional[str] = Field(
        default=None,
        description="Meta WhatsApp Cloud API WABA Phone Number ID opsional",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = (v or "").strip()
        if len(clean) < 3:
            raise ValueError("Nama tenant minimal 3 karakter")
        return clean

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        if not re.match(SLUG_REGEX, clean):
            raise ValueError(
                "Slug hanya boleh berisi karakter alfanumerik dan tanda hubung '-' (contoh: 'klinik-sehat', 'little-bite-1')"
            )
        return clean


class TenantResponse(BaseModel):
    """Response schema setelah proses onboarding tenant selesai."""
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: str = Field(..., description="Unique Tenant ID (UUID)")
    name: str = Field(..., description="Nama resmi tenant")
    slug: str = Field(..., description="Slug unik tenant")
    business_category: Optional[str] = Field(
        default=None,
        description="Kategori bisnis tenant",
    )
    status: str = Field(
        default="active",
        description="Status tenant: active, inactive, pending",
    )
    is_active: bool = Field(
        default=True,
        description="Status keaktifan tenant",
    )
    waba_phone_number_id: Optional[str] = Field(
        default=None,
        description="Meta WABA Phone Number ID yang terikat jika ada",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp pembuatan tenant",
    )
