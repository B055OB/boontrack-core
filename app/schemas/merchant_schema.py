from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from enum import Enum
import re

class BusinessCategoryEnum(str, Enum):
    FASHION = "fashion"
    SKINCARE = "skincare"
    FNB = "fnb"
    DIGITAL = "digital"
    GENERAL = "general"
    OTHER = "other"

class PlanTierEnum(str, Enum):
    STARTER = "STARTER"
    GROWTH = "GROWTH"
    PRO_SCALE = "PRO_SCALE"
    ENTERPRISE = "ENTERPRISE"

class MerchantRegisterRequest(BaseModel):
    store_name: str = Field(..., min_length=3, max_length=100)
    slug: str = Field(..., min_length=3, max_length=50)
    business_category: BusinessCategoryEnum = BusinessCategoryEnum.GENERAL
    owner_name: str = Field(..., min_length=3, max_length=100)
    owner_whatsapp: str = Field(..., min_length=9, max_length=20)
    owner_email: EmailStr
    password: Optional[str] = Field(None, min_length=6)
    plan_tier: PlanTierEnum = PlanTierEnum.GROWTH
    referral_code: Optional[str] = None
    cf_turnstile_token: Optional[str] = None

    @validator("slug")
    def validate_slug(cls, v):
        clean_slug = re.sub(r"[^a-z0-9-]", "", v.lower().strip())
        if len(clean_slug) < 3:
            raise ValueError("Slug minimal 3 karakter alfanumerik.")
        return clean_slug

    @validator("owner_whatsapp")
    def format_whatsapp(cls, v):
        clean_num = re.sub(r"\D", "", v)
        if clean_num.startswith("0"):
            clean_num = "62" + clean_num[1:]
        elif not clean_num.startswith("62"):
            clean_num = "62" + clean_num
        return clean_num

class VerifyOtpRequest(BaseModel):
    phone: str
    otp_code: str = Field(..., min_length=6, max_length=6)

class SlugCheckResponse(BaseModel):
    slug: str
    available: bool
    message: str