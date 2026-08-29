# Legacy / Existing Core Models
from app.models.domain import Goal, Intent, User
from app.models.digital_asset import Delivery, DigitalAsset, KnowledgeMapping

# Sprint 1 Multi-Tenant Foundations
from app.models.base import Base, TenantScopedBaseMixin
from app.models.tenant import Tenant, TenantTier, TenantPayout
from app.models.catalog import LicenseStatus, Product, ProductType
from app.models.channels import ChannelStatus, TelegramBot, TenantWhatsAppChannel
from app.models.device import (
    ActivationCode,
    ActivationCodeStatus,
    DeviceStatus,
    MerchantDevice,
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
]
