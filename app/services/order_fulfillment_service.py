import os
import sys
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from app.core.database import get_db_connection
from app.services.whatsapp_service import get_supabase
from app.services.meta_capi_service import send_meta_capi_purchase

logger = logging.getLogger("boontrack.fulfillment")

async def handle_order_paid_fulfillment(
    order_id: str, 
    tenant_slug: Optional[str] = None,
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Eksekusi otomatis alur pasca-bayar (Settlement & Akses Produk Digital):
    1. Verifikasi dan mutasi status order menjadi 'PAID' (DB Postgres & Supabase).
    2. Upgrade / sinkronisasi langganan tenant ke tier 'CHECKOUT_LITE'.
    3. Resolusi tautan produk digital (download_url / Telegram group / asset reference).
    4. Persist pesan pengiriman akses ke tabel 'messages' Supabase untuk Inbox Console.
    5. Dispatch notifikasi via WhatsApp Delivery Service (graceful skip jika WA offline).
    6. Dispatch event Purchase ke Meta Conversions API (CAPI).
    """
    logger.info(f"[FULFILLMENT] Memproses settlement pasca-bayar untuk order '{order_id}', tenant '{tenant_slug}'...")
    now_iso = datetime.now(timezone.utc).isoformat()
    order_data: Dict[str, Any] = {}

    # 1. Lookup order di PostgreSQL
    conn = None
    try:
        from psycopg2.extras import RealDictCursor
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id = %s;", (order_id,))
            row = cur.fetchone()
            if row:
                order_data = dict(row)
                if str(order_data.get("status") or "").upper() != "PAID":
                    cur.execute(
                        "UPDATE orders SET status = 'PAID', updated_at = NOW() WHERE id = %s RETURNING *;",
                        (order_id,)
                    )
                    order_data = dict(cur.fetchone())
                    conn.commit()
    except Exception as db_err:
        logger.warning(f"[FULFILLMENT DB NOTE] Postgres lookup error: {db_err}")
    finally:
        if conn:
            conn.close()

    # Fallback lookup di Supabase jika belum ditemukan di Postgres
    sb = get_supabase()
    if not order_data and sb:
        try:
            res = sb.table("orders").select("*").eq("id", order_id).limit(1).execute()
            if res.data:
                order_data = res.data[0]
                if str(order_data.get("status") or "").upper() != "PAID":
                    upd = sb.table("orders").update({
                        "status": "PAID",
                        "payment_status": "PAID",
                        "paid_at": now_iso,
                        "updated_at": now_iso
                    }).eq("id", order_id).execute()
                    if upd.data:
                        order_data = upd.data[0]
        except Exception as sb_err:
            logger.warning(f"[FULFILLMENT SB NOTE] Supabase order error: {sb_err}")

    if not order_data:
        logger.error(f"[FULFILLMENT ERROR] Order '{order_id}' tidak ditemukan di database.")
        return {"success": False, "error": f"Order {order_id} tidak ditemukan"}

    resolved_tenant = tenant_slug or order_data.get("tenant_slug") or "buzzerukm"
    product_title = order_data.get("product_title") or "Produk Digital"
    gross_amount = float(order_data.get("gross_amount") or order_data.get("total_amount") or 0)
    customer_name = order_data.get("customer_name") or "Pelanggan Setia"
    customer_phone = str(order_data.get("customer_phone") or "").strip()
    customer_email = str(order_data.get("customer_email") or "").strip()

    # 2. Update Langganan Tenant ke Tier 'CHECKOUT_LITE'
    try:
        if sb and resolved_tenant:
            t_res = sb.table("tenants").select("tier, metadata").eq("slug", resolved_tenant).limit(1).execute()
            if t_res.data:
                meta = t_res.data[0].get("metadata") or {}
                meta["tier"] = "CHECKOUT_LITE"
                meta["plan_tier"] = "CHECKOUT_LITE"
                meta["subscription_status"] = "ACTIVE"
                meta["subscription_tier"] = "CHECKOUT_LITE"
                
                sb.table("tenants").update({
                    "status": "active",
                    "metadata": meta
                }).eq("slug", resolved_tenant).execute()
                logger.info(f"[FULFILLMENT TIER] Langganan tenant '{resolved_tenant}' berhasil diupdate ke CHECKOUT_LITE.")
    except Exception as tier_err:
        logger.warning(f"[FULFILLMENT TIER WARN] Gagal sinkronisasi tier CHECKOUT_LITE: {tier_err}")

    # 3. Resolusi Akses Produk Digital
    access_url = order_data.get("download_url")
    fulfillment_metadata = order_data.get("fulfillment_metadata") or {}
    if not access_url and isinstance(fulfillment_metadata, dict):
        access_url = fulfillment_metadata.get("access_url")

    # Jika belum ada di order, cari dari katalog produk tenant di Supabase
    if not access_url and sb and resolved_tenant:
        try:
            t_res = sb.table("tenants").select("metadata").eq("slug", resolved_tenant).limit(1).execute()
            if t_res.data:
                prods = t_res.data[0].get("metadata", {}).get("products") or []
                if prods:
                    sel = prods[0]
                    access_url = sel.get("download_url") or sel.get("link_digital") or sel.get("asset_reference")
                    if not access_url and sel.get("fulfillment_metadata"):
                        access_url = sel.get("fulfillment_metadata", {}).get("access_url")
        except Exception as prod_err:
            logger.debug(f"[FULFILLMENT PROD WARN] {prod_err}")

    # Default fallback URL untuk Buzzer UKM / CTWA Mastery
    if not access_url:
        access_url = "https://t.me/+zhWxgGbzZxhmMjU1"

    # Simpan kembali download_url ke record orders
    try:
        if sb:
            sb.table("orders").update({
                "status": "PAID",
                "payment_status": "PAID",
                "download_url": access_url,
                "fulfillment_status": "DELIVERED",
                "updated_at": now_iso
            }).eq("id", order_id).execute()
    except Exception:
        pass

    # 4. Susun Pesan Delivery dan Simpan ke Supabase messages (Inbox Console)
    delivery_message = (
        f"🎉 *PEMBAYARAN BERHASIL & TERKONFIRMASI!*\n\n"
        f"Halo Kak *{customer_name}*! Pesanan Kakak telah kami terima dan terverifikasi lunas.\n\n"
        f"📋 *Rincian Transaksi:*\n"
        f"• *Order ID:* `{order_id}`\n"
        f"• *Item:* {product_title}\n"
        f"• *Total Bayar:* Rp {gross_amount:,.0f}\n\n"
        f"📦 *Akses Produk / Kelas Digital Kakak:*\n"
        f"👉 {access_url}\n\n"
        f"Selamat bergabung! Jika ada kendala, silakan balas pesan ini kapan saja. Tim kami siap membantu! ✨"
    )

    try:
        from app.services.whatsapp.cloud_api import log_to_supabase_messages
        asyncio.create_task(log_to_supabase_messages(
            sender="bot",
            text=delivery_message,
            tenant_id=resolved_tenant,
            channel="whatsapp",
            user_phone=customer_phone,
            user_name=customer_name,
            metadata={
                "order_id": order_id,
                "fulfillment_type": "DIGITAL_DELIVERY",
                "access_url": access_url,
                "agent_id": agent_id or "auto_system"
            }
        ))
        logger.info(f"[FULFILLMENT INBOX] Delivery message tersimpan ke Supabase messages untuk {customer_phone}.")
    except Exception as log_err:
        logger.warning(f"[FULFILLMENT LOG WARN] {log_err}")

    # 5. Pengiriman notifikasi live via WhatsAppDeliveryService (Graceful safe dispatch)
    wa_dispatched = False
    try:
        from app.services.whatsapp_delivery_service import WhatsAppDeliveryService
        wa_service = WhatsAppDeliveryService()
        wa_dispatched = await wa_service.send_order_success_notification(
            customer_phone=customer_phone,
            order_id=order_id,
            product_name=product_title,
            amount=gross_amount,
            download_url=access_url
        )
    except Exception as wa_err:
        logger.warning(f"[FULFILLMENT WA GATEWAY NOTE] Live WhatsApp dispatch skipped/failed (gateway disconnected): {wa_err}")

    # 6. Meta CAPI Purchase Dispatch
    capi_dispatched = False
    try:
        if gross_amount > 0:
            asyncio.create_task(
                send_meta_capi_purchase(
                    external_id=str(order_id),
                    value=gross_amount,
                    currency="IDR",
                    phone=customer_phone,
                    email=customer_email,
                    fbclid=order_data.get("fbclid"),
                    user_id=customer_phone
                )
            )
            capi_dispatched = True
            logger.info(f"[FULFILLMENT CAPI] Dispatched Meta Purchase CAPI untuk order {order_id} (Rp {gross_amount:,.0f}).")
    except Exception as capi_err:
        logger.warning(f"[FULFILLMENT CAPI WARN] {capi_err}")

    return {
        "success": True,
        "order_id": order_id,
        "tenant_slug": resolved_tenant,
        "tier": "CHECKOUT_LITE",
        "status": "PAID",
        "access_url": access_url,
        "wa_dispatched": wa_dispatched,
        "capi_dispatched": capi_dispatched,
        "message": f"Order #{order_id} berhasil disetujui, tenant di-upgrade ke CHECKOUT_LITE, dan akses produk terkirim."
    }
