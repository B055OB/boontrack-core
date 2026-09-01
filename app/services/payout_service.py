import logging
from datetime import datetime
from typing import Dict, Any, List
from supabase import Client

logger = logging.getLogger("boontrack.payout")

class PayoutService:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client

    async def get_pending_settlements(self) -> List[Dict[str, Any]]:
        """Mengambil seluruh antrean komisi yang siap dicairkan."""
        res = self.supabase.table("commission_ledger").select("*").eq("status", "PENDING_PAYOUT").execute()
        return res.data or []

    async def settle_affiliate_batch(self, affiliate_code: str, reference_notes: str = "Disbursement via Manual Transfer") -> Dict[str, Any]:
        """
        Mengubah status komisi pending menjadi PAID_OUT untuk affiliate tertentu.
        """
        pending_records = self.supabase.table("commission_ledger") \
            .select("id, affiliate_commission_amount") \
            .match({"affiliate_code": affiliate_code, "status": "PENDING_PAYOUT"}) \
            .execute()

        rows = pending_records.data or []
        if not rows:
            return {
                "status": "noop",
                "message": f"No pending payout found for affiliate {affiliate_code}",
                "records_settled": 0,
                "total_payout": 0
            }

        total_settled = sum(float(r["affiliate_commission_amount"]) for r in rows)
        record_ids = [r["id"] for r in rows]

        # Update status batch di Postgres Supabase
        settled_at = datetime.utcnow().isoformat()
        self.supabase.table("commission_ledger").update({
            "status": "PAID_OUT",
            "settled_at": settled_at,
            "settlement_notes": reference_notes
        }).in_("id", record_ids).execute()

        logger.info(f"[Payout] Settled Rp {total_settled:,.0f} for affiliate {affiliate_code} ({len(record_ids)} records).")

        return {
            "status": "success",
            "affiliate_code": affiliate_code,
            "total_payout": total_settled,
            "records_settled": len(record_ids),
            "settled_at": settled_at,
            "notes": reference_notes
        }