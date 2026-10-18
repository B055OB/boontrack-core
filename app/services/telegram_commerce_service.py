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
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")
    if not sb_key:
        return None
    return {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _get_supabase_url() -> str:
    url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
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

    existing_meta = tenant_record.get("metadata")
    if not isinstance(existing_meta, dict):
        existing_meta = {}

    from_user_id = str((from_user or {}).get("id") or "").strip()

    # -------------------------------------------------------------------------
    # NODE 4: ANTI-SPOOFING VALIDATION KEPEMILIKAN TOKO
    # 1. Validasi Kepemilikan (tenant_id == telegram_user_id / owner match)
    # -------------------------------------------------------------------------
    stored_owner_id = str(existing_meta.get("telegram_user_id") or "").strip()
    if stored_owner_id and from_user_id and stored_owner_id != from_user_id:
        logger.warning(
            f"[ANTI-SPOOFING] Rejected: from_user {from_user_id} does not match stored owner {stored_owner_id} for tenant {tenant_id}"
        )
        return {
            "success": False,
            "message": (
                f"❌ *Validasi Anti-Spoofing Gagal: Kepemilikan Tidak Cocok*\n\n"
                f"Akun Telegram Anda (`{from_user_id}`) tidak cocok dengan ID pemilik terdaftar (`{stored_owner_id}`). "
                f"Akses konfigurasi toko ditolak demi keamanan aset bisnis Anda."
            ),
        }

    # -------------------------------------------------------------------------
    # 2. Validasi Produk Aktif (produk >= 1)
    # -------------------------------------------------------------------------
    prod_count = 0
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM public.products WHERE tenant_slug = %s OR tenant_id = %s;",
                (tenant_record.get("slug"), str(tenant_id))
            )
            row = cur.fetchone()
            if row:
                prod_count = row[0]
        conn.close()
    except Exception as _p_err:
        logger.debug(f"[AntiSpoofing] Product count DB note: {_p_err}")
        prods = existing_meta.get("products") or []
        prod_count = len(prods)

    if prod_count < 1:
        logger.warning(f"[ANTI-SPOOFING] Rejected: tenant {tenant_id} has 0 active products")
        return {
            "success": False,
            "message": (
                f"❌ *Validasi Anti-Spoofing Gagal: Produk Kosong*\n\n"
                f"Toko *{tenant_name}* belum memiliki minimal 1 produk aktif di katalog.\n"
                f"Silakan gunakan menu *Import Starter Product* di dashboard toko terlebih dahulu."
            ),
        }

    # -------------------------------------------------------------------------
    # 3. Validasi Saluran QRIS Aktif
    # -------------------------------------------------------------------------
    qris_active = bool(
        existing_meta.get("qris_active") is True
        or existing_meta.get("qris_status") == "ACTIVE"
        or tenant_record.get("payment_provider")
        or existing_meta.get("payment_provider")
        or existing_meta.get("qris_string")
    )
    if not qris_active:
        logger.warning(f"[ANTI-SPOOFING] Rejected: tenant {tenant_id} has inactive QRIS")
        return {
            "success": False,
            "message": (
                f"❌ *Validasi Anti-Spoofing Gagal: Saluran QRIS Tidak Aktif*\n\n"
                f"Saluran pembayaran Dynamic QRIS untuk toko *{tenant_name}* belum aktif.\n"
                f"Silakan aktifkan gateway pembayaran di menu Pengaturan Kasir toko Anda."
            ),
        }

    # -------------------------------------------------------------------------
    # 4. Sukses: Unlock Onboarding Stage = 2
    # -------------------------------------------------------------------------
    existing_meta["telegram_chat_id"] = chat_id_str
    existing_meta["telegram_user_id"] = from_user_id or str(chat_id_str)
    existing_meta["onboarding_stage"] = 2
    existing_meta["anti_spoofing_verified"] = True
    existing_meta["anti_spoofing_verified_at"] = datetime.now(timezone.utc).isoformat()
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
    except Exception as e:
        logger.error(f"[TELEGRAM COMMERCE] Error updating tenant {tenant_id}: {e}")

    # Simpan juga langsung ke PostgreSQL
    try:
        from app.core.database import get_db_connection
        conn_u = get_db_connection()
        with conn_u.cursor() as cur_u:
            cur_u.execute(
                """
                UPDATE public.tenants
                SET telegram_chat_id = %s,
                    enable_telegram = TRUE,
                    metadata = %s,
                    updated_at = NOW()
                WHERE id::text = %s OR slug = %s;
                """,
                (chat_id_str, json.dumps(existing_meta), str(tenant_id), tenant_record.get("slug"))
            )
            conn_u.commit()
        conn_u.close()
    except Exception as _db_u_err:
        logger.debug(f"[TELEGRAM COMMERCE] DB direct update note: {_db_u_err}")

    logger.info(
        f"[TELEGRAM COMMERCE] Successfully linked tenant '{tenant_name}' ({tenant_id}) to chat_id={chat_id_str} (Onboarding Stage 2 UNLOCKED)"
    )

    reply_msg = (
        f"✅ *Validasi Anti-Spoofing Kepemilikan Toko Berhasil!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Nama Toko*: {tenant_name}\n"
        f"• *ID Pemilik Telegram*: `{from_user_id or chat_id_str}` ✅\n"
        f"• *Katalog Produk*: Aktif ({prod_count} produk) ✅\n"
        f"• *Saluran Dynamic QRIS*: Aktif ✅\n\n"
        f"🔓 *Onboarding Stage 2 Berhasil Dibuka!* "
        f"Mulai sekarang seluruh notifikasi order baru, status pembayaran, dan Flexing Alert otomatis aktif."
    )

    return {
        "success": True,
        "tenant_id": tenant_id,
        "tenant_name": tenant_name,
        "chat_id": chat_id_str,
        "onboarding_stage": 2,
        "anti_spoofing_verified": True,
        "message": reply_msg,
    }


