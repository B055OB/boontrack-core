import os
import re
import logging
from aiohttp import web
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.core.bot import bot
from app.core.database import match_and_complete_order, match_and_complete_donation
from app.services.cloudflare_service import generate_unique_slug

logger = logging.getLogger("DANA_WEBHOOK")

EBOOK_FILE_ID = os.getenv("EBOOK_FILE_ID", "YOUR_TELEGRAM_EBOOK_FILE_ID")

async def dana_webhook_handler(request: web.Request) -> web.Response:
    """Handler webhook pembayaran DANA otomatis."""
    try:
        data = await request.json()
        print(f"[DANA RAW INCOMING]: {data}", flush=True)

        source = str(
            data.get("source", "") 
            or data.get("app", "") 
            or data.get("package_name", "") 
            or data.get("title", "") 
            or data.get("sender", "")
        ).lower()

        message = str(
            data.get("message", "") 
            or data.get("text", "") 
            or data.get("content", "") 
            or data.get("notification", "") 
            or data.get("body", "")
        )

        full_payload_str = (source + " " + message).lower()

        if "dana" not in full_payload_str:
            print(f"[DANA IGNORED] Not DANA related payload: {full_payload_str}", flush=True)
            return web.json_response({"status": "ignored", "reason": "not_dana"}, status=200)

        clean_text = message.replace(".", "").replace(",", "").replace("Rp", "Rp ").replace("rp", "Rp ")
        match = re.search(r"Rp\s*(\d+)", clean_text, re.IGNORECASE) or re.search(r"(\d{4,8})", clean_text)

        if match:
            incoming_amount = int(match.group(1))
            print(f"[DANA MATCHED AMOUNT]: Rp{incoming_amount:,}", flush=True)

            order = await match_and_complete_order(incoming_amount)
            if order:
                if order.get("status") == "PAID":
                    return web.json_response({"status": "already_fulfilled"}, status=200)

                buyer_id = order["telegram_id"]
                product = order["product_name"]

                caption_text = (
                    f"🎉 <b>Pembayaran Terkonfirmasi! (Rp{incoming_amount:,})</b>\n\n"
                    f"Terima kasih telah membeli <b>{product}</b>.\n"
                    f"File E-book kamu terlampir langsung di bawah ini. Selamat membaca dan sukses terus!"
                )
                try:
                    await bot.send_document(
                        chat_id=buyer_id,
                        document=EBOOK_FILE_ID,
                        caption=caption_text,
                        protect_content=True,
                        parse_mode="HTML"
                    )
                except Exception as doc_err:
                    print(f"[Document Send Error]: {doc_err}", flush=True)
                    fallback_msg = f"{caption_text}\n\n👉 Link Akses Alternative: https://cvats.boontrack.com/ebook-interview-boontrack.pdf"
                    await bot.send_message(chat_id=buyer_id, text=fallback_msg, parse_mode="HTML")

                return web.json_response({"status": "success_order", "order_id": order["order_id"]}, status=200)

            donation = await match_and_complete_donation(incoming_amount)
            if donation:
                if donation.get("status") == "VERIFIED":
                    return web.json_response({"status": "already_verified"}, status=200)

                donor_id = donation["telegram_id"]
                
                # Setup user data
                user_data = {"cp_status": "active"}
                default_slug = await generate_unique_slug(user_data)

                kbd_post = InlineKeyboardMarkup(row_width=1)
                kbd_post.add(
                    InlineKeyboardButton(f"✅ Pakai {default_slug}.boontrack.com", callback_data="cp_confirm_default_slug"),
                    InlineKeyboardButton("✏️ Ketik Nama Custom Sendiri", callback_data="cp_change_slug_start")
                )

                don_thanks = (
                    f"🎉 <b>PEMBAYARAN CAREER PAGE TERKONFIRMASI!</b>\n\n"
                    f"Terima kasih atas dukunganmu sebesar <b>Rp{incoming_amount:,}</b>! 🙏\n\n"
                    f"Sekarang, silakan tentukan nama link subdomain untuk Career Page milikmu:\n\n"
                    f"<b>Rekomendasi Subdomain:</b>\n"
                    f"👉 <code>{default_slug}.boontrack.com</code>\n\n"
                    f"Apakah kamu mau memakai nama rekomendasi di atas, atau ingin mengetik nama custom sendiri?"
                )
                await bot.send_message(chat_id=donor_id, text=don_thanks, reply_markup=kbd_post, parse_mode="HTML")
                return web.json_response({"status": "success_donation", "donation_id": donation["donation_id"]}, status=200)

            print(f"[DANA WARNING] Nominal Rp{incoming_amount:,} tidak cocok dengan order/donasi pending manapun.", flush=True)
            return web.json_response({"status": "no_matching_transaction", "amount": incoming_amount}, status=200)

        print(f"[DANA PARSE ERROR] Gagal mengekstrak nominal dari teks: {message}", flush=True)
        return web.json_response({"status": "failed_parsing", "message": message}, status=200)

    except Exception as e:
        print(f"[Webhook Exception]: {e}", flush=True)
        return web.json_response({"status": "error", "detail": str(e)}, status=500)
