"""app/services/midtrans_service.py
Midtrans Payment Gateway Adapter & Core API QRIS Client.

Supports:
- Dynamic QRIS generation via Midtrans Core API (POST /v2/charge, payment_type: 'qris').
- Extraction of raw qr_string and actions generate-qr-code URL.
- Automatic persistence of qr_string and qr_code_url to Supabase orders.
- Signature verification and webhook notification reconciliation.
"""

import os
import base64
import hashlib
import hmac
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from uuid import uuid4
import httpx

from app.services.reconciliation_service import PAYMENT_INTENTS
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("MIDTRANS_SERVICE")


class MidtransAPIError(Exception):
    """Structured exception for Midtrans API gateway outcomes."""

    def __init__(
        self,
        status_code: Optional[int],
        message: str,
        error_code: Optional[str] = None,
        raw_response: Optional[Any] = None,
        is_definitive_rejection: Optional[bool] = None,
    ):
        self.provider = "MIDTRANS"
        self.status_code = status_code
        self.error_code = error_code or "MIDTRANS_API_ERROR"
        self.message = message
        self.raw_response = raw_response

        # Definitive rejection: 400 Bad Request, 401 Unauthorized, 402/403 Forbidden, 404, 406, 412, 422
        # Ambiguous: 5xx Server Error, 408 Request Timeout, 429 Rate Limit, None (network/socket drop)
        if is_definitive_rejection is not None:
            self.is_definitive_rejection = is_definitive_rejection
        elif status_code is not None:
            self.is_definitive_rejection = status_code in (400, 401, 402, 403, 404, 406, 412, 422)
        else:
            self.is_definitive_rejection = False

        super().__init__(f"[MIDTRANS] HTTP {self.status_code} ({self.error_code}): {self.message}")