def link_creator_telegram(
    creator_ref: str,
    chat_id: Union[int, str],
    from_user: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Menghubungkan creatorId atau handle ke telegram_chat_id di tabel creator_profiles Supabase.
    Deep link pairing: https://t.me/booncreator_bot?start=auth_${creatorId}
    """
    clean_ref = str(creator_ref).strip()
    if not clean_ref:
        return {
            "success": False,
            "message": "❌ *Parameter otentikasi kreator tidak valid.*\nFormat yang benar: `/start auth_<creator_id>`",
        }

    sb_url = _get_supabase_url()
    headers = _get_supabase_headers()
    if not headers:
        logger.error("[TELEGRAM COMMERCE] Supabase credentials not found in env.")
        return {
            "success": False,
            "message": "⚠️ Terjadi kendala konfigurasi server saat menghubungkan kreator. Hubungi admin.",
        }

    chat_id_str = str(chat_id).strip()

    is_uuid = False
    try:
        uuid.UUID(clean_ref)
        is_uuid = True
    except (ValueError, TypeError, AttributeError):
        is_uuid = False

    creator_record = None
    try:
        with httpx.Client(timeout=6.0) as client:
            if is_uuid:
                params = {
                    "or": f"(id.eq.{clean_ref},tenant_id.eq.{clean_ref})",
                    "select": "id,handle,display_name,tenant_id,telegram_chat_id",
                    "limit": "1",
                }
            else:
                params = {
                    "handle": f"eq.{clean_ref.lower().replace('@', '')}",
                    "select": "id,handle,display_name,tenant_id,telegram_chat_id",
                    "limit": "1",
                }

            res = client.get(f"{sb_url}/rest/v1/creator_profiles", headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data and len(data) > 0:
                    creator_record = data[0]

            if not creator_record and not is_uuid:
                fallback_params = {
                    "id": f"eq.{clean_ref}",
                    "select": "id,handle,display_name,tenant_id,telegram_chat_id",
                    "limit": "1",
                }
                res_fb = client.get(f"{sb_url}/rest/v1/creator_profiles", headers=headers, params=fallback_params)
                if res_fb.status_code == 200 and res_fb.json():
                    creator_record = res_fb.json()[0]

    except Exception as e:
        logger.error(f"[TELEGRAM COMMERCE] Error querying creator_profiles '{clean_ref}': {e}")
        return {
            "success": False,
            "message": f"⚠️ Gagal menghubungkan profil kreator karena gangguan koneksi database: {e}",
        }

    if not creator_record:
        logger.warning(f"[TELEGRAM COMMERCE] Creator profile not found for ref: '{clean_ref}'")
        return {
            "success": False,
            "message": (
                f"❌ *Profil Kreator Tidak Ditemukan*\n\n"
                f"Rujukan kreator (`{clean_ref}`) belum terdaftar di platform BoonTrack Bio Link.\n"
                "Silakan periksa kembali tautan integrasi di Dashboard Kreator Anda."
            ),
        }

    cid = creator_record["id"]
    creator_name = creator_record.get("display_name") or creator_record.get("handle") or "Kreator"
    handle = creator_record.get("handle") or "kreator"

    # Simpan telegram_chat_id ke tabel creator_profiles
    try:
        with httpx.Client(timeout=6.0) as client:
            patch_headers = dict(headers)
            patch_headers["Prefer"] = "return=representation"
            update_payload = {
                "telegram_chat_id": chat_id_str,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            update_res = client.patch(
                f"{sb_url}/rest/v1/creator_profiles?id=eq.{cid}",
                headers=patch_headers,
                json=update_payload,
            )
            if update_res.status_code not in (200, 204):
                logger.error(f"[TELEGRAM COMMERCE] Failed to update creator telegram_chat_id: {update_res.text}")
                return {
                    "success": False,
                    "message": "⚠️ Gagal memperbarui sambungan Telegram ke database profil kreator.",
                }
    except Exception as update_err:
        logger.error(f"[TELEGRAM COMMERCE] Exception updating creator telegram_chat_id: {update_err}")
        return {
            "success": False,
            "message": f"⚠️ Terjadi kesalahan saat menyimpan sambungan: {update_err}",
        }

    logger.info(f"[TELEGRAM COMMERCE] Creator '{handle}' ({cid}) successfully linked to telegram chat {chat_id_str}")

    return {
        "success": True,
        "message": (
            f"🎉 *Akun Kreator Berhasil Terhubung!*\n\n"
            f"Halo *{creator_name}* (@{handle}), akun Telegram ini telah tersambung resmi ke profil Bio Link BoonTrack Anda via @booncreator_bot.\n\n"
            f"🔔 *Notifikasi Aktif:*\n"
            f"• Notifikasi traktir tip / donasi QRIS instan\n"
            f"• Notifikasi komisi reseller & affiliate\n"
            f"• Laporan transaksi kartu bio\n\n"
            f"_Chat ID: `{chat_id_str}`_"
        ),
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
        # Cek apakah ada parameter creator deep link: /start auth_<creator_id>
        if len(parts) > 1 and parts[1].startswith("auth_"):
            creator_ref = parts[1][5:].strip()
            link_res = link_creator_telegram(
                creator_ref=creator_ref,
                chat_id=chat_id,
                from_user={"id": user_id, "first_name": user_name},
            )
            return link_res["message"]
        # Cek apakah ada parameter deep link: /start link_<tenant_id>
        elif len(parts) > 1 and parts[1].startswith("link_"):
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

    # 4. Handler Command Fallback: LINK BARU (OnlineBoost Batch 1)
    if cmd in ["/link_baru", "/linkbaru", "link_baru"] or clean_text.upper() in ["LINK BARU", "LINK_BARU", "MINTA LINK BARU"]:
        return await handle_telegram_link_baru(
            user_id=user_id,
            user_name=user_name,
            chat_id=chat_id,
            bot_token=bot_token,
        )

    # 5. Pesan Non-Command
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
    """
    try:
        from app.core.security.inter_service_auth import generate_inter_service_signature
        target_tenant = "onlineboost"
        sig, ts, _ = generate_inter_service_signature(target_tenant, body=update)
        signed_headers = {
            "Content-Type": "application/json",
            "X-Boontrack-Signature": sig,
            "X-Boontrack-Timestamp": str(ts),
            "X-Boontrack-Tenant-Id": target_tenant,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://shop.boontrack.com/api/webhooks/telegram",
                json=update,
                headers=signed_headers
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[TELEGRAM PROXY] Forwarded to Next.js gateway: {data.get('status')}")
                return {"status": "success", "forwarded": True, "result": data}
    except Exception as forward_err:
        logger.warning(f"[TELEGRAM PROXY WARNING] Failed forwarding to shop.boontrack.com: {forward_err}")
    # Handle chat_member updates (Listener user join via single-use invite link)
    chat_member = update.get("chat_member")
    if chat_member:
        new_cm = chat_member.get("new_chat_member", {})
        status = new_cm.get("status")
        if status in ("member", "administrator", "creator"):
            u_info = new_cm.get("user", {})
            u_id = u_info.get("id")
            u_name = u_info.get("first_name") or "Member"
            inv_obj = chat_member.get("invite_link", {})
            inv_link = inv_obj.get("invite_link")
            res_cm = await handle_chat_member_joined(
                joined_link=inv_link,
                user_id=u_id,
                user_name=u_name,
                chat_id=chat_member.get("chat", {}).get("id"),
            )
            return res_cm

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


# =============================================================================
# NODE 3 & 4 HELPER FUNCTIONS (CTWA BATCH 1)
# =============================================================================

async def handle_chat_member_joined(
    joined_link: Optional[str],
    user_id: Union[int, str],
    user_name: str = "Member",
    chat_id: Optional[Union[int, str]] = None,
    tenant_id: str = "onlineboost",
) -> Dict[str, Any]:
    """
    Listener update chat_member:
    Ketika peserta bergabung ke Supergroup Telegram via Single-Use Invite Link,
    tandai token di telegram_single_use_tokens sebagai CLAIMED dan catat ke audit_logs.
    """
    logger.info(f"[ChatMemberListener] User {user_id} ({user_name}) joined via link: {joined_link}")
    updated = False
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL app.current_tenant_id = '{tenant_id}';")
            if joined_link:
                cur.execute(
                    """
                    UPDATE public.telegram_single_use_tokens
                    SET claimed = TRUE, claimed_at = NOW(), claimed_by = %s
                    WHERE (invite_link = %s OR token = %s) AND claimed = FALSE;
                    """,
                    (str(user_id), joined_link, joined_link)
                )
                if cur.rowcount > 0:
                    updated = True

            # Catat audit trail ke public.audit_logs
            cur.execute(
                """
                INSERT INTO public.audit_logs (
                    tenant_id, actor_id, action, resource_type, resource_id, metadata
                ) VALUES (
                    %s, %s, 'TELEGRAM_INVITE_CLAIMED', 'telegram_invite', %s, %s::jsonb
                );
                """,
                (
                    tenant_id,
                    str(user_id),
                    str(joined_link),
                    json.dumps({
                        "invite_link": joined_link,
                        "chat_id": str(chat_id),
                        "user_name": user_name,
                    })
                )
            )
            conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[ChatMemberListener] Error updating token / audit log: {e}")

    return {
        "status": "success",
        "event": "chat_member_joined",
        "claimed": updated,
        "user_id": str(user_id),
        "invite_link": joined_link,
    }


async def handle_telegram_link_baru(
    user_id: Union[int, str],
    user_name: str = "Kak",
    chat_id: Optional[Union[int, str]] = None,
    bot_token: Optional[str] = None,
    tenant_id: str = "onlineboost",
) -> str:
    """
    Command fallback 'LINK BARU':
    Mengecek order lunas peserta atau token yang hangus / belum digunakan,
    kemudian menerbitkan ulang single-use invite link baru (+24 jam, member_limit=1).
    """
    from app.services.ctwa_fulfillment_service import create_telegram_single_use_invite_link

    token_row = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL app.current_tenant_id = '{tenant_id}';")
            cur.execute(
                """
                SELECT token, order_id, invite_link, claimed, expires_at
                FROM public.telegram_single_use_tokens
                WHERE tenant_id = %s AND (claimed_by = %s OR token LIKE %s)
                ORDER BY created_at DESC LIMIT 1;
                """,
                (tenant_id, str(user_id), f"%{user_id}%")
            )
            token_row = cur.fetchone()
        conn.close()
    except Exception as e:
        logger.debug(f"[LinkBaruFallback] DB query note: {e}")

    order_id = token_row[1] if token_row else f"REFRESH-{uuid.uuid4().hex[:8].upper()}"

    # Panggil generator single-use invite link baru
    new_link = await create_telegram_single_use_invite_link(
        order_id=order_id,
        buyer_name=user_name,
        chat_id=None,
    )

    # Catat ke database telegram_single_use_tokens
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL app.current_tenant_id = '{tenant_id}';")
            cur.execute(
                """
                INSERT INTO public.telegram_single_use_tokens (
                    token, order_id, invite_link, claimed, expires_at, created_at, tenant_id
                ) VALUES (%s, %s, %s, FALSE, NOW() + INTERVAL '24 hours', NOW(), %s)
                ON CONFLICT (token) DO UPDATE SET
                    invite_link = EXCLUDED.invite_link,
                    claimed = FALSE,
                    expires_at = EXCLUDED.expires_at;
                """,
                (f"tok_{order_id}", order_id, new_link, tenant_id)
            )
            conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"[LinkBaruFallback] DB save note: {e}")

    return (
        f"🔄 *Tautan Undangan Baru Diterbitkan!*\n\n"
        f"Halo {user_name}! Berikut adalah tautan baru Anda untuk bergabung ke "
        f"*Supergroup Praktikum OnlineBoost Batch 1*:\n\n"
        f"🔗 {new_link}\n\n"
        f"⚠️ *Penting*: Tautan ini bersifat *single-use* (1 kali masuk) dan aktif selama *24 jam*. "
        f"Silakan langsung klik untuk bergabung ya Kak!"
    )


async def dispatch_flexing_alert(
    tenant_id: str,
    order_id: str,
    product_title: str,
    amount: int,
    customer_name: Optional[str] = None,
    bot_token: Optional[str] = None,
) -> bool:
    """
    Automated Flexing Alert saat ada order masuk / lunas via Dynamic QRIS.
    Dikirimkan ke telegram_chat_id milik tenant toko.
    """
    target_chat_id = None
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT telegram_chat_id, metadata FROM public.tenants WHERE id::text = %s OR slug = %s LIMIT 1;",
                (str(tenant_id), str(tenant_id))
            )
            row = cur.fetchone()
            if row:
                target_chat_id = row[0]
                if not target_chat_id and row[1]:
                    meta = row[1] if isinstance(row[1], dict) else json.loads(row[1])
                    target_chat_id = meta.get("telegram_chat_id")
        conn.close()
    except Exception as e:
        logger.debug(f"[FlexingAlert] DB lookup note: {e}")

    if not target_chat_id:
        target_chat_id = os.getenv("TELEGRAM_FLEXING_CHAT_ID") or os.getenv("ONLINEBOOST_TELEGRAM_GROUP_ID") or "-1004371114362"

    if not target_chat_id:
        logger.warning(f"[FlexingAlert] No telegram_chat_id resolved for tenant '{tenant_id}'")
        return False

    formatted_amount = f"{int(amount):,}".replace(",", ".")
    buyer = customer_name or "Pelanggan"
    flexing_text = (
        f"🔥 *ORDER MASUK! (PECAH TELUR)* 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Produk*: {product_title}\n"
        f"💰 *Nominal*: *Rp {formatted_amount}*\n"
        f"🧾 *No. Order*: `{order_id}`\n"
        f"👤 *Pembeli*: {buyer}\n"
        f"⚡ *Metode*: *Dynamic QRIS 0% fee (LUNAS)*\n\n"
        f"🚀 _Mesin kasir otomatis 24 jam Anda terus bekerja tanpa henti! Semangat scale up!_"
    )

    return await send_telegram_reply(
        chat_id=target_chat_id,
        text=flexing_text,
        bot_token=bot_token,
        parse_mode="Markdown",
    )
