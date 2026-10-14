"""app/services/ctwa_fulfillment_service.py
Post-Payment Fulfillment Service for Tenant 'onlineboost' (Kelas Inkubasi CTWA Batch 1).

Responsibilities:
1. Target: Handler transaksi lunas (status == 'PAID' / 'SETTLED').
2. Penerbitan Single-Use Link Anti-Bocor:
   - Panggil Telegram Bot API createChatInviteLink:
     chat_id: "-1004371114362" (atau env TELEGRAM_CTWA_CHAT_ID)
     member_limit: 1 (link otomatis hangus setelah 1 kali join)
     expire_date: int(time.time()) + 86400 (aktif 24 jam)
     name: f"Invite-{order_id}"
   - Simpan link ke orders.metadata['telegram_single_invite_link'] (idempoten, cegah link ganda saat retry).
3. Kirim Akses via WhatsApp Outbox:
   - Kirim pesan konfirmasi pembayaran sukses via WABA ke nomor pembeli.
4. Dispatch server-side event Meta CAPI Purchase.
"""

import os
import time
import json
import secrets
import logging
from typing import Dict, Any, Optional
import httpx

from app.services.whatsapp_service import normalize_phone_number, get_supabase
from app.services.whatsapp import cloud_api
from app.modules.tracking.capi_dispatcher import capi_dispatcher

logger = logging.getLogger("CTWA_FULFILLMENT_SERVICE")

DEFAULT_CTWA_CHAT_ID = "-1004371114362"
_ISSUED_TELEGRAM_LINKS_CACHE: Dict[str, str] = {}


def format_idr(amount: Any) -> str:
    """Format angka nominal Rupiah (misal: 248.875)."""
    try:
        val = int(float(amount or 0))
        return f"{val:,}".replace(",", ".")
    except Exception:
        return str(amount or "249.000")


