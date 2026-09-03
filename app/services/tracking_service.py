"""app/services/tracking_service.py
Server-side Conversions API (CAPI) Tracking Service for Meta & TikTok.

Handles server-side purchase event dispatching on confirmed payment:
- Meta Conversions API (CAPI): POST https://graph.facebook.com/v20.0/{PIXEL_ID}/events with event 'Purchase'
- TikTok Events API (CAPI): POST https://business-api.tiktok.com/open_api/v1.3/pixel/track/ with event 'CompletePayment'
- SHA-256 Hashing for user privacy data (email, phone formatted E.164).
"""

import os
import time
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("TRACKING_SERVICE")


def hash_sha256(val: Optional[str]) -> Optional[str]:
    """Hashes string with SHA-256 for privacy compliance (Meta & TikTok CAPI requirement)."""
    if not val:
        return None
    clean = str(val).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def normalize_phone_digits(phone: Optional[str]) -> str:
    """Normalizes phone number to standard international E.164 without plus sign."""
    if not phone:
        return ""
    digits = "".join(filter(str.isdigit, str(phone).strip()))
    if digits.startswith("08"):
        digits = "62" + digits[1:]
    elif digits.startswith("008"):
        digits = "62" + digits[2:]
    elif digits.startswith("8") and len(digits) in (9, 10, 11, 12, 13):
        digits = "62" + digits
    elif digits.startswith("6208"):
        digits = "62" + digits[3:]
    return digits


