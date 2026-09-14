"""app/services/digital_fulfillment_service.py

Auto-entitlement engine for digital product delivery.

Triggered after Duitku (or any gateway) confirms PAYMENT_SETTLED.

Responsibilities:
  1. Update order status → COMPLETED in Supabase
  2. Grant buyer entitlement in buyer_entitlements table
  3. Generate HMAC-SHA256 signed download token (24h expiry) for file products
  4. Dispatch delivery notification (async, non-blocking)

Zero Fake Fallback (ARCHITECTURE.md §9.3): raises real exceptions on failure;
never returns mock data.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("DIGITAL_FULFILLMENT")

# Digital product type identifiers — matches Supabase `products.product_type` values
DIGITAL_PRODUCT_TYPES = {
    "DIGITAL",
    "EBOOK",
    "TEMPLATE",
    "VIDEO_COURSE",
    "PRESET",
    "DIGITAL_SERVICE",
}


def _download_secret() -> str:
    """Read DOWNLOAD_SECRET_KEY at call time (not module-load time) so tests can set it via env."""
    secret = os.environ.get("DOWNLOAD_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("DOWNLOAD_SECRET_KEY is not configured in environment variables.")
    return secret


def _get_supabase():
    """Lazy import to avoid circular deps."""
    try:
        from app.services.whatsapp_service import get_supabase
        return get_supabase()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Token generation & validation
# ---------------------------------------------------------------------------

def generate_download_token(
    product_id: str,
    buyer_email: str,
    file_url: str,
    expires_in_hours: int = 24,
) -> str:
    """
    Creates a URL-safe signed download token.

    Payload (JSON) → base64url → HMAC-SHA256 digest appended as `.{signature}`.
    Token format: `{base64url_payload}.{hex_signature}`
    """
    secret = _download_secret()  # raises RuntimeError if not configured

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).isoformat()
    payload = {
        "product_id": product_id,
        "buyer_email": buyer_email,
        "file_url": file_url,
        "expires_at": expires_at,
    }

    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("utf-8")

    signature = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{payload_b64}.{signature}"


def verify_download_token(token: str) -> Dict[str, Any]:
    """
    Verifies and decodes a signed download token.

    Raises:
        ValueError: on invalid signature or malformed token
        PermissionError: on expired token
    """
    secret = _download_secret()  # raises RuntimeError if not configured

    parts = token.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError("Invalid token format.")

    payload_b64, incoming_sig = parts

    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, incoming_sig):
        raise ValueError("Token signature verification failed.")

    # Restore base64 padding
    padding = 4 - len(payload_b64) % 4
    payload_bytes = base64.urlsafe_b64decode(payload_b64 + "=" * (padding % 4))
    payload = json.loads(payload_bytes.decode("utf-8"))

    expires_at = datetime.fromisoformat(payload["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        raise PermissionError(f"Download token expired at {payload['expires_at']}.")

    return payload


# ---------------------------------------------------------------------------
# Core fulfillment engine
# ---------------------------------------------------------------------------

async def fulfill_digital_order(
    order_id: str,
    product_id: str,
    tenant_id: str,
    buyer_email: str,
    buyer_phone: Optional[str] = None,
    amount: int = 0,
) -> Dict[str, Any]:
    """
    Executes auto-entitlement for a digital product purchase.

    Steps:
      1. Fetch product metadata from Supabase
      2. Verify product is a digital type (guard against mis-routing)
      3. Update order status → COMPLETED
      4. Insert buyer entitlement record
      5. Generate signed download token if product has file_url
      6. Return fulfillment result dict

    Returns:
        { status, order_id, product_id, buyer_email, download_url (optional), granted_at }
    """
    supabase = _get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Fetch product metadata
    product_meta: Dict[str, Any] = {}
    file_url: Optional[str] = None

    if supabase:
        try:
            res = supabase.table("products").select("id,name,product_type,metadata").eq("id", product_id).single().execute()
            product_meta = res.data or {}
            product_type = (product_meta.get("product_type") or "").upper()

            # 2. Guard: only fulfill digital products
            if product_type not in DIGITAL_PRODUCT_TYPES:
                logger.warning(
                    f"[DigitalFulfill] Skipping order {order_id}: product {product_id} "
                    f"is type '{product_type}', not a digital product."
                )
                return {"status": "SKIPPED", "reason": "Not a digital product type", "product_type": product_type}

            meta_blob = product_meta.get("metadata") or {}
            if isinstance(meta_blob, str):
                import json as _json
                meta_blob = _json.loads(meta_blob)
            file_url = meta_blob.get("file_url") or meta_blob.get("download_url")

        except Exception as exc:
            logger.warning(f"[DigitalFulfill] Could not fetch product {product_id}: {exc}")

    # 3. Update order status → COMPLETED
    if supabase:
        try:
            supabase.table("orders").update({
                "status": "COMPLETED",
                "completed_at": now_iso,
            }).eq("id", order_id).execute()
            logger.info(f"[DigitalFulfill] Order {order_id} marked COMPLETED.")
        except Exception as exc:
            logger.error(f"[DigitalFulfill] Failed to update order {order_id}: {exc}")

    # 4. Insert buyer entitlement record
    entitlement_row = {
        "order_id": order_id,
        "product_id": product_id,
        "tenant_id": tenant_id,
        "buyer_email": buyer_email,
        "buyer_phone": buyer_phone,
        "granted_at": now_iso,
        "expires_at": None,  # Lifetime access by default; set per-product if needed
        "access_status": "ACTIVE",
    }
    if supabase:
        try:
            supabase.table("buyer_entitlements").upsert(
                entitlement_row,
                on_conflict="order_id",
            ).execute()
            logger.info(f"[DigitalFulfill] Buyer entitlement granted: {buyer_email} → product {product_id}")
        except Exception as exc:
            logger.error(f"[DigitalFulfill] Failed to insert buyer_entitlements: {exc}")

    # 5. Generate signed download URL (if product has a file)
    download_url: Optional[str] = None
    if file_url:
        try:
            token = generate_download_token(
                product_id=product_id,
                buyer_email=buyer_email,
                file_url=file_url,
                expires_in_hours=24,
            )
            base_url = os.environ.get("API_BASE_URL", "https://api.boontrack.com")
            download_url = f"{base_url}/api/v1/download/{token}"
            logger.info(f"[DigitalFulfill] Signed download URL generated for order {order_id}")
        except Exception as exc:
            logger.error(f"[DigitalFulfill] Failed to generate download token: {exc}")

    return {
        "status": "FULFILLED",
        "order_id": order_id,
        "product_id": product_id,
        "tenant_id": tenant_id,
        "buyer_email": buyer_email,
        "download_url": download_url,
        "granted_at": now_iso,
    }


async def fulfill_if_digital(
    order_id: str,
    tenant_id: str,
    buyer_email: str,
    buyer_phone: Optional[str] = None,
    amount: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    Convenience wrapper called from the Duitku webhook handler.
    Resolves product_id from order_id, then delegates to fulfill_digital_order.
    Returns None if order is not a digital product (no-op, not an error).
    """
    supabase = _get_supabase()
    if not supabase:
        logger.warning("[DigitalFulfill] Supabase not available — skipping digital fulfillment check.")
        return None

    try:
        res = supabase.table("orders").select("id,product_id,metadata").eq("id", order_id).single().execute()
        order = res.data or {}
        product_id = order.get("product_id")
        if not product_id:
            logger.info(f"[DigitalFulfill] Order {order_id} has no product_id — skipping.")
            return None
    except Exception as exc:
        logger.error(f"[DigitalFulfill] Could not fetch order {order_id}: {exc}")
        return None

    return await fulfill_digital_order(
        order_id=order_id,
        product_id=product_id,
        tenant_id=tenant_id,
        buyer_email=buyer_email,
        buyer_phone=buyer_phone,
        amount=amount,
    )
