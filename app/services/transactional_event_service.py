"""
app/services/transactional_event_service.py

Layanan Event-Driven Transactional Messaging Hooks via Meta Cloud API resmi WABA (+6285181830080).
Mendengarkan transisi status resmi dari State Machine BoonTrack:
1. ORDER_CREATED: Ringkasan pesanan & invoice link/QRIS
2. PAYMENT_CONFIRMED: Konfirmasi pembayaran sah (hanya terpicu oleh Financial State Machine / webhook PG)
3. SHIPMENT_CREATED: Notifikasi no. resi & kurir pengiriman resmi (Biteship/Lincah)

Menyertakan quick reply buttons / pilihan opsi pada setiap pesan:
- [📦 Cek Status Pesanan]
- [👨💼 Tanya Admin]
Serta mencatat atribusi percakapan ke tabel waba_conversations.
"""

import logging
import asyncio
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from app.services.whatsapp_service import normalize_phone_number

logger = logging.getLogger("SHOP_TRANSACTIONAL_EVENTS")

# Nomor resmi Meta Cloud API WABA Shop BoonTrack
WABA_PHONE_OFFICIAL = "+6285181830080"
WABA_TENANT_ID = "shop"

# Quick Reply standard choices per CTO spec
DEFAULT_QUICK_REPLY_BUTTONS: List[Dict[str, str]] = [
    {"id": "btn_cek_status", "title": "📦 Cek Status"},
    {"id": "btn_tanya_admin", "title": "👨💼 Tanya Admin"},
]

QUICK_REPLY_TEXT_OPTIONS: str = (
    "\n\n━━━━━━━━━━━━━━━━━━━━\n"
    "Pilihan Opsi:\n"
    "[📦 Cek Status Pesanan]\n"
    "[👨💼 Tanya Admin]"
)


async def send_whatsapp_message(
    tenant_slug: str,
    recipient_phone: str,
    message_text: str,
    buttons: Optional[List[Dict[str, str]]] = None,
    header_text: str = "",
    footer_text: str = "BoonTrack Official WABA",
) -> bool:
    """
    Mengirim pesan notifikasi sistem WA via Meta Cloud API resmi WABA (+6285181830080).
    Mendukung tombol interaktif (Quick Reply) dan otomatis menyertakan teks opsi fallback.
    """
    clean_phone = normalize_phone_number(recipient_phone) or "".join(filter(str.isdigit, str(recipient_phone or "")))
    if not clean_phone:
        logger.warning(f"[WABA TX NOTIF] Nomor tujuan kosong/tidak valid: '{recipient_phone}'")
        return False

    # Pastikan teks pilihan opsi ada di dalam body text jika belum tercantum
    body_text = message_text
    if "[📦 Cek Status Pesanan]" not in body_text and "[👨💼 Tanya Admin]" not in body_text:
        body_text = f"{body_text}{QUICK_REPLY_TEXT_OPTIONS}"

    active_buttons = buttons if buttons is not None else DEFAULT_QUICK_REPLY_BUTTONS

    # 1. Coba kirim via send_whatsapp_buttons (Interactive Button Meta Cloud API)
    try:
        from app.services.whatsapp.cloud_api import send_whatsapp_buttons, send_whatsapp_text
        res = await send_whatsapp_buttons(
            to_phone=clean_phone,
            body_text=body_text,
            buttons=active_buttons,
            header_text=header_text,
            footer_text=footer_text,
            tenant_id=WABA_TENANT_ID,
        )
        if res:
            logger.info(f"[WA SYSTEM NOTIF SENT VIA META WABA BUTTONS] Store: {tenant_slug} -> {clean_phone}")
            return True
    except Exception as btn_err:
        logger.debug(f"[WA SYSTEM NOTIF BUTTONS NOTE] {btn_err}, trying plain text fallback...")

    # 2. Fallback jika interactive button tidak didukung atau credentials override
    try:
        from app.services.whatsapp.cloud_api import send_whatsapp_text
        res_text = await send_whatsapp_text(
            to_phone=clean_phone,
            text=body_text,
            tenant_id=WABA_TENANT_ID,
        )
        if res_text:
            logger.info(f"[WA SYSTEM NOTIF SENT VIA META WABA TEXT] Store: {tenant_slug} -> {clean_phone}")
            return True
    except Exception as waba_err:
        logger.error(f"[WA SYSTEM NOTIF META WABA ERROR] {waba_err}", exc_info=True)

    return False


