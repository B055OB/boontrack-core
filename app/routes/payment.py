import re
import logging
from aiohttp import web
from typing import Dict, Any
from app.services.whatsapp_service import send_whatsapp_text
from app.services.cv_state_engine import GLOBAL_USER_STATES
from app.core.database import track_event

logger = logging.getLogger(__name__)


def extract_amount_from_text(text: str) -> int:
    """Ekstraksi nominal angka dari berbagai pola teks notifikasi transfer DANA."""
    if not text:
        return 0
    match = re.search(r"(?:rp\.?|idr)?\s*([\d\.,]+)", text, re.IGNORECASE)
    if match:
        clean_digit = re.sub(r"\D", "", match.group(1))
        return int(clean_digit) if clean_digit else 0
    return 0


async def notify_payment_success_universal(user_id: str, amount: int, platform: str = "whatsapp"):
    """
    Mengirimkan notifikasi aktivasi Career Page secara otomatis
    baik untuk pengguna Telegram maupun WhatsApp.
    """
    user_session = GLOBAL_USER_STATES.get(user_id, {})
    user_data = user_session.get("data", {})
    nama = user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""
    sapaan = f", *{nama}*" if nama else ""
    career_page_url = f"https://boontrack.com/p/{user_id}"

    success_msg = (
        f"🎉 *PEMBAYARAN DITERIMA! TERIMA KASIH{sapaan.upper()}!* 🎉\n\n"
        f"Pembayaran sebesar *Rp{amount:,}* telah berhasil diverifikasi oleh sistem BoonTrack.\n\n"
        f"🌐 *Career Page Portofolio Kamu Sudah Aktif (Seumur Hidup):*\n"
        f"👉 {career_page_url}\n\n"
        "✨ *Fitur yang aktif:*\n"
        "• Link halaman portofolio personal responsif\n"
        "• Direct contact button menuju kontakmu\n"
        "• Badge verifikasi ATS-Friendly\n\n"
        "_Ketik *Menu* untuk opsi lainnya._"
    )

    # Routing otomatis: Cek apakah ID berasal dari WhatsApp atau Telegram
    is_wa_number = str(user_id).startswith("62") or len(str(user_id)) >= 11 or platform == "whatsapp"

    if is_wa_number:
        try:
            await send_whatsapp_text(str(user_id), success_msg)
            logger.info(f"[PAYMENT NOTIFY] WhatsApp sent to {user_id}")
        except Exception as e:
            logger.error(f"[Payment WhatsApp Notify Error] {e}")
    else:
        try:
            # Kirim ke Telegram jika user bertransaksi lewat Telegram Bot
            from app.services.telegram_service import send_telegram_message
            await send_telegram_message(int(user_id), success_msg.replace("*", "**"))
            logger.info(f"[PAYMENT NOTIFY] Telegram sent to {user_id}")
        except Exception as te:
            logger.error(f"[Payment Telegram Notify Error] {te}")


async def handle_dana_webhook(request: web.Request) -> web.Response:
    """Handler endpoint webhook notifikasi mutasi DANA (Telegram & WA)."""
    try:
        data: Dict[str, Any] = await request.json()
    except Exception:
        try:
            data = dict(await request.post())
        except Exception:
            data = {}

    text = data.get("notification_text") or data.get("raw_text") or data.get("text") or data.get("keterangan") or ""
    raw_amount = data.get("amount") or data.get("nominal") or 0

    if raw_amount:
        try:
            amount = int(re.sub(r"\D", "", str(raw_amount)))
        except Exception:
            amount = extract_amount_from_text(text)
    else:
        amount = extract_amount_from_text(text)

    logger.info(f"[DANA WEBHOOK] Incoming Text: '{text}' | Amount: {amount}")

    if amount <= 0:
        return web.json_response({"status": "failed", "reason": "invalid_amount", "amount_detected": 0}, status=400)

    # Cari user aktif (baik sesi Telegram maupun sesi WhatsApp)
    matched_user_id = None
    matched_platform = "whatsapp"

    for uid, session in list(GLOBAL_USER_STATES.items()):
        payment_info = session.get("active_payment", {})
        expected_amt = payment_info.get("total_amt")

        if expected_amt and int(expected_amt) == amount:
            matched_user_id = uid
            matched_platform = session.get("platform", "whatsapp")
            break

    if matched_user_id:
        try:
            await notify_payment_success_universal(matched_user_id, amount, platform=matched_platform)
            GLOBAL_USER_STATES[matched_user_id]["is_premium"] = True
            GLOBAL_USER_STATES[matched_user_id]["active_payment"] = None

            await track_event(
                matched_user_id,
                "payment_success",
                meta={"amount": amount, "method": "DANA_QRIS", "text": text, "platform": matched_platform}
            )
        except Exception as e:
            logger.error(f"[Payment Process Error] {e}")

        return web.json_response({"status": "success", "amount_detected": amount, "user_matched": matched_user_id}, status=200)

    return web.json_response({"status": "success", "amount_detected": amount, "matched": False}, status=200)


def register_payment_routes(app: web.Application):
    """Mendaftarkan seluruh endpoint pembayaran."""
    app.router.add_post("/webhook/dana", handle_dana_webhook)
    app.router.add_post("/api/webhook/dana", handle_dana_webhook)
    app.router.add_post("/api/payments/webhook", handle_dana_webhook)
    app.router.add_get("/webhook/dana", lambda r: web.json_response({"status": "running"}))