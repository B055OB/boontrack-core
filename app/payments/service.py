from app.payments.matcher import (
    extract_clean_dana_amount,
    find_matching_unpaid_job,
    match_and_fulfill_payment,
    handle_admin_verify_command,
    handle_admin_retry_doc_command
)

class PaymentMatchingService:
    """Service facade untuk verifikasi pembayaran dan auto fulfillment."""

    @staticmethod
    def extract_amount(text_or_payload) -> int:
        return extract_clean_dana_amount(text_or_payload)

    @staticmethod
    async def fulfill(amount: int, raw_text: str = "", tenant_id: str = "boontrack-career", source: str = "dana_reader", direct_phone=None):
        return await match_and_fulfill_payment(
            amount=amount,
            raw_text=raw_text,
            tenant_id=tenant_id,
            source=source,
            direct_phone=direct_phone
        )

    @staticmethod
    async def verify_command(cmd_text: str, tenant_id: str = "boontrack-career") -> str:
        return await handle_admin_verify_command(cmd_text, tenant_id)

    @staticmethod
    async def retry_doc_command(cmd_text: str, tenant_id: str = "boontrack-career") -> str:
        return await handle_admin_retry_doc_command(cmd_text, tenant_id)


payment_matching_service = PaymentMatchingService()
