"""app/services/affiliate_service.py
Centralized Affiliate Commission & Ledger Service.

Architectural Guarantees:
1. Strict Cash-Collected Accounting: Komisi HANYA dihitung dari kas riil invoice prorata yang dibayar.
2. Holding Status Safeguard: Komisi dicatat dengan status 'HOLDING' untuk proteksi transaksi.
3. Standardized Audit Description: 'Komisi Upgrade ke [Tier Baru] (Prorata [X] Hari)'.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("AFFILIATE_SERVICE")

DEFAULT_AFFILIATE_COMMISSION_RATE = 0.20  # 20%


class AffiliateService:
    """Service untuk pengelolaan komisi mitra affiliate berbasis kas terkumpul (cash collected)."""

    def __init__(self):
        # In-memory ledger storage fallback {commission_id: {...}}
        self._commissions: Dict[str, Dict[str, Any]] = {}

    def calculate_commission(
        self,
        amount_paid: float,
        rate: Optional[float] = None
    ) -> float:
        """
        Hitung komisi strictly dari kas riil invoice yang dibayar (cash collected).
        Formula: komisi = rate_komisi * amount_paid
        """
        effective_rate = float(rate) if rate is not None else DEFAULT_AFFILIATE_COMMISSION_RATE
        if amount_paid <= 0 or effective_rate <= 0:
            return 0.0
        return round(float(amount_paid) * effective_rate, 2)

    async def record_prorated_upgrade_commission(
        self,
        tenant_id: str,
        new_tier: str,
        remaining_days: int,
        amount_paid: float,
        affiliate_id: Optional[str] = None,
        affiliate_rate: Optional[float] = None,
        invoice_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Mencatat komisi upgrade prorata ke ledger dengan status HOLDING.
        Deskripsi mutasi: 'Komisi Upgrade ke [Tier Baru] (Prorata [X] Hari)'.
        """
        if amount_paid <= 0:
            logger.info(f"[AffiliateService] Zero amount paid for tenant '{tenant_id}', skipping commission.")
            return None

        # 1. Resolve Affiliate jika belum diberikan
        resolved_aff_id = affiliate_id
        resolved_rate = affiliate_rate or DEFAULT_AFFILIATE_COMMISSION_RATE

        supabase = get_supabase()
        if not resolved_aff_id and supabase:
            try:
                # Periksa apakah tenant_id adalah UUID valid
                is_uuid = False
                try:
                    uuid.UUID(str(tenant_id))
                    is_uuid = True
                except (ValueError, AttributeError):
                    is_uuid = False

                t_query = supabase.table("tenants").select("id, affiliate_id, affiliate_ref, metadata")
                if is_uuid:
                    t_res = t_query.eq("id", str(tenant_id)).maybe_single().execute()
                else:
                    t_res = t_query.eq("slug", str(tenant_id)).maybe_single().execute()

                if t_res and t_res.data:
                    row = t_res.data
                    resolved_aff_id = row.get("affiliate_id") or (row.get("metadata") or {}).get("affiliate_id")
                    if not resolved_aff_id and row.get("affiliate_ref"):
                        ref = row.get("affiliate_ref")
                        aff_res = supabase.table("affiliates").select("id, commission_rate").ilike("referral_code", ref).maybe_single().execute()
                        if aff_res and aff_res.data:
                            resolved_aff_id = aff_res.data.get("id")
                            if aff_res.data.get("commission_rate") is not None:
                                rate_val = float(aff_res.data.get("commission_rate"))
                                resolved_rate = rate_val / 100.0 if rate_val > 1 else rate_val
            except Exception as e:
                logger.debug(f"[AffiliateService] Affiliate resolution info: {e}")

        commission_amount = self.calculate_commission(amount_paid, resolved_rate)
        if commission_amount <= 0:
            return None

        commission_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        description = f"Komisi Upgrade ke [{new_tier}] (Prorata [{remaining_days}] Hari)"

        record = {
            "id": commission_id,
            "commission_id": commission_id,
            "tenant_id": str(tenant_id),
            "affiliate_id": str(resolved_aff_id or "PLATFORM_RESERVED"),
            "invoice_id": invoice_id,
            "order_id": invoice_id or f"inv_prorata_{commission_id[:8]}",
            "order_amount": float(amount_paid),
            "amount": commission_amount,
            "rate": resolved_rate,
            "description": description,
            "status": "HOLDING",
            "created_at": now_iso,
        }

        # 2. Simpan ke Supabase table affiliate_commissions
        if supabase:
            try:
                db_payload = {
                    "tenant_id": str(tenant_id),
                    "affiliate_id": str(resolved_aff_id) if (resolved_aff_id and resolved_aff_id != "PLATFORM_RESERVED") else None,
                    "order_id": record["order_id"],
                    "order_amount": float(amount_paid),
                    "amount": commission_amount,
                    "status": "HOLDING",
                    "created_at": now_iso,
                }
                supabase.table("affiliate_commissions").upsert(db_payload, on_conflict="tenant_id, order_id").execute()
                logger.info(f"[AffiliateService] Commission '{commission_id}' saved to Supabase (Status: HOLDING)")
            except Exception as sb_err:
                logger.debug(f"[AffiliateService] Supabase ledger note: {sb_err}")

        # 3. Simpan ke in-memory ledger
        self._commissions[commission_id] = record
        logger.info(
            f"[AffiliateService] Logged commission '{commission_id}' for affiliate '{resolved_aff_id}': "
            f"Rp {commission_amount:,.0f} [HOLDING] - '{description}'"
        )
        return record

    def get_commission(self, commission_id: str) -> Optional[Dict[str, Any]]:
        """Mengambil data komisi berdasarkan commission_id."""
        return self._commissions.get(commission_id)

    def list_commissions_by_tenant(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Mengambil daftar komisi untuk tenant tertentu."""
        clean = str(tenant_id).strip()
        return [c for c in self._commissions.values() if str(c.get("tenant_id")).strip() == clean]


affiliate_service = AffiliateService()
