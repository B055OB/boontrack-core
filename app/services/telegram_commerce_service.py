"""
telegram_commerce_service.py
Service Handler Telegram Commerce Engine untuk BoonTrack Shop (@boonshop_bot / @boontrack_bot).

Fungsi Utama:
1. Deep Link Handler: /start link_<tenant_id>
   - Resolusi tenant dari Supabase berdasarkan ID atau slug
   - Update field telegram_chat_id di tabel `tenants` (kolom langsung & metadata)
   - Respon konfirmasi:
     "✅ Toko [Nama Toko] berhasil terhubung! Mulai sekarang seluruh notifikasi order baru dan konfirmasi bayar akan dikirim ke sini."
2. Command /id:
   - Mengembalikan Chat ID (Personal atau Grup) serta User ID pengirim
3. Command /start & /help:
   - Respon panduan resmi integrasi e-commerce BoonTrack
4. Safe Multi-Channel Dispatcher:
   - Mengabaikan pesan grup acak tanpa mention/wake word
   - Bebas dari alur legacy CV / Karier
"""

import os
import re
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union
import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("TELEGRAM_COMMERCE")

_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "boonshop_bot").strip().lstrip("@")
_WAKE_WORDS = ["boon", "@boon", f"@{_BOT_USERNAME.lower()}", "@boonshop_bot", "@boontrack_bot"]