async def trigger_order_created(payload: Dict[str, Any]) -> bool:
    """
    Event: ORDER_CREATED
    Kirim notifikasi ringkasan pesanan & invoice link/QRIS via WABA (085181830080).
    Mendengarkan event resmi pembuatan pesanan baru dari State Machine.
    """
    tenant_slug = payload.get("tenant_slug") or payload.get("tenant_id") or "onlineboost"
    phone = payload.get("customer_phone") or payload.get("recipient_phone") or payload.get("phone") or ""
    order_id = payload.get("order_id") or f"ORD-{int(datetime.now().timestamp())}"
    total = int(payload.get("total_amount") or payload.get("amount") or payload.get("total") or 0)
    items_summary = payload.get("items_summary") or payload.get("product_name") or "Pesanan Anda"
    payment_url = payload.get("payment_url") or payload.get("invoice_url") or f"https://shop.boontrack.com/invoice/{order_id}"
    qris_url = payload.get("qris_url") or payload.get("qris_image_url")

    qris_section = f"\n📲 *QRIS:* {qris_url}" if qris_url else ""

    msg = (
        f"🛍️ *RINGKASAN PESANAN #{order_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Halo! Terima kasih telah berbelanja di toko kami.\n"
        f"Pesanan Anda telah resmi tercatat di sistem:\n\n"
        f"📋 *Rincian Pesanan:*\n"
        f"{items_summary}\n\n"
        f"💰 *Total Tagihan:* *Rp {total:,}*\n"
        f"🔗 *Link Invoice / Pembayaran:*\n{payment_url}{qris_section}\n\n"
        f"Silakan selesaikan pembayaran agar pesanan Anda dapat segera kami proses."
    )

    success = await send_whatsapp_message(
        tenant_slug=tenant_slug,
        recipient_phone=phone,
        message_text=msg,
        header_text="BoonTrack Order Notification",
    )

    # Catat atribusi percakapan ke waba_conversations
    try:
        from app.services.waba_conversation_service import record_waba_conversation
        asyncio.create_task(record_waba_conversation(
            wa_user_id=phone,
            source="ORDER_NOTIFICATION",
            tenant_slug=tenant_slug,
            order_id=order_id,
            storefront_url=payment_url,
        ))
    except Exception as attr_err:
        logger.debug(f"[WABA_CONV ATTRIBUTION NOTE] {attr_err}")

    return success


async def trigger_payment_confirmed(payload: Dict[str, Any]) -> bool:
    """
    Event: PAYMENT_CONFIRMED
    Kirim konfirmasi pembayaran sah via WABA (+6285181830080).
    HANYA terpicu oleh Financial State Machine / webhook Payment Gateway sah (Duitku, Xendit, Midtrans).
    """
    payment_status = str(
        payload.get("payment_status")
        or payload.get("status")
        or payload.get("event_type")
        or ""
    ).upper().strip()

    is_verified = bool(
        payload.get("verified")
        or payload.get("is_verified")
        or payment_status in ("PAID", "SETTLED", "COMPLETED", "SUCCESS", "SUCCEEDED", "LUNAS", "PAYMENT_SETTLED")
    )

    if not is_verified:
        logger.warning(
            f"[PAYMENT_CONFIRMED REJECTED] Notifikasi pembayaran sah #{payload.get('order_id')} "
            f"ditolak karena status belum terverifikasi oleh Financial State Machine: "
            f"status='{payment_status}', verified={is_verified}"
        )
        return False

    tenant_slug = payload.get("tenant_slug") or payload.get("tenant_id") or "onlineboost"
    phone = payload.get("customer_phone") or payload.get("recipient_phone") or payload.get("phone") or ""
    order_id = payload.get("order_id") or ""
    amount = int(payload.get("amount") or payload.get("total_amount") or payload.get("settled_amount") or 0)
    items_summary = payload.get("items_summary") or payload.get("product_name") or "Pesanan Anda"
    payment_method = payload.get("payment_method") or payload.get("provider") or "QRIS / Payment Gateway"

    msg = (
        f"✅ *KONFIRMASI PEMBAYARAN SAH #{order_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Kabar baik! Pembayaran Anda telah *TERVERIFIKASI SAH* oleh sistem keuangan resmi kami.\n\n"
        f"📋 *Pesanan:* {items_summary}\n"
        f"💰 *Nominal Terbayar:* *Rp {amount:,}*\n"
        f"💳 *Metode Pembayaran:* {payment_method}\n\n"
        f"Pesanan Anda saat ini masuk ke tahap *DIPROSES & DISIAPKAN* oleh tim merchant.\n"
        f"Terima kasih atas kepercayaannya! 🙏"
    )

    success = await send_whatsapp_message(
        tenant_slug=tenant_slug,
        recipient_phone=phone,
        message_text=msg,
        header_text="BoonTrack Payment Confirmed",
    )

    # Catat atribusi percakapan ke waba_conversations
    try:
        from app.services.waba_conversation_service import record_waba_conversation
        asyncio.create_task(record_waba_conversation(
            wa_user_id=phone,
            source="PAYMENT_NOTIFICATION",
            tenant_slug=tenant_slug,
            order_id=order_id,
        ))
    except Exception as attr_err:
        logger.debug(f"[WABA_CONV ATTRIBUTION NOTE] {attr_err}")

    return success


