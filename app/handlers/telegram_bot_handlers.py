"""
telegram_bot_handlers.py
Handler Resmi Dispatcher Telegram Commerce Engine untuk BoonTrack Shop (@boonshop_bot / @boontrack_bot).

Fitur:
1. Deep Link Handler: /start link_<tenant_id>
   - Menghubungkan tenant_id ke telegram_chat_id di database Supabase
   - Merespons konfirmasi:
     "✅ Toko [Nama Toko] berhasil terhubung! Mulai sekarang seluruh notifikasi order baru dan konfirmasi bayar akan dikirim ke sini."
2. Command /id:
   - Menampilkan Chat ID (Personal/Grup) dan User ID secara presisi
3. Command /help & /start (generic):
   - Memberikan panduan resmi integrasi e-commerce BoonTrack
4. Nonaktifkan Alur CV Legacy:
   - Alur CV/Karier lama dinonaktifkan secara default agar tidak menimpa alur e-commerce resmi.
"""

import os
import logging
from typing import Optional

from aiogram import types, Dispatcher, Bot

from app.services.telegram_commerce_service import (
    link_tenant_telegram,
    format_id_reply,
    format_start_welcome,
    format_help_reply,
    format_general_reply,
    _WAKE_WORDS,
)

logger = logging.getLogger("TELEGRAM_HANDLERS")


def register_all_bot_handlers(dp: Dispatcher, bot: Bot):
    """Mendaftarkan seluruh handler E-Commerce resmi ke Aiogram Dispatcher."""

    # 1. COMMAND /start (Mendukung deep link /start link_<tenant_id>)
    @dp.message_handler(commands=['start'])
    async def handle_start(message: types.Message):
        chat_id = message.chat.id
        from_id = message.from_user.id if message.from_user else chat_id
        user_name = message.from_user.first_name if message.from_user else "Teman"
        text = (message.text or "").strip()

        logger.info(f"[TELEGRAM HANDLER] /start received from chat_id={chat_id}, text='{text}'")

        text_parts = text.split()
        param = text_parts[1].strip() if len(text_parts) > 1 else ""

        # Handler Deep Link Pairing: /start link_<tenant_id>
        if param.startswith("link_"):
            tenant_ref = param[5:].strip()
            link_result = link_tenant_telegram(
                tenant_ref=tenant_ref,
                chat_id=chat_id,
                from_user={
                    "id": from_id,
                    "username": message.from_user.username if message.from_user else None,
                    "first_name": user_name,
                },
            )
            await message.reply(link_result["message"], parse_mode="Markdown")
            return

        # /start tanpa parameter -> Sambutan resmi Commerce Engine
        welcome_text = format_start_welcome()
        await message.reply(welcome_text, parse_mode="Markdown")

    # 2. COMMAND /id (Merespons angka chat ID personal maupun grup)
    @dp.message_handler(commands=['id'])
    async def handle_id(message: types.Message):
        chat_id = message.chat.id
        from_id = message.from_user.id if message.from_user else chat_id
        user_name = message.from_user.first_name if message.from_user else "Pengguna"
        chat_type = message.chat.type or "private"
        chat_title = message.chat.title

        logger.info(f"[TELEGRAM HANDLER] /id received from chat_id={chat_id}, type={chat_type}")

        id_text = format_id_reply(
            chat_id=chat_id,
            user_id=from_id,
            user_name=user_name,
            chat_title=chat_title,
            chat_type=chat_type,
        )
        await message.reply(id_text, parse_mode="Markdown")

    # 3. COMMAND /help & /bantuan
    @dp.message_handler(commands=['help', 'bantuan'])
    async def handle_help(message: types.Message):
        help_text = format_help_reply()
        await message.reply(help_text, parse_mode="Markdown")

    # 4. COMMAND /cancel
    @dp.message_handler(commands=['cancel'])
    async def handle_cancel(message: types.Message):
        cancel_text = (
            "Perintah dibatalkan. Ketik /help untuk panduan atau /id untuk melihat Chat ID Anda."
        )
        await message.reply(cancel_text, parse_mode="Markdown")

    # 5. HANDLER MEDIA & DOKUMEN (Pencegahan pesan error atau trigger CV)
    @dp.message_handler(content_types=['document', 'photo', 'video', 'audio', 'voice', 'sticker'])
    async def handle_media(message: types.Message):
        chat_type = message.chat.type or "private"
        if chat_type in ["group", "supergroup"]:
            # Abaikan media di grup (silent ignore)
            return

        reply_text = (
            "Terima kasih telah menghubungi @boonshop_bot.\n\n"
            "Bot ini bertugas mengirimkan notifikasi pesanan dan konfirmasi pembayaran toko online Anda.\n"
            "Ketik `/id` untuk melihat Chat ID Anda atau `/help` untuk panduan integrasi."
        )
        await message.reply(reply_text, parse_mode="Markdown")

    # 6. HANDLER PESAN TEKS BEBAS (Non-command)
    @dp.message_handler()
    async def handle_general_message(message: types.Message):
        chat_id = message.chat.id
        user_name = message.from_user.first_name if message.from_user else "Teman"
        chat_type = message.chat.type or "private"
        text = (message.text or "").strip()

        if chat_type in ["group", "supergroup"]:
            # Di grup: Hanya merespons jika ada kata pemicu / mention bot
            lower_text = text.lower()
            has_wake = any(w in lower_text for w in _WAKE_WORDS)
            if not has_wake:
                return  # Silent ignore di grup

            reply_text = format_general_reply(user_name)
            await message.reply(reply_text, parse_mode="Markdown")
            return

        # Di DM pribadi:
        reply_text = format_general_reply(user_name)
        await message.reply(reply_text, parse_mode="Markdown")

    # 7. HANDLER CALLBACK QUERY
    @dp.callback_query_handler(lambda c: True)
    async def handle_callback_query(callback_query: types.CallbackQuery):
        try:
            await callback_query.answer()
        except Exception:
            pass

        data = callback_query.data or ""
        logger.info(f"[TELEGRAM HANDLER] Callback query received: {data}")

        reply_text = (
            "Pilihan telah diterima. Bot ini saat ini aktif sebagai Bot Notifikasi E-Commerce Toko BoonTrack.\n"
            "Ketik /help untuk panduan integrasi atau /id untuk cek Chat ID Anda."
        )
        try:
            await callback_query.message.reply(reply_text, parse_mode="Markdown")
        except Exception:
            pass

    # 8. OPTIONAL: LEGACY CV BOT (Hanya jika diaktifkan via environment variable)
    if os.getenv("ENABLE_LEGACY_CV_BOT", "false").lower() == "true":
        logger.warning("[TELEGRAM HANDLERS] ENABLE_LEGACY_CV_BOT is true. Legacy CV flow loaded.")
        try:
            from app.handlers.career_page_flow import register_career_page_handlers
            register_career_page_handlers(dp)
        except Exception as e:
            logger.error(f"[TELEGRAM HANDLERS] Failed to load legacy career handlers: {e}")

    logger.info("[TELEGRAM HANDLERS] All Commerce Engine handlers registered successfully.")
