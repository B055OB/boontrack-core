"""app/services/billing_service.py
Core Billing & Prorata Engine.

Architectural Authority:
1. Prorata Calculation Authority: Hitung tagihan upgrade berbasis sisa hari dalam siklus 30 hari.
   Formula: tagihan = max(0, round((sisa_hari / 30) * (harga_tier_baru - harga_tier_lama)))
2. Preserved Billing Cycle: Tanggal renewal TIDAK BERUBAH saat upgrade prorata.
3. Invoice Generation: Menghasilkan invoice berstatus 'pending' dengan invoice_type 'UPGRADE_PRORATION'.
4. Internal Official API Endpoint support for BoonPilot and clients (No LLM manual math).
5. Event Hook on Payment:
   - Update tier tenant seketika di database.
   - Trigger pencatatan komisi affiliate ke ledger dengan status 'HOLDING'.
"""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

from app.services.whatsapp_service import get_supabase
from app.services.affiliate_service import affiliate_service

logger = logging.getLogger("BILLING_SERVICE")

# Standar Harga Tier Resmi Bulanan (Rupiah)
TIER_MONTHLY_PRICING: Dict[str, int] = {
    "FREE": 0,
    "TRIAL": 0,
    "SOLO_TRIAL": 0,
    "SOLO": 149000,
    "ADS_PERFORMANCE": 299000,
    "ADS_PERF": 299000,
    "PRO_SCALE": 349000,
    "TEAM_SCALE": 749000,
    "ENTERPRISE": 1490000,
}


class ProrationResult(BaseModel):
    tenant_id: str
    tenant_slug: str
    current_tier: str
    new_tier: str
    current_tier_price: int
    new_tier_price: int
    days_remaining: int
    total_cycle_days: int = 30
    prorated_amount: int
    renewal_date: Optional[str]
    invoice_id: str
    invoice_type: str = "UPGRADE_PRORATION"
    status: str = "pending"
    summary_message: str


