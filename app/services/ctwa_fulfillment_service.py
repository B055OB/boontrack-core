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
from datetime import datetime, timezone

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

    # Fail closed: Never fabricate a fake Telegram link per CTO P0 directive
    logger.error(f"[CTWA FULFILLMENT] Telegram Bot API failed to return invite link for Order {order_id} (fail-closed)")
    raise RuntimeError(f"Telegram Bot API failed to generate verified invite link for Order {order_id}")


def get_stored_telegram_link_from_order(order_data: Dict[str, Any]) -> Optional[str]:
    """Cek apakah link invite sudah ada di metadata, download_url, atau fulfillment_metadata (idempoten)."""
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
    if order_data.get("download_url") and str(order_data.get("download_url", "")).startswith("https://t.me/"):
        return order_data.get("download_url")
    f_meta = order_data.get("fulfillment_metadata") or {}
    if isinstance(f_meta, str):
        try:
            f_meta = json.loads(f_meta)
        except Exception:
            f_meta = {}
    if isinstance(f_meta, dict) and str(f_meta.get("access_url", "")).startswith("https://t.me/"):
        return f_meta.get("access_url")
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

    # P0 RESTRICT TO VERIFIED PAID ORDERS ONLY:
    # If an order record exists in DB, ensure payment status is PAID/SETTLED/LUNAS
    if order_record:
        order_st = str(order_record.get("status") or "").upper()
        pay_st = str(order_record.get("payment_status") or "").upper()
        if (order_st and order_st not in ("PAID", "SETTLED", "LUNAS")) or (pay_st and pay_st not in ("PAID", "SETTLED", "LUNAS")):
            logger.error(
                f"[CTWA FULFILLMENT] Order '{order_id}' is not in a verified paid state (status={order_st}, payment_status={pay_st}). Denying access."
            )
            return {
                "status": "REJECTED_UNPAID",
                "order_id": order_id,
                "error": f"Order '{order_id}' has unverified payment status ({order_st}/{pay_st}). Access denied.",
            }

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
        is_already_delivered = bool(
            _ISSUED_TELEGRAM_LINKS_CACHE.get(f"{order_id}_DELIVERED")
            or (order_record.get("metadata") or {}).get("fulfillment_status") == "DELIVERED"
        )
        if is_already_delivered:
            confirmation_message = (
                f"Selamat Kak {resolved_name}! Pembayaran sebesar Rp{amt_formatted} untuk Kelas Inkubasi CTWA Batch 1 telah BERHASIL diverifikasi ✅\n\n"
                f"Berikut link akses eksklusif Kakak untuk bergabung ke Supergroup Praktikum: 🔗 {single_use_link}\n\n"
                f"⚠️ Penting: Tautan di atas adalah link khusus 1 kali masuk dan berlaku selama 24 jam. Jangan dibagikan ke orang lain ya Kak!\n\n"
                f"Sampai jumpa di ruang praktikum!"
            )
            return {
                "status": "SUCCESS",
                "order_id": order_id,
                "single_use_invite_link": single_use_link,
                "confirmation_message": confirmation_message,
                "buyer_name": resolved_name,
                "buyer_phone": clean_phone,
                "amount": resolved_amount,
                "wa_result": {"status": "skipped", "reason": "ALREADY_DELIVERED"},
                "capi_result": {"status": "skipped", "reason": "ALREADY_DELIVERED"},
                "idempotency_hit": True,
            }
    else:
        # Panggil Telegram Bot API createChatInviteLink
        try:
            single_use_link = await create_telegram_single_use_invite_link(
                order_id=order_id,
                buyer_name=resolved_name,
                chat_id=chat_id,
            )
        except Exception as tg_err:
            logger.error(f"[CTWA FULFILLMENT] Failed generating Telegram invite for {order_id}: {tg_err}")
            current_meta = order_record.get("metadata") or {}
            if isinstance(current_meta, str):
                try:
                    current_meta = json.loads(current_meta)
                except Exception:
                    current_meta = {}
            if not isinstance(current_meta, dict):
                current_meta = {}
            current_meta["fulfillment_status"] = "TELEGRAM_INVITE_PENDING_RETRY"
            current_meta["fulfillment_error"] = str(tg_err)
            if sb and order_id:
                try:
                    sb.table("orders").update({"metadata": current_meta, "status": "PAID", "payment_status": "PAID"}).eq("id", order_id).execute()
                except Exception:
                    pass
            pending_msg = (
                f"Selamat Kak {resolved_name}! Pembayaran sebesar Rp{amt_formatted} untuk Kelas Inkubasi CTWA Batch 1 telah BERHASIL diverifikasi ✅\n\n"
                f"Tautan akses eksklusif Supergroup Praktikum Kakak sedang dalam antrean penerbitan sistem dan akan segera dikirimkan ke chat ini begitu siap.\n\n"
                f"Sampai jumpa di ruang praktikum!"
            )
            if clean_phone:
                try:
                    await cloud_api.send_whatsapp_text(
                        to_phone=clean_phone,
                        text=pending_msg,
                        tenant_id=tenant_id,
                    )
                except Exception:
                    pass
            return {
                "status": "PENDING_TELEGRAM_LINK",
                "order_id": order_id,
                "error": str(tg_err),
            }

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
        current_meta["delivered_at"] = datetime.now(timezone.utc).isoformat()

        fulfillment_payload = {
            "type": "digital",
            "delivery_type": "TELEGRAM_GROUP",
            "access_url": single_use_link,
            "download_url": single_use_link,
            "file_format": "TELEGRAM_INVITE",
            "button_text": "Gabung Grup Telegram",
            "delivered_at": datetime.now(timezone.utc).isoformat(),
        }

        if sb and order_id:
            try:
                sb.table("orders").update({
                    "metadata": current_meta,
                    "status": "PAID",
                    "payment_status": "PAID",
                    "download_url": single_use_link,
                    "fulfillment_metadata": fulfillment_payload,
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
                    SET metadata = %s,
                        status = 'PAID',
                        payment_status = 'PAID',
                        paid_at = COALESCE(paid_at, NOW()),
                        download_url = %s,
                        fulfillment_metadata = %s,
                        updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (json.dumps(current_meta), single_use_link, json.dumps(fulfillment_payload), order_id)
                )
                conn.commit()
            conn.close()
        except Exception as pg_upd_err:
            logger.debug(f"[CTWA FULFILLMENT] Postgres metadata update note: {pg_upd_err}")

    # Simpan ke tabel telegram_single_use_tokens dengan RLS
    try:
        from app.core.database import get_db_connection
        conn_tok = get_db_connection()
        with conn_tok.cursor() as cur_tok:
            cur_tok.execute(f"SET LOCAL app.current_tenant_id = '{tenant_id}';")
            tok_str = f"tok_{order_id}"
            cur_tok.execute(
                """
                INSERT INTO public.telegram_single_use_tokens (
                    token, order_id, invite_link, claimed, expires_at, created_at, tenant_id
                ) VALUES (%s, %s, %s, FALSE, NOW() + INTERVAL '24 hours', NOW(), %s)
                ON CONFLICT (token) DO UPDATE SET
                    invite_link = EXCLUDED.invite_link,
                    expires_at = EXCLUDED.expires_at;
                """,
                (tok_str, order_id, single_use_link, tenant_id)
            )
            conn_tok.commit()
        conn_tok.close()
        logger.info(f"[CTWA FULFILLMENT] Recorded single-use invite link into telegram_single_use_tokens for order {order_id}")
    except Exception as _tok_err:
        logger.warning(f"[CTWA FULFILLMENT] Failed to record telegram_single_use_tokens: {_tok_err}")

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

    if order_id:
        _ISSUED_TELEGRAM_LINKS_CACHE[f"{order_id}_DELIVERED"] = single_use_link

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