def _get_supabase_headers() -> Optional[Dict[str, str]]:
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not sb_key:
        return None
    return {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _get_supabase_url() -> str:
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "https://mpluzajlzpregmjwpjqr.supabase.co"
    return url.rstrip("/")


def link_tenant_telegram(
    tenant_ref: str,
    chat_id: Union[int, str],
    from_user: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Menghubungkan tenant_id atau tenant_slug ke telegram_chat_id di Supabase.
    Memperbarui kolom `telegram_chat_id` dan `metadata.telegram_chat_id`.
    """
    clean_ref = str(tenant_ref).strip()
    if not clean_ref:
        return {
            "success": False,
            "message": "❌ *Parameter link tidak valid.*\nFormat yang benar: `/start link_<id_toko>`",
        }

    sb_url = _get_supabase_url()
    headers = _get_supabase_headers()
    if not headers:
        logger.error("[TELEGRAM COMMERCE] Supabase credentials not found in env.")
        return {
            "success": False,
            "message": "⚠️ Terjadi kendala konfigurasi server saat menghubungkan toko. Hubungi admin.",
        }

    chat_id_str = str(chat_id).strip()

    # 1. Cari tenant di tabel tenants Supabase
    is_uuid = False
    try:
        uuid.UUID(clean_ref)
        is_uuid = True
    except (ValueError, TypeError, AttributeError):
        is_uuid = False

    tenant_record = None
    try:
        with httpx.Client(timeout=6.0) as client:
            if is_uuid:
                params = {
                    "id": f"eq.{clean_ref}",
                    "select": "id,name,slug,telegram_chat_id,metadata",
                    "limit": "1",
                }
            else:
                params = {
                    "slug": f"eq.{clean_ref.lower()}",
                    "select": "id,name,slug,telegram_chat_id,metadata",
                    "limit": "1",
                }

            res = client.get(f"{sb_url}/rest/v1/tenants", headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data and len(data) > 0:
                    tenant_record = data[0]

            # Fallback jika slug tidak ditemukan tapi mungkin ID berupa string bebas
            if not tenant_record and not is_uuid:
                fallback_params = {
                    "id": f"eq.{clean_ref}",
                    "select": "id,name,slug,telegram_chat_id,metadata",
                    "limit": "1",
                }
                res_fb = client.get(f"{sb_url}/rest/v1/tenants", headers=headers, params=fallback_params)
                if res_fb.status_code == 200 and res_fb.json():
                    tenant_record = res_fb.json()[0]

    except Exception as e:
        logger.error(f"[TELEGRAM COMMERCE] Error querying tenant '{clean_ref}': {e}")
        return {
            "success": False,
            "message": f"⚠️ Gagal menghubungkan toko karena gangguan koneksi database: {e}",
        }

    if not tenant_record:
        logger.warning(f"[TELEGRAM COMMERCE] Tenant not found for ref: '{clean_ref}'")
        return {
            "success": False,
            "message": (
                f"❌ *Toko Tidak Ditemukan*\n\n"
                f"ID atau kode pairing toko (`{clean_ref}`) tidak valid atau belum terdaftar di BoonTrack.\n"
                "Silakan periksa kembali tautan integrasi di Dashboard BoonTrack Anda."
            ),
        }

    tenant_id = tenant_record["id"]
    tenant_name = tenant_record.get("name") or tenant_record.get("slug") or "Toko Anda"

    # 2. Update telegram_chat_id dan metadata di Supabase
    existing_meta = tenant_record.get("metadata")
    if not isinstance(existing_meta, dict):
        existing_meta = {}

    existing_meta["telegram_chat_id"] = chat_id_str
    existing_meta["telegram_linked_at"] = datetime.now(timezone.utc).isoformat()
    if from_user:
        existing_meta["telegram_linked_by"] = {
            "id": from_user.get("id"),
            "username": from_user.get("username"),
            "first_name": from_user.get("first_name"),
        }

    update_payload = {
        "telegram_chat_id": chat_id_str,
        "enable_telegram": True,
        "metadata": existing_meta,
    }

    try:
        with httpx.Client(timeout=6.0) as client:
            update_url = f"{sb_url}/rest/v1/tenants?id=eq.{tenant_id}"
            res_up = client.patch(update_url, headers=headers, json=update_payload)
            if res_up.status_code not in (200, 204):
                logger.error(f"[TELEGRAM COMMERCE] Failed to update tenant: {res_up.status_code} {res_up.text}")
                return {
                    "success": False,
                    "message": "⚠️ Gagal menyimpan konfigurasi Telegram ke database toko.",
                }
    except Exception as e:
        logger.error(f"[TELEGRAM COMMERCE] Error updating tenant {tenant_id}: {e}")
        return {
            "success": False,
            "message": f"⚠️ Gagal menyimpan konfigurasi: {e}",
        }

    logger.info(
        f"[TELEGRAM COMMERCE] Successfully linked tenant '{tenant_name}' ({tenant_id}) to chat_id={chat_id_str}"
    )

    # Format balasan resmi sesuai instruksi
    reply_msg = (
        f"✅ Toko *{tenant_name}* berhasil terhubung! "
        "Mulai sekarang seluruh notifikasi order baru dan konfirmasi bayar akan dikirim ke sini."
    )

    return {
        "success": True,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "chat_id": chat_id_str,
        "message": reply_msg,
    }


def format_id_reply(
    chat_id: Union[int, str],
    user_id: Union[int, str],
    user_name: str = "Pengguna",
    chat_title: Optional[str] = None,
    chat_type: str = "private",
) -> str:
    """
    Format respon command /id yang aman dan informatif.
    """
    chat_id_str = str(chat_id).strip()
    user_id_str = str(user_id).strip()

    if chat_type in ["group", "supergroup"]:
        title_str = chat_title or "Grup"
        return (
            f"🆔 *Informasi Chat Telegram (Grup)*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Group Chat ID*: `{chat_id_str}`\n"
            f"• *Nama Grup*: {title_str}\n"
            f"• *User ID Pengirim*: `{user_id_str}`\n"
            f"• *Tipe*: {chat_type}\n\n"
            f"📋 _Salin Chat ID di atas (termasuk tanda minus '-') untuk menghubungkan notifikasi toko ke grup ini di Dashboard BoonTrack._"
        )

    return (
        f"🆔 *Informasi Chat Telegram*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Chat ID*: `{chat_id_str}`\n"
        f"• *User ID*: `{user_id_str}`\n"
        f"• *Nama*: {user_name}\n"
        f"• *Tipe*: Personal (DM)\n\n"
        f"📋 _Salin Chat ID di atas untuk dimasukkan ke pengaturan notifikasi toko Anda di Dashboard BoonTrack._"
    )


def format_start_welcome() -> str:
    """
    Format sambutan resmi e-commerce ketika user mengirim /start tanpa parameter deep link.
    """
    return (
        f"👋 *Halo! Selamat datang di Bot Resmi BoonTrack (@{_BOT_USERNAME}).*\n\n"
        "Bot ini bertugas mengirimkan notifikasi instan untuk pesanan baru (*New Order*) "
        "dan konfirmasi pembayaran (*Payment Confirmed*) langsung ke chat pribadi atau grup toko Anda.\n\n"
        "📌 *Cara Menghubungkan Toko:*\n"
        "1. Buka dashboard merchant Anda di [dashboard.boontrack.com](https://dashboard.boontrack.com)\n"
        "2. Buka menu *Pengaturan* ➡️ *Notifikasi & Integrasi*\n"
        "3. Klik tombol *Hubungkan ke Telegram* atau gunakan link pairing toko Anda\n\n"
        "💡 *Perintah Bantuan:*\n"
        "• `/id` — Cek Chat ID (Personal atau Grup) Anda\n"
        "• `/help` — Panduan integrasi bot"
    )


def format_help_reply() -> str:
    """
    Format panduan /help bot notifikasi toko.
    """
    return (
        f"📖 *Panduan Bot Notifikasi Toko BoonTrack*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "1. *Notifikasi ke Chat Pribadi:*\n"
        "   Ketik `/id` di sini, lalu masukkan Chat ID tersebut di Dashboard Toko Anda. "
        "Atau klik tombol *Hubungkan Telegram* langsung dari Dashboard.\n\n"
        "2. *Notifikasi ke Grup Telegram:*\n"
        f"   - Tambahkan bot ini (@{_BOT_USERNAME}) ke grup toko Anda.\n"
        "   - Ketik `/id` di dalam grup tersebut.\n"
        "   - Salin angka ID grup yang berawalan minus (contoh: `-1001234567890`) ke Dashboard Toko Anda.\n"
        "   - Bot akan otomatis mengirimkan notifikasi transaksi flexing ke grup tersebut setiap ada pesanan masuk!"
    )


def format_general_reply(user_name: str) -> str:
    """Format respon chat umum non-perintah."""
    return (
        f"Halo {user_name}! Ada yang bisa kami bantu seputar pesanan atau toko online Anda?\n\n"
        "• Ketik `/id` untuk melihat Chat ID\n"
        "• Ketik `/help` untuk panduan integrasi"
    )
async def send_telegram_reply(
    chat_id: Union[int, str],
    text: str,
    bot_token: Optional[str] = None,
    parse_mode: str = "Markdown",
) -> bool:
    """
    Mengirim pesan balasan ke chat Telegram via Telegram Bot API HTTP POST.
    """
    token = bot_token or _BOT_TOKEN
    if not token:
        logger.error("[TELEGRAM COMMERCE] Bot token not provided or missing from env.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True

            # Jika Markdown parse error, coba fallback tanpa parse_mode
            logger.warning(
                f"[TELEGRAM COMMERCE] Send with {parse_mode} failed ({resp.status_code}): {resp.text}. Retrying plain text."
            )
            payload.pop("parse_mode", None)
            resp_fallback = await client.post(url, json=payload)
            return resp_fallback.status_code == 200
    except Exception as e:
        logger.error(f"[TELEGRAM COMMERCE] Error sending telegram reply to {chat_id}: {e}")
        return False


async def process_telegram_incoming(
    chat_id: Union[int, str],
    user_id: Union[int, str],
    text: str,
    user_name: str = "User",
    chat_type: str = "private",
    chat_title: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> Optional[str]:
    """
    Dispatcher pusat untuk setiap pesan masuk Telegram (baik via Webhook maupun Aiogram Polling).
    Mengembalikan string respon balasan, atau None jika pesan harus diabaikan (silent ignore).
    """
    clean_text = (text or "").strip()
    if not clean_text:
        return None

    parts = clean_text.split()
    raw_cmd = parts[0].lower() if parts else ""
    # Bersihkan nama bot dari command (contoh: /start@boonshop_bot -> /start)
    cmd = raw_cmd.split("@")[0]

    # 1. Handler Command: /start
    if cmd == "/start":
        # Cek apakah ada parameter deep link: /start link_<tenant_id>
        if len(parts) > 1 and parts[1].startswith("link_"):
            tenant_ref = parts[1][5:].strip()
            link_res = link_tenant_telegram(
                tenant_ref=tenant_ref,
                chat_id=chat_id,
                from_user={"id": user_id, "first_name": user_name},
            )
            return link_res["message"]
        else:
            return format_start_welcome()

    # 2. Handler Command: /id
    if cmd == "/id":
        return format_id_reply(
            chat_id=chat_id,
            user_id=user_id,
            user_name=user_name,
            chat_title=chat_title,
            chat_type=chat_type,
        )

    # 3. Handler Command: /help
    if cmd in ["/help", "/bantuan"]:
        return format_help_reply()

    # 4. Pesan Non-Command
    if chat_type in ["group", "supergroup"]:
        # Di grup: Silent ignore KECUALI mengandung wake word atau mention bot
        lower_text = clean_text.lower()
        has_wake = any(w in lower_text for w in _WAKE_WORDS)
        # Di grup publik, jangan kirim template notifikasi toko
        return None

    # Di Chat Pribadi (DM):
    return format_general_reply(user_name)


async def handle_telegram_update(
    update: Dict[str, Any],
    bot_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Handler universal untuk raw Update payload dari Telegram Webhook.
    Forwarding payload ke Next.js BoonPilot Inbox Gateway (Gemini AI Sales Representative).
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://shop.boontrack.com/api/webhooks/telegram",
                json=update,
                headers={"User-Agent": "TelegramBot (via BoonTrack Core Proxy)"}
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[TELEGRAM PROXY] Forwarded to Next.js gateway: {data.get('status')}")
                return {"status": "success", "forwarded": True, "result": data}
    except Exception as forward_err:
        logger.warning(f"[TELEGRAM PROXY WARNING] Failed forwarding to shop.boontrack.com: {forward_err}")
    message = update.get("message") or update.get("edited_message")
    callback_query = update.get("callback_query")

    if callback_query:
        from_user = callback_query.get("from", {})
        user_id = from_user.get("id")
        user_name = from_user.get("first_name") or from_user.get("username") or "User"
        callback_msg = callback_query.get("message", {})
        chat = callback_msg.get("chat", {})
        chat_id = chat.get("id") or user_id
        chat_type = chat.get("type", "private")
        chat_title = chat.get("title")
        text = callback_query.get("data", "")
    elif message:
        from_user = message.get("from", {})
        user_id = from_user.get("id")
        user_name = from_user.get("first_name") or from_user.get("username") or "User"
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        chat_title = chat.get("title")
        text = message.get("text", "")
    else:
        return {"status": "ignored", "reason": "unsupported_update_type"}

    if not chat_id:
        return {"status": "ignored", "reason": "missing_chat_id"}

    reply_text = await process_telegram_incoming(
        chat_id=chat_id,
        user_id=user_id,
        text=text,
        user_name=user_name,
        chat_type=chat_type,
        chat_title=chat_title,
        bot_token=bot_token,
    )

    sent = False
    if reply_text:
        sent = await send_telegram_reply(
            chat_id=chat_id,
            text=reply_text,
            bot_token=bot_token,
        )

    return {
        "status": "success",
        "chat_id": chat_id,
        "handled": bool(reply_text),
        "sent": sent,
    }
