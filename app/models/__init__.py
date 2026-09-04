# Legacy / Existing Core Models
from app.models.domain import Goal, Intent, User
from app.models.digital_asset import Delivery, DigitalAsset, KnowledgeMapping

# Sprint 1 Multi-Tenant Foundations
from app.models.base import Base, TenantScopedBaseMixin
from app.models.tenant import Tenant, TenantTier, OnboardingMode, TenantPayout
from app.models.catalog import LicenseStatus, Product, ProductType
from app.models.channels import ChannelStatus, TelegramBot, TenantWhatsAppChannel
from app.models.device import (
    ActivationCode,
    ActivationCodeStatus,
    DeviceStatus,
    MerchantDevice,
)
from app.models.affiliate import (
    Partner,
    PartnerRole,
    PartnerStatus,
    PartnerBankAccount,
    PayoutRequest,
    PayoutStatus,
    AllowedBank,
)

__all__ = [
    # Legacy Exports
    "Goal",
    "Intent",
    "User",
    "DigitalAsset",
    "Delivery",
    "KnowledgeMapping",
    # Multi-Tenant & Security Exports
    "Base",
    "TenantScopedBaseMixin",
    "Tenant",
    "TenantTier",
    "OnboardingMode",
    "TenantPayout",
    "Product",
    "ProductType",
    "LicenseStatus",
    "TelegramBot",
    "TenantWhatsAppChannel",
    "ChannelStatus",
    "MerchantDevice",
    "ActivationCode",
    "DeviceStatus",
    "ActivationCodeStatus",
    # Partner & Whitelist Exports
    "Partner",
    "PartnerRole",
    "PartnerStatus",
    "PartnerBankAccount",
    "PayoutRequest",
    "PayoutStatus",
    "AllowedBank",
]

