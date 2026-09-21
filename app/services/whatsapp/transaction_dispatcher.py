"""app/services/whatsapp/transaction_dispatcher.py
Universal Transaction Dispatcher for WhatsApp Commerce:
1. Universal Webhook Dispatch (ORDER_PENDING / INVOICE_CREATED) across Unofficial (Evolution) & Official (Meta WABA).
2. Meta Conversions API (CAPI) Dispatch with SHA-256 privacy hashing.
3. Robust customer name extraction and sanitization (anti 'Hello hijau' bug).
"""

import os
import re
import json
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
import httpx

logger = logging.getLogger("TRANSACTION_DISPATCHER")


def hash_sha256(value: Optional[str]) -> Optional[str]:
    """Menghasilkan hash SHA-256 lowercase untuk data privasi (CTO Zero-PII Leakage Policy)."""
    if not value:
        return None
    clean = str(value).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def normalize_phone_for_capi(phone: Optional[str]) -> str:
    """Format nomor telepon internasional E.164 tanpa tanda '+' atau spasi (contoh: '628123456789')."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if digits.startswith("08"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    return digits


def extract_customer_name(text: str, fallback: str = "Kakak") -> str:
    """
    Ekstraksi nama pembeli secara cerdas & tangguh dari isi pesan percakapan.
    Mendukung variasi: 'Nama Lengkap: Aldi', 'Nama Asli: Aldi', 'Nama: Aldi', 'Full Name: Aldi'.
    Menghilangkan bug pushName WhatsApp (seperti 'hijau', 'admin', 'user') agar tidak disapa salah.
    """
    clean_text = str(text or "")
    pattern = re.compile(
        r"(?:nama\s+lengkap|nama\s+asli|nama\s+saya|full\s*name|nama|name)\s*[:=\-]?\s*([a-zA-Z\s\.'\-]+?)(?:[\n,;.]|\s+email|\s+no|\s+hp|\s+wa|$)",
        re.IGNORECASE
    )
    m = pattern.search(clean_text)
    if m:
        val = m.group(1).strip().strip(".,;:-").strip()
        if val and len(val) >= 2 and val.lower() not in ("lengkap", "asli", "saya", "kamu", "anda", "toko", "admin"):
            return val.title()

    fb = str(fallback or "").strip()
    if not fb or fb.lower() in ("pelanggan", "kakak", "hijau", "merah", "biru", "user", "guest", "test", "tester", "admin", "owner", "customer"):
        return "Kakak"
    if re.match(r"^[\d\+\s\-]+$", fb):
        return "Kakak"
    return fb


async def dispatch_universal_transaction_webhook(
    tenant_slug: str,
    invoice: Dict[str, Any],
    buyer_name: str,
    buyer_email: Optional[str] = None,
    buyer_phone: Optional[str] = None,
    gateway_channel: str = "unofficial_evolution",
) -> Dict[str, Any]:
    """
    Mengirimkan webhook transaksi standar (ORDER_PENDING / INVOICE_CREATED)
    secara universal baik untuk jalur Unofficial (Baileys/Evolution) maupun Official (Meta WABA).
    """
    clean_slug = str(tenant_slug or "").strip().lower()
    order_id = str(invoice.get("external_id") or invoice.get("order_id") or f"INV-{uuid.uuid4().hex[:8].upper()}")
    total_amount = int(invoice.get("amount") or 0)
    base_amount = int(invoice.get("base_amount") or total_amount)
    unique_code = int(invoice.get("unique_code") or 0)
    product_name = str(invoice.get("product_name") or "Produk Digital")

    webhook_payload = {
        "event": "ORDER_PENDING",
        "event_type": "INVOICE_CREATED",
        "tenant_slug": clean_slug,
        "order_id": order_id,
        "product_name": product_name,
        "total_amount": total_amount,
        "base_amount": base_amount,
        "unique_code": unique_code,
        "buyer_name": buyer_name or "Pelanggan",
        "buyer_email": buyer_email or "",
        "buyer_phone": buyer_phone or "",
        "gateway_channel": gateway_channel,
        "status": "PENDING",
        "currency": "IDR",
        "qr_string": invoice.get("qr_string") or "",
        "qr_code_url": invoice.get("qr_code_url") or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        f"[UNIVERSAL WEBHOOK DISPATCH] {webhook_payload['event']} for '{clean_slug}' "
        f"| order_id='{order_id}' | total=Rp{total_amount:,} (base=Rp{base_amount:,} + unique={unique_code}) "
        f"| buyer='{buyer_name}' | channel='{gateway_channel}'"
    )

    # 1. Simpan pesanan ke database Supabase tabel 'orders' jika tersedia
    try:
        from app.services.whatsapp_service import get_supabase
        sb = get_supabase()
        if sb:
            order_record = {
                "id": order_id,
                "tenant_slug": clean_slug,
                "customer_name": buyer_name,
                "customer_email": buyer_email,
                "customer_phone": buyer_phone,
                "product_name": product_name,
                "total_amount": total_amount,
                "status": "PENDING",
                "payment_method": "SELLER_NATIVE_QRIS",
                "metadata": {
                    "unique_code": unique_code,
                    "base_amount": base_amount,
                    "gateway_channel": gateway_channel,
                    "qr_code_url": invoice.get("qr_code_url"),
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            sb.table("orders").upsert(order_record).execute()
            logger.info(f"[DB ORDER UPSERT SUCCESS] Order {order_id} recorded for tenant '{clean_slug}'")
    except Exception as db_err:
        logger.debug(f"[DB ORDER UPSERT NOTE] {db_err}")

    # 2. Tembakkan ke custom webhook URL tenant jika dikonfigurasi di metadata
    try:
        from app.services.onboarding_service import onboarding_service
        tenant_details = onboarding_service.get_tenant_details_by_slug(clean_slug) or {}
        tenant_meta = tenant_details.get("metadata") or (tenant_details.get("tenant", {}) or {}).get("metadata") or {}
        custom_hook = (
            tenant_meta.get("webhook_url")
            or (tenant_meta.get("payment_settings", {}) or {}).get("webhook_url")
        )
        if custom_hook and custom_hook.startswith("http"):
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(custom_hook, json=webhook_payload)
                logger.info(f"[TENANT CUSTOM WEBHOOK] Dispatched to {custom_hook}: {res.status_code}")
    except Exception as hook_err:
        logger.warning(f"[TENANT CUSTOM WEBHOOK ERROR] {hook_err}")

    return webhook_payload


async def dispatch_meta_capi_checkout_initiated(
    tenant_slug: str,
    invoice: Dict[str, Any],
    buyer_name: str,
    buyer_email: Optional[str] = None,
    buyer_phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Mengirimkan event 'InitiateCheckout' ke Meta Conversions API (CAPI)
    saat QRIS Dinamis berhasil diterbitkan ke pembeli.
    Menggunakan hashing SHA-256 untuk Nama, Email, dan Nomor WhatsApp.
    """
    clean_slug = str(tenant_slug or "").strip().lower()
    order_id = str(invoice.get("external_id") or invoice.get("order_id") or f"ORD-{uuid.uuid4().hex[:8].upper()}")
    total_amount = float(invoice.get("amount") or 0)
    product_name = str(invoice.get("product_name") or "Produk Digital")

    # 1. Resolusi Kredensial Pixel & CAPI Token dari profil tenant / metadata
    pixel_id = None
    access_token = None
    try:
        from app.services.onboarding_service import onboarding_service
        tenant_details = onboarding_service.get_tenant_details_by_slug(clean_slug) or {}
        tenant_meta = tenant_details.get("metadata") or (tenant_details.get("tenant", {}) or {}).get("metadata") or {}

        pixel_id = (
            tenant_meta.get("pixel_id")
            or tenant_meta.get("meta_pixel_id")
            or (tenant_meta.get("tracking") or {}).get("pixel_id")
            or (tenant_meta.get("meta_config") or {}).get("pixel_id")
        )
        access_token = (
            tenant_meta.get("capi_token")
            or tenant_meta.get("meta_capi_token")
            or (tenant_meta.get("meta_config") or {}).get("access_token")
            or (tenant_meta.get("tracking") or {}).get("capi_token")
        )
    except Exception as cred_err:
        logger.debug(f"[CAPI CREDENTIAL RESOLVE NOTE] {cred_err}")

    # Fallback ke env default jika tenant belum mengisi kredensial khusus
    if not pixel_id:
        pixel_id = os.getenv("META_PIXEL_ID") or os.getenv("META_DATASET_ID") or "mock_pixel_boontrack"
    if not access_token:
        access_token = os.getenv("META_CAPI_TOKEN") or os.getenv("WHATSAPP_TOKEN") or "mock_token"

    # 2. Hashing data privasi pembeli (Zero PII Leakage)
    clean_phone_capi = normalize_phone_for_capi(buyer_phone)
    hashed_phone = hash_sha256(clean_phone_capi) if clean_phone_capi else None
    hashed_email = hash_sha256(buyer_email) if buyer_email else None

    hashed_fn = None
    if buyer_name and buyer_name.lower() != "kakak":
        first_word = buyer_name.strip().split()[0]
        hashed_fn = hash_sha256(first_word)

    event_id = f"INIT_{order_id}"
    event_time = int(datetime.now(timezone.utc).timestamp())

    user_data = {}
    if hashed_phone:
        user_data["ph"] = [hashed_phone]
    if hashed_email:
        user_data["em"] = [hashed_email]
    if hashed_fn:
        user_data["fn"] = [hashed_fn]

    custom_data = {
        "currency": "IDR",
        "value": total_amount,
        "content_name": product_name,
        "content_ids": [order_id],
        "content_type": "product",
        "status": "pending",
    }

    capi_body = {
        "data": [
            {
                "event_name": "InitiateCheckout",
                "event_time": event_time,
                "event_id": event_id,
                "action_source": "business_messaging",
                "user_data": user_data,
                "custom_data": custom_data,
            }
        ]
    }

    delivery_status = "PENDING"
    resp_text = None

    if str(pixel_id).startswith("mock_") or str(access_token).startswith("mock_"):
        logger.info(
            f"[META CAPI MOCK] InitiateCheckout for '{clean_slug}' | order_id='{order_id}' | "
            f"value=Rp{total_amount:,.0f} | pixel='{pixel_id}'"
        )
        delivery_status = "MOCK_SENT"
    else:
        url = f"https://graph.facebook.com/v21.0/{pixel_id}/events"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=capi_body, params={"access_token": access_token})
                resp_text = res.text
                if res.status_code in (200, 201):
                    delivery_status = "SENT"
                    logger.info(f"[META CAPI SUCCESS] InitiateCheckout dispatched for '{clean_slug}' -> Pixel {pixel_id}: {res.status_code}")
                else:
                    delivery_status = "FAILED"
                    logger.warning(f"[META CAPI WARN] Failed ({res.status_code}): {res.text[:200]}")
        except Exception as capi_err:
            delivery_status = "FAILED"
            resp_text = str(capi_err)
            logger.error(f"[META CAPI EXCEPTION] {capi_err}")

    # 3. Catat ke event_ledger database jika ada tabelnya
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO event_ledger (event_id, tenant_id, event_name, occurred_at, payload, delivery_status, response_payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING;
                    """,
                    (
                        event_id,
                        clean_slug,
                        "InitiateCheckout",
                        datetime.now(timezone.utc),
                        json.dumps(capi_body),
                        delivery_status,
                        resp_text,
                    )
                )
            conn.commit()
            conn.close()
    except Exception:
        pass

    return {
        "status": delivery_status,
        "event_id": event_id,
        "pixel_id": pixel_id,
        "value": total_amount,
    }


async def dispatch_checkout_events(
    tenant_slug: str,
    invoice: Dict[str, Any],
    buyer_name: str,
    buyer_email: Optional[str] = None,
    buyer_phone: Optional[str] = None,
    gateway_channel: str = "unofficial_evolution",
):
    """
    Fungsi orkestrator yang memicu Universal Webhook Dispatch dan Meta Conversions API
    secara bersamaan di latar belakang tanpa memblokir respon percakapan WhatsApp.
    """
    try:
        await dispatch_universal_transaction_webhook(
            tenant_slug=tenant_slug,
            invoice=invoice,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
            gateway_channel=gateway_channel,
        )
    except Exception as wh_err:
        logger.error(f"[CHECKOUT EVENTS WEBHOOK ERROR] {wh_err}")

    try:
        await dispatch_meta_capi_checkout_initiated(
            tenant_slug=tenant_slug,
            invoice=invoice,
            buyer_name=buyer_name,
            buyer_email=buyer_email,
            buyer_phone=buyer_phone,
        )
    except Exception as capi_err:
        logger.error(f"[CHECKOUT EVENTS CAPI ERROR] {capi_err}")
