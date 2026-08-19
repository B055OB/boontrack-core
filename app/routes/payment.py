import re
import logging
from aiohttp import web
from typing import Dict, Any, Optional
from app.services.whatsapp_service import send_whatsapp_text
from app.services.cv_state_engine import GLOBAL_USER_STATES
from app.core.database import track_event

logger = logging.getLogger(__name__)


def extract_amount_from_text(text: str) -> int:
    """Ekstraksi nominal angka dari format notifikasi DANA."""
    if not text:
        return 0
    # Mencocokkan 'Rp 10.416' / 'Rp10.416' / '10.416' / 'Rp 10416'
    match = re.search(r"(?:rp\.?|idr)?\s*([\d\.,]+)", text, re.IGNORECASE)
    if match:
        clean_digit = re.sub(r"\D", "", match.group(1))
        return int(clean_digit) if clean_digit else 0
    return 0


async def notify_payment_success(user_id: str, amount: int, platform: str = "whatsapp"):
    """Mengirim pesan konfirmasi aktivasi Career Page otomatis."""
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
        "• Direct contact button menuju WhatsApp kamu\n"
        "• Badge verifikasi ATS-Friendly\n\n"
        "_Ketik *Menu* untuk opsi lainnya._"
    )

    if platform == "whatsapp" or str(user_id).startswith("62") or len(str(user_id)) > 10:
        await send_whatsapp_text(str(user_id), success_msg)
    else:
        try:
            from app.services.telegram_service import send_telegram_message
            await send_telegram_message(int(user_id), success_msg.replace("*", "**"))
        except Exception as te:
            logger.debug(f"[Telegram Notify Fallback] {te}")


async def handle_dana_webhook(request: web.Request) -> web.Response:
    """Handler endpoint webhook notifikasi DANA reader."""
    try:
        data: Dict[str, Any] = await request.json()
    except Exception:
        try:
            post_data = await request.post()
            data = dict(post_data)
        except Exception:
            data = {}

    text = data.get("notification_text", "") or data.get("raw_text", "") or data.get("text", "")
    
    # Ambil nominal dari amount langsung atau dari text notifikasi
    raw_amount = data.get("amount") or data.get("nominal") or 0
    if raw_amount:
        try:
            amount = int(re.sub(r"\D", "", str(raw_amount)))
        except Exception:
            amount = extract_amount_from_text(text)
    else:
        amount = extract_amount_from_text(text)

    logger.info(f"\n[NOTIF INCOMING]: {text}")
    logger.info(f"[PARSED AMOUNT]: {amount}\n")

    if amount <= 0:
        return web.json_response({"status": "failed", "message": "Nominal tidak terbaca", "amount_detected": 0}, status=400)

    # Verifikasi dan pencocokan ke session invoice user
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
            await notify_payment_success(matched_user_id, amount, platform=matched_platform)
            GLOBAL_USER_STATES[matched_user_id]["is_premium"] = True
            GLOBAL_USER_STATES[matched_user_id]["active_payment"] = None

            await track_event(
                matched_user_id,
                "payment_success",
                meta={"amount": amount, "method": "DANA_NOTIF", "raw_text": text}
            )
        except Exception as e:
            logger.error(f"[Payment Process Error] {e}")

        return web.json_response({"status": "success", "amount_detected": amount, "user_matched": matched_user_id}, status=200)

    return web.json_response({"status": "success", "amount_detected": amount, "matched": False}, status=200)


def register_payment_routes(app: web.Application):
    """Mendaftarkan seluruh variasi path endpoint webhook DANA."""
    app.router.add_post("/webhook/dana", handle_dana_webhook)
    app.router.add_post("/api/webhook/dana", handle_dana_webhook)
    app.router.add_post("/api/payments/webhook", handle_dana_webhook)
    app.router.add_get("/webhook/dana", lambda r: web.json_response({"status": "running"}))