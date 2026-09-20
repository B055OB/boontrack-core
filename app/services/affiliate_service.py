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

    def get_commissions_by_invoice(self, invoice_id: str) -> List[Dict[str, Any]]:
        """Mengambil komisi yang dicatat untuk invoice tertentu."""
        clean = str(invoice_id).strip()
        return [c for c in self._commissions.values() if str(c.get("invoice_id")).strip() == clean]

    def clear_commissions(self) -> None:
        """Membersihkan in-memory ledger komisi (berguna untuk isolasi testing)."""
        self._commissions.clear()

    async def allocate_upgrade_commission(
        self,
        tenant_id: str,
        invoice_id: str,
        amount_paid: float,
        affiliate_id: Optional[str] = None,
        referral_code: Optional[str] = None,
        am_id: Optional[str] = None,
        affiliate_direct_rate: Optional[float] = None,
        am_override_rate: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Alokasi komisi upgrade prorata berbasis kas terkumpul dengan prinsip Strict Zero Financial Leakage:
        1. Tenant organik tanpa referral: 100% Platform Revenue (Komisi = Rp 0). Early return, 0 row inserted.
        2. Tenant dengan referral sah:
           - Direct Affiliate: round(base_amount * affiliate_direct_rate) -> affiliate_commissions
           - AM Override (Anti-Ghost AM): HANYA jika am_id ada & aktif di database -> round(base_amount * am_override_rate).
           - Sisa margin tetap milik platform.
        """
        from app.core.tracing import log_structured_event

        clean_tenant = str(tenant_id or "").strip()
        base_amount = float(amount_paid or 0)
        supabase = get_supabase()

        resolved_aff_id = affiliate_id
        resolved_ref_code = referral_code

        # 1. Resolusi referral tenant dari database jika belum diberikan
        if not resolved_aff_id and not resolved_ref_code and supabase:
            try:
                t_res = supabase.table("tenants").select("id, slug, affiliate_id, affiliate_ref, metadata").eq("slug", clean_tenant).execute()
                if not t_res.data:
                    try:
                        uuid.UUID(clean_tenant)
                        t_res = supabase.table("tenants").select("id, slug, affiliate_id, affiliate_ref, metadata").eq("id", clean_tenant).execute()
                    except Exception:
                        pass
                if t_res and t_res.data:
                    row = t_res.data[0]
                    resolved_aff_id = row.get("affiliate_id") or (row.get("metadata") or {}).get("affiliate_id")
                    resolved_ref_code = row.get("affiliate_ref") or (row.get("metadata") or {}).get("referral_code")

                if not resolved_aff_id and not resolved_ref_code:
                    m_res = supabase.table("merchants").select("referral_code").eq("slug", clean_tenant).execute()
                    if m_res and m_res.data:
                        resolved_ref_code = m_res.data[0].get("referral_code")
            except Exception as e:
                logger.debug(f"[AffiliateService] Referral resolution note: {e}")

        # 2. Strict Null Check & Early Exit (Prinsip Zero Financial Leakage)
        if not resolved_aff_id and not resolved_ref_code:
            log_structured_event(
                service='billing',
                event_type='ORGANIC_SUBSCRIPTION_PROCESSED',
                entity_type='invoice',
                entity_id=invoice_id,
                status='SUCCESS',
                tenant_id=clean_tenant,
                extra_metadata={'reason': 'ORGANIC_NO_AFFILIATE', 'payout_commission': 0, 'revenue': base_amount}
            )
            return {
                "status": "skipped",
                "reason": "ORGANIC_NO_AFFILIATE",
                "tenant_id": clean_tenant,
                "invoice_id": invoice_id,
                "payout_commission": 0,
                "revenue": base_amount,
                "net_platform_revenue": base_amount,
                "commissions": []
            }

        # 3. Verifikasi Keberadaan Affiliate di Database
        aff_record = None
        if supabase:
            try:
                candidate = resolved_aff_id or resolved_ref_code
                aff_query = supabase.table("affiliates").select("*").eq("id", str(candidate)).execute()
                if aff_query.data:
                    aff_record = aff_query.data[0]
                else:
                    ref_query = supabase.table("affiliates").select("*").ilike("referral_code", str(candidate)).execute()
                    if ref_query.data:
                        aff_record = ref_query.data[0]
            except Exception as aff_err:
                logger.debug(f"[AffiliateService] Affiliate query note: {aff_err}")

        # Jika affiliate tidak ditemukan di tabel affiliate: Tolak komisi, 100% masuk platform
        if not aff_record and not (resolved_aff_id and not supabase):
            log_structured_event(
                service='billing',
                event_type='ORGANIC_SUBSCRIPTION_PROCESSED',
                entity_type='invoice',
                entity_id=invoice_id,
                status='SUCCESS',
                tenant_id=clean_tenant,
                extra_metadata={'reason': 'ORGANIC_NO_AFFILIATE', 'payout_commission': 0, 'revenue': base_amount}
            )
            return {
                "status": "skipped",
                "reason": "ORGANIC_NO_AFFILIATE",
                "tenant_id": clean_tenant,
                "invoice_id": invoice_id,
                "payout_commission": 0,
                "revenue": base_amount,
                "net_platform_revenue": base_amount,
                "commissions": []
            }

        valid_aff_id = (aff_record.get("id") if aff_record else resolved_aff_id) or str(resolved_aff_id)

        # Hitung Direct Affiliate Commission berbasis kas riil yang dibayar
        if affiliate_direct_rate is not None:
            effective_direct_rate = float(affiliate_direct_rate)
        elif aff_record and aff_record.get("commission_rate") is not None:
            r = float(aff_record.get("commission_rate"))
            effective_direct_rate = r / 100.0 if r > 1.0 else r
        else:
            effective_direct_rate = DEFAULT_AFFILIATE_COMMISSION_RATE  # 0.20

        direct_commission = round(base_amount * effective_direct_rate)

        comm_id_direct = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        direct_comm_record = {
            "id": comm_id_direct,
            "tenant_id": clean_tenant,
            "affiliate_id": str(valid_aff_id),
            "type": "SUBSCRIPTION_UPGRADE_PRORATED",
            "amount": direct_commission,
            "invoice_id": invoice_id,
            "order_id": invoice_id,
            "order_amount": float(base_amount),
            "status": "HOLDING",
            "created_at": now_iso
        }
        self._commissions[comm_id_direct] = direct_comm_record
        if supabase:
            try:
                supabase.table("affiliate_commissions").insert(direct_comm_record).execute()
            except Exception as sb_ins_err:
                logger.debug(f"[AffiliateService] Supabase direct comm insert note: {sb_ins_err}")

        # 4. Anti-Ghost AM Check
        valid_am_id = None
        override_commission = 0
        am_comm_record = None

        am_candidate = am_id or (aff_record.get("parent_am_id") if aff_record else None) or (aff_record.get("manager_id") if aff_record else None) or (aff_record.get("registered_by_am_id") if aff_record else None)

        if am_candidate and supabase:
            try:
                am_query = supabase.table("affiliates").select("*").eq("id", str(am_candidate)).execute()
                if not am_query.data:
                    am_query = supabase.table("affiliates").select("*").ilike("referral_code", str(am_candidate)).execute()
                if am_query.data:
                    am_row = am_query.data[0]
                    if am_row.get("status") in ("ACTIVE", "active", "APPROVED", None):
                        valid_am_id = am_row.get("id") or str(am_candidate)
            except Exception as am_lookup_err:
                logger.debug(f"[AffiliateService] AM lookup note: {am_lookup_err}")
        elif am_candidate and not supabase:
            valid_am_id = str(am_candidate)

        if valid_am_id:
            effective_am_rate = float(am_override_rate) if am_override_rate is not None else 0.05
            override_commission = round(base_amount * effective_am_rate)
            comm_id_am = str(uuid.uuid4())
            am_comm_record = {
                "id": comm_id_am,
                "tenant_id": clean_tenant,
                "affiliate_id": str(valid_am_id),
                "type": "AM_OVERRIDE_UPGRADE",
                "amount": override_commission,
                "invoice_id": invoice_id,
                "order_id": f"{invoice_id}_am",
                "order_amount": float(base_amount),
                "status": "HOLDING",
                "created_at": now_iso
            }
            self._commissions[comm_id_am] = am_comm_record
            if supabase:
                try:
                    supabase.table("affiliate_commissions").insert(am_comm_record).execute()
                except Exception as sb_am_err:
                    logger.debug(f"[AffiliateService] Supabase AM comm insert note: {sb_am_err}")

        # 5. Observability Trace
        log_structured_event(
            service='affiliate_engine',
            event_type='AFFILIATE_COMMISSION_DISPATCHED',
            entity_type='invoice',
            entity_id=invoice_id,
            status='SUCCESS',
            tenant_id=clean_tenant,
            extra_metadata={
                'direct_affiliate_id': valid_aff_id,
                'direct_commission': direct_commission,
                'am_id': valid_am_id,
                'override_commission': override_commission,
                'prorated_amount_paid': base_amount
            }
        )

        records_created = [direct_comm_record]
        if am_comm_record:
            records_created.append(am_comm_record)

        return {
            "status": "success",
            "tenant_id": clean_tenant,
            "invoice_id": invoice_id,
            "base_amount": base_amount,
            "direct_affiliate_id": valid_aff_id,
            "direct_commission": direct_commission,
            "am_id": valid_am_id,
            "override_commission": override_commission,
            "commissions": records_created
        }


affiliate_service = AffiliateService()


async def allocate_upgrade_commission(*args, **kwargs) -> Dict[str, Any]:
    return await affiliate_service.allocate_upgrade_commission(*args, **kwargs)

