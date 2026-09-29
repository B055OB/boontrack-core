"""app/services/quota_service.py
Tenant AI Session Quota Decrement & Top-Up Service.

Architectural Authority (§3.1, §4.2, §8.4):
- Manages AI session quotas for multi-tenant stores (tenants table & tenant_quotas).
- Atomic decrement on bot reply to unique phone per 24-hour conversation window.
- Atomic increment on paid Xendit billing top-up invoices.
- Single Source of Truth: Supabase database.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple

from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("QUOTA_SERVICE")

# Tier Baseline Quotas
TIER_BASELINE_QUOTAS: Dict[str, int] = {
    "ENTERPRISE": 600,
    "TEAM_SCALE": 600,
    "PRO_SCALE": 300,
    "ADS_PERFORMANCE": 300,
    "STARTER": 150,
    "SOLO": 150,
    "CHECKOUT_LITE": 50,
    "LITE": 50,
}

# In-memory 24-hour session window tracker: {(tenant_slug, clean_phone): datetime}
_SESSION_WINDOWS: Dict[Tuple[str, str], datetime] = {}


def resolve_tier_baseline_quota(tier: Optional[str]) -> int:
    """Resolves base monthly sessions allocated for a given tier."""
    if not tier:
        return 150
    return TIER_BASELINE_QUOTAS.get(tier.strip().upper(), 150)


class QuotaService:
    """Service for atomic quota decrementing and top-up incrementing."""

    def is_session_active(self, tenant_slug: str, sender_phone: str) -> bool:
        """
        Checks if an active 24-hour conversation session window already exists
        for the given (tenant_slug, sender_phone).
        """
        clean_slug = (tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in sender_phone if c.isdigit())
        key = (clean_slug, clean_phone)

        last_time = _SESSION_WINDOWS.get(key)
        if not last_time:
            return False

        now = datetime.now(timezone.utc)
        if (now - last_time).total_seconds() < 86400:  # 24 hours
            return True

        return False

    def mark_session_active(self, tenant_slug: str, sender_phone: str) -> None:
        """Registers or extends the 24-hour conversation window for a unique contact."""
        clean_slug = (tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in sender_phone if c.isdigit())
        _SESSION_WINDOWS[(clean_slug, clean_phone)] = datetime.now(timezone.utc)

    async def get_tenant_quota(self, tenant_slug: str) -> Dict[str, Any]:
        """
        Fetches current quota stats for a tenant from Supabase.
        """
        clean_slug = (tenant_slug or "").strip().lower()
        supabase = get_supabase()
        if not supabase:
            base = 150
            return {
                "tier": "STARTER",
                "base_quota": base,
                "overage_quota": 0,
                "total_quota": base,
                "used_sessions": 0,
                "remaining_sessions": base,
                "percentage": 100,
                "is_low": False,
                "is_depleted": False,
            }

        try:
            res = supabase.from_("tenants").select("id, slug, tier, metadata").eq("slug", clean_slug).maybe_single().execute()
            tenant = res.data if res else None
            if not tenant:
                return {"error": "Tenant not found", "remaining_sessions": 0}

            metadata = tenant.get("metadata") or {}
            tier = str(tenant.get("tier") or metadata.get("plan_tier") or "STARTER").upper()
            base_quota = resolve_tier_baseline_quota(tier)
            overage_quota = int(metadata.get("overage_sessions") or 0)
            total_quota = base_quota + overage_quota

            # Read remaining sessions
            if "sessions_remaining" in metadata and metadata["sessions_remaining"] is not None:
                remaining_sessions = max(0, int(metadata["sessions_remaining"]))
                used_sessions = max(0, total_quota - remaining_sessions)
            else:
                used_sessions = int(metadata.get("ai_sessions_used") or 0)
                remaining_sessions = max(0, total_quota - used_sessions)

            percentage = round((remaining_sessions / total_quota) * 100) if total_quota > 0 else 0
            is_low = remaining_sessions <= max(1, round(total_quota * 0.2))
            is_depleted = remaining_sessions <= 0

            return {
                "tier": tier,
                "base_quota": base_quota,
                "overage_quota": overage_quota,
                "total_quota": total_quota,
                "used_sessions": used_sessions,
                "remaining_sessions": remaining_sessions,
                "percentage": percentage,
                "is_low": is_low,
                "is_depleted": is_depleted,
            }
        except Exception as e:
            logger.error(f"[QUOTA_FETCH_ERROR] {clean_slug}: {e}")
            return {"error": str(e), "remaining_sessions": 0}

    async def decrement_session_quota_if_eligible(
        self,
        tenant_slug: str,
        sender_phone: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Checks 24-hour window for (tenant_slug, sender_phone).
        If new or expired window:
        Atomically decrements sessions_remaining by 1 and increments ai_sessions_used by 1.
        """
        clean_slug = (tenant_slug or "").strip().lower()
        clean_phone = "".join(c for c in sender_phone if c.isdigit())
        if not clean_slug or not clean_phone:
            return None

        # 1. 24-Hour Session Window Check (deduplicate within 24h)
        if self.is_session_active(clean_slug, clean_phone):
            logger.debug(
                f"[QUOTA_WINDOW_HIT] Sesi aktif 24 jam masih berlaku untuk {clean_phone} di tenant '{clean_slug}'. Tidak memotong kuota."
            )
            return None

        # 2. Mark session active immediately to prevent concurrent duplicate deductions
        self.mark_session_active(clean_slug, clean_phone)

        supabase = get_supabase()
        if not supabase:
            logger.warning("[QUOTA_DECREMENT] Supabase client not available, deduction skipped.")
            return None

        try:
            res = supabase.from_("tenants").select("id, slug, tier, metadata").eq("slug", clean_slug).maybe_single().execute()
            tenant = res.data if res else None
            if not tenant:
                logger.warning(f"[QUOTA_DECREMENT] Tenant '{clean_slug}' not found.")
                return None

            metadata = tenant.get("metadata") or {}
            tier = str(tenant.get("tier") or metadata.get("plan_tier") or "STARTER").upper()
            base_quota = resolve_tier_baseline_quota(tier)
            overage_quota = int(metadata.get("overage_sessions") or 0)
            total_quota = base_quota + overage_quota

            # Read current remaining
            if "sessions_remaining" in metadata and metadata["sessions_remaining"] is not None:
                current_remaining = max(0, int(metadata["sessions_remaining"]))
            else:
                used = int(metadata.get("ai_sessions_used") or 0)
                current_remaining = max(0, total_quota - used)

            new_remaining = max(0, current_remaining - 1)
            new_used = int(metadata.get("ai_sessions_used") or 0) + 1
            now_iso = datetime.now(timezone.utc).isoformat()

            metadata["sessions_remaining"] = new_remaining
            metadata["ai_sessions_used"] = new_used
            metadata["last_session_deduction_at"] = now_iso

            # Update Supabase tenants metadata
            supabase.from_("tenants").update({"metadata": metadata}).eq("slug", clean_slug).execute()

            # Optional update to tenant_quotas table if it exists
            try:
                supabase.from_("tenant_quotas").upsert({
                    "tenant_id": tenant.get("id"),
                    "slug": clean_slug,
                    "sessions_remaining": new_remaining,
                    "updated_at": now_iso,
                }).execute()
            except Exception:
                pass

            logger.info(
                f"[QUOTA_DECREMENT_SUCCESS] Tenant '{clean_slug}': remaining={new_remaining}/{total_quota} "
                f"(used={new_used}) | Sender: {clean_phone}"
            )

            return {
                "status": "decremented",
                "tenant_slug": clean_slug,
                "remaining_sessions": new_remaining,
                "used_sessions": new_used,
                "total_quota": total_quota,
            }
        except Exception as err:
            logger.error(f"[QUOTA_DECREMENT_ERROR] Tenant '{clean_slug}': {err}")
            return None

    async def increment_session_quota(
        self,
        tenant_slug: str,
        additional_sessions: int,
        invoice_id: Optional[str] = None,
        package_id: Optional[str] = None,
        amount_paid: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Atomically increments sessions_remaining and overage_sessions upon successful payment.
        Logs invoice to billing_invoices history.
        """
        clean_slug = (tenant_slug or "").strip().lower()
        if additional_sessions <= 0:
            return {"error": "additional_sessions must be positive"}

        supabase = get_supabase()
        if not supabase:
            return {"error": "Supabase client not available"}

        try:
            res = supabase.from_("tenants").select("id, slug, tier, metadata").eq("slug", clean_slug).maybe_single().execute()
            tenant = res.data if res else None
            if not tenant:
                return {"error": f"Tenant '{clean_slug}' not found"}

            metadata = tenant.get("metadata") or {}
            tier = str(tenant.get("tier") or metadata.get("plan_tier") or "STARTER").upper()
            base_quota = resolve_tier_baseline_quota(tier)
            current_overage = int(metadata.get("overage_sessions") or 0)
            new_overage = current_overage + additional_sessions

            # Calculate current remaining
            if "sessions_remaining" in metadata and metadata["sessions_remaining"] is not None:
                current_remaining = max(0, int(metadata["sessions_remaining"]))
            else:
                used = int(metadata.get("ai_sessions_used") or 0)
                current_remaining = max(0, (base_quota + current_overage) - used)

            new_remaining = current_remaining + additional_sessions
            now_iso = datetime.now(timezone.utc).isoformat()

            metadata["sessions_remaining"] = new_remaining
            metadata["overage_sessions"] = new_overage
            metadata["last_quota_topup"] = {
                "invoice_id": invoice_id,
                "package_id": package_id or "topup",
                "sessions_added": additional_sessions,
                "amount": amount_paid,
                "timestamp": now_iso,
            }

            # Update tenant
            supabase.from_("tenants").update({"metadata": metadata}).eq("slug", clean_slug).execute()

            # Record history to billing_invoices
            invoice_record = {
                "tenant_id": tenant.get("id"),
                "tenant_slug": clean_slug,
                "invoice_id": invoice_id or f"topup_{int(datetime.now().timestamp())}",
                "type": "SESSION_QUOTA_TOPUP",
                "sessions_added": additional_sessions,
                "amount": amount_paid or 0,
                "status": "PAID",
                "created_at": now_iso,
                "metadata": {
                    "package_id": package_id,
                    "tier": tier,
                    "new_remaining": new_remaining,
                },
            }

            try:
                supabase.from_("billing_invoices").insert(invoice_record).execute()
            except Exception as _bi_err:
                # If table does not exist, persist into tenant metadata history array
                history = metadata.setdefault("billing_invoices_history", [])
                history.append(invoice_record)
                supabase.from_("tenants").update({"metadata": metadata}).eq("slug", clean_slug).execute()

            # Optional update to tenant_quotas
            try:
                supabase.from_("tenant_quotas").upsert({
                    "tenant_id": tenant.get("id"),
                    "slug": clean_slug,
                    "sessions_remaining": new_remaining,
                    "updated_at": now_iso,
                }).execute()
            except Exception:
                pass

            logger.info(
                f"[QUOTA_INCREMENT_SUCCESS] Tenant '{clean_slug}': +{additional_sessions} sessions. "
                f"New remaining={new_remaining} | Invoice={invoice_id}"
            )

            return {
                "status": "success",
                "tenant_slug": clean_slug,
                "sessions_added": additional_sessions,
                "new_remaining_sessions": new_remaining,
                "total_overage": new_overage,
                "tier": tier,
            }
        except Exception as err:
            logger.error(f"[QUOTA_INCREMENT_ERROR] Tenant '{clean_slug}': {err}")
            return {"error": str(err)}


quota_service = QuotaService()
