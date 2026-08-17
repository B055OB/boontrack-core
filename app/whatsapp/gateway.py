import logging
import os
from typing import Any, Dict
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channels import ChannelStatus, TenantWhatsAppChannel

logger = logging.getLogger(__name__)

META_VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "boontrack-secure-verify-token")


def verify_whatsapp_handshake(request: web.Request) -> web.Response:
    """GET /api/v1/whatsapp/webhook (Meta Challenge Verification)"""
    mode = request.query.get("hub.mode")
    token = request.query.get("hub.verify_token")
    challenge = request.query.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        logger.info("[WABA MASTER] Webhook challenge verified successfully.")
        return web.Response(text=challenge or "", status=200)

    return web.Response(status=403, text="Verification token mismatch")


async def handle_whatsapp_inbound(payload: Dict[str, Any], db: AsyncSession) -> Dict[str, Any]:
    """
    POST /api/v1/whatsapp/webhook
    Dynamic Multi-Tenant Ingestion: Mengekstrak phone_number_id -> resolve tenant_id.
    """
    entries = payload.get("entry", [])
    processed_events = []

    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")

            if not phone_number_id:
                continue

            query = select(TenantWhatsAppChannel).where(
                TenantWhatsAppChannel.phone_number_id == str(phone_number_id),
                TenantWhatsAppChannel.status == ChannelStatus.ACTIVE,
            )
            result = await db.execute(query)
            channel = result.scalar_one_or_none()

            if not channel:
                logger.warning(f"[WABA GATEWAY] Unregistered or Suspended phone_number_id: {phone_number_id}")
                continue

            tenant_id = channel.tenant_id
            messages = value.get("messages", [])

            for msg in messages:
                user_wa_id = msg.get("from")
                msg_type = msg.get("type")
                body = msg.get("text", {}).get("body", "") if msg_type == "text" else ""

                logger.info(
                    f"[WABA GATEWAY] Routed message from {user_wa_id} to tenant_id: {tenant_id} (Phone ID: {phone_number_id})"
                )

                processed_events.append({
                    "tenant_id": str(tenant_id),
                    "phone_number_id": phone_number_id,
                    "from_wa_id": user_wa_id,
                    "message_body": body,
                })

    return {"status": "received", "events_processed": len(processed_events)}