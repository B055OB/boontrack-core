import os
import logging
import httpx
from typing import Dict, Any

logger = logging.getLogger("boontrack.wa_delivery")

class WhatsAppDeliveryService:
    def __init__(self):
        self.meta_phone_number_id = os.getenv("META_WA_PHONE_NUMBER_ID", "")
        self.meta_access_token = os.getenv("META_WA_ACCESS_TOKEN", "")
        self.api_url = f"https://graph.facebook.com/v19.0/{self.meta_phone_number_id}/messages"

    async def send_order_success_notification(
        self, 
        customer_phone: str, 
        order_id: str, 
        product_name: str, 
        amount: float,
        download_url: str = "https://shop.boontrack.com/access"
    ) -> bool:
        """
        Mengirim notifikasi instan dan akses produk digital via Meta WhatsApp Cloud API.
        """
        if not customer_phone or not self.meta_access_token or not self.meta_phone_number_id:
            logger.warning(f"[WA Delivery] Credentials missing or no phone provided: {customer_phone}. Simulating dispatch.")
            return True

        # Normalisasi nomor telepon (pastikan awalan 62)
        cleaned_phone = customer_phone.strip().replace("+", "").replace("-", "").replace(" ", "")
        if cleaned_phone.startswith("0"):
            cleaned_phone = "62" + cleaned_phone[1:]

        message_body = (
            f"🎉 *PEMBAYARAN BERHASIL!*\n\n"
            f"Halo Kak! Pesanan Anda telah kami terima dan terkonfirmasi lunas.\n\n"
            f"📋 *Detail Transaksi:*\n"
            f"• *Order ID:* `{order_id}`\n"
            f"• *Item:* {product_name}\n"
            f"• *Total Bayar:* Rp {amount:,.0f}\n\n"
            f"📦 *Akses Produk Digital Anda:*\n"
            f"{download_url}\n\n"
            f"Terima kasih telah berbelanja di BoonTrack Store Network!"
        )

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": cleaned_phone,
            "type": "text",
            "text": {"preview_url": True, "body": message_body}
        }

        headers = {
            "Authorization": f"Bearer {self.meta_access_token}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, json=payload, headers=headers)
                if response.status_code in [200, 201]:
                    logger.info(f"[WA Delivery] Message delivered to {cleaned_phone} for order {order_id}")
                    return True
                else:
                    logger.error(f"[WA Delivery] Meta API Error ({response.status_code}): {response.text}")
                    return False
        except Exception as e:
            logger.error(f"[WA Delivery] Failed to dispatch WhatsApp message: {str(e)}")
            return False