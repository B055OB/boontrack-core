"""
app/services/meta_waba_service.py
Service Dispatcher for Meta WhatsApp Business Cloud API (Graph API v20.0).

Provides:
1. MetaGraphAPIDispatcher: Handshake validation, template formatting & dispatch.
2. Broadcast Worker: Asynchronous queue runner with rate limiter and database logging.
3. Webhook Status Tracker: Idempotent message state transitions (sent, delivered, read, failed).
"""

import os
import time
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Union
import httpx

from app.services.whatsapp_service import normalize_phone_number, get_supabase

logger = logging.getLogger("META_WABA_SERVICE")

# In-memory storage for broadcast runs and message status lookup (fast & resilient)
BROADCAST_LOGS: Dict[str, Dict[str, Any]] = {}
MESSAGE_STATUS_TRACKER: Dict[str, Dict[str, Any]] = {}

# State hierarchy ranking for idempotent status updates
STATUS_RANK = {
    "queued": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "failed": 4
}


class MetaGraphAPIDispatcher:
    """Dispatcher for direct Meta WhatsApp Business Cloud API (Graph API)."""

    def __init__(self, default_version: str = "v20.0"):
        self.version = os.getenv("META_GRAPH_VERSION", default_version)
        self.base_url = f"https://graph.facebook.com/{self.version}"

    def get_default_credentials(self, tenant_id: str = "boontrack-career") -> tuple[str, str]:
        """Resolves phone_number_id and permanent_access_token from environment."""
        token = (
            os.getenv("META_WA_PERMANENT_TOKEN")
            or os.getenv("CAREER_ACCESS_TOKEN")
            or os.getenv("WHATSAPP_TOKEN")
            or os.getenv("META_ACCESS_TOKEN")
            or "EAANbiVgBfGQBSQkvsZBc8JmqdEZBJWSrZAWR1gnJep0lkyZAv4O02LKEwjoNAc8lNOvaEeKhtb6pcr45S8wtd5CrSKdoMwEq6A1eJV4Yb140DBOMbmj3wLzo0Y7fZBrus25EJ0xeqXlPbDisP6d4DmZAGkvbJ7hnKfFih3G7L7mn6g56OQVU42dZByNSHNEiwZDZD"
        ).strip()

        phone_id = (
            os.getenv("META_WA_PHONE_NUMBER_ID")
            or os.getenv("CAREER_PHONE_NUMBER_ID")
            or os.getenv("PHONE_NUMBER_ID")
            or "1340866379104241"
        ).strip()

        return phone_id, token

    def transform_template_payload(
        self,
        clean_phone_number: str,
        template_name: str,
        language_code: str = "id",
        body_parameters: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Transforms parameters into Meta WhatsApp Cloud API template message specification."""
        clean_phone = normalize_phone_number(clean_phone_number)
        body_parameters = body_parameters or []

        components = []
        if body_parameters:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": str(val)} for val in body_parameters]
            })

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code or "id"},
            }
        }
        if components:
            payload["template"]["components"] = components

        return payload

    async def test_handshake(
        self,
        phone_number_id: str,
        permanent_access_token: str,
    ) -> Dict[str, Any]:
        """Validates tenant WABA credentials via GET https://graph.facebook.com/v20.0/{phone_number_id}."""
        phone_id = str(phone_number_id).strip()
        token = str(permanent_access_token).strip()

        if not phone_id or not token:
            return {
                "success": False,
                "error": "Missing phone_number_id or permanent_access_token",
                "status_code": 400,
            }

        url = f"{self.base_url}/{phone_id}?fields=verified_name,quality_rating,code_verification_status"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    logger.info(f"[Meta WABA Handshake OK] Phone ID: {phone_id} | Verified Name: {data.get('verified_name')}")
                    return {
                        "success": True,
                        "status": "success",
                        "phone_number_id": phone_id,
                        "verified_name": data.get("verified_name"),
                        "quality_rating": data.get("quality_rating"),
                        "code_verification_status": data.get("code_verification_status"),
                        "raw": data,
                    }
                else:
                    err_msg = resp.text
                    logger.warning(f"[Meta WABA Handshake Failed] Status: {resp.status_code} | Body: {err_msg[:200]}")
                    return {
                        "success": False,
                        "status": "error",
                        "status_code": resp.status_code,
                        "error": err_msg,
                    }
        except Exception as e:
            logger.error(f"[Meta WABA Handshake Exception] {e}", exc_info=True)
            return {
                "success": False,
                "status": "error",
                "error": str(e),
            }

    async def send_template(
        self,
        phone_number_id: str,
        permanent_access_token: str,
        to_phone: str,
        template_name: str,
        language_code: str = "id",
        body_parameters: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Dispatches an official template message to recipient phone number."""
        clean_phone = normalize_phone_number(to_phone)
        if not clean_phone or len(clean_phone) < 10:
            return {
                "success": False,
                "error": f"Invalid recipient phone number: {to_phone}",
                "clean_phone": clean_phone,
            }

        url = f"{self.base_url}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {permanent_access_token}",
            "Content-Type": "application/json",
        }
        payload = self.transform_template_payload(
            clean_phone_number=clean_phone,
            template_name=template_name,
            language_code=language_code,
            body_parameters=body_parameters,
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    res_json = resp.json()
                    msg_id = (res_json.get("messages", [{}])[0].get("id"))
                    logger.info(f"[Meta WABA Template Dispatched] To: {clean_phone} | Template: {template_name} | ID: {msg_id}")
                    return {
                        "success": True,
                        "message_id": msg_id,
                        "data": res_json,
                        "clean_phone": clean_phone,
                    }
                else:
                    err_text = resp.text
                    logger.warning(f"[Meta WABA Template Error] To: {clean_phone} | Code: {resp.status_code} | Msg: {err_text[:200]}")
                    return {
                        "success": False,
                        "status_code": resp.status_code,
                        "error": err_text,
                        "clean_phone": clean_phone,
                    }
        except Exception as e:
            logger.error(f"[Meta WABA Exception] To: {clean_phone}: {e}")
            return {
                "success": False,
                "error": str(e),
                "clean_phone": clean_phone,
            }


# Singleton dispatcher instance
meta_waba_dispatcher = MetaGraphAPIDispatcher()


# ============================================================================
# DATABASE LOGGING & IDEMPOTENT STATUS UPDATES
# ============================================================================

async def log_broadcast_message_to_db(
    broadcast_id: str,
    recipient_phone: str,
    template_name: str,
    status: str,
    message_id: Optional[str] = None,
    error_details: Optional[str] = None,
    tenant_id: str = "boontrack-career",
) -> None:
    """Logs individual broadcast message item to Supabase broadcast_logs / messages."""
    supabase = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()

    if supabase:
        try:
            # 1. Attempt write to broadcast_logs table
            supabase.table("broadcast_logs").insert({
                "broadcast_id": broadcast_id,
                "recipient_phone": recipient_phone,
                "template_name": template_name,
                "status": status,
                "message_id": message_id,
                "error_details": error_details,
                "tenant_id": tenant_id,
                "created_at": now_iso,
            }).execute()
        except Exception as b_err:
            logger.debug(f"[Broadcast Log DB Note] {b_err}")
            # 2. Fallback write to messages table if broadcast_logs is not present
            try:
                supabase.table("messages").insert({
                    "tenant_id": tenant_id,
                    "sender": "bot",
                    "channel": "whatsapp",
                    "user_phone": recipient_phone,
                    "text": f"[Template: {template_name}]",
                    "status": status,
                    "metadata": {
                        "broadcast_id": broadcast_id,
                        "message_id": message_id,
                        "error": error_details,
                        "template_name": template_name,
                    }
                }).execute()
            except Exception as m_err:
                logger.debug(f"[Messages Log DB Note] {m_err}")


async def update_message_status_idempotent(
    message_id: str,
    new_status: str,
    timestamp: Optional[str] = None,
    error_details: Optional[Any] = None,
    recipient_phone: Optional[str] = None,
) -> bool:
    """Idempotently updates message delivery status ('sent', 'delivered', 'read', 'failed')."""
    if not message_id:
        return False

    status_clean = str(new_status).lower().strip()
    incoming_rank = STATUS_RANK.get(status_clean, 1)

    existing = MESSAGE_STATUS_TRACKER.get(message_id)
    if existing:
        current_rank = STATUS_RANK.get(existing.get("status", "queued"), 0)
        # Prevent downgrades: e.g. if already 'read', do not overwrite with 'delivered'
        if incoming_rank < current_rank:
            logger.info(
                f"[Idempotent Skip] Message '{message_id}' already has status '{existing.get('status')}', "
                f"ignoring earlier transition to '{status_clean}'"
            )
            return False

    # Update in-memory tracker
    now_iso = datetime.now(timezone.utc).isoformat()
    MESSAGE_STATUS_TRACKER[message_id] = {
        "status": status_clean,
        "updated_at": now_iso,
        "timestamp": timestamp,
        "error": error_details,
        "recipient_phone": recipient_phone,
    }

    # Update broadcast log registry if tracked
    for b_id, b_data in BROADCAST_LOGS.items():
        if message_id in b_data.get("items_by_mid", {}):
            b_data["items_by_mid"][message_id]["status"] = status_clean
            b_data["items_by_mid"][message_id]["status_updated_at"] = now_iso
            if status_clean == "delivered":
                b_data["stats"]["delivered"] = b_data["stats"].get("delivered", 0) + 1
            elif status_clean == "read":
                b_data["stats"]["read"] = b_data["stats"].get("read", 0) + 1
            elif status_clean == "failed":
                b_data["stats"]["failed"] = b_data["stats"].get("failed", 0) + 1
            break

    # Persist update to Supabase
    supabase = get_supabase()
    if supabase:
        try:
            update_payload: Dict[str, Any] = {
                "status": status_clean,
                "updated_at": now_iso,
            }
            if error_details:
                update_payload["error_details"] = str(error_details)

            supabase.table("broadcast_logs").update(update_payload).eq("message_id", message_id).execute()
        except Exception as db_err:
            logger.debug(f"[Supabase Status Update Note] {db_err}")

    logger.info(f"[WABA Status Updated] ID: '{message_id}' -> Status: '{status_clean}'")
    return True


# ============================================================================
# ASYNCHRONOUS BROADCAST RUNNER WITH RATE LIMITER
# ============================================================================

async def execute_meta_broadcast(
    broadcast_id: str,
    template_name: str,
    language_code: str,
    body_parameters: List[str],
    recipients: List[Union[str, Dict[str, Any]]],
    phone_number_id: str,
    permanent_access_token: str,
    rate_limit_per_second: int = 15,
    tenant_id: str = "boontrack-career",
) -> None:
    """Executes asynchronous broadcast sending with rate limiting and database logging."""
    logger.info(f"[Meta Broadcast Start] Broadcast ID: {broadcast_id} | Total Recipients: {len(recipients)}")
    
    BROADCAST_LOGS[broadcast_id] = {
        "broadcast_id": broadcast_id,
        "template_name": template_name,
        "language_code": language_code,
        "total": len(recipients),
        "status": "processing",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "sent": 0,
            "failed": 0,
            "delivered": 0,
            "read": 0,
        },
        "items_by_mid": {},
        "results": [],
    }

    # Delay between requests to honor rate limiter (default 15 msgs/sec -> ~0.067s delay)
    rate_limit = max(1, min(rate_limit_per_second, 80))
    interval = 1.0 / float(rate_limit)

    for item in recipients:
        if isinstance(item, dict):
            phone = str(item.get("phone") or item.get("recipient") or item.get("number") or "")
            # Support per-recipient parameter override
            recipient_params = item.get("parameters") or item.get("params") or body_parameters
        else:
            phone = str(item)
            recipient_params = body_parameters

        clean_phone = normalize_phone_number(phone)
        if not clean_phone:
            logger.warning(f"[Broadcast Invalid Phone] Skipped: {phone}")
            BROADCAST_LOGS[broadcast_id]["stats"]["failed"] += 1
            BROADCAST_LOGS[broadcast_id]["results"].append({
                "phone": phone,
                "status": "failed",
                "error": "Invalid phone format",
            })
            continue

        # Send template via Meta Cloud API
        result = await meta_waba_dispatcher.send_template(
            phone_number_id=phone_number_id,
            permanent_access_token=permanent_access_token,
            to_phone=clean_phone,
            template_name=template_name,
            language_code=language_code,
            body_parameters=recipient_params,
        )

        success = result.get("success", False)
        msg_id = result.get("message_id")
        error_msg = result.get("error")
        status = "sent" if success else "failed"

        log_item = {
            "broadcast_id": broadcast_id,
            "phone": clean_phone,
            "template_name": template_name,
            "status": status,
            "message_id": msg_id,
            "error": error_msg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if success:
            BROADCAST_LOGS[broadcast_id]["stats"]["sent"] += 1
            if msg_id:
                BROADCAST_LOGS[broadcast_id]["items_by_mid"][msg_id] = log_item
                MESSAGE_STATUS_TRACKER[msg_id] = {
                    "broadcast_id": broadcast_id,
                    "phone": clean_phone,
                    "status": "sent",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
        else:
            BROADCAST_LOGS[broadcast_id]["stats"]["failed"] += 1

        BROADCAST_LOGS[broadcast_id]["results"].append(log_item)

        # Log asynchronously to Supabase
        asyncio.create_task(log_broadcast_message_to_db(
            broadcast_id=broadcast_id,
            recipient_phone=clean_phone,
            template_name=template_name,
            status=status,
            message_id=msg_id,
            error_details=error_msg,
            tenant_id=tenant_id,
        ))

        # Enforce rate limiter
        await asyncio.sleep(interval)

    BROADCAST_LOGS[broadcast_id]["status"] = "completed"
    BROADCAST_LOGS[broadcast_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
    logger.info(
        f"[Meta Broadcast Finished] ID: {broadcast_id} | "
        f"Sent: {BROADCAST_LOGS[broadcast_id]['stats']['sent']} | "
        f"Failed: {BROADCAST_LOGS[broadcast_id]['stats']['failed']}"
    )