# Alias untuk backwards compatibility
trigger_payment_success = trigger_payment_confirmed


async def trigger_shipment_created(payload: Dict[str, Any]) -> bool:
    """
    Event: SHIPMENT_CREATED
    Kirim notifikasi nomor resi & kurir pengiriman resmi (Biteship/Lincah) via WABA (+6285181830080).
    Terpicu saat order berhasil dibooking dan nomor resi diterbitkan.
    """
    tenant_slug = payload.get("tenant_slug") or payload.get("tenant_id") or "onlineboost"
    phone = payload.get("customer_phone") or payload.get("recipient_phone") or payload.get("phone") or ""
    order_id = payload.get("order_id") or ""
    courier_name = payload.get("courier_name") or payload.get("courier_code") or "Kurir Resmi"
    service_name = payload.get("service_name") or payload.get("courier_service_name") or "Standard"
    tracking_number = payload.get("tracking_number") or payload.get("courier_tracking_id") or payload.get("resi") or "-"
    address = payload.get("shipping_address") or payload.get("address") or "-"
    tracking_url = payload.get("tracking_url")

    track_line = f"\n🔎 *Lacak Pengiriman:* {tracking_url}" if tracking_url else ""

    msg = (
        f"🚚 *PESANAN DALAM PENGIRIMAN #{order_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Halo! Pesanan Anda telah resmi diserahkan kepada kurir pengiriman resmi:\n\n"
        f"📦 *Kurir Pengiriman:* *{courier_name.upper()}* ({service_name})\n"
        f"🧾 *Nomor Resi:* `{tracking_number}`\n"
        f"📍 *Alamat Tujuan:* _{address}_{track_line}\n\n"
        f"Paket Anda sedang bergerak menuju lokasi pengantaran. "
        f"Mohon pastikan nomor WhatsApp ini aktif saat kurir melakukan pengantaran."
    )

    success = await send_whatsapp_message(
        tenant_slug=tenant_slug,
        recipient_phone=phone,
        message_text=msg,
        header_text="BoonTrack Shipping Update",
    )

    # Catat atribusi percakapan ke waba_conversations
    try:
        from app.services.waba_conversation_service import record_waba_conversation
        asyncio.create_task(record_waba_conversation(
            wa_user_id=phone,
            source="SHIPPING_NOTIFICATION",
            tenant_slug=tenant_slug,
            order_id=order_id,
        ))
    except Exception as attr_err:
        logger.debug(f"[WABA_CONV ATTRIBUTION NOTE] {attr_err}")

    return success


async def trigger_cod_confirmation(payload: Dict[str, Any]) -> bool:
    """
    Event: COD_CONFIRMATION
    Validasi Alamat COD (Anti RTS / Gagal Kirim) via WABA (+6285181830080).
    """
    tenant_slug = payload.get("tenant_slug") or payload.get("tenant_id") or "onlineboost"
    phone = payload.get("customer_phone") or payload.get("recipient_phone") or payload.get("phone") or ""
    order_id = payload.get("order_id") or ""
    address = payload.get("shipping_address") or payload.get("address") or "-"
    total = int(payload.get("total_amount") or payload.get("amount") or 0)

    msg = (
        f"📦 *KONFIRMASI PESANAN COD #{order_id}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Pesanan Bayar di Tempat (COD) sebesar *Rp {total:,}* akan dikirim ke alamat:\n"
        f"📍 _{address}_\n\n"
        f"Mohon pastikan nomor ini aktif dan ada penerima di lokasi.\n"
        f"Balas *'YA'* untuk konfirmasi pengiriman sekarang."
    )

    return await send_whatsapp_message(
        tenant_slug=tenant_slug,
        recipient_phone=phone,
        message_text=msg,
        header_text="BoonTrack COD Verification",
    )