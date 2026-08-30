"""app/services/whatsapp_dispatcher.py
Worker for Dual-Delivery QRIS Dispatch via Meta WhatsApp Cloud API.
"""

import logging
import httpx
from typing import Dict, Any, Optional
from app.utils.phone_sanitizer import sanitize_phone_number

logger = logging.getLogger("WA_DISPATCHER")

async def dispatch_whatsapp_qris(
    raw_phone: str,
    merchant_name: str,
    product_name: str,
    order_id: str,
    total_amount: int,
    qris_image_url: str,
    wa_token: str,
    wa_phone_number_id: str,
    meta_graph_version: str = "v20.0"
) -> Dict[str, Any]:
    """Mengirim gambar QRIS dinamis dan ringkasan tagihan via WhatsApp Cloud API."""
    to_phone = sanitize_phone_number(raw_phone)
    if not to_phone:
        logger.warning(f"[WA Dispatcher] Nomor telepon tidak valid: {raw_phone}")
        return {"success": False, "reason": "invalid_phone"}

    amount_fmt = f"{total_amount:,.0f}".replace(",", ".")
    caption_text = (
        f"Halo Kak! 👋\n\n"
        f"Terima kasih telah memesan di *{merchant_name}*.\n\n"
        f"📋 *Rincian Pesanan:*\n"
        f"• Produk: *{product_name}*\n"
        f"• No. Order: `#{order_id}`\n"
        f"• Total Tagihan: *Rp {amount_fmt}*\n"
        f"• Batas Pembayaran: *15 Menit*\n\n"
        f"📱 *Cara Pembayaran:*\n"
        f"1. Simpan/Screenshot gambar QRIS di atas.\n"
        f"2. Buka aplikasi BCA, GoPay, OVO, Dana, atau ShopeePay.\n"
        f"3. Pilih menu Scan/Bayar QRIS lalu upload gambar ini.\n\n"
        f"_Akses file/materi digital akan otomatis dikirim ke chat ini detik setelah pembayaran berhasil._"
    )

    url = f"https://graph.facebook.com/{meta_graph_version}/{wa_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {wa_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "image",
        "image": {
            "link": qris_image_url,
            "caption": caption_text
        }
    }

    async with httpx.AsyncClient(timeout=25.0) as client:
        try:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                logger.info(f"[WA Dispatcher] Berhasil kirim QRIS ke {to_phone} (Order: {order_id})")
                return {"success": True, "data": res.json()}
            else:
                logger.error(f"[WA Dispatcher Error] Meta Status {res.status_code}: {res.text}")
                return {"success": False, "error": res.text}
        except Exception as e:
            logger.error(f"[WA Dispatcher Exception] {str(e)}")
            return {"success": False, "error": str(e)}