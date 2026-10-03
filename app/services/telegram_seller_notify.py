"""
telegram_seller_notify.py
=========================
Modul Notifikasi Telegram Seller BoonTrack (@boontrack_bot).

Multi-Tenant Dispatcher Logic:
  1. Saat order berstatus PAID atau PENDING:
     - Query telegram_chat_id milik tenant terkait berdasarkan order.tenant_id / tenant_slug
     - Jika tenant memiliki telegram_chat_id, kirim notifikasi order flexing ke chat/grup tersebut
     - Fallback: Jika tenant belum set chat_id, kirim notifikasi ke BOONPILOT_TG_SELLER_CHAT_ID (superadmin platform)
"""
import os
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from app.core.channels.telegram import send_telegram_message

logger = logging.getLogger("TELEGRAM_SELLER_NOTIFY")

_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
_DEFAULT_SELLER_CHAT_ID: str = os.getenv("BOONPILOT_TG_SELLER_CHAT_ID", "")


def _fmt_rupiah(amount: int) -> str:
    return f"Rp{amount:,}".replace(",", ".")


def _now_wib() -> str:
    now = datetime.now()
    return now.strftime("%d %b %Y, %H:%M WIB")


def resolve_tenant_telegram_chat_id(tenant_ref: Optional[str]) -> Optional[str]:
    """
    Query telegram_chat_id milik tenant terkait dari Supabase.
    Mendukung field telegram_chat_id dan jsonb metadata.telegram_chat_id.
    Fallback: None (akan fallback ke BOONPILOT_TG_SELLER_CHAT_ID).
    """
    if not tenant_ref:
        return None

    sb_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not sb_url or not sb_key:
        return None

    try:
        import httpx
        url = f"{sb_url.rstrip('/')}/rest/v1/tenants"
        headers = {
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "Content-Type": "application/json",
        }
        params = {
            "or": f"(id.eq.{tenant_ref},slug.eq.{tenant_ref})",
            "select": "id,slug,name,telegram_chat_id,metadata",
            "limit": "1",
        }
        with httpx.Client(timeout=4.0) as client:
            res = client.get(url, headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data and len(data) > 0:
                    tenant = data[0]
                    chat_id = tenant.get("telegram_chat_id")
                    if not chat_id and isinstance(tenant.get("metadata"), dict):
                        chat_id = tenant["metadata"].get("telegram_chat_id")
                    if chat_id:
                        return str(chat_id).strip()
    except Exception as e:
        logger.debug(f"[SELLER NOTIFY] Error resolving tenant chat_id for {tenant_ref}: {e}")

    return None


async def notify_new_order(
    tenant_name: str,
    order_id: str,
    product_name: str,
    amount: int,
    buyer_name: Optional[str] = None,
    buyer_phone: Optional[str] = None,
    payment_method: str = "QRIS / Transfer",
    seller_chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> bool:
    token = bot_token or _BOT_TOKEN
    chat_id = seller_chat_id or _DEFAULT_SELLER_CHAT_ID
    if not token:
        logger.error("[SELLER NOTIFY] TELEGRAM_BOT_TOKEN tidak tersedia.")
        return False
    if not chat_id:
        logger.warning("[SELLER NOTIFY] BOONPILOT_TG_SELLER_CHAT_ID belum diset.")
        return False

    buyer_line = ""
    if buyer_name or buyer_phone:
        parts = [buyer_name] if buyer_name else []
        if buyer_phone:
            parts.append(f"{buyer_phone}")
        buyer_line = f"\n👤 Pembeli: {' | '.join(parts)}"

    text = (
        f"⚡ *PESANAN BARU MASUK!*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏪 Toko: {tenant_name}\n"
        f"🧾 Invoice: #{order_id}\n"
        f"📦 Produk: {product_name}\n"
        f"💰 Tagihan: *{_fmt_rupiah(amount)}*\n"
        f"💳 Metode: {payment_method}"
        f"{buyer_line}\n"
        f"🕒 Waktu: {_now_wib()}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👉 *Segera siapkan pesanan!* Customer sedang menunggu konfirmasi. 🚀"
    )
    result = await send_telegram_message(bot_token=token, chat_id=chat_id, text=text, parse_mode="Markdown")
    if result and result.get("ok"):
        logger.info(f"[SELLER NOTIFY] ✅ NEW_ORDER sent   chat={chat_id} order=#{order_id}")
        return True
    logger.warning(f"[SELLER NOTIFY] ⚠️ NEW_ORDER FAILED   chat={chat_id} result={result}")
    return False


async def notify_payment_confirmed(
    tenant_name: str,
    order_id: str,
    product_name: str,
    amount: int,
    payment_method: str = "DANA Bisnis / QRIS",
    buyer_name: Optional[str] = None,
    buyer_phone: Optional[str] = None,
    ref_code: Optional[str] = None,
    seller_chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> bool:
    token = bot_token or _BOT_TOKEN
    chat_id = seller_chat_id or _DEFAULT_SELLER_CHAT_ID
    if not token:
        logger.error("[SELLER NOTIFY] TELEGRAM_BOT_TOKEN tidak tersedia.")
        return False
    if not chat_id:
        logger.warning("[SELLER NOTIFY] BOONPILOT_TG_SELLER_CHAT_ID belum diset.")
        return False

    buyer_line = ""
    if buyer_name or buyer_phone:
        parts = [buyer_name] if buyer_name else []
        if buyer_phone:
            parts.append(f"{buyer_phone}")
        buyer_line = f"\n👤 Pembeli: {' | '.join(parts)}"

    ref_line = f"\n🔖 Ref Transaksi: {ref_code}" if ref_code else ""
    text = (
        f"🎉 *PEMBAYARAN LUNAS!*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏪 Toko: {tenant_name}\n"
        f"🧾 Invoice: #{order_id}\n"
        f"📦 Produk: {product_name}\n"
        f"💰 Nominal Diterima: *{_fmt_rupiah(amount)}*\n"
        f"💳 Via: {payment_method}"
        f"{buyer_line}"
        f"{ref_line}\n"
        f"🕒 Waktu: {_now_wib()}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ *Pembayaran OTOMATIS terverifikasi!*\n"
        f"🚀 Sistem sedang memproses & mengirim produk ke customer."
    )
    result = await send_telegram_message(bot_token=token, chat_id=chat_id, text=text, parse_mode="Markdown")
    if result and result.get("ok"):
        logger.info(f"[SELLER NOTIFY] ✅ PAYMENT_CONFIRMED sent   chat={chat_id} order=#{order_id}")
        return True
    logger.warning(f"[SELLER NOTIFY] ⚠️ PAYMENT_CONFIRMED FAILED   chat={chat_id} result={result}")
    return False


async def dispatch_seller_event(
    event: str,
    order_data: Dict[str, Any],
    seller_chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> bool:
    """
    Multi-tenant Telegram event dispatcher.
    Resolves tenant's telegram_chat_id from database if not explicitly provided.
    Falls back to BOONPILOT_TG_SELLER_CHAT_ID if tenant has not linked their Telegram yet.
    """
    tenant_ref = order_data.get("tenant_id") or order_data.get("tenant_slug")
    effective_chat_id = seller_chat_id

    # Resolusi multi-tenant: query telegram_chat_id milik tenant terkait
    if not effective_chat_id and tenant_ref:
        effective_chat_id = resolve_tenant_telegram_chat_id(str(tenant_ref))

    # Fallback jika belum di-set: gunakan master seller/admin chat
    if not effective_chat_id:
        effective_chat_id = _DEFAULT_SELLER_CHAT_ID

    tenant_name = (
        order_data.get("tenant_name")
        or order_data.get("store_name")
        or order_data.get("tenant_slug")
        or order_data.get("tenant_id")
        or "BoonTrack Merchant"
    )
    order_id = (
        order_data.get("order_id")
        or order_data.get("invoice_id")
        or order_data.get("id")
        or "N/A"
    )
    product_name = (
        order_data.get("product_name")
        or order_data.get("product_title")
        or order_data.get("product")
        or order_data.get("product_id")
        or order_data.get("task_type")
        or "Produk BoonTrack"
    )
    amount = int(
        order_data.get("amount")
        or order_data.get("total_amount")
        or order_data.get("gross_amount")
        or order_data.get("price_amount")
        or 0
    )
    buyer_name = order_data.get("buyer_name") or order_data.get("customer_name") or order_data.get("user_name")
    buyer_phone = order_data.get("buyer_phone") or order_data.get("customer_phone") or order_data.get("user_phone") or order_data.get("user_id")
    payment_method = order_data.get("payment_method") or "DANA Bisnis / QRIS"
    ref_code = order_data.get("ref") or order_data.get("ref_code") or order_data.get("transaction_ref")

    if event in ("new_order", "order_pending", "order_created"):
        return await notify_new_order(
            tenant_name=tenant_name,
            order_id=str(order_id),
            product_name=product_name,
            amount=amount,
            buyer_name=buyer_name,
            buyer_phone=buyer_phone,
            payment_method=payment_method,
            seller_chat_id=effective_chat_id,
            bot_token=bot_token,
        )
    elif event in ("payment_confirmed", "order_paid", "paid"):
        return await notify_payment_confirmed(
            tenant_name=tenant_name,
            order_id=str(order_id),
            product_name=product_name,
            amount=amount,
            payment_method=payment_method,
            buyer_name=buyer_name,
            buyer_phone=buyer_phone,
            ref_code=ref_code,
            seller_chat_id=effective_chat_id,
            bot_token=bot_token,
        )

    logger.warning(f"[SELLER NOTIFY] Unknown event type: {event}")
    return False
