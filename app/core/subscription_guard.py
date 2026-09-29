"""
app/core/subscription_guard.py
Centralized subscription guard for multi-tenant isolation and write-protection.
Zero Hardcoding Policy: Dynamically inspects Supabase tenants table.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import HTTPException, status

import uuid

logger = logging.getLogger("SUBSCRIPTION_GUARD")

SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD = {
    "error": "SUBSCRIPTION_REQUIRED",
    "message": "Masa aktif paket/trial telah berakhir. Toko dalam mode baca-saja. Silakan lakukan upgrade langganan.",
}


def _is_valid_uuid(val: Any) -> bool:
    try:
        uuid.UUID(str(val).strip())
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _parse_iso_datetime(dt_val: Any) -> Optional[datetime]:
    if not dt_val:
        return None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val
    try:
        s = str(dt_val).strip()
        # Handle trailing Z or offsets
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as exc:
        logger.debug(f"Failed to parse datetime '{dt_val}': {exc}")
        return None


def get_tenant_subscription_state(slug_or_id: str) -> Dict[str, Any]:
    """
    Queries Supabase 'tenants' table and determines whether the tenant
    is active or suspended/expired.
    Zero Hardcoding Policy: Dynamically inspects Supabase tenants table.
    """
    clean_target = str(slug_or_id or "").strip().lower()
    if not clean_target:
        return {
            "is_suspended": True,
            "subscription_status": "suspended",
            "reason": "Tenant identifier is empty.",
        }

    try:
        from app.services.whatsapp_service import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Could not initialize Supabase in subscription guard: {e}")
        supabase = None

    if not supabase:
        # Fallback to permissive if DB unavailable
        return {
            "is_suspended": False,
            "subscription_status": "active",
            "reason": None,
        }

    try:
        # Query tenants table by slug or id safely without Postgres UUID cast error
        if _is_valid_uuid(clean_target):
            query = (
                supabase.from_("tenants")
                .select("id, slug, tier, is_active, status, subscription_ends_at, trial_ends_at, metadata")
                .eq("id", clean_target)
            )
        else:
            query = (
                supabase.from_("tenants")
                .select("id, slug, tier, is_active, status, subscription_ends_at, trial_ends_at, metadata")
                .eq("slug", clean_target)
            )
        res = query.limit(1).execute()
        data = res.data if res else None
        if not data or len(data) == 0:
            return {
                "is_suspended": False,
                "not_found": True,
                "subscription_status": "unknown",
                "reason": "Tenant not found.",
            }

        t_row = data[0]
        t_status = str(t_row.get("status") or "active").strip().lower()
        is_active = t_row.get("is_active") is not False
        meta = t_row.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}

        meta_sub_status = str(meta.get("subscription_status") or "").strip().lower()

        # Check Special Grant
        sub_obj = meta.get("subscription") if isinstance(meta.get("subscription"), dict) else {}
        is_special_grant = bool(
            sub_obj.get("type") == "granted"
            or sub_obj.get("subscription_type") == "granted"
            or sub_obj.get("billing_cycle") == "grant"
            or meta.get("subscription_type") == "granted"
            or sub_obj.get("is_grant") is True
        )

        if is_special_grant:
            return {
                "tenant_id": t_row.get("id"),
                "slug": t_row.get("slug"),
                "tier": t_row.get("tier"),
                "is_active": is_active,
                "status": t_status,
                "subscription_status": "active",
                "is_suspended": False,
                "reason": None,
                "trial_ends_at": t_row.get("trial_ends_at") or meta.get("trial_ends_at"),
                "subscription_ends_at": t_row.get("subscription_ends_at") or meta.get("subscription_ends_at"),
                "metadata": meta,
            }

        now = datetime.now(timezone.utc)
        is_suspended = False
        reason = None

        # 1. Explicit status check
        if t_status in ["expired", "suspended"] or meta_sub_status in ["expired", "suspended"]:
            is_suspended = True
            reason = "Masa aktif paket/trial telah berakhir. Toko dalam mode baca-saja. Silakan lakukan upgrade langganan."

        # 2. Deactivated tenant
        elif not is_active:
            is_suspended = True
            reason = "Status toko non-aktif."

        # 3. Check trial expiration
        else:
            is_trial = (
                t_status == "trial"
                or meta_sub_status == "trial"
                or bool(meta.get("is_trial"))
                or bool(t_row.get("trial_ends_at"))
                or bool(meta.get("trial_ends_at"))
            )
            trial_ends_at = _parse_iso_datetime(t_row.get("trial_ends_at") or meta.get("trial_ends_at"))
            sub_ends_at = _parse_iso_datetime(t_row.get("subscription_ends_at") or meta.get("subscription_ends_at"))

            if is_trial and trial_ends_at:
                if now > trial_ends_at:
                    if not sub_ends_at or now > sub_ends_at:
                        is_suspended = True
                        reason = "Masa aktif paket/trial telah berakhir. Toko dalam mode baca-saja. Silakan lakukan upgrade langganan."

            if not is_suspended and sub_ends_at:
                if now > sub_ends_at:
                    is_suspended = True
                    reason = "Masa aktif paket/trial telah berakhir. Toko dalam mode baca-saja. Silakan lakukan upgrade langganan."

        resolved_status = "expired" if is_suspended else (meta_sub_status or t_status or "active")

        return {
            "tenant_id": t_row.get("id"),
            "slug": t_row.get("slug"),
            "tier": t_row.get("tier"),
            "is_active": is_active,
            "status": t_status,
            "subscription_status": resolved_status,
            "is_suspended": is_suspended,
            "reason": reason,
            "trial_ends_at": t_row.get("trial_ends_at") or meta.get("trial_ends_at"),
            "subscription_ends_at": t_row.get("subscription_ends_at") or meta.get("subscription_ends_at"),
            "metadata": meta,
        }

    except Exception as exc:
        logger.error(f"Error checking subscription status for {clean_target}: {exc}")
        return {
            "is_suspended": False,
            "subscription_status": "active",
            "reason": None,
        }


def assert_tenant_subscription_active(slug_or_id: str) -> Dict[str, Any]:
    """
    Guards execution against expired or suspended tenants.
    Raises HTTP 403 Forbidden with exact mandatory payload if subscription is not active.
    """
    state = get_tenant_subscription_state(slug_or_id)
    if state.get("is_suspended") or state.get("subscription_status") in ["expired", "suspended"]:
        logger.warning(
            f"[SUBSCRIPTION GUARD REJECTED] Tenant '{slug_or_id}' blocked from execution: {state.get('reason')}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD,
        )
    return state


def assert_tenant_mutation_allowed(slug_or_id: str) -> Dict[str, Any]:
    """
    Guards mutation endpoints (POST/PUT/PATCH/DELETE) against expired/suspended tenants.
    Enforces read-only mode for tenants whose trial has expired or subscription suspended.
    Raises HTTP 403 Forbidden with exact payload required by Acceptance Criteria:
    {"error": "SUBSCRIPTION_REQUIRED", "message": "Masa aktif paket/trial telah berakhir. Toko dalam mode baca-saja. Silakan lakukan upgrade langganan."}
    """
    state = get_tenant_subscription_state(slug_or_id)
    if state.get("is_suspended") or state.get("subscription_status") in ["expired", "suspended"]:
        logger.warning(
            f"[MUTATION GUARD REJECTED] Tenant '{slug_or_id}' blocked from mutation: {state.get('reason')}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD,
        )
    return state
