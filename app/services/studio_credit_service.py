"""app/services/studio_credit_service.py
Core-owned Studio Credit Settlement & Entitlement Service.
Authoritative SSOT for Xendit webhook settlements of Studio render credits and AI utilities.
"""

import os
import re
import uuid
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from app.services.whatsapp_service import get_supabase
from app.core.database import get_db_connection

logger = logging.getLogger("STUDIO_CREDIT_SERVICE")

# Studio Token Packages SSOT (mirrors inbox studio-pricing.ts)
STUDIO_TOKEN_PACKAGES = {
    "ketengan": {
        "name": "Paket Ketengan",
        "credits": 5,
        "public_price": 20000,
        "member_price": 15000,
    },
    "starter": {
        "name": "Paket Starter",
        "credits": 25,
        "public_price": 75000,
        "member_price": 49000,
    },
    "creator": {
        "name": "Paket Kreator Hemat",
        "credits": 50,
        "public_price": 135000,
        "member_price": 89000,
    },
    "pro_monthly": {
        "name": "Langganan Studio Pro",
        "credits": 100,
        "public_price": 149000,
        "member_price": 149000,
    },
}

PACKAGE_CREDIT_MAP = {
    5: "ketengan",
    10: "ketengan",  # legacy support
    25: "starter",
    50: "creator",
    100: "pro_monthly",
}


