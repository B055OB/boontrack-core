import logging
import asyncio
import os
import httpx
from typing import Dict, Any, Optional
from datetime import datetime
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("SHOP_TRANSACTIONAL_EVENTS")

WA_ENGINE_BASE_URL = os.getenv("WA_ENGINE_BASE_URL", "http://localhost:8080")
WA_ENGINE_API_KEY = os.getenv("WA_ENGINE_API_KEY", "boontrack_secret_engine_key_2026")


async def send_whatsapp_message(tenant_slug: str, recipient_phone: str, message_text: str):
    """Mengirim pesan notifikasi sistem WA via Meta Cloud API resmi WABA (+6285179555449)."""
    clean_phone = "".join(filter(str.isdigit, recipient_phone))
    if clean_phone.startswith("0"):
        clean_phone = "62" + clean_phone[1:]

    try:
        from app.services.whatsapp.cloud_api import send_whatsapp_text
        res = await send_whatsapp_text(
            to_phone=clean_phone,
            text=message_text,
            tenant_id="shop",
        )
        if res:
            logger.info(f"[WA SYSTEM NOTIF SENT VIA META WABA] Store: {tenant_slug} -> {clean_phone}")
            return True
    except Exception as waba_err:
        logger.error(f"[WA SYSTEM NOTIF META WABA ERROR] {waba_err}", exc_info=True)

    return False



async def trigger_order_created(payload: Dict[str, Any]):
    """Event: Pesanan baru terbit (Invoice / Instruksi Bayar)."""
    tenant_slug = payload.get("tenant_slug", "onlineboost")
    phone = payload.get("customer_phone", "")
    order_id = payload.get("order_id", f"ORD-{int(datetime.now().timestamp())}")
    total = int(payload.get("total_amount", 0))
    payment_url = payload.get("payment_url", "https://shop.boontrack.com/checkout")

    msg = (
        f"🛍️ *INVOICE PESANAN #{order_id}*\n\n"
        f"Halo, terima kasih telah berbelanja!\n"
        f"Pesanan Anda telah kami catat dengan total tagihan:\n"
        f"👉 *Rp {total:,}*\n\n"
        f"Silakan selesaikan pembayaran melalui link berikut:\n"
        f"🔗 {payment_url}\n\n"
        f"_Abaikan pesan ini jika Anda sudah melakukan transaksi._"
    )
    return await send_whatsapp_message(tenant_slug, phone, msg)


async def trigger_payment_success(payload: Dict[str, Any]):
    """Event: Pembayaran Lunas (Kirim Akses / Nota)."""
    tenant_slug = payload.get("tenant_slug", "onlineboost")
    phone = payload.get("customer_phone", "")
    order_id = payload.get("order_id", "")
    items_summary = payload.get("items_summary", "Pesanan Anda")

    msg = (
        f"✅ *PEMBAYARAN DITERIMA #{order_id}*\n\n"
        f"Terima kasih! Pembayaran untuk *{items_summary}* telah kami terima.\n\n"
        f"Pesanan Anda sedang diproses oleh tim merchant kami.\n"
        f"Terima kasih atas kepercayaannya! 🙏"
    )
    return await send_whatsapp_message(tenant_slug, phone, msg)


async def trigger_cod_confirmation(payload: Dict[str, Any]):
    """Event: Validasi Alamat COD (Anti RTS / Gagal Kirim)."""
    tenant_slug = payload.get("tenant_slug", "onlineboost")
    phone = payload.get("customer_phone", "")
    order_id = payload.get("order_id", "")
    address = payload.get("shipping_address", "-")
    total = int(payload.get("total_amount", 0))

    msg = (
        f"📦 *KONFIRMASI PESANAN COD #{order_id}*\n\n"
        f"Pesanan Bayar di Tempat (COD) sebesar *Rp {total:,}* akan dikirim ke alamat:\n"
        f"📍 _{address}_\n\n"
        f"Mohon pastikan nomor ini aktif dan ada penerima di lokasi.\n"
        f"Balas *'YA'* untuk konfirmasi pengiriman sekarang."
    )
    return await send_whatsapp_message(tenant_slug, phone, msg)