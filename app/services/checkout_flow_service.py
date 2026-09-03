"""app/services/checkout_flow_service.py
D2C Retail Checkout Flow, Dual-Delivery QRIS Dispatch, and Idempotent Webhook Reconciler.
"""

import io
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import httpx

from app.services.whatsapp_service import (
    send_whatsapp_image,
    send_whatsapp_text,
    get_supabase,
    normalize_phone_number
)
from app.services.xendit_service import xendit_service
from app.services.qris_generator import generate_qris_png_bytes

logger = logging.getLogger("CHECKOUT_FLOW_SERVICE")

PROCESSED_WEBHOOK_EVENTS = set()


async def create_d2c_order_and_dispatch_qris(
    merchant_slug: str,
    customer_name: str,
    customer_phone: str,
    items: list,
    total_amount: int,
    is_digital: bool = True,
    delivery_asset_url: Optional[str] = None,
) -> Dict[str, Any]:
    """1. Membuat record pesanan di Supabase.
    2. Menghasilkan QRIS Dinamis via Gateway.
    3. Mengirimkan Native QR Image + Ringkasan Pesanan ke WhatsApp Buyer.
    """
    supabase = get_supabase()
    clean_phone = normalize_phone_number(customer_phone)
    order_id = f"ORD-{merchant_slug.upper()[:6]}-{int(datetime.now().timestamp())}"
    
    # 1. Buat Dynamic QRIS via Gateway Engine (Midtrans / Xendit)
    provider = os.getenv("PAYMENT_GATEWAY_PROVIDER", "").strip().lower()
    if provider == "midtrans" or (not provider and os.getenv("MIDTRANS_SERVER_KEY")):
        from app.services.midtrans_service import midtrans_service
        qris_data = await midtrans_service.create_qris_charge(
            order_id=order_id,
            amount=total_amount,
            customer_name=customer_name,
            customer_phone=clean_phone,
            tenant_id=merchant_slug,
            metadata={"merchant_slug": merchant_slug, "customer_name": customer_name}
        )
    else:
        qris_data = await xendit_service.create_dynamic_qris(
            external_id=order_id,
            amount=total_amount,
            tenant_id=merchant_slug,
            customer_phone=clean_phone,
            metadata={"merchant_slug": merchant_slug, "customer_name": customer_name}
        )
    
    qr_string = qris_data.get("qr_string", "")
    qr_code_url = qris_data.get("qr_code_url", "")
    qr_png_bytes = generate_qris_png_bytes(qr_string) if qr_string else b""
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    # 2. Simpan order ke database Supabase
    if supabase:
        try:
            supabase.table("orders").insert({
                "order_id": order_id,
                "tenant_slug": merchant_slug,
                "customer_name": customer_name,
                "customer_phone": clean_phone,
                "items": items,
                "total_amount": total_amount,
                "status": "PENDING",
                "qr_string": qr_string,
                "is_digital": is_digital,
                "delivery_asset_url": delivery_asset_url,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_at,
            }).execute()
        except Exception as db_err:
            logger.warning(f"[DB ORDER INSERT WARNING] {db_err}")

    # 3. Format Pesan WhatsApp Invoice Summary
    amount_fmt = f"Rp{total_amount:,.0f}".replace(",", ".")
    caption = (
        f"Halo Kak *{customer_name}*, terima kasih telah melakukan pemesanan di *{merchant_slug}*! 🛍️\n\n"
        f"📄 *No. Pesanan:* `{order_id}`\n"
        f"💰 *Total Tagihan:* *{amount_fmt}*\n"
        f"⏱️ *Batas Waktu Bayar:* 15 Menit\n\n"
        f"Silakan scan kode QRIS di atas melalui m-Banking atau E-Wallet pilihan Anda.\n"
        f"Setelah pembayaran berhasil, bukti bayar & akses produk akan langsung dikirim ke chat ini secara otomatis."
    )

    # 4. Dispatch WhatsApp Native Image QRIS ke Buyer
    if clean_phone and qr_png_bytes:
        try:
            await send_whatsapp_image(
                to_phone=clean_phone,
                image_path_or_bytes=qr_png_bytes,
                caption=caption,
                tenant_id=merchant_slug
            )
        except Exception as wa_err:
            logger.warning(f"[WA QRIS Dispatch Warning] {wa_err}")
            await send_whatsapp_text(to_phone=clean_phone, text=caption, tenant_id=merchant_slug)

    return {
        "order_id": order_id,
        "merchant_slug": merchant_slug,
        "total_amount": total_amount,
        "qr_string": qr_string,
        "qr_code_url": qr_code_url,
        "expires_at": expires_at,
        "status": "PENDING"
    }


async def reconcile_payment_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Menangani webhook gateway pembayaran secara Idempotent (anti-duplikasi)."""
    event_id = payload.get("id") or payload.get("external_id")
    external_id = payload.get("external_id") or payload.get("reference_id")
    payment_status = str(payload.get("status", "")).upper()

    # Idempotency Lock
    if event_id and event_id in PROCESSED_WEBHOOK_EVENTS:
        logger.info(f"[WEBHOOK IDEMPOTENT] Event {event_id} already processed. Skipping.")
        return {"status": "skipped", "reason": "duplicate_event"}

    if payment_status not in ("SUCCEEDED", "COMPLETED", "PAID", "SETTLED"):
        return {"status": "ignored", "payment_status": payment_status}

    supabase = get_supabase()
    order_data = None

    if supabase and external_id:
        try:
            res = supabase.table("orders").select("*").eq("id", external_id).execute()
            if res.data:
                order_data = res.data[0]
                supabase.table("orders").update({
                    "status": "PAID",
                    "paid_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", external_id).execute()
        except Exception:
            try:
                res = supabase.table("orders").select("*").eq("order_id", external_id).execute()
                if res.data:
                    order_data = res.data[0]
                    supabase.table("orders").update({
                        "status": "PAID",
                        "paid_at": datetime.now(timezone.utc).isoformat()
                    }).eq("order_id", external_id).execute()
            except Exception as e2:
                logger.debug(f"[RECONCILE DB NOTE] {e2}")

    if event_id:
        PROCESSED_WEBHOOK_EVENTS.add(event_id)

    # Kirim WhatsApp E-Receipt & Akses Produk Otomatis
    if order_data:
        buyer_phone = order_data.get("customer_phone")
        buyer_name = order_data.get("customer_name", "Kakak")
        merchant = order_data.get("tenant_slug", "Store")
        is_digital = order_data.get("is_digital", True)
        asset_url = order_data.get("delivery_asset_url") or "https://drive.google.com"

        if is_digital:
            fulfillment_msg = (
                f"✅ *PEMBAYARAN BERHASIL!* 🎉\n\n"
                f"Terima kasih Kak *{buyer_name}*, pembayaran untuk pesanan `{external_id}` telah kami terima.\n\n"
                f"📂 *Akses Produk Digital Anda:*\n{asset_url}\n\n"
                f"Silakan simpan link di atas. Jika ada pertanyaan atau kendala akses, silakan balas pesan ini!"
            )
        else:
            fulfillment_msg = (
                f"✅ *PEMBAYARAN BERHASIL!* 📦\n\n"
                f"Terima kasih Kak *{buyer_name}*, pembayaran untuk pesanan `{external_id}` sukses.\n\n"
                f"Pesanan Anda saat ini sedang disiapkan oleh tim *{merchant}* dan resi pengiriman akan diinfokan segera."
            )

        if buyer_phone:
            await send_whatsapp_text(to_phone=buyer_phone, text=fulfillment_msg, tenant_id=merchant)

    return {"status": "success", "order_id": external_id}