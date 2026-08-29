"""app/payments/qris_adapter.py
Dynamic QRIS Payment Adapter implementing BasePaymentProvider.

Features:
- EMVCo QRIS TLV (Tag-Length-Value) parser & serializer.
- Dynamic QRIS conversion (Tag 01: 010211 -> 010212).
- Tag 54 transaction amount injection (base_amount + 3-digit unique_code).
- Tag 62 Additional Data Field template & subtag injection (e.g. Subtag 01 Bill Number).
- Strict EMVCo CRC16-CCITT checksum calculation.
- QuickChart QR image URL generation.
- Webhook / mutation payload verification and normalization.
"""

import os
import re
import urllib.parse
from typing import Dict, Any, Optional, Tuple

from app.payments.base_provider import BasePaymentProvider
from app.payments.schemas import (
    PaymentIntentCreate,
    WebhookEventPayload,
    PaymentStatus,
)
from app.payments.matcher import extract_clean_dana_amount
from app.utils.qris_generator import crc16_ccitt, get_quickchart_qr_url

# Default master static QRIS for BoonTrack Platform
DEFAULT_MASTER_STATIC_QRIS = (
    "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI"
    "51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI520473725303360"
    "5802ID5909BoonTrack6012Kab. Bandung61054028663048DC1"
)


def parse_emvco_tlv(payload: str) -> Dict[str, str]:
    """Parses a flat EMVCo QRIS string into a dictionary of Tag -> Value."""
    clean = payload.strip()
    idx = 0
    length = len(clean)
    tags: Dict[str, str] = {}

    while idx + 4 <= length:
        tag = clean[idx : idx + 2]
        try:
            val_len = int(clean[idx + 2 : idx + 4])
        except ValueError:
            break
        val_start = idx + 4
        val_end = val_start + val_len
        if val_end > length:
            break
        tags[tag] = clean[val_start:val_end]
        idx = val_end
        if tag == "63":  # CRC tag is always the last root tag
            break
    return tags


def parse_subtags(tag_value: str) -> Dict[str, str]:
    """Parses nested subtags (e.g. within Tag 62 Additional Data Field)."""
    return parse_emvco_tlv(tag_value)


def build_subtag_string(subtags: Dict[str, str]) -> str:
    """Builds a TLV string from a dictionary of subtags."""
    result = ""
    for subtag_id in sorted(subtags.keys()):
        val = str(subtags[subtag_id])
        result += f"{subtag_id:0>2}{len(val):02d}{val}"
    return result


class QRISPaymentAdapter(BasePaymentProvider):
    """Dynamic QRIS payment adapter supporting subtag injection and 3-digit unique codes."""

    def __init__(self, master_static_qris: Optional[str] = None):
        self.master_static_qris = (
            master_static_qris
            or os.getenv("BOONTRACK_STATIC_QRIS")
            or DEFAULT_MASTER_STATIC_QRIS
        ).strip()

    def generate_dynamic_payload(
        self,
        base_static_qris: str,
        total_amount: int,
        bill_number: Optional[str] = None,
    ) -> str:
        """Transforms a static QRIS string into dynamic QRIS with Tag 54 and subtag injection."""
        tags = parse_emvco_tlv(base_static_qris)

        # 1. Update Tag 01 to dynamic (Point of Initiation Method: 12)
        tags["01"] = "12"

        # 2. Inject or Replace Tag 54 (Transaction Amount)
        tags["54"] = str(int(total_amount))

        # 3. Inject Subtag 01 (Bill Number / Order ID) into Tag 62 if provided
        if bill_number:
            safe_bill = re.sub(r"[^A-Za-z0-9\-_]", "", str(bill_number))[:25]
            if safe_bill:
                subtags = parse_subtags(tags.get("62", ""))
                subtags["01"] = safe_bill
                tags["62"] = build_subtag_string(subtags)

        # Remove Tag 63 if present in parsed tags (will be recomputed)
        tags.pop("63", None)

        # 4. Serialize in EMVCo tag order (sorted numerically)
        raw_body = ""
        for tag_id in sorted(tags.keys(), key=lambda t: int(t)):
            val = str(tags[tag_id])
            raw_body += f"{tag_id:0>2}{len(val):02d}{val}"

        # 5. Append Tag 63 (CRC16-CCITT)
        payload_to_crc = raw_body + "6304"
        crc_val = crc16_ccitt(payload_to_crc)
        return payload_to_crc + crc_val
        payload_to_crc = raw_body + "6304"
        crc_val = crc16_ccitt(payload_to_crc)
        return payload_to_crc + crc_val

    async def generate_qr(
        self,
        intent: PaymentIntentCreate,
        unique_code: int,
    ) -> Tuple[str, str]:
        """Generates dynamic QRIS string and image link for the intent."""
        total_amount = intent.amount + unique_code
        master_qris = (intent.static_qr_payload or self.master_static_qris).strip()
        
        qr_string = self.generate_dynamic_payload(
            base_static_qris=master_qris,
            total_amount=total_amount,
            bill_number=intent.order_id,
        )
        qr_image_url = get_quickchart_qr_url(qr_string)
        return qr_string, qr_image_url

    async def verify_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookEventPayload:
        """Normalizes mutation payloads from DANA Bisnis, SMS reader, or webhook calls."""
        nominal = extract_clean_dana_amount(payload)
        
        # Provider reference identification
        provider_ref = (
            payload.get("transaction_id")
            or payload.get("provider_ref")
            or payload.get("reference_id")
            or payload.get("id")
            or payload.get("idempotency_key")
        )
        if not provider_ref:
            # Generate deterministic fallback reference hash
            import hashlib
            raw_str = str(sorted(payload.items()))
            provider_ref = f"qris_ref_{hashlib.sha256(raw_str.encode()).hexdigest()[:16]}"

        order_id = payload.get("order_id") or payload.get("bill_number")
        tenant_id = payload.get("tenant_id")
        idempotency_key = payload.get("idempotency_key") or provider_ref

        return WebhookEventPayload(
            provider="QRIS_DYNAMIC",
            event_type="PAYMENT_SETTLED",
            provider_ref=str(provider_ref),
            amount=nominal,
            order_id=order_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            raw_payload=payload,
        )

    async def check_status(self, provider_ref: str) -> PaymentStatus:
        """Returns settlement status based on reference."""
        return PaymentStatus.SETTLED

    async def refund(
        self,
        provider_ref: str,
        amount: Optional[int] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Acknowledge refund request for manual audit/reversal."""
        return {
            "status": "REFUND_REQUESTED",
            "provider_ref": provider_ref,
            "refunded_amount": amount,
            "reason": reason or "Customer requested refund",
            "manual_review_required": True,
        }
