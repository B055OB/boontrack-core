import hashlib
import time
import httpx
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("capi_service")

def _hash_field(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    clean = val.strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()

def _hash_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    # Bersihkan karakter non-digit
    clean = "".join(filter(str.isdigit, phone.strip()))
    # Normalisasi format internasional Indonesia jika berawalan '0'
    if clean.startswith("0"):
        clean = "62" + clean[1:]
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()

async def dispatch_seller_capi_purchase(
    order: Dict[str, Any],
    pixel_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Mengirim event Purchase server-side ke Meta dan TikTok.
    Deduplication key identik dengan browser: PURCHASE_{order_id}
    """
    order_id = str(order.get("id"))
    dedup_event_id = f"PURCHASE_{order_id}"
    amount = float(order.get("gross_amount", 0))
    email = order.get("customer_email")
    phone = order.get("customer_phone")
    user_agent = order.get("user_agent")
    client_ip = order.get("client_ip")
    
    # Click IDs & UTMs
    fbclid = order.get("fbclid")
    ttclid = order.get("ttclid")

    hashed_email = _hash_field(email)
    hashed_phone = _hash_phone(phone)
    event_timestamp = int(time.time())

    results = {"meta": None, "tiktok": None}

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. META CONVERSIONS API (CAPI)
        meta_pixel_id = pixel_config.get("meta_pixel_id")
        meta_access_token = pixel_config.get("meta_access_token")

        if meta_pixel_id and meta_access_token:
            user_data = {
                "client_user_agent": user_agent,
                "client_ip_address": client_ip,
            }
            if hashed_email:
                user_data["em"] = [hashed_email]
            if hashed_phone:
                user_data["ph"] = [hashed_phone]
            if fbclid:
                user_data["fbc"] = f"fb.1.{event_timestamp}.{fbclid}"

            meta_payload = {
                "data": [
                    {
                        "event_name": "Purchase",
                        "event_time": event_timestamp,
                        "event_id": dedup_event_id,
                        "action_source": "website",
                        "user_data": user_data,
                        "custom_data": {
                            "currency": "IDR",
                            "value": amount,
                            "order_id": order_id
                        }
                    }
                ],
                "access_token": meta_access_token
            }

            try:
                meta_url = f"https://graph.facebook.com/v19.0/{meta_pixel_id}/events"
                meta_res = await client.post(meta_url, json=meta_payload)
                results["meta"] = meta_res.json()
            except Exception as e:
                logger.error(f"[CAPI Meta] Gagal dispatch untuk order {order_id}: {e}")

        # 2. TIKTOK EVENTS API
        tiktok_pixel_id = pixel_config.get("tiktok_pixel_id")
        tiktok_access_token = pixel_config.get("tiktok_access_token")

        if tiktok_pixel_id and tiktok_access_token:
            user_info = {
                "ip": client_ip,
                "user_agent": user_agent,
            }
            if hashed_email:
                user_info["email"] = hashed_email
            if hashed_phone:
                user_info["phone_number"] = hashed_phone
            if ttclid:
                user_info["ttclid"] = ttclid

            tiktok_payload = {
                "pixel_code": tiktok_pixel_id,
                "event": "CompletePayment",
                "event_id": dedup_event_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "context": {
                    "user": user_info
                },
                "properties": {
                    "currency": "IDR",
                    "value": amount
                }
            }

            try:
                tiktok_url = "https://business-api.tiktok.com/open_api/v1.3/event/track/"
                tiktok_headers = {
                    "Access-Token": tiktok_access_token,
                    "Content-Type": "application/json"
                }
                tiktok_res = await client.post(tiktok_url, json=tiktok_payload, headers=tiktok_headers)
                results["tiktok"] = tiktok_res.json()
            except Exception as e:
                logger.error(f"[CAPI TikTok] Gagal dispatch untuk order {order_id}: {e}")

    return results