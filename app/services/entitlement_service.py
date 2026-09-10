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
PlanId = Literal["SOLO_TRIAL", "FREE", "SOLO", "ADS_PERF", "TEAM_SCALE"]


class TenantCapabilities(BaseModel):
    catalog: bool = True
    orders: bool = True
    qris: bool = True
    ai_bot: bool = False
    shipping: bool = False
    meta_capi: bool = False
    multi_cs: bool = False


class TenantLimits(BaseModel):
    order_quota: int = 50          # 0 = unlimited
    ai_conversations: int = 0      # 0 = disabled


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
    "SOLO_TRIAL": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": True, "multi_cs": False,
        },
        "limits": {"order_quota": 100, "ai_conversations": 250},
    },
    "FREE": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": False, "shipping": False,
            "meta_capi": False, "multi_cs": False,
        },
        "limits": {"order_quota": 50, "ai_conversations": 0},
    },
    "SOLO": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": False, "multi_cs": False,
        },
        "limits": {"order_quota": 0, "ai_conversations": 250},
    },
    "ADS_PERF": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": True, "multi_cs": False,
        },
        "limits": {"order_quota": 0, "ai_conversations": 500},
    },
    "TEAM_SCALE": {
        "capabilities": {
            "catalog": True, "orders": True, "qris": True,
            "ai_bot": True, "shipping": True,
            "meta_capi": True, "multi_cs": True,
        },
        "limits": {"order_quota": 0, "ai_conversations": 1000},
    },
}


def _static_context(
    tenant_id: str,
    plan_id: str,
    status: str = "FREE",
    business_type: BusinessType = "PHYSICAL",
    trial_ends_at: Optional[str] = None,
) -> TenantRuntimeContext:
    """Bangun TenantRuntimeContext dari preset statis (fallback)."""
    safe_plan = plan_id.upper() if plan_id.upper() in _PLAN_DEFAULTS else "FREE"
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

    @staticmethod
    async def resolve(
        tenant_slug: str,
        supabase_client=None,
    ) -> TenantRuntimeContext:
        """
        Resolve runtime context untuk tenant_slug.

        1. Jika supabase_client tersedia, baca dari tabel `tenant_entitlements`
           + join `plan_entitlements` untuk capabilities.
        2. Fallback ke preset statis (FREE) jika record tidak ditemukan.
        """
        clean_slug = str(tenant_slug or "").strip().lower()
        if not clean_slug:
            logger.warning("[ENTITLEMENT] Empty tenant_slug → fallback FREE")
            return _static_context("unknown", "FREE")

        # ── Path 1: Baca dari Supabase ──────────────────────────────────────
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
                logger.error(f"[ENTITLEMENT] DB error untuk {clean_slug}: {exc} → fallback statis")

        # ── Path 2: Fallback statis ─────────────────────────────────────────
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

        if raw_data:
            plan_id = str(raw_data.get("plan_id", "FREE")).upper()
            status = str(raw_data.get("status", "FREE"))
            business_type: BusinessType = raw_data.get("business_type", "PHYSICAL")  # type: ignore
            trial_ends_at = raw_data.get("trial_ends_at")
            return _static_context(clean_slug, plan_id, status, business_type, trial_ends_at)

        return _static_context(clean_slug, "FREE")

    @staticmethod
    def can_use(context: TenantRuntimeContext, feature_key: str) -> bool:
        """Guard helper: apakah tenant boleh menggunakan fitur ini?"""
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
