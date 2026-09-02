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


def hash_sha256(value: Optional[str]) -> Optional[str]:
    """CTO Guardrail: Data privasi WAJIB di-hash SHA-256 sebelum keluar dari backend."""
    if not value:
        return None
    clean = str(value).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


async def send_meta_capi_purchase(
    external_id: str,
    value: float,
    currency: str = "IDR",
    phone: Optional[str] = None,
    email: Optional[str] = None,
    fbclid: Optional[str] = None,
    client_ip: Optional[str] = None,
    client_user_agent: Optional[str] = None,
    user_id: Optional[str] = None,
) -> bool:
    """Sends a 'Purchase' conversion event to Meta Conversions API.
    
    Fail-safe: tidak melempar exception fatal jika Meta API down.
    """
    pixel_id = os.getenv("META_PIXEL_ID", "boontrack_pixel_default")
    token = (
        os.getenv("META_CAPI_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or ""
    )

    now_ts = int(datetime.now(timezone.utc).timestamp())

    # Format nomor telepon (standar internasional 628xxx) lalu di-hash
    clean_phone = ""
    if phone:
        digits = "".join(filter(str.isdigit, str(phone)))
        if digits.startswith("08"):
            digits = "62" + digits[1:]
        elif digits.startswith("8"):
            digits = "62" + digits
        clean_phone = digits

    hashed_phone = hash_sha256(clean_phone) if clean_phone else None
    hashed_email = hash_sha256(email) if email else None

    user_data: Dict[str, Any] = {
        "ph": [hashed_phone] if hashed_phone else [],
        "em": [hashed_email] if hashed_email else [],
        "external_id": [hash_sha256(str(external_id))],
    }

    if client_ip:
        user_data["client_ip_address"] = client_ip
    if client_user_agent:
        user_data["client_user_agent"] = client_user_agent
    if fbclid:
        user_data["fbc"] = f"fb.1.{now_ts}.{fbclid}"

    event_data = {
        "event_name": "Purchase",
        "event_time": now_ts,
        "event_id": f"order_{external_id}",
        "action_source": "website",
        "user_data": user_data,
        "custom_data": {
            "currency": currency.upper(),
            "value": float(value),
            "order_id": str(external_id),
        },
    }

    payload = {"data": [event_data]}

    # Mode Mock jika token belum dipasang
    if not token or pixel_id == "boontrack_pixel_default":
        logger.info(
            f"[Meta CAPI Mock/Skip] Event Purchase dicatat untuk order '{external_id}' "
            f"(Value: {currency} {value:,.0f}) | pixel_id={pixel_id}"
        )
        return True

    url = f"https://graph.facebook.com/v19.0/{pixel_id}/events"
    params = {"access_token": token}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, params=params, json=payload)
            if resp.status_code in (200, 201):
                logger.info(f"[Meta CAPI] Berhasil kirim Purchase order '{external_id}' (Value: {value})")
                return True
            else:
                logger.warning(f"[Meta CAPI] Dispatch warning: {resp.status_code} - {resp.text}")
                return False
    except Exception as e:
        logger.error(f"[Meta CAPI] Error kirim purchase event untuk '{external_id}': {e}", exc_info=True)
        return False