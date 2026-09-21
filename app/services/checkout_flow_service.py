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
from app.core.tracing import log_structured_event, set_trace_context, get_trace_context

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
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """1. Membuat record pesanan di Supabase & PostgreSQL dengan trace/correlation_id.
    2. Menghasilkan QRIS Dinamis via Gateway.
    3. Mengirimkan Native QR Image + Ringkasan Pesanan ke WhatsApp Buyer.
    """
    supabase = get_supabase()
    clean_phone = normalize_phone_number(customer_phone)
    order_id = f"ORD-{merchant_slug.upper()[:6]}-{int(datetime.now().timestamp())}"
    active_corr = correlation_id or order_id
    
    set_trace_context(correlation_id=active_corr, tenant_id=merchant_slug)
    log_structured_event(
        service="checkout_flow",
        event_type="INBOUND_CHECKOUT",
        entity_type="order",
        entity_id=order_id,
        status="SUCCESS",
        tenant_id=merchant_slug,
        correlation_id=active_corr,
    )

    # 1. Resolve Tenant Context & Payment Provider (Manual Transfer vs Gateway)
    from app.services.tenant_context_resolver import tenant_context_resolver
    from app.services.payment.factory import PaymentAdapterFactory
    from app.services.payment.manual_adapter import ManualTransferAdapter

    tenant_ctx = await tenant_context_resolver.resolve_context(merchant_slug)
    if not tenant_ctx:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail="MERCHANT_QRIS_NOT_CONFIGURED",
        )

    # 1.5 CFO Hard-Cap Guardrail for trial accounts (Max 30 orders)
    is_trial = (
        getattr(tenant_ctx, "is_trial", False)
        or (bool(tenant_ctx.metadata) and tenant_ctx.metadata.get("is_trial") is True)
        or getattr(tenant_ctx, "status", "") == "TRIALING"
    )
    if is_trial:
        from app.core.trial_guardrail import trial_guardrail
        trial_guardrail.check_order_quota(merchant_slug, is_trial=True)
        trial_guardrail.record_order(merchant_slug)

    adapter = PaymentAdapterFactory.resolve(tenant_ctx)
    is_manual = isinstance(adapter, ManualTransferAdapter)
    pcfg = (tenant_ctx.metadata if tenant_ctx else {}).get("payment_config") or {}

    provider = os.getenv("PAYMENT_GATEWAY_PROVIDER", "").strip().lower()
    meta_payload = {
        "merchant_slug": merchant_slug,
        "customer_name": customer_name,
        "correlation_id": active_corr
    }

    if is_manual:
        static_payload = pcfg.get("static_qris_payload") or ""
        qr_code_url = adapter.qris_image_url or pcfg.get("qris_image_url") or ""
        if not static_payload and not qr_code_url:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=422,
                detail="MERCHANT_QRIS_NOT_CONFIGURED",
            )

        qr_string = ""
        if static_payload:
            from app.utils.qris_generator import generate_dynamic_qris_payload
            qr_string = generate_dynamic_qris_payload(static_payload, total_amount, invoice_id=order_id)
            qr_png_bytes = generate_qris_png_bytes(qr_string)
            if not qr_code_url:
                from app.utils.qris_generator import get_qr_code_image_url
                qr_code_url = get_qr_code_image_url(qr_string, size=600)
        else:
            qr_png_bytes = b""
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    elif provider == "midtrans" or (not provider and os.getenv("MIDTRANS_SERVER_KEY")):
        from app.services.midtrans_service import midtrans_service
        qris_data = await midtrans_service.create_qris_charge(
            order_id=order_id,
            amount=total_amount,
            customer_name=customer_name,
            customer_phone=clean_phone,
            tenant_id=merchant_slug,
            metadata=meta_payload
        )
        qr_string = qris_data.get("qr_string", "")
        qr_code_url = qris_data.get("qr_code_url", "")
        qr_png_bytes = generate_qris_png_bytes(qr_string) if qr_string else b""
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    else:
        qris_data = await xendit_service.create_dynamic_qris(
            external_id=order_id,
            amount=total_amount,
            tenant_id=merchant_slug,
            customer_phone=clean_phone,
            metadata=meta_payload
        )
        qr_string = qris_data.get("qr_string", "")
        qr_code_url = qris_data.get("qr_code_url", "")
        qr_png_bytes = generate_qris_png_bytes(qr_string) if qr_string else b""
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()

    # 2. Simpan order ke database PostgreSQL (Immutable Source of Truth)
    first_item = items[0] if items and isinstance(items, list) else {}
    prod_id = first_item.get("product_id") or "prod_sample"
    prod_title = first_item.get("title") or "Sample Product"

    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (
                id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, status, correlation_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                correlation_id = EXCLUDED.correlation_id,
                updated_at = NOW();
            """,
            (
                str(order_id),
                merchant_slug,
                str(prod_id),
                str(prod_title),
                total_amount,
                customer_name,
                clean_phone,
                correlation_id
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"[DB ORDER INSERT PG] Order {order_id} stored in Postgres with correlation_id '{correlation_id}'.")
    except Exception as pg_err:
        logger.warning(f"[DB ORDER INSERT PG WARNING] {pg_err}")

    # 3. Simpan order ke database Supabase (Aligned with DB schema & Idempotent Upsert)
    if supabase:
        try:
            supabase.table("orders").upsert({
                "id": str(order_id),
                "tenant_slug": merchant_slug,
                "product_id": str(prod_id),
                "product_title": str(prod_title),
                "gross_amount": total_amount,
                "customer_name": customer_name,
                "customer_phone": clean_phone,
                "status": "PENDING",
                "correlation_id": correlation_id,
            }).execute()
        except Exception as db_err:
            logger.warning(f"[DB ORDER INSERT WARNING] {db_err}")

    # 4. Format Pesan WhatsApp Invoice Summary
    amount_fmt = f"Rp{total_amount:,.0f}".replace(",", ".")
    if is_manual:
        bank_details = f"🏦 *Bank:* {adapter.bank_name}\n🔢 *No. Rekening:* `{adapter.account_number}`\n👤 *Atas Nama:* {adapter.account_holder}"
        caption = (
            f"Halo Kak *{customer_name}*, terima kasih telah melakukan pemesanan di *{merchant_slug}*! 🛍️\n\n"
            f"📄 *No. Pesanan:* `{order_id}`\n"
            f"💰 *Total Tagihan:* *{amount_fmt}*\n\n"
            f"Silakan lakukan pembayaran melalui transfer manual ke rekening berikut:\n"
            f"{bank_details}\n\n"
            f"Atau scan kode QRIS toko yang tertera.\n\n"
            f"Setelah transfer, silakan kirimkan foto/tangkapan layar bukti pembayaran ke chat ini untuk verifikasi. 🙏"
        )
    else:
        caption = (
            f"Halo Kak *{customer_name}*, terima kasih telah melakukan pemesanan di *{merchant_slug}*! 🛍️\n\n"
            f"📄 *No. Pesanan:* `{order_id}`\n"
            f"💰 *Total Tagihan:* *{amount_fmt}*\n"
            f"⏱️ *Batas Waktu Bayar:* 15 Menit\n\n"
            f"Silakan scan kode QRIS di atas melalui m-Banking atau E-Wallet pilihan Anda.\n"
            f"Setelah pembayaran berhasil, bukti bayar & akses produk akan langsung dikirim ke chat ini secara otomatis."
        )

    # 5. Dispatch WhatsApp Native Image QRIS / Static QR ke Buyer
    img_to_send = qr_png_bytes or qr_code_url
    if clean_phone:
        if img_to_send:
            try:
                await send_whatsapp_image(
                    to_phone=clean_phone,
                    image_path_or_bytes=img_to_send,
                    caption=caption,
                    tenant_id=merchant_slug
                )
            except Exception as wa_err:
                logger.warning(f"[WA QRIS Dispatch Warning] {wa_err}")
                await send_whatsapp_text(to_phone=clean_phone, text=caption, tenant_id=merchant_slug)
        else:
            await send_whatsapp_text(to_phone=clean_phone, text=caption, tenant_id=merchant_slug)

        log_structured_event(
            service="whatsapp_delivery",
            event_type="WA_QRIS_DISPATCHED",
            entity_type="message",
            entity_id=order_id,
            status="SUCCESS",
            provider="meta",
            tenant_id=merchant_slug,
            correlation_id=active_corr,
        )

    log_structured_event(
        service="checkout_flow",
        event_type="QRIS_GENERATED",
        entity_type="payment",
        entity_id=order_id,
        status="SUCCESS",
        provider="manual" if is_manual else (provider or "xendit"),
        tenant_id=merchant_slug,
        correlation_id=active_corr,
    )

    return {
        "order_id": order_id,
        "merchant_slug": merchant_slug,
        "tenant_id": merchant_slug,
        "total_amount": total_amount,
        "qr_string": qr_string,
        "qr_code_url": qr_code_url,
        "expires_at": expires_at,
        "status": "PENDING",
        "correlation_id": active_corr,
        "payment_method": "MANUAL_TRANSFER" if is_manual else "QRIS_DYNAMIC",
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

    merchant = (order_data or {}).get("tenant_slug") or payload.get("tenant_slug") or "default"

    # Kirim WhatsApp E-Receipt & Akses Produk Otomatis
    if order_data:
        buyer_phone = order_data.get("customer_phone")
        buyer_name = order_data.get("customer_name", "Kakak")
        merchant = order_data.get("tenant_slug", merchant)
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
            log_structured_event(
                service="whatsapp_delivery",
                event_type="WA_NOTIF_DISPATCHED",
                entity_type="message",
                entity_id=str(external_id),
                status="SUCCESS",
                provider="meta",
                tenant_id=merchant,
                correlation_id=str(external_id),
            )

    log_structured_event(
        service="checkout_flow",
        event_type="ORDER_SETTLED",
        entity_type="order",
        entity_id=str(external_id),
        status="SUCCESS",
        tenant_id=merchant,
        correlation_id=str(external_id),
    )

    return {"status": "success", "order_id": external_id}