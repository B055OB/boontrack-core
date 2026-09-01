import os
import logging
import httpx
from typing import Dict, Any

logger = logging.getLogger("boontrack.wa_delivery")

class WhatsAppDeliveryService:
    def __init__(self):
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        self.access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        self.api_version = os.getenv("WHATSAPP_API_VERSION", "v21.0")
        self.base_url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    async def send_digital_product_delivery(self, job_payload: Dict[str, Any]) -> bool:
        recipient_phone = job_payload.get("customer_phone")
        order_id = job_payload.get("order_id")
        delivery_url = job_payload.get("delivery_url") or f"https://shop.boontrack.com/access/{order_id}"
        tenant_slug = job_payload.get("tenant_slug", "BoonTrack")

        if not recipient_phone:
            logger.warning(f"[WA Delivery] Order {order_id} has no customer_phone. Skipping delivery.")
            return False

        formatted_phone = recipient_phone.strip().replace("+", "").replace(" ", "").replace("-", "")
        if formatted_phone.startswith("08"):
            formatted_phone = "62" + formatted_phone[1:]

        message_text = (
            f"✅ *Pembayaran Terkonfirmasi!*\n\n"
            f"Terima kasih atas pesanan Anda di *{tenant_slug.upper()}*.\n"
            f"No. Order: `{order_id}`\n\n"
            f"📦 *Akses Produk Digital Anda:*\n"
            f"{delivery_url}\n\n"
            f"Simpan pesan ini jika sewaktu-waktu ingin mengakses materi kembali. "
            f"Jika ada kendala, balas langsung pesan ini untuk terhubung ke tim kami."
        )

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": formatted_phone,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": message_text
            }
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.base_url, headers=headers, json=body)
                if response.status_code in [200, 201]:
                    logger.info(f"[WA Delivery] Successfully sent delivery to {formatted_phone} for Order {order_id}")
                    return True
                else:
                    logger.error(f"[WA Delivery] Failed to send WA to {formatted_phone}. Response: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"[WA Delivery] Error connecting to WhatsApp Cloud API: {str(e)}")
            return False