async def dispatch_meta_capi(order_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dispatches server-side 'Purchase' conversion event to Meta Conversions API (Graph API v20.0).
    
    POST https://graph.facebook.com/v20.0/{PIXEL_ID}/events
    """
    pixel_id = (
        order_data.get("meta_pixel_id")
        or order_data.get("pixel_id")
        or os.getenv("META_PIXEL_ID")
        or os.getenv("PIXEL_ID")
        or "1035252514589252"
    )
    access_token = (
        order_data.get("meta_access_token")
        or os.getenv("META_CAPI_ACCESS_TOKEN")
        or os.getenv("META_CAPI_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("CAREER_ACCESS_TOKEN")
        or ""
    )

    if not pixel_id or not access_token:
        logger.warning(f"[Meta CAPI] Skipped: Missing pixel_id or access_token (pixel_id={pixel_id})")
        return None

    order_id = str(
        order_data.get("order_id")
        or order_data.get("id")
        or order_data.get("external_id")
        or f"ORD-{int(time.time())}"
    )
    raw_amount = (
        order_data.get("amount")
        or order_data.get("total_amount")
        or order_data.get("gross_amount")
        or 0
    )
    try:
        amount_val = float(raw_amount)
    except (ValueError, TypeError):
        amount_val = 0.0

    email = order_data.get("customer_email") or order_data.get("email")
    phone = order_data.get("customer_phone") or order_data.get("phone")
    clean_phone = normalize_phone_digits(phone)

    hashed_email = hash_sha256(email) if email else None
    hashed_phone = hash_sha256(clean_phone) if clean_phone else None
    event_timestamp = int(time.time())
    dedup_event_id = f"PURCHASE_{order_id}"

    user_data: Dict[str, Any] = {
        "client_user_agent": order_data.get("user_agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "client_ip_address": order_data.get("client_ip") or "127.0.0.1",
    }
    if hashed_email:
        user_data["em"] = [hashed_email]
    if hashed_phone:
        user_data["ph"] = [hashed_phone]
    if order_data.get("fbclid"):
        user_data["fbc"] = f"fb.1.{event_timestamp}.{order_data['fbclid']}"
    if order_data.get("fbp"):
        user_data["fbp"] = str(order_data["fbp"])

    custom_data = {
        "currency": "IDR",
        "value": amount_val,
        "order_id": order_id,
        "content_type": "product",
    }
    if order_data.get("product_name"):
        custom_data["content_name"] = str(order_data["product_name"])

    payload = {
        "data": [
            {
                "event_name": "Purchase",
                "event_time": event_timestamp,
                "event_id": dedup_event_id,
                "action_source": "website",
                "user_data": user_data,
                "custom_data": custom_data,
            }
        ]
    }

    url = f"https://graph.facebook.com/v20.0/{pixel_id}/events"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                res_json = resp.json()
                logger.info(f"[Meta CAPI Success] Purchase event sent for order '{order_id}': {res_json.get('events_received', 1)} event(s) received")
                return res_json
            else:
                logger.warning(f"[Meta CAPI Warning] Status {resp.status_code}: {resp.text[:200]}")
                return None
    except Exception as e:
        logger.error(f"[Meta CAPI Error] Exception dispatching Purchase for '{order_id}': {e}")
        return None


async def dispatch_tiktok_capi(order_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Dispatches server-side 'CompletePayment' conversion event to TikTok Events API.
    
    POST https://business-api.tiktok.com/open_api/v1.3/pixel/track/
    """
    pixel_id = (
        order_data.get("tiktok_pixel_id")
        or order_data.get("tiktok_pixel_code")
        or os.getenv("TIKTOK_PIXEL_ID")
        or os.getenv("TIKTOK_PIXEL_CODE")
        or ""
    )
    access_token = (
        order_data.get("tiktok_access_token")
        or os.getenv("TIKTOK_ACCESS_TOKEN")
        or os.getenv("TIKTOK_API_KEY")
        or ""
    )

    if not pixel_id or not access_token:
        logger.info("[TikTok CAPI] Skipped: Missing pixel_id or access_token")
        return None

    order_id = str(
        order_data.get("order_id")
        or order_data.get("id")
        or order_data.get("external_id")
        or f"ORD-{int(time.time())}"
    )
    raw_amount = (
        order_data.get("amount")
        or order_data.get("total_amount")
        or order_data.get("gross_amount")
        or 0
    )
    try:
        amount_val = float(raw_amount)
    except (ValueError, TypeError):
        amount_val = 0.0

    email = order_data.get("customer_email") or order_data.get("email")
    phone = order_data.get("customer_phone") or order_data.get("phone")
    clean_phone = normalize_phone_digits(phone)

    hashed_email = hash_sha256(email) if email else None
    hashed_phone = hash_sha256(clean_phone) if clean_phone else None
    dedup_event_id = f"COMPLETEPAYMENT_{order_id}"

    user_obj: Dict[str, Any] = {}
    if hashed_email:
        user_obj["email"] = hashed_email
    if hashed_phone:
        user_obj["phone"] = hashed_phone
    if order_data.get("ttclid"):
        user_obj["ttclid"] = str(order_data["ttclid"])

    properties_obj: Dict[str, Any] = {
        "currency": "IDR",
        "value": amount_val,
        "order_id": order_id,
    }
    if order_data.get("product_name"):
        properties_obj["content_name"] = str(order_data["product_name"])

    payload = {
        "pixel_code": pixel_id,
        "event": "CompletePayment",
        "event_id": dedup_event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": {
            "ad": {
                "callback": order_data.get("ttclid")
            },
            "user": user_obj,
            "ip": order_data.get("client_ip") or "127.0.0.1",
            "user_agent": order_data.get("user_agent") or "Mozilla/5.0",
        },
        "properties": properties_obj,
    }

    url = "https://business-api.tiktok.com/open_api/v1.3/pixel/track/"
    headers = {
        "Access-Token": access_token,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                res_json = resp.json()
                logger.info(f"[TikTok CAPI Success] CompletePayment event sent for order '{order_id}'")
                return res_json
            else:
                logger.warning(f"[TikTok CAPI Warning] Status {resp.status_code}: {resp.text[:200]}")
                return None
    except Exception as e:
        logger.error(f"[TikTok CAPI Error] Exception dispatching CompletePayment for '{order_id}': {e}")
        return None


async def dispatch_all_capi(order_data: Dict[str, Any]) -> None:
    """Asynchronous background task executing Meta CAPI & TikTok CAPI concurrently."""
    import asyncio
    try:
        await asyncio.gather(
            dispatch_meta_capi(order_data),
            dispatch_tiktok_capi(order_data),
            return_exceptions=True
        )
    except Exception as e:
        logger.warning(f"[CAPI Dispatch Error] {e}")
