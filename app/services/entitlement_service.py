"""
app/services/entitlement_service.py
====================================
BoonTrack Entitlement Engine & Reverse Trial Resolver.

Menghasilkan runtime context per-tenant:
  - plan (SOLO_TRIAL / FREE / SOLO / ADS_PERF / TEAM_SCALE)
  - capabilities (dict boolean fitur)
  - limits (order_quota, ai_conversations)

Sumber data: tabel `tenant_entitlements` & `plan_entitlements` di Supabase.
Fallback ke FREE jika tenant belum memiliki record entitlement.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel

logger = logging.getLogger("ENTITLEMENT_SERVICE")

# ---------------------------------------------------------------------------
# Pydantic Schemas (runtime output)
# ---------------------------------------------------------------------------

BusinessType = Literal["DIGITAL", "PHYSICAL", "FIELD_SERVICE"]
PlanId = Literal["CHECKOUT_LITE", "SOLO_TRIAL", "FREE", "SOLO", "ADS_PERF", "TEAM_SCALE"]


# Granular nested capability schemas for structured entitlement checking
class StorefrontCaps(BaseModel):
    single_page: bool = True

class ProductsCaps(BaseModel):
    max_active: int = 3

class OrdersCaps(BaseModel):
    basic: bool = True

class PaymentCaps(BaseModel):
    qris: bool = True

class CheckoutCaps(BaseModel):
    digital: bool = True
    physical: bool = True

class ShippingCaps(BaseModel):
    basic: bool = True
    max_providers: int = 1

class TrackingCaps(BaseModel):
    meta: bool = True
    capi: bool = False

class AnalyticsCaps(BaseModel):
    advanced: bool = False


class TenantCapabilities(BaseModel):
    catalog: bool = True
    orders: bool = True
    qris: bool = True
    ai_bot: bool = False
    shipping: bool = False
    meta_capi: bool = False
    multi_cs: bool = False
    powertools: bool = False
    affiliate: bool = False

    # Granular capability attributes
    single_page: bool = True
    shipping_basic: bool = True
    meta_pixel: bool = True
    analytics_advanced: bool = False
    multi_user: bool = False
    broadcast: bool = False

    # Nested namespaces for structured entitlement queries
    storefront: StorefrontCaps = StorefrontCaps()
    products: ProductsCaps = ProductsCaps()
    orders_detail: OrdersCaps = OrdersCaps()
    payment: PaymentCaps = PaymentCaps()
    checkout: CheckoutCaps = CheckoutCaps()
    shipping_detail: ShippingCaps = ShippingCaps()
    tracking: TrackingCaps = TrackingCaps()
    analytics: AnalyticsCaps = AnalyticsCaps()


class TenantLimits(BaseModel):
    order_quota: int = 50          # 0 = unlimited
    ai_conversations: int = 0      # 0 = disabled
    max_active_products: int = 0   # 0 = unlimited, 3 for CHECKOUT_LITE
    shipping_providers_max: int = 0 # 0 = unlimited, 1 for CHECKOUT_LITE


class TenantRuntimeContext(BaseModel):
    tenant_id: str
    business_type: BusinessType = "PHYSICAL"
    plan: PlanId = "FREE"
    status: str = "FREE"          # TRIALING | ACTIVE | EXPIRED | FREE
    trial_ends_at: Optional[str] = None
    capabilities: TenantCapabilities = TenantCapabilities()
    limits: TenantLimits = TenantLimits()


# ---------------------------------------------------------------------------
# Static Fallback Definitions
# (dipakai jika DB tidak tersedia / cold-start tanpa tabel entitlement)
# ---------------------------------------------------------------------------

_PLAN_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "CHECKOUT_LITE": {
        "capabilities": {
            "catalog": True,
            "orders": True,
            "qris": True,
            "ai_bot": False,
            "shipping": True,
            "shipping_basic": True,
            "meta_capi": False,
            "multi_cs": False,
            "powertools": False,
            "affiliate": False,
            "single_page": True,
            "meta_pixel": True,
            "analytics_advanced": False,
            "multi_user": False,
            "broadcast": False,
            "storefront": {"single_page": True},
            "products": {"max_active": 3},
            "orders_detail": {"basic": True},
            "payment": {"qris": True},
            "checkout": {"digital": True, "physical": True},
            "shipping_detail": {"basic": True, "max_providers": 1},
            "tracking": {"meta": True, "capi": False},
            "analytics": {"advanced": False},
        },
        "limits": {
            "order_quota": 0,
            "ai_conversations": 0,
            "max_active_products": 3,
            "shipping_providers_max": 1,
        },
    },
    "SOLO_TRIAL": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": True, "multi_cs": False,
            "powertools": True, "affiliate": False,
            "single_page": True, "shipping_basic": True, "meta_pixel": True,
            "analytics_advanced": True, "multi_user": False, "broadcast": True,
            "storefront": {"single_page": True},
            "products": {"max_active": 0},
            "orders_detail": {"basic": True},
            "payment": {"qris": True},
            "checkout": {"digital": True, "physical": True},
            "shipping_detail": {"basic": True, "max_providers": 0},
            "tracking": {"meta": True, "capi": True},
            "analytics": {"advanced": True},
        },
        "limits": {"order_quota": 30, "ai_conversations": 50, "max_active_products": 0, "shipping_providers_max": 0},
    },
    "FREE": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": False, "shipping": False,
            "meta_capi": False, "multi_cs": False,
            "powertools": False, "affiliate": False,
            "single_page": False, "shipping_basic": False, "meta_pixel": False,
            "analytics_advanced": False, "multi_user": False, "broadcast": False,
            "storefront": {"single_page": False},
            "products": {"max_active": 1},
            "orders_detail": {"basic": True},
            "payment": {"qris": True},
            "checkout": {"digital": False, "physical": False},
            "shipping_detail": {"basic": False, "max_providers": 0},
            "tracking": {"meta": False, "capi": False},
            "analytics": {"advanced": False},
        },
        "limits": {"order_quota": 50, "ai_conversations": 0, "max_active_products": 1, "shipping_providers_max": 0},
    },
    "SOLO": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": False, "multi_cs": False,
            "powertools": False, "affiliate": False,
            "single_page": True, "shipping_basic": True, "meta_pixel": True,
            "analytics_advanced": False, "multi_user": False, "broadcast": False,
            "storefront": {"single_page": True},
            "products": {"max_active": 0},
            "orders_detail": {"basic": True},
            "payment": {"qris": True},
            "checkout": {"digital": True, "physical": True},
            "shipping_detail": {"basic": True, "max_providers": 0},
            "tracking": {"meta": True, "capi": False},
            "analytics": {"advanced": False},
        },
        "limits": {"order_quota": 0, "ai_conversations": 250, "max_active_products": 0, "shipping_providers_max": 0},
    },
    "ADS_PERF": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": True, "multi_cs": False,
            "powertools": True, "affiliate": False,
            "single_page": True, "shipping_basic": True, "meta_pixel": True,
            "analytics_advanced": True, "multi_user": False, "broadcast": True,
            "storefront": {"single_page": True},
            "products": {"max_active": 0},
            "orders_detail": {"basic": True},
            "payment": {"qris": True},
            "checkout": {"digital": True, "physical": True},
            "shipping_detail": {"basic": True, "max_providers": 0},
            "tracking": {"meta": True, "capi": True},
            "analytics": {"advanced": True},
        },
        "limits": {"order_quota": 0, "ai_conversations": 500, "max_active_products": 0, "shipping_providers_max": 0},
    },
    "TEAM_SCALE": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": True, "multi_cs": True,
            "powertools": True, "affiliate": True,
            "single_page": True, "shipping_basic": True, "meta_pixel": True,
            "analytics_advanced": True, "multi_user": True, "broadcast": True,
            "storefront": {"single_page": True},
            "products": {"max_active": 0},
            "orders_detail": {"basic": True},
            "payment": {"qris": True},
            "checkout": {"digital": True, "physical": True},
            "shipping_detail": {"basic": True, "max_providers": 0},
            "tracking": {"meta": True, "capi": True},
            "analytics": {"advanced": True},
        },
        "limits": {"order_quota": 0, "ai_conversations": 1000, "max_active_products": 0, "shipping_providers_max": 0},
    },
}

_TENANT_PLAN_OVERRIDES: Dict[str, str] = {
    "onlineboost": "ADS_PERF",
    "growthplus": "ADS_PERF",
    "proscale": "ADS_PERF",
    "boontrack-career": "TEAM_SCALE",
}


def _static_context(
    tenant_id: str,
    plan_id: str,
    status: str = "FREE",
    business_type: BusinessType = "PHYSICAL",
    trial_ends_at: Optional[str] = None,
) -> TenantRuntimeContext:
    """Bangun TenantRuntimeContext dari preset statis (fallback)."""
    clean_plan = plan_id.upper().replace("-", "_")
    safe_plan = clean_plan if clean_plan in _PLAN_DEFAULTS else "FREE"
    defaults = _PLAN_DEFAULTS[safe_plan]
    return TenantRuntimeContext(
        tenant_id=tenant_id,
        business_type=business_type,
        plan=safe_plan,  # type: ignore[arg-type]
        status=status,
        trial_ends_at=trial_ends_at,
        capabilities=TenantCapabilities(**defaults["capabilities"]),
        limits=TenantLimits(**defaults["limits"]),
    )


# ---------------------------------------------------------------------------
# TenantContextResolver
# ---------------------------------------------------------------------------

class TenantContextResolver:
    """
    Resolver utama entitlement engine BoonTrack.

    Usage:
        ctx = await TenantContextResolver.resolve("toko-abc")
        if ctx.capabilities.ai_bot:
            # boleh pakai BoonPilot AI
    """

    @classmethod
    def register_plan_override(cls, tenant_slug: str, plan_id: str):
        """Registrasi plan override sementara (berguna untuk testing)."""
        _TENANT_PLAN_OVERRIDES[str(tenant_slug).strip().lower()] = plan_id.upper()

    @classmethod
    def clear_plan_overrides(cls):
        """Reset plan override kembali ke baseline default."""
        _TENANT_PLAN_OVERRIDES.clear()
        _TENANT_PLAN_OVERRIDES.update({
            "onlineboost": "ADS_PERF",
            "growthplus": "ADS_PERF",
            "proscale": "ADS_PERF",
            "boontrack-career": "TEAM_SCALE",
        })

    @staticmethod
    async def resolve(
        tenant_slug: str,
        supabase_client=None,
    ) -> TenantRuntimeContext:
        """
        Resolve runtime context untuk tenant_slug.

        1. Jika slug terdaftar di _TENANT_PLAN_OVERRIDES atau nama slug mengandung 'checkout_lite'/'checkout-lite',
           gunakan preset plan tersebut.
        2. Jika supabase_client tersedia, baca dari tabel `tenant_entitlements`
           + join `plan_entitlements` untuk capabilities.
        3. Fallback ke preset statis (FREE) jika record tidak ditemukan.
        """
        clean_slug = str(tenant_slug or "").strip().lower()
        if not clean_slug:
            logger.warning("[ENTITLEMENT] Empty tenant_slug -> fallback FREE")
            return _static_context("unknown", "FREE")

        # In-memory overrides & pattern matching
        if clean_slug in _TENANT_PLAN_OVERRIDES:
            return _static_context(clean_slug, _TENANT_PLAN_OVERRIDES[clean_slug])
        if "checkout_lite" in clean_slug or "checkout-lite" in clean_slug:
            return _static_context(clean_slug, "CHECKOUT_LITE")

        # Path 1: Baca dari Supabase
        if supabase_client is not None:
            try:
                row = (
                    supabase_client
                    .from_("tenant_entitlements")
                    .select(
                        "tenant_slug, plan_id, status, business_type, "
                        "trial_ends_at, order_quota_used, ai_conversations_used"
                    )
                    .eq("tenant_slug", clean_slug)
                    .maybe_single()
                    .execute()
                )
                data = row.data if row else None

                if data:
                    plan_id: str = data.get("plan_id", "FREE").upper()
                    status: str = data.get("status", "FREE")
                    business_type: BusinessType = data.get("business_type", "PHYSICAL")  # type: ignore
                    trial_ends_at: Optional[str] = data.get("trial_ends_at")

                    # Cek trial expired
                    if status == "TRIALING" and trial_ends_at:
                        try:
                            ends = datetime.fromisoformat(trial_ends_at.replace("Z", "+00:00"))
                            if ends < datetime.now(tz=timezone.utc):
                                status = "EXPIRED"
                                plan_id = "FREE"
                        except Exception:
                            pass

                    # Baca capabilities dari plan_entitlements
                    caps_row = (
                        supabase_client
                        .from_("plan_entitlements")
                        .select("feature_key, is_enabled")
                        .eq("plan_id", plan_id)
                        .execute()
                    )
                    caps_data = caps_row.data if caps_row else []

                    caps_dict: Dict[str, bool] = {}
                    for item in (caps_data or []):
                        caps_dict[item["feature_key"]] = bool(item.get("is_enabled", False))

                    # Merge dengan default agar field tidak hilang jika DB belum lengkap
                    safe_plan = plan_id if plan_id in _PLAN_DEFAULTS else "FREE"
                    merged_caps = {**_PLAN_DEFAULTS[safe_plan]["capabilities"], **caps_dict}
                    merged_limits = dict(_PLAN_DEFAULTS[safe_plan]["limits"])

                    return TenantRuntimeContext(
                        tenant_id=clean_slug,
                        business_type=business_type,
                        plan=safe_plan,  # type: ignore[arg-type]
                        status=status,
                        trial_ends_at=trial_ends_at,
                        capabilities=TenantCapabilities(**merged_caps),
                        limits=TenantLimits(**merged_limits),
                    )

            except Exception as exc:
                logger.error(f"[ENTITLEMENT] DB error untuk {clean_slug}: {exc} -> fallback statis")

        # Path 2: Fallback statis
        logger.info(f"[ENTITLEMENT] Fallback statis FREE untuk tenant: {clean_slug}")
        return _static_context(clean_slug, "FREE")

    @staticmethod
    def resolve_sync(
        tenant_slug: str,
        raw_data: Optional[Dict[str, Any]] = None,
    ) -> TenantRuntimeContext:
        """
        Versi synchronous (untuk konteks non-async seperti aiohttp middleware).
        Hanya menggunakan raw_data yang sudah diambil sebelumnya, atau fallback statis.
        """
        clean_slug = str(tenant_slug or "").strip().lower()

        if clean_slug in _TENANT_PLAN_OVERRIDES:
            return _static_context(clean_slug, _TENANT_PLAN_OVERRIDES[clean_slug])
        if "checkout_lite" in clean_slug or "checkout-lite" in clean_slug:
            return _static_context(clean_slug, "CHECKOUT_LITE")

        if raw_data:
            plan_id = str(raw_data.get("plan_id", "FREE")).upper()
            status = str(raw_data.get("status", "FREE"))
            business_type: BusinessType = raw_data.get("business_type", "PHYSICAL")  # type: ignore
            trial_ends_at = raw_data.get("trial_ends_at")
            return _static_context(clean_slug, plan_id, status, business_type, trial_ends_at)

        return _static_context(clean_slug, "FREE")

    @staticmethod
    def can_use(context: TenantRuntimeContext, feature_key: str) -> bool:
        """
        Guard helper: apakah tenant boleh menggunakan fitur ini?
        Mendukung flat key ('broadcast', 'ai_bot') dan dot-notation ('tracking.capi', 'analytics.advanced', 'storefront.single_page').
        """
        clean_key = str(feature_key or "").strip().lower()

        # Direct mapped checks for known features
        if clean_key == "broadcast":
            return bool(context.capabilities.broadcast)
        if clean_key in ("multi_user", "multi-user"):
            return bool(context.capabilities.multi_user)
        if clean_key in ("analytics.advanced", "analytics_advanced"):
            return bool(context.capabilities.analytics_advanced or (hasattr(context.capabilities, "analytics") and getattr(context.capabilities.analytics, "advanced", False)))
        if clean_key in ("tracking.capi", "meta_capi"):
            return bool(context.capabilities.meta_capi and (hasattr(context.capabilities, "tracking") and getattr(context.capabilities.tracking, "capi", False)))
        if clean_key in ("tracking.meta", "meta_pixel", "tracking.pixel"):
            return bool(context.capabilities.meta_pixel or (hasattr(context.capabilities, "tracking") and getattr(context.capabilities.tracking, "meta", False)))
        if clean_key in ("storefront.single_page", "single_page"):
            return bool(context.capabilities.single_page or (hasattr(context.capabilities, "storefront") and getattr(context.capabilities.storefront, "single_page", False)))
        if clean_key in ("shipping.basic", "shipping_basic"):
            return bool(context.capabilities.shipping_basic or (hasattr(context.capabilities, "shipping_detail") and getattr(context.capabilities.shipping_detail, "basic", False)))
        if clean_key in ("payment.qris", "qris"):
            return bool(context.capabilities.qris or (hasattr(context.capabilities, "payment") and getattr(context.capabilities.payment, "qris", False)))
        if clean_key == "checkout.digital":
            return bool(hasattr(context.capabilities, "checkout") and getattr(context.capabilities.checkout, "digital", False))
        if clean_key == "checkout.physical":
            return bool(hasattr(context.capabilities, "checkout") and getattr(context.capabilities.checkout, "physical", False))
        if clean_key == "orders.basic":
            return bool(context.capabilities.orders or (hasattr(context.capabilities, "orders_detail") and getattr(context.capabilities.orders_detail, "basic", False)))

        # Generic dot notation traversal
        if "." in feature_key:
            parts = feature_key.split(".")
            current: Any = context.capabilities
            for part in parts:
                if hasattr(current, part):
                    current = getattr(current, part)
                elif isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return False
            return bool(current)

        return bool(getattr(context.capabilities, feature_key, False))

    @staticmethod
    def is_trial_active(context: TenantRuntimeContext) -> bool:
        """True jika tenant sedang dalam masa trial yang belum expired."""
        if context.status != "TRIALING":
            return False
        if not context.trial_ends_at:
            return True
        try:
            ends = datetime.fromisoformat(context.trial_ends_at.replace("Z", "+00:00"))
            return ends > datetime.now(tz=timezone.utc)
        except Exception:
            return False

    @staticmethod
    def is_quota_exceeded(context: TenantRuntimeContext, quota_type: str, used: int) -> bool:
        """
        Cek apakah kuota sudah habis.
        quota_type: 'order_quota' | 'ai_conversations'
        Kuota 0 = unlimited.
        """
        limit = getattr(context.limits, quota_type, 0)
        if limit == 0:
            return False  # unlimited
        return used >= limit


# Singleton instance
tenant_context_resolver = TenantContextResolver()
