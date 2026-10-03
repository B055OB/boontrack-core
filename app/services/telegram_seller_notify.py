"""
telegram_seller_notify.py
─────────────────────────
Modul Notifikasi Telegram Seller BoonTrack (@boontrack_bot).

Mengirim notifikasi "flexing" ke grup/chat seller setiap kali terjadi event:
  A. PESANAN BARU MASUK  → format 🛒
  B. PEMBAYARAN LUNAS    → format 💸

Token  : env TELEGRAM_BOT_TOKEN  (bot @boontrack_bot)
Chat ID: env BOONPILOT_TG_SELLER_CHAT_ID  (bisa grup negatif atau user positif)
         Bisa juga di-override per-order via seller_chat_id kwarg.

§REF: User Request #3 – Modul Notifikasi Telegram Seller (Format Flexing)
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
        f"🛒 *PESANAN BARU MASUK!*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏪 Toko: {tenant_name}\n"
        f"🧾 Invoice: #{order_id}\n"
        f"📦 Produk: {product_name}\n"
        f"💰 Tagihan: *{_fmt_rupiah(amount)}*\n"
        f"💳 Metode: {payment_method}"
        f"{buyer_line}\n"
        f"⏰ Waktu: {_now_wib()}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚡ *Segera siapkan pesanan!* Customer sedang menunggu konfirmasi. 🙏"
    )
    result = await send_telegram_message(bot_token=token, chat_id=chat_id, text=text, parse_mode="Markdown")
    if result and result.get("ok"):
        logger.info(f"[SELLER NOTIFY] ✅ NEW_ORDER sent → chat={chat_id} order=#{order_id}")
        return True
    logger.warning(f"[SELLER NOTIFY] ⚠️ NEW_ORDER FAILED → chat={chat_id} result={result}")
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
        f"💸 *PEMBAYARAN LUNAS!*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏪 Toko: {tenant_name}\n"
        f"🧾 Invoice: #{order_id}\n"
        f"📦 Produk: {product_name}\n"
        f"💰 Nominal Diterima: *{_fmt_rupiah(amount)}*\n"
        f"💳 Via: {payment_method}"
        f"{buyer_line}"
        f"{ref_line}\n"
        f"⏰ Waktu: {_now_wib()}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ *Pembayaran OTOMATIS terverifikasi!*\n"
        f"🚀 Sistem sedang memproses & mengirim produk ke customer."
    )
    result = await send_telegram_message(bot_token=token, chat_id=chat_id, text=text, parse_mode="Markdown")
    if result and result.get("ok"):
        logger.info(f"[SELLER NOTIFY] ✅ PAYMENT_CONFIRMED sent → chat={chat_id} order=#{order_id}")
        return True
    logger.warning(f"[SELLER NOTIFY] ⚠️ PAYMENT_CONFIRMED FAILED → chat={chat_id} result={result}")
    return False


async def dispatch_seller_event(
    event: str,
    order_data: Dict[str, Any],
    seller_chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> bool:
    tenant_name = order_data.get("tenant_name") or order_data.get("store_name") or order_data.get("tenant_id") or "BoonTrack Merchant"
    order_id = order_data.get("order_id") or order_data.get("invoice_id") or order_data.get("id") or "N/A"
    product_name = order_data.get("product_name") or order_data.get("product") or order_data.get("product_id") or order_data.get("task_type") or "Produk BoonTrack"
    amount = int(order_data.get("amount") or order_data.get("total_amount") or order_data.get("price_amount") or 0)
    buyer_name = order_data.get("buyer_name") or order_data.get("user_name")
    buyer_phone = order_data.get("buyer_phone") or order_data.get("user_phone") or order_data.get("user_id")
    payment_method = order_data.get("payment_method") or "DANA Bisnis / QRIS"
    ref_code = order_data.get("ref") or order_data.get("ref_code") or order_data.get("transaction_ref")
    if event == "new_order":
        return await notify_new_order(
            tenant_name=tenant_name, order_id=str(order_id), product_name=product_name,
            amount=amount, buyer_name=buyer_name, buyer_phone=buyer_phone,
            payment_method=payment_method, seller_chat_id=seller_chat_id, bot_token=bot_token,
        )
    elif event == "payment_confirmed":
        return await notify_payment_confirmed(
            tenant_name=tenant_name, order_id=str(order_id), product_name=product_name,
            amount=amount, payment_method=payment_method, buyer_name=buyer_name,
            buyer_phone=buyer_phone, ref_code=ref_code,
            seller_chat_id=seller_chat_id, bot_token=bot_token,
        )
    logger.warning(f"[SELLER NOTIFY] Unknown event type: {event}")
    return False