class StudioCreditService:
    """Core-owned Studio Credit Service managing entitlements and immutable credit ledger."""

    def resolve_tenant(self, tenant_id_or_slug: str) -> Optional[Dict[str, Any]]:
        """Authoritatively resolves tenant by UUID or slug from Supabase.
        Fails closed on sandbox/dummy slugs ('creator', 'sandbox', 'studio').
        """
        clean = str(tenant_id_or_slug or "").strip().lower()
        if not clean or clean in ("creator", "sandbox", "studio"):
            logger.warning(f"[StudioCreditService] Rejected invalid or sandbox tenant slug: '{clean}'")
            return None

        supabase = get_supabase()
        if not supabase:
            logger.warning("[StudioCreditService] Supabase client unavailable for resolve_tenant")
            return None

        try:
            # Detect UUID
            is_uuid = False
            try:
                uuid.UUID(clean)
                is_uuid = True
            except ValueError:
                is_uuid = False

            if is_uuid:
                res = supabase.table("tenants").select("id, slug, tier, metadata").eq("id", clean).limit(1).execute()
            else:
                res = supabase.table("tenants").select("id, slug, tier, metadata").eq("slug", clean).limit(1).execute()

            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            logger.error(f"[StudioCreditService] Error resolving tenant '{clean}': {e}")

        return None

    def is_tenant_shop_member(self, tenant: Optional[Dict[str, Any]]) -> bool:
        """Determines if a tenant is an active Shop subscriber (entitled to discounted member pricing)."""
        if not tenant:
            return False
        tier = str(tenant.get("tier") or "").upper()
        paid_tiers = {"SOLO", "PRO_SCALE", "ADS_PERFORMANCE", "ENTERPRISE", "TEAM_SCALE", "PRO", "FOUNDER", "MEMBER"}
        if tier in paid_tiers:
            return True
        meta = tenant.get("metadata") or {}
        if isinstance(meta, dict):
            if any(meta.get(k) is True for k in ("is_shop_member", "is_shop_subscriber", "is_subscriber", "has_active_shop", "is_tenant_subscriber")):
                return True
        return False

    def parse_external_id(self, external_id: str, metadata: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], Optional[str], int]:
        """Parses external_id and optional metadata into (tenant_slug, package_id, credits)."""
        meta = metadata or {}
        slug_candidate = meta.get("tenant_slug") or meta.get("tenant_id")
        package_candidate = meta.get("package_id")
        credits_candidate = int(meta.get("credits") or 0)

        # Regex parsing patterns:
        # Pattern 1: TOPUP-STUDIO-{tenantSlug}-{packageId}-{credits}-{timestamp}
        # Pattern 2: TOPUP-STUDIO-{tenantSlug}-{credits}-{timestamp}
        m_pkg = re.match(
            r"^TOPUP[-_]STUDIO[-_](.+?)[-_](ketengan|starter|creator|pro_monthly)[-_](\d+)[-_]([a-zA-Z0-9]+)$",
            external_id,
            re.IGNORECASE,
        )
        m_simple = re.match(
            r"^TOPUP[-_]STUDIO[-_](.+?)[-_](\d+)[-_]([a-zA-Z0-9]+)$",
            external_id,
            re.IGNORECASE,
        )

        if m_pkg:
            if not slug_candidate:
                slug_candidate = m_pkg.group(1)
            package_candidate = m_pkg.group(2).lower()
            credits_candidate = int(m_pkg.group(3))
        elif m_simple:
            if not slug_candidate:
                slug_candidate = m_simple.group(1)
            credits_candidate = int(m_simple.group(2))
            if not package_candidate:
                package_candidate = PACKAGE_CREDIT_MAP.get(credits_candidate, "starter")

        return slug_candidate, package_candidate, credits_candidate

    async def process_studio_credit_topup(
        self,
        external_id: str,
        amount: int,
        event_id: str,
        event_status: str,
        payload: Dict[str, Any],
        headers: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Authoritative Core handler for Studio Render Credit & AI Utility Top-Ups.
        Validates tenant, package amount, idempotency, updates entitlements, and logs audit ledger.
        """
        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        metadata = payload.get("metadata") or data_obj.get("metadata") or {}

        slug_candidate, package_id, credits = self.parse_external_id(external_id, metadata)

        # 1. Authoritative Tenant Resolution (Fail-Closed)
        tenant = self.resolve_tenant(slug_candidate)
        if not tenant:
            logger.error(f"[Studio Topup Failed] Tenant '{slug_candidate}' could not be resolved from database for order '{external_id}'")
            return {
                "success": False,
                "status": "TENANT_NOT_FOUND",
                "message": f"Tenant '{slug_candidate}' not found or invalid",
                "order_id": external_id,
            }

        tenant_id = tenant["id"]
        tenant_slug = tenant["slug"]

        # 2. Package & Amount Validation (Fail-Closed)
        if not package_id or package_id not in STUDIO_TOKEN_PACKAGES:
            # Fallback deduction from credits count
            package_id = PACKAGE_CREDIT_MAP.get(credits)

        if not package_id or package_id not in STUDIO_TOKEN_PACKAGES:
            logger.error(f"[Studio Topup Failed] Unknown package '{package_id}' for order '{external_id}'")
            return {
                "success": False,
                "status": "INVALID_PACKAGE",
                "message": f"Unknown Studio credit package '{package_id}'",
                "order_id": external_id,
            }

        pkg_spec = STUDIO_TOKEN_PACKAGES[package_id]
        if credits <= 0:
            credits = pkg_spec["credits"]

        is_member = self.is_tenant_shop_member(tenant)
        valid_prices = {pkg_spec["member_price"], pkg_spec["public_price"]}

        if amount not in valid_prices:
            logger.error(f"[Studio Topup Failed] Amount mismatch for order '{external_id}': paid Rp{amount:,}, expected one of {valid_prices}")
            return {
                "success": False,
                "status": "AMOUNT_MISMATCH",
                "message": f"Amount Rp{amount:,} does not match valid package prices for '{package_id}'",
                "order_id": external_id,
            }

        supabase = get_supabase()
        if not supabase:
            logger.error("[Studio Topup Failed] Supabase client unavailable")
            return {
                "success": False,
                "status": "DB_UNAVAILABLE",
                "message": "Database client unavailable",
                "order_id": external_id,
            }

        # 3. Idempotency Guard (Pre-Flight Check)
        primary_idempotency_key = f"TOPUP_{tenant_id}_{external_id}"
        try:
            existing_ledger = (
                supabase.table("tenant_credit_ledger")
                .select("id, amount, balance_after")
                .eq("tenant_id", tenant_id)
                .eq("idempotency_key", primary_idempotency_key)
                .limit(1)
                .execute()
            )
            if existing_ledger.data and len(existing_ledger.data) > 0:
                row = existing_ledger.data[0]
                logger.info(f"[Studio Topup Idempotency Hit] Order '{external_id}' already processed in tenant_credit_ledger")
                return {
                    "success": True,
                    "status": "ALREADY_PROCESSED",
                    "idempotent": True,
                    "credits_added": 0,
                    "new_balance": row.get("balance_after", 0),
                    "tenant_slug": tenant_slug,
                    "order_id": external_id,
                }
        except Exception as idemp_err:
            logger.warning(f"[Studio Topup Idempotency Check Note] {idemp_err}")

        # 4. Fetch Current Entitlements
        current_balance = 0
        is_unlimited = False
        tenant_tier = tenant.get("tier") or "PRO_SCALE"
        try:
            ent_res = (
                supabase.table("tenant_entitlements")
                .select("credits_remaining, is_unlimited, tier")
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            if ent_res.data and len(ent_res.data) > 0:
                ent_row = ent_res.data[0]
                current_balance = int(ent_row.get("credits_remaining") or 0)
                is_unlimited = bool(ent_row.get("is_unlimited", False))
                tenant_tier = ent_row.get("tier") or tenant_tier
        except Exception as ent_err:
            logger.warning(f"[Studio Topup Entitlements Query Note] {ent_err}")

        new_balance = 999999 if is_unlimited else current_balance + credits

        # 5. Atomic Entitlement Mutation
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            supabase.table("tenant_entitlements").upsert(
                {
                    "tenant_id": tenant_id,
                    "credits_remaining": new_balance,
                    "is_unlimited": is_unlimited,
                    "tier": tenant_tier,
                    "updated_at": now_iso,
                },
                on_conflict="tenant_id",
            ).execute()
        except Exception as upsert_err:
            logger.error(f"[Studio Topup Error] Failed to update tenant_entitlements: {upsert_err}")
            return {
                "success": False,
                "status": "ENTITLEMENT_MUTATION_FAILED",
                "message": str(upsert_err),
                "order_id": external_id,
            }

        # 6. Immutable Ledger Recording (tenant_credit_ledger)
        desc = f"Top-up +{credits} Render Credits (Rp {amount:,.0f}) - Ref: {external_id}"
        try:
            supabase.table("tenant_credit_ledger").insert(
                {
                    "tenant_id": tenant_id,
                    "amount": credits,
                    "balance_after": new_balance,
                    "action": "TOPUP",
                    "event": "STUDIO_TOKEN_PURCHASE",
                    "type": "CREDIT_IN",
                    "description": desc,
                    "actor_id": "XENDIT_WEBHOOK",
                    "actor_role": "SYSTEM",
                    "reason": "Top-up Studio Credits via XENDIT",
                    "idempotency_key": primary_idempotency_key,
                    "metadata": {
                        "transaction_id": external_id,
                        "invoice_id": event_id,
                        "package_id": package_id,
                        "credits": credits,
                        "amount_paid": amount,
                        "channel": "XENDIT",
                    },
                }
            ).execute()
            logger.info(f"[Studio Topup Settled] Successfully credited +{credits} credits to tenant '{tenant_slug}' (New balance: {new_balance})")
        except Exception as ledger_err:
            logger.error(f"[Studio Topup Error] Failed to insert tenant_credit_ledger: {ledger_err}")

        # 7. Record to PostgreSQL payment_events and financial_ledger
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO payment_events (provider, event_id, reference_id, event_type, status, created_at, updated_at)
                VALUES ('XENDIT', %s, %s, 'STUDIO_TOPUP', 'PROCESSED', NOW(), NOW())
                ON CONFLICT (event_id) DO UPDATE SET status = 'PROCESSED', updated_at = NOW();
                """,
                (str(event_id), str(external_id)),
            )
            cur.execute(
                """
                INSERT INTO financial_ledger (order_id, tenant_id, gross_amount, net_amount, gateway_fee, status, payment_method, transaction_type, created_at)
                VALUES (%s, %s, %s, %s, 0, 'SETTLED', 'XENDIT', 'STUDIO_CREDIT_TOPUP', NOW());
                """,
                (str(external_id), str(tenant_id), amount, amount),
            )
            conn.commit()
        except Exception as pg_err:
            logger.warning(f"[Studio Topup PG Ledger Note] {pg_err}")
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        return {
            "success": True,
            "status": "STUDIO_TOPUP_PROCESSED",
            "tenant_slug": tenant_slug,
            "package_id": package_id,
            "credits_added": credits,
            "new_balance": new_balance,
            "order_id": external_id,
            "amount_paid": amount,
        }


studio_credit_service = StudioCreditService()