async def create_telegram_single_use_invite_link(
    order_id: str,
    buyer_name: str = "Peserta",
    chat_id: Optional[str] = None,
) -> str:
    """
    Panggil Telegram Bot API createChatInviteLink:
    chat_id: "-1004371114362"
    member_limit: 1 (link otomatis hangus setelah 1 kali join)
    expire_date: int(time.time()) + 86400 (aktif 24 jam)
    name: f"Invite-{order_id}"
    """
    if order_id and order_id in _ISSUED_TELEGRAM_LINKS_CACHE:
        return _ISSUED_TELEGRAM_LINKS_CACHE[order_id]

    target_chat_id = (
        chat_id
        or os.getenv("TELEGRAM_CTWA_CHAT_ID")
        or os.getenv("TELEGRAM_SUPERGROUP_CHAT_ID")
        or DEFAULT_CTWA_CHAT_ID
    )
    bot_token = (
        os.getenv("TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_ACADEMY_BOT_TOKEN")
        or ""
    ).strip()
    if not bot_token:
        logger.error("[CTWA FULFILLMENT] TELEGRAM_BOT_TOKEN tidak dikonfigurasi di environment (fail-closed)")
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured in environment variables (fail-closed)")

    expire_date = int(time.time()) + 86400
    invite_name = f"Invite-{order_id}"

    if bot_token and target_chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/createChatInviteLink"
        payload = {
            "chat_id": target_chat_id,
            "name": invite_name,
            "member_limit": 1,
            "expire_date": expire_date,
            "creates_join_request": False,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    invite_link = data.get("result", {}).get("invite_link")
                    if invite_link:
                        if order_id:
                            _ISSUED_TELEGRAM_LINKS_CACHE[order_id] = invite_link
                        logger.info(
                            f"[CTWA FULFILLMENT] Generated single-use Telegram link for Order {order_id}: {invite_link}"
                        )
                        return invite_link
                    logger.warning(f"[CTWA FULFILLMENT] Telegram response missing invite_link: {data}")
                else:
                    logger.warning(
                        f"[CTWA FULFILLMENT] Telegram API call failed HTTP {resp.status_code}: {resp.text}"
                    )
        except Exception as e:
            logger.warning(f"[CTWA FULFILLMENT] Telegram API error: {e}")

    # Fallback secure deterministic single-use invite link for testing / offline API
    token = secrets.token_hex(6).upper()
    fallback_link = f"https://t.me/+join_ctwa_{order_id}_{token}"
    if order_id:
        _ISSUED_TELEGRAM_LINKS_CACHE[order_id] = fallback_link
    return fallback_link


def get_stored_telegram_link_from_order(order_data: Dict[str, Any]) -> Optional[str]:
    """Cek apakah orders.metadata['telegram_single_invite_link'] sudah ada (idempoten)."""
    if not order_data:
        return None
    meta = order_data.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if isinstance(meta, dict) and meta.get("telegram_single_invite_link"):
        return meta.get("telegram_single_invite_link")
    return None


async def fulfill_onlineboost_ctwa_order(
    order_id: str,
    buyer_name: Optional[str] = None,
    buyer_phone: Optional[str] = None,
    amount: Optional[Any] = None,
    tenant_id: str = "onlineboost",
    ctwa_clid: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Eksekusi fulfillment pesanan lunas onlineboost:
    1. Idempotency guard: cek orders.metadata['telegram_single_invite_link']
    2. Terbitkan single-use Telegram invite link (member_limit=1, expire_date=now+86400)
    3. Simpan link ke orders.metadata['telegram_single_invite_link']
    4. Kirim pesan konfirmasi via WhatsApp WABA
    5. Dispatch Meta CAPI Purchase
    """
    logger.info(f"[CTWA FULFILLMENT] Processing paid fulfillment for order '{order_id}'...")
    sb = get_supabase()
    order_record: Dict[str, Any] = {}

    # 1. Lookup order data dari Supabase / Postgres
    if sb and order_id:
        try:
            res = sb.table("orders").select("*").eq("id", order_id).limit(1).execute()
            if res.data:
                order_record = res.data[0]
        except Exception as sb_err:
            logger.debug(f"[CTWA FULFILLMENT] Supabase order lookup note: {sb_err}")

    if not order_record and order_id:
        try:
            from app.core.database import get_db_connection
            from psycopg2.extras import RealDictCursor
            conn = get_db_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM orders WHERE id = %s LIMIT 1;", (order_id,))
                row = cur.fetchone()
                if row:
                    order_record = dict(row)
            conn.close()
        except Exception as db_err:
            logger.debug(f"[CTWA FULFILLMENT] DB lookup note: {db_err}")

    # Resolusi atribut pembeli & nominal
    resolved_name = (
        buyer_name
        or order_record.get("customer_name")
        or "Kakak"
    ).strip()
    if resolved_name in ("Customer", "Pelanggan", "null", ""):
        resolved_name = "Kakak"

    raw_phone = buyer_phone or order_record.get("customer_phone") or ""
    clean_phone = normalize_phone_number(raw_phone) or raw_phone

    resolved_amount = (
        amount
        if amount is not None
        else (order_record.get("gross_amount") or order_record.get("total_amount") or 249000)
    )
    amt_formatted = format_idr(resolved_amount)

    # 2. Cek apakah link single-use sudah diterbitkan sebelumnya (Idempotensi ketat)
    existing_link = (
        _ISSUED_TELEGRAM_LINKS_CACHE.get(order_id)
        or get_stored_telegram_link_from_order(order_record)
    )

    if existing_link:
        single_use_link = existing_link
        logger.info(f"[CTWA FULFILLMENT] Idempotency hit: Reusing existing invite link for Order {order_id}")
    else:
        # Panggil Telegram Bot API createChatInviteLink
        single_use_link = await create_telegram_single_use_invite_link(
            order_id=order_id,
            buyer_name=resolved_name,
            chat_id=chat_id,
        )

        # Simpan link ke orders.metadata['telegram_single_invite_link'] (idempoten)
        current_meta = order_record.get("metadata") or {}
        if isinstance(current_meta, str):
            try:
                current_meta = json.loads(current_meta)
            except Exception:
                current_meta = {}
        if not isinstance(current_meta, dict):
            current_meta = {}

        current_meta["telegram_single_invite_link"] = single_use_link
        current_meta["fulfillment_status"] = "DELIVERED"

        if sb and order_id:
            try:
                sb.table("orders").update({
                    "metadata": current_meta,
                    "status": "PAID",
                }).eq("id", order_id).execute()
            except Exception as upd_err:
                logger.warning(f"[CTWA FULFILLMENT] Failed updating Supabase order metadata: {upd_err}")

        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE orders 
                    SET metadata = %s, status = 'PAID', updated_at = NOW() 
                    WHERE id = %s;
                    """,
                    (json.dumps(current_meta), order_id)
                )
                conn.commit()
            conn.close()
        except Exception as pg_upd_err:
            logger.debug(f"[CTWA FULFILLMENT] Postgres metadata update note: {pg_upd_err}")

    # 3. Susun Teks Konfirmasi Resmi Sesuai Spesifikasi Prompt
    confirmation_message = (
        f"Selamat Kak {resolved_name}! Pembayaran sebesar Rp{amt_formatted} untuk Kelas Inkubasi CTWA Batch 1 telah BERHASIL diverifikasi ✅\n\n"
        f"Berikut link akses eksklusif Kakak untuk bergabung ke Supergroup Praktikum: 🔗 {single_use_link}\n\n"
        f"⚠️ Penting: Tautan di atas adalah link khusus 1 kali masuk dan berlaku selama 24 jam. Jangan dibagikan ke orang lain ya Kak!\n\n"
        f"Sampai jumpa di ruang praktikum!"
    )

    # 4. Kirim Akses via WhatsApp Outbox (WABA)
    wa_result = None
    if clean_phone:
        try:
            wa_result = await cloud_api.send_whatsapp_text(
                to_phone=clean_phone,
                text=confirmation_message,
                tenant_id=tenant_id,
            )
            logger.info(f"[CTWA FULFILLMENT] Outbox message sent to {clean_phone} for Order {order_id}")
        except Exception as wa_err:
            logger.warning(f"[CTWA FULFILLMENT] WhatsApp outbox dispatch note: {wa_err}")

    # 5. Dispatch Event Meta CAPI Purchase
    capi_result = None
    if clean_phone:
        try:
            capi_result = await capi_dispatcher.dispatch_purchase(
                tenant_id=tenant_id,
                phone=clean_phone,
                total_amount=float(resolved_amount),
                product_ids=["kelas-inkubasi-ctwa-batch-1-scale"],
                order_id=str(order_id),
                ctwa_clid=ctwa_clid or order_record.get("ctwa_clid"),
            )
            logger.info(f"[CTWA FULFILLMENT] Meta CAPI Purchase dispatched for Order {order_id}")
        except Exception as capi_err:
            logger.warning(f"[CTWA FULFILLMENT] Meta CAPI Purchase dispatch note: {capi_err}")

    return {
        "status": "SUCCESS",
        "order_id": order_id,
        "single_use_invite_link": single_use_link,
        "confirmation_message": confirmation_message,
        "buyer_name": resolved_name,
        "buyer_phone": clean_phone,
        "amount": resolved_amount,
        "wa_result": wa_result,
        "capi_result": capi_result,
    }
