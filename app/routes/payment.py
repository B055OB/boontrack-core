import os
import re
import logging
from aiohttp import web
from typing import Dict, Any
from app.services.whatsapp_service import send_whatsapp_text
from app.services.cv_state_engine import GLOBAL_USER_STATES
from app.core.database import track_event

logger = logging.getLogger(__name__)


def extract_amount_from_text(text: str) -> int:
    """Ekstraksi nominal angka dari format notifikasi DANA Android / SMS."""
    if not text:
        return 0
    match = re.search(r"(?:rp\.?|idr)?\s*([\d\.,]+)", text, re.IGNORECASE)
    if match:
        clean_digit = re.sub(r"\D", "", match.group(1))
        return int(clean_digit) if clean_digit else 0
    return 0


async def serve_qris_asset(request: web.Request) -> web.Response:
    """Endpoint penyedia file fisik gambar QRIS dari folder assets."""
    possible_paths = [
        os.path.join(os.getcwd(), "assets", "qris_dana.jpg"),
        os.path.join(os.getcwd(), "assets", "qris_dana.png"),
        os.path.join(os.getcwd(), "assets", "qris.png"),
        os.path.join(os.getcwd(), "assets", "qris.jpg"),
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            content_type = "image/jpeg" if path.endswith((".jpg", ".jpeg")) else "image/png"
            with open(path, "rb") as f:
                return web.Response(body=f.read(), content_type=content_type)
                
    return web.Response(text="QRIS image not found", status=404)


async def notify_payment_success_universal(user_id: str, amount: int, platform: str = "whatsapp"):
    """Mengirim notifikasi keberhasilan transaksi sesuai jenis produk."""
    user_session = GLOBAL_USER_STATES.get(str(user_id), {})
    user_data = user_session.get("data", {})
    nama = user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""
    sapaan = f", *{nama}*" if nama else ""

    # Skenario 1: Pembayaran Premium CV Rewrite (Rp25.000)
    if amount == 25000:
        success_msg = (
            f"🎉 *PEMBAYARAN DITERIMA! TERIMA KASIH{sapaan.upper()}!* 🎉\n\n"
            f"Pembayaran sebesar *Rp25.000* telah berhasil diverifikasi oleh sistem BoonTrack.\n\n"
            "AI kami sedang menyusun ulang CV Anda menggunakan struktur dan diksi pencapaian tinggi "
            "berdasarkan metodologi ATS-friendly dan masukan profesional HR. ⏳\n\n"
            "File CV Premium Anda akan segera terkirim di chat ini."
        )
    # Skenario 2: Pembayaran Career Page / Produk Standar (Rp10.000)
    else:
        career_page_url = f"https://boontrack.com/p/{user_id}"
        success_msg = (
            f"🎉 *PEMBAYARAN DITERIMA! TERIMA KASIH{sapaan.upper()}!* 🎉\n\n"
            f"Pembayaran sebesar *Rp{amount:,}* telah berhasil diverifikasi oleh sistem BoonTrack.\n\n"
            f"🌐 *Career Page Portofolio Kamu Sudah Aktif (Seumur Hidup):*\n"
            f"👉 {career_page_url}\n\n"
            "✨ *Fitur yang aktif:*\n"
            "• Link halaman portofolio personal responsif\n"
            "• Direct contact button menuju WhatsApp/kontakmu\n"
            "• Badge verifikasi ATS-Friendly\n\n"
            "_Ketik *Menu* untuk kembali ke menu utama._"
        )

    is_wa = str(user_id).startswith("62") or len(str(user_id)) >= 11 or platform == "whatsapp"

    if is_wa:
        try:
            await send_whatsapp_text(str(user_id), success_msg)
            logger.info(f"[PAYMENT NOTIFY] WhatsApp success sent to {user_id}")
        except Exception as e:
            logger.error(f"[Payment WhatsApp Notify Error] {e}")
    else:
        try:
            from app.services.telegram_service import send_telegram_message
            await send_telegram_message(int(user_id), success_msg.replace("*", "**"))
            logger.info(f"[PAYMENT NOTIFY] Telegram success sent to {user_id}")
        except Exception as te:
            logger.error(f"[Payment Telegram Notify Error] {te}")


async def handle_dana_webhook(request: web.Request) -> web.Response:
    """Handler endpoint webhook mutasi DANA (Mendukung Payload Reader & Custom Test)."""
    try:
        data: Dict[str, Any] = await request.json()
    except Exception:
        try:
            data = dict(await request.post())
        except Exception:
            data = {}

    text = data.get("notification_text") or data.get("raw_text") or data.get("text") or data.get("keterangan") or ""
    raw_amount = data.get("amount") or data.get("nominal") or 0
    direct_phone = data.get("user_phone") or data.get("phone") or ""

    if raw_amount:
        try:
            amount = int(re.sub(r"\D", "", str(raw_amount)))
        except Exception:
            amount = extract_amount_from_text(text)
    else:
        amount = extract_amount_from_text(text)

    logger.info(f"[DANA WEBHOOK RECEIVED] Amount: {amount} | Raw Text: '{text}' | Direct Phone: '{direct_phone}'")

    if amount <= 0:
        return web.json_response({"status": "ignored", "reason": "invalid_amount", "amount_detected": 0}, status=200)

    # 1. Matching terhadap Active Session di Memori atau Direct Phone Test
    matched_user_id = None
    matched_platform = "whatsapp"

    if direct_phone:
        matched_user_id = str(direct_phone)
    else:
        for uid, session in list(GLOBAL_USER_STATES.items()):
            mode = session.get("mode")
            payment_info = session.get("active_payment", {})
            expected_amt = payment_info.get("total_amt") or payment_info.get("amount") if payment_info else None

            # Cek matching: via state awaiting_rewrite_payment (Rp25k) ATAU via expected nominal
            if (mode == "awaiting_rewrite_payment" and amount == 25000) or (
                expected_amt and int(re.sub(r"\D", "", str(expected_amt))) == amount
            ):
                matched_user_id = str(uid)
                matched_platform = session.get("platform", "whatsapp")
                break

    if matched_user_id:
        try:
            await notify_payment_success_universal(matched_user_id, amount, platform=matched_platform)
            
            if matched_user_id in GLOBAL_USER_STATES:
                GLOBAL_USER_STATES[matched_user_id]["is_premium"] = True
                GLOBAL_USER_STATES[matched_user_id]["active_payment"] = None
                GLOBAL_USER_STATES[matched_user_id]["mode"] = "post_cv"

            # Track event payment success
            await track_event(
                matched_user_id,
                "payment_success",
                meta={"amount": amount, "method": "DANA_QRIS", "platform": matched_platform}
            )

            # Jika rewrite Rp25k, catat event rewrite_delivered
            if amount == 25000:
                await track_event(matched_user_id, "rewrite_delivered", meta={"status": "completed"})

        except Exception as e:
            logger.error(f"[Payment Trigger Error] {e}")

        return web.json_response({
            "status": "success",
            "message": "Payment verified successfully",
            "amount_detected": amount,
            "user_matched": matched_user_id,
            "platform": matched_platform
        }, status=200)

    return web.json_response({
        "status": "success",
        "amount_detected": amount,
        "matched": False,
        "note": "No active pending session for this exact amount"
    }, status=200)


def register_payment_routes(app: web.Application):
    """Mendaftarkan endpoint pembayaran DANA & QRIS Asset universal."""
    # Endpoint asset gambar QRIS publik
    app.router.add_get("/assets/qris.png", serve_qris_asset)
    app.router.add_get("/assets/qris.jpg", serve_qris_asset)

    # Endpoint webhook mutasi pembayaran
    app.router.add_post("/webhook/dana", handle_dana_webhook)
    app.router.add_post("/api/webhook/dana", handle_dana_webhook)
    app.router.add_post("/api/payments/webhook", handle_dana_webhook)
    app.router.add_get("/webhook/dana", lambda r: web.json_response({"status": "running", "gateway": "BoonTrack QRIS"}))