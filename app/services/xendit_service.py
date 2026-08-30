"""app/services/xendit_service.py
Xendit Payment Gateway Client & Dynamic QRIS Engine.

Provides:
- Asynchronous dynamic QRIS generation via Xendit QR Codes API.
- Basic Authentication with Xendit Secret Key.
- In-flight intent tracking and integration with BoonTrack payment registry.
"""

import os
import base64
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from uuid import uuid4
import httpx

from app.services.reconciliation_service import PAYMENT_INTENTS

logger = logging.getLogger("XENDIT_SERVICE")


class XenditService:
    """Client wrapper for Xendit QR Codes & Payment APIs."""

    def __init__(self):
        self.secret_key = os.getenv(
            "XENDIT_SECRET_KEY",
            "xnd_development_2itAoTg8FOAdr8Vk7jKpU0MksgDSAjaWzlLHzEMkPuHcRyf5IUxfvO7MG1KPe",
        ).strip()
        self.api_url = os.getenv("XENDIT_API_URL", "https://api.xendit.co").rstrip("/")
        self.env = os.getenv("XENDIT_ENV", "sandbox")
        self.callback_token = os.getenv(
            "XENDIT_CALLBACK_TOKEN",
            "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS",
        ).strip()

        # In-memory tracking for fast lookups & test isolation
        self._intents_by_external_id: Dict[str, Dict[str, Any]] = {}
        self._processed_transactions: set = set()

    def get_auth_header(self) -> str:
        """Encodes Xendit Secret Key for HTTP Basic Authentication."""
        raw = f"{self.secret_key}:"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    async def create_dynamic_qris(
        self,
        external_id: str,
        amount: int,
        tenant_id: str = "onlineboost",
        callback_url: Optional[str] = None,
        customer_phone: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Creates a Dynamic QRIS code via Xendit API."""
        app_domain = os.getenv("APP_DOMAIN", "https://boontrack.com").rstrip("/")
        resolved_callback = callback_url or f"{app_domain}/api/v1/payments/xendit/callback"

        payload = {
            "reference_id": str(external_id),
            "external_id": str(external_id),
            "type": "DYNAMIC",
            "currency": "IDR",
            "amount": int(amount),
            "callback_url": resolved_callback,
        }

        endpoint = f"{self.api_url}/qr_codes"
        headers = {
            "Authorization": self.get_auth_header(),
            "Content-Type": "application/json",
            "api-version": "2022-07-31",
        }

        logger.info(
            f"[Xendit] Requesting Dynamic QRIS: external_id='{external_id}', amount={amount}, tenant='{tenant_id}'"
        )

        data: Dict[str, Any] = {}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    logger.info(f"[Xendit] QR Code created successfully from API: {data.get('id')}")
                else:
                    logger.warning(f"[Xendit API Warning] HTTP {resp.status_code} - {resp.text}")
                    raise RuntimeError(f"Xendit API ({resp.status_code}): {resp.text}")
        except Exception as api_err:
            logger.warning(f"[Xendit Fallback] Generating dynamic QRIS locally: {api_err}")
            from app.utils.qris_generator import generate_dynamic_qris_payload

            static_qris = os.getenv(
                "BOONTRACK_STATIC_QRIS",
                "00020101021126540014ID.LINKAJA.WWW011893600911002237890202152009221102000010303UMI51440014ID.DANA.WWW011893600911002237890202152009221102000010303UMI5802ID5911BOONTRACK6007JAKARTA6105129406304C22F",
            )
            raw_emvco = generate_dynamic_qris_payload(static_qris, amount)
            exp_time = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&format=png&data={urllib.parse.quote(raw_emvco)}"
            data = {
                "id": f"qr_{uuid4().hex[:12]}",
                "qr_string": raw_emvco,
                "qr_code_url": qr_url,
                "status": "ACTIVE",
                "amount": amount,
                "external_id": external_id,
                "expires_at": exp_time,
            }

        # Gunakan string QR resmi Xendit jika tersedia
        qr_string = data.get("qr_string", "")
        if not qr_string:
            from app.utils.qris_generator import generate_dynamic_qris_payload
            static_qris = os.getenv(
                "BOONTRACK_STATIC_QRIS",
                "00020101021126540014ID.LINKAJA.WWW011893600911002237890202152009221102000010303UMI51440014ID.DANA.WWW011893600911002237890202152009221102000010303UMI5802ID5911BOONTRACK6007JAKARTA6105129406304C22F",
            )
            qr_string = generate_dynamic_qris_payload(static_qris, amount)

        qr_code_url = (
            data.get("qr_code_url")
            or f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&format=png&data={urllib.parse.quote(qr_string)}"
        )
        expired_at = (
            data.get("expires_at")
            or data.get("expired_at")
            or (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        )

        result = {
            "qr_string": qr_string,
            "qr_code_url": qr_code_url,
            "qr_id": data.get("id", ""),
            "status": data.get("status", "ACTIVE"),
            "amount": data.get("amount", amount),
            "external_id": data.get("external_id", external_id),
            "currency": data.get("currency", "IDR"),
            "type": data.get("type", "DYNAMIC"),
            "tenant_id": tenant_id,
            "customer_phone": customer_phone,
            "expired_at": expired_at,
            "expires_at": expired_at,
            "created": data.get("created", datetime.now(timezone.utc).isoformat()),
        }

        # Track intent in-memory & legacy store for cross-service reconciliation
        self._intents_by_external_id[str(external_id)] = result
        PAYMENT_INTENTS[external_id] = {
            "invoice_id": external_id,
            "order_id": external_id,
            "tenant_id": tenant_id,
            "amount": amount,
            "total_amount": amount,
            "status": "PENDING",
            "phone": customer_phone,
            "metadata": metadata or {},
        }

        return result

    def get_intent(self, external_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves stored payment intent by external_id."""
        return self._intents_by_external_id.get(str(external_id))

    def mark_settled(self, external_id: str) -> None:
        """Marks a transaction as settled / paid in local state and attaches digital delivery link."""
        self._processed_transactions.add(str(external_id))
        intent = self._intents_by_external_id.get(str(external_id), {})
        tenant_id = intent.get("tenant_id", "onlineboost")

        download_url = "https://drive.google.com/drive/folders/onlineboost-starterkit-2026"
        delivery_msg = (
            f"Pembayaran Berhasil! Silakan akses materi lengkap Anda di sini: {download_url}\n[📂 Buka Materi Drive]"
        )

        if str(external_id) in self._intents_by_external_id:
            self._intents_by_external_id[str(external_id)]["status"] = "COMPLETED"
            self._intents_by_external_id[str(external_id)]["download_url"] = download_url
            self._intents_by_external_id[str(external_id)]["delivery_message"] = delivery_msg

        if str(external_id) in PAYMENT_INTENTS:
            PAYMENT_INTENTS[str(external_id)]["status"] = "PAID"
            PAYMENT_INTENTS[str(external_id)]["download_url"] = download_url
            PAYMENT_INTENTS[str(external_id)]["delivery_message"] = delivery_msg

    def is_settled(self, external_id: str) -> bool:
        """Checks if a transaction is already completed / settled."""
        return str(external_id) in self._processed_transactions

    async def create_qris_invoice(
        self,
        tenant_slug: str,
        amount: int,
        product_name: str = "Produk",
        customer_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates a dynamic QRIS invoice specifically for closing and checkout flows."""
        clean_slug = str(tenant_slug).replace("_", "-").lower()[:8]
        external_id = f"INV-{clean_slug.upper()}-{uuid4().hex[:6].upper()}"
        return await self.create_dynamic_qris(
            external_id=external_id,
            amount=int(amount),
            tenant_id=tenant_slug,
            customer_phone=customer_phone,
            metadata={"product_name": product_name, "tenant_slug": tenant_slug},
        )

    def clear_state(self) -> None:
        """Resets in-memory state for testing isolation."""
        self._intents_by_external_id.clear()
        self._processed_transactions.clear()


# Global Singleton
xendit_service = XenditService()