class BillingService:
    """Authority Mutlak Backend untuk Billing & Prorata Upgrade."""

    def __init__(self):
        # In-memory invoice store {invoice_id: {...}}
        self._invoices: Dict[str, Dict[str, Any]] = {}

    def get_tier_price(self, tier_name: str) -> int:
        """Mendapatkan harga bulanan resmi untuk tier tertentu."""
        clean = (tier_name or "FREE").strip().upper()
        return TIER_MONTHLY_PRICING.get(clean, 0)

    def calculate_proration(
        self,
        current_tier: str,
        new_tier: str,
        days_remaining: int,
    ) -> Tuple[int, int, int]:
        """
        Kalkulasi murni formula prorata:
        tagihan = (sisa_hari / 30) * (harga_tier_baru - harga_tier_lama)
        Returns: (old_price, new_price, prorated_amount)
        """
        old_price = self.get_tier_price(current_tier)
        new_price = self.get_tier_price(new_tier)
        
        diff = new_price - old_price
        if diff <= 0 or days_remaining <= 0:
            return old_price, new_price, 0

        clamped_days = min(30, max(0, days_remaining))
        prorated = round((clamped_days / 30.0) * diff)
        return old_price, new_price, int(prorated)

    async def calculate_upgrade_proration(
        self,
        tenant_id_or_slug: str,
        new_tier: str,
        override_days_remaining: Optional[int] = None,
        override_current_tier: Optional[str] = None,
    ) -> ProrationResult:
        """
        Hitung tagihan upgrade berbasis sisa hari dalam siklus 30 hari.
        Tanggal renewal TIDAK BERUBAH.
        Menghasilkan invoice berstatus 'pending'.
        """
        clean_target_tier = (new_tier or "PRO_SCALE").strip().upper()
        clean_key = str(tenant_id_or_slug or "").strip().lower()

        # 1. Resolve Tenant Profile & Renewal Date
        tenant_id = clean_key
        tenant_slug = clean_key
        current_tier = (override_current_tier or "SOLO").strip().upper()
        renewal_date_iso = None
        days_remaining = override_days_remaining if override_days_remaining is not None else 15

        supabase = get_supabase()
        if supabase and not override_current_tier:
            try:
                is_uuid = False
                try:
                    uuid.UUID(clean_key)
                    is_uuid = True
                except (ValueError, AttributeError):
                    is_uuid = False

                query = supabase.table("tenants").select("id, slug, tier, subscription_ends_at, trial_ends_at, metadata")
                if is_uuid:
                    t_res = query.eq("id", clean_key).maybe_single().execute()
                else:
                    t_res = query.eq("slug", clean_key).maybe_single().execute()

                if t_res and t_res.data:
                    t_data = t_res.data
                    tenant_id = t_data.get("id") or clean_key
                    tenant_slug = t_data.get("slug") or clean_key
                    current_tier = (t_data.get("tier") or "SOLO").upper()
                    
                    if override_days_remaining is None:
                        # Hitung sisa hari dari subscription_ends_at atau trial_ends_at
                        end_str = t_data.get("subscription_ends_at") or t_data.get("trial_ends_at")
                        if end_str:
                            renewal_date_iso = end_str
                            try:
                                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                                now_dt = datetime.now(timezone.utc)
                                delta = end_dt - now_dt
                                days_remaining = max(1, delta.days)
                            except Exception as parse_err:
                                logger.debug(f"[BillingService] Date parse note: {parse_err}")
            except Exception as e:
                logger.warning(f"[BillingService] Tenant lookup warning: {e}")

        # Jika renewal_date belum diset, gunakan default berdasarkan days_remaining
        if not renewal_date_iso:
            renewal_date_iso = (datetime.now(timezone.utc) + timedelta(days=days_remaining)).isoformat()

        # 2. Eksekusi Formula Prorata
        old_price, new_price, prorated_amount = self.calculate_proration(
            current_tier=current_tier,
            new_tier=clean_target_tier,
            days_remaining=days_remaining,
        )

        invoice_id = f"INV-UPG-{clean_target_tier[:3]}-{uuid.uuid4().hex[:6].upper()}"
        summary = (
            f"Upgrade dari {current_tier} ke {clean_target_tier} (Sisa {days_remaining} hari). "
            f"Tagihan Prorata: Rp {prorated_amount:,.0f}. Tanggal perpanjangan tetap: {renewal_date_iso[:10]}."
        )

        invoice_record = {
            "id": invoice_id,
            "invoice_id": invoice_id,
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant_slug,
            "current_tier": current_tier,
            "new_tier": clean_target_tier,
            "current_tier_price": old_price,
            "new_tier_price": new_price,
            "days_remaining": days_remaining,
            "amount": prorated_amount,
            "amount_due": prorated_amount,
            "amount_paid": 0,
            "renewal_date": renewal_date_iso,
            "status": "pending",
            "invoice_type": "UPGRADE_PRORATION",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Simpan ke cache internal
        self._invoices[invoice_id] = invoice_record

        # Simpan ke Supabase tabel payment_intents / invoices jika tersedia
        if supabase:
            try:
                supabase.table("payment_intents").upsert({
                    "tenant_id": str(tenant_id),
                    "order_id": invoice_id,
                    "amount": prorated_amount,
                    "unique_code": 0,
                    "total_amount": prorated_amount,
                    "qr_string": f"PRORATE_UPGRADE_{invoice_id}",
                    "status": "PENDING",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                }, on_conflict="tenant_id, order_id").execute()
            except Exception as sb_inv_err:
                logger.debug(f"[BillingService] Supabase intent sync note: {sb_inv_err}")

        logger.info(f"[BillingService] Generated Proration Invoice '{invoice_id}': Rp {prorated_amount:,.0f} for '{tenant_slug}'")

        return ProrationResult(
            tenant_id=str(tenant_id),
            tenant_slug=tenant_slug,
            current_tier=current_tier,
            new_tier=clean_target_tier,
            current_tier_price=old_price,
            new_tier_price=new_price,
            days_remaining=days_remaining,
            total_cycle_days=30,
            prorated_amount=prorated_amount,
            renewal_date=renewal_date_iso,
            invoice_id=invoice_id,
            invoice_type="UPGRADE_PRORATION",
            status="pending",
            summary_message=summary,
        )

    async def mark_invoice_paid(
        self,
        invoice_id: str,
        payment_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Event Hook saat pembayaran terkonfirmasi (misal dari webhook gateway):
        1. Update status invoice menjadi 'paid'.
        2. Update tier tenant seketika di database.
        3. Trigger pencatatan komisi affiliate ke ledger.
        """
        invoice = self._invoices.get(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice '{invoice_id}' tidak ditemukan.")

        if invoice.get("status") == "paid":
            logger.info(f"[BillingService] Invoice '{invoice_id}' already marked paid.")
            return {"status": "already_paid", "invoice": invoice}

        tenant_id = invoice["tenant_id"]
        tenant_slug = invoice.get("tenant_slug", tenant_id)
        new_tier = invoice["new_tier"]
        remaining_days = invoice["days_remaining"]
        amount_paid = float(invoice["amount"])

        # 1. Update status invoice
        invoice["status"] = "paid"
        invoice["amount_paid"] = amount_paid
        invoice["payment_ref"] = payment_ref or f"PAY-{uuid.uuid4().hex[:8].upper()}"
        invoice["paid_at"] = datetime.now(timezone.utc).isoformat()

        # 2. Update Tier Tenant Seketika di Database Supabase
        supabase = get_supabase()
        if supabase:
            try:
                is_uuid = False
                try:
                    uuid.UUID(str(tenant_id))
                    is_uuid = True
                except (ValueError, AttributeError):
                    is_uuid = False

                t_query = supabase.table("tenants").update({
                    "tier": new_tier,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                if is_uuid:
                    t_query.eq("id", str(tenant_id)).execute()
                else:
                    t_query.eq("slug", tenant_slug).execute()

                logger.info(f"[BillingService] Updated tenant '{tenant_slug}' tier to '{new_tier}'")

                # Update payment intent
                supabase.table("payment_intents").update({
                    "status": "SETTLED"
                }).eq("order_id", invoice_id).execute()
            except Exception as e:
                logger.error(f"[BillingService] Failed to update tenant tier in DB: {e}")

        # 3. Trigger Pencatatan Komisi Affiliate
        commission_entry = await affiliate_service.record_prorated_upgrade_commission(
            tenant_id=tenant_id,
            new_tier=new_tier,
            remaining_days=remaining_days,
            amount_paid=amount_paid,
            invoice_id=invoice_id,
        )

        return {
            "success": True,
            "status": "paid",
            "invoice_id": invoice_id,
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "new_tier": new_tier,
            "amount_paid": amount_paid,
            "commission_entry": commission_entry,
        }

    def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        """Mengambil data invoice berdasarkan invoice_id."""
        return self._invoices.get(invoice_id)


billing_service = BillingService()
