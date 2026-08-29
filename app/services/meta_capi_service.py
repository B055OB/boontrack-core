"""app/services/meta_capi_service.py
Meta Conversions API (CAPI) service for dispatching purchase and conversion events.
"""

import os
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("META_CAPI")


def hash_sha256(value: str) -> str:
    """Hashes normalized string using SHA-256 for Meta CAPI PII requirements."""
    if not value:
        return ""
    clean = str(value).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


async def send_meta_capi_purchase(
    external_id: str,
    value: int,
    currency: str = "IDR",
    phone: Optional[str] = None,
    user_id: Optional[str] = None,
) -> bool:
    """Sends a 'Purchase' conversion event to Meta Conversions API.
    
    Args:
        external_id: Transaction / Order ID used as event_id for deduplication.
        value: Monetary value of the purchase.
        currency: 3-letter currency code (default: 'IDR').
        phone: Customer phone number (will be normalized and SHA-256 hashed).
        user_id: Optional user identifier.
        
    Returns:
        bool: True if event was dispatched successfully or mocked safely.
    """
    pixel_id = os.getenv("META_PIXEL_ID", "boontrack_pixel_default")
    token = (
        os.getenv("META_CAPI_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or ""
    )

    now_ts = int(datetime.now(timezone.utc).timestamp())
    
    # Normalize and hash phone number if provided
    clean_phone = ""
    if phone:
        digits = "".join(filter(str.isdigit, str(phone)))
        if digits.startswith("08"):
            digits = "62" + digits[1:]
        clean_phone = digits

    hashed_phone = hash_sha256(clean_phone) if clean_phone else None
    hashed_uid = hash_sha256(str(user_id)) if user_id else None

    event_data = {
        "event_name": "Purchase",
        "event_time": now_ts,
        "event_id": str(external_id),
        "action_source": "system_generated",
        "user_data": {
            "ph": [hashed_phone] if hashed_phone else [],
            "external_id": [hash_sha256(str(external_id))],
        },
        "custom_data": {
            "currency": currency,
            "value": float(value),
        },
    }
    if hashed_uid:
        event_data["user_data"]["client_user_agent"] = "BoonTrack-Core/1.0"

    payload = {"data": [event_data]}

    # In testing or missing token mode, acknowledge gracefully
    if not token or pixel_id == "boontrack_pixel_default":
        logger.info(
            f"[Meta CAPI Mock/Skip] Purchase event recorded for '{external_id}' "
            f"(Value: {currency} {value:,}) - pixel_id={pixel_id}"
        )
        return True

    url = f"https://graph.facebook.com/v19.0/{pixel_id}/events"
    params = {"access_token": token}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, params=params, json=payload)
            if resp.status_code in (200, 201):
                logger.info(f"[Meta CAPI] Successfully sent Purchase event for '{external_id}' (Value: {value})")
                return True
            else:
                logger.warning(f"[Meta CAPI] Event dispatch warning: {resp.status_code} - {resp.text}")
                return False
    except Exception as e:
        logger.error(f"[Meta CAPI] Error sending purchase event for '{external_id}': {e}", exc_info=True)
        return False
