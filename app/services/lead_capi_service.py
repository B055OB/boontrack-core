"""app/services/lead_capi_service.py
Meta Conversions API (CAPI) background dispatcher for 'Lead' conversion events.
Triggered asynchronously via FastAPI BackgroundTasks during tenant onboarding intake.
"""

import os
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("LEAD_CAPI")


def sanitize_e164_phone(phone: Optional[str]) -> str:
    """Sanitizes phone number into E.164 compatible format (Indonesian standard: 628...)."""
    if not phone:
        return ""
    digits = "".join(filter(str.isdigit, str(phone).strip()))
    if digits.startswith("08"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    return digits


def hash_sha256(value: Optional[str]) -> Optional[str]:
    """Generates SHA-256 hex digest of stripped lowercase string for privacy compliance."""
    if not value:
        return None
    clean = str(value).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


async def dispatch_meta_lead_event(
    prospect_id: str,
    brand_name: str,
    industry: str,
    pic_name: str,
    whatsapp: str,
    client_ip: Optional[str] = None,
    client_user_agent: Optional[str] = None,
) -> bool:
    """Sends a 'Lead' conversion event to Meta Conversions API asynchronously.
    
    Ensures zero PII leakage: WhatsApp and PIC Name are hashed with SHA-256 before egress.
    Designed for FastAPI BackgroundTasks (non-blocking, fail-safe).
    """
    pixel_id = os.getenv("META_PIXEL_ID", "boontrack_pixel_default")
    token = (
        os.getenv("META_CAPI_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or ""
    )

    now_ts = int(datetime.now(timezone.utc).timestamp())

    # 1. Privacy Hashing
    e164_phone = sanitize_e164_phone(whatsapp)
    hashed_phone = hash_sha256(e164_phone) if e164_phone else None

    name_tokens = pic_name.strip().split()
    first_name = name_tokens[0] if name_tokens else ""
    last_name = " ".join(name_tokens[1:]) if len(name_tokens) > 1 else ""
    hashed_first_name = hash_sha256(first_name) if first_name else None
    hashed_last_name = hash_sha256(last_name) if last_name else None
    hashed_external_id = hash_sha256(str(prospect_id))

    user_data: Dict[str, Any] = {
        "ph": [hashed_phone] if hashed_phone else [],
        "fn": [hashed_first_name] if hashed_first_name else [],
        "ln": [hashed_last_name] if hashed_last_name else [],
        "external_id": [hashed_external_id] if hashed_external_id else [],
    }

    if client_ip:
        user_data["client_ip_address"] = client_ip
    if client_user_agent:
        user_data["client_user_agent"] = client_user_agent

    event_data = {
        "event_name": "Lead",
        "event_time": now_ts,
        "event_id": f"lead_{prospect_id}",
        "action_source": "website",
        "user_data": user_data,
        "custom_data": {
            "content_name": "Tenant Pilot Onboarding",
            "content_category": industry,
            "brand_name": brand_name,
            "status": "PROSPECT_PILOT_REQUESTED",
        },
    }

    payload = {"data": [event_data]}

    # Mock mode jika token belum diset
    if not token or pixel_id == "boontrack_pixel_default":
        logger.info(
            f"[Meta CAPI Lead Mock/Skip] Lead event logged for prospect '{prospect_id}' | "
            f"Brand: '{brand_name}' | PIC: '{pic_name}' | Pixel: {pixel_id}"
        )
        return True

    url = f"https://graph.facebook.com/v19.0/{pixel_id}/events"
    params = {"access_token": token}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, params=params, json=payload)
            if resp.status_code in (200, 201):
                logger.info(
                    f"[Meta CAPI Lead] Berhasil kirim event Lead prospect '{prospect_id}' ({brand_name})"
                )
                return True
            else:
                logger.warning(
                    f"[Meta CAPI Lead] Dispatch warning ({resp.status_code}): {resp.text}"
                )
                return False
    except Exception as e:
        logger.error(
            f"[Meta CAPI Lead] Gagal kirim Lead event untuk prospect '{prospect_id}': {e}",
            exc_info=True,
        )
        return False
