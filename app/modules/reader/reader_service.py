import logging
from typing import Dict, Any, Optional
from app.payments.matcher import extract_clean_dana_amount, match_and_fulfill_payment

logger = logging.getLogger("READER_SERVICE")


class ReaderNotificationService:
    """Service pemroses mutasi transaksi dari Android Reader / DANA Bisnis."""

    @staticmethod
    async def process_mutation_payload(data: Dict[str, Any], tenant_id: str = "boontrack-career") -> Dict[str, Any]:
        raw_text = (
            data.get("raw_text")
            or data.get("message")
            or data.get("notification_text")
            or data.get("text")
            or data.get("keterangan")
            or ""
        )
        amount = extract_clean_dana_amount(data)
        direct_phone = data.get("user_phone") or data.get("phone")
        source = data.get("source") or data.get("package_name") or "android_reader"

        logger.info(f"[ReaderService] Incoming mutation: amount={amount}, text='{raw_text}', source='{source}'")

        if amount <= 0:
            return {"status": "IGNORED", "reason": "invalid_amount", "amount": 0}

        return await match_and_fulfill_payment(
            amount=amount,
            raw_text=raw_text,
            tenant_id=tenant_id,
            source=source,
            direct_phone=direct_phone
        )


reader_notification_service = ReaderNotificationService()