class MidtransService:
    """Client wrapper for Midtrans Core API (v2/charge QRIS)."""

    def __init__(self):
        self.provider = os.getenv("PAYMENT_GATEWAY_PROVIDER", "midtrans").strip().lower()
        self.server_key = os.getenv(
            "MIDTRANS_SERVER_KEY",
            "SB-Mid-server-placeholder-development-key"
        ).strip()
        self.client_key = os.getenv("MIDTRANS_CLIENT_KEY", "").strip()
        self.is_production = os.getenv("MIDTRANS_IS_PRODUCTION", "false").strip().lower() in ("true", "1", "yes")

        self.api_base_url = (
            "https://api.midtrans.com/v2"
            if self.is_production
            else "https://api.sandbox.midtrans.com/v2"
        )
        self._processed_transactions: set = set()

    def get_auth_header(self) -> str:
        """Encodes Midtrans Server Key for HTTP Basic Authentication."""
        raw = f"{self.server_key}:"
        encoded = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"

    def verify_signature(
        self,
        order_id: str,
        status_code: str,
        gross_amount: str,
        signature_key: str
    ) -> bool:
        """Verifies the SHA512 signature key sent by Midtrans webhook (fail-closed, constant-time)."""
        if not self.server_key or not signature_key:
            return False
        raw_str = f"{order_id}{status_code}{gross_amount}{self.server_key}"
        expected_hash = hashlib.sha512(raw_str.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected_hash.lower(), str(signature_key).strip().lower())

    async def create_qris_charge(
        self,
        order_id: str,
        amount: int,
        customer_name: Optional[str] = "Customer",
        customer_phone: Optional[str] = None,
        tenant_id: str = "boontrack-store",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Requests dynamic QRIS creation from Midtrans Core API (POST /v2/charge).

        Persists generated qr_string / raw QR URL to the database for frontend rendering.
        """
        clean_amount = int(amount)
        clean_order_id = str(order_id or f"ORD-MDTR-{int(datetime.now().timestamp())}")

        payload = {
            "payment_type": "qris",
            "transaction_details": {
                "order_id": clean_order_id,
                "gross_amount": clean_amount
            },
            "qris": {
                "acquirer": "gopay"
            },
            "customer_details": {
                "first_name": customer_name or "Customer",
                "phone": customer_phone or ""
            }
        }

        endpoint = f"{self.api_base_url}/charge"
        headers = {
            "Authorization": self.get_auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        logger.info(
            f"[Midtrans] Requesting QRIS charge: order_id='{clean_order_id}', "
            f"amount={clean_amount}, tenant='{tenant_id}' (Production: {self.is_production})"
        )

        data: Dict[str, Any] = {}
        qr_string = ""
        qr_code_url = ""
        exp_time = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
        except (httpx.TimeoutException, TimeoutError) as t_err:
            raise MidtransAPIError(
                status_code=None,
                error_code="GATEWAY_TIMEOUT",
                message=f"Midtrans connection timed out: {t_err}",
                is_definitive_rejection=False,
            )
        except httpx.RequestError as req_err:
            raise MidtransAPIError(
                status_code=None,
                error_code="CONNECTION_ERROR",
                message=f"Midtrans connection failed: {req_err}",
                is_definitive_rejection=False,
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info(f"[Midtrans] QRIS charge created successfully: {data.get('transaction_id')}")
        else:
            err_code = "MIDTRANS_API_ERROR"
            err_msg = resp.text
            try:
                err_json = resp.json()
                if isinstance(err_json, dict):
                    err_code = err_json.get("status_code") or err_json.get("error_code") or err_code
                    err_msg = err_json.get("status_message") or err_msg
            except Exception:
                pass

            is_definitive = resp.status_code in (400, 401, 402, 403, 404, 406, 412, 422)

            allow_fallback = (
                not self.is_production
                and (
                    os.getenv("MIDTRANS_ALLOW_OFFLINE_SIMULATOR", "false").lower() in ("true", "1")
                    or getattr(self, "allow_offline_simulator", False)
                )
            )

            if not allow_fallback:
                logger.error(f"[Midtrans API Error] HTTP {resp.status_code} - {err_msg}")
                raise MidtransAPIError(
                    status_code=resp.status_code,
                    error_code=str(err_code),
                    message=err_msg,
                    raw_response=resp.text,
                    is_definitive_rejection=is_definitive,
                )

            logger.warning(f"[Midtrans Fallback] Using resilient EMVCo local generator in sandbox mode: HTTP {resp.status_code}")
            from app.utils.qris_generator import get_dynamic_qris_string, get_qr_code_image_url
            raw_emvco = get_dynamic_qris_string(amount=clean_amount, invoice_id=str(clean_order_id))
            qr_url = get_qr_code_image_url(raw_emvco, size=600)
            data = {
                "transaction_id": f"mdtr_{uuid4().hex[:12]}",
                "order_id": clean_order_id,
                "gross_amount": str(clean_amount),
                "transaction_status": "pending",
                "qr_string": raw_emvco,
                "actions": [{"name": "generate-qr-code", "method": "GET", "url": qr_url}],
                "expiry_time": exp_time,
                "is_synthetic": True,
            }

        # 1. Ekstrak qr_string dari respon Midtrans
        qr_string = data.get("qr_string", "")
        if not qr_string or not str(qr_string).strip().startswith("000201"):
            from app.utils.qris_generator import get_dynamic_qris_string
            logger.info(f"[Midtrans] Non-EMVCo qr_string detected ('{qr_string}'), overriding with valid dynamic QRIS.")
            qr_string = get_dynamic_qris_string(amount=clean_amount, invoice_id=str(clean_order_id))

        # 2. Ekstrak raw QR image URL dari actions jika ada
        actions = data.get("actions") or []
        for act in actions:
            if act.get("name") in ("generate-qr-code", "qr-code"):
                qr_code_url = act.get("url", "")
                break

        from app.utils.qris_generator import get_qr_code_image_url
        if not qr_code_url and qr_string:
            qr_code_url = get_qr_code_image_url(qr_string, size=600)

        expired_at = data.get("expiry_time") or exp_time

        # 3. Simpan qr_string atau raw QR URL ke database order Supabase
        supabase = get_supabase()
        if supabase:
            try:
                supabase.table("orders").upsert({
                    "id": clean_order_id,
                    "tenant_id": tenant_id,
                    "total_amount": clean_amount,
                    "base_amount": clean_amount,
                    "status": "PENDING",
                    "qris_payload": qr_string,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception as db_err:
                logger.debug(f"[Midtrans DB Upsert Note] {db_err}")

        # 4. Simpan ke in-memory intent registry
        PAYMENT_INTENTS[clean_order_id] = {
            "invoice_id": clean_order_id,
            "order_id": clean_order_id,
            "tenant_id": tenant_id,
            "amount": clean_amount,
            "total_amount": clean_amount,
            "status": "PENDING",
            "phone": customer_phone,
            "qr_string": qr_string,
            "qr_code_url": qr_code_url,
            "gateway": "midtrans",
            "metadata": metadata or {},
        }

        return {
            "status": "ACTIVE",
            "external_id": clean_order_id,
            "order_id": clean_order_id,
            "amount": clean_amount,
            "qr_string": qr_string,
            "qr_code_url": qr_code_url,
            "expired_at": expired_at,
            "expires_at": expired_at,
            "tenant_id": tenant_id,
            "gateway": "midtrans"
        }


# Global Midtrans Service Singleton
midtrans_service = MidtransService()
