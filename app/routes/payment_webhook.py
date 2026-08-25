import logging
from aiohttp import web
from app.services.reconciliation_service import reconcile_incoming_mutation
from app.services.whatsapp_service import send_whatsapp_text
from app.services.cv_state_engine import GLOBAL_USER_STATES

logger = logging.getLogger(__name__)


async def handle_reader_mutation_webhook(request: web.Request) -> web.Response:
    """Webhook listener untuk menerima notifikasi mutasi transaksi dari Android Reader."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="INVALID_PAYLOAD", status=400)

    amount = data.get("amount") or data.get("nominal")
    raw_message = data.get("raw_text") or data.get("message") or ""
    tenant_id = data.get("tenant_id", "boontrack_career")

    if not amount:
        return web.Response(text="AMOUNT_REQUIRED", status=400)

    try:
        amount = int(amount)
    except ValueError:
        return web.Response(text="INVALID_AMOUNT_FORMAT", status=400)

    # Eksekusi Smart Reconciliation
    status, intent, diff = await reconcile_incoming_mutation(
        incoming_amount=amount,
        raw_text=raw_message,
        tenant_id=tenant_id
    )

    if not intent:
        logger.warning(f"[MUTATION UNMATCHED] Rp{amount:,} tidak cocok dengan invoice pending manapun.")
        return web.json_response({"status": "UNMATCHED", "action": "IGNORED"})

    user_id = intent.get("user_id")
    invoice_id = intent.get("invoice_id")
    expected_amount = intent.get("total_amount")

    # 1. EXACT MATCH: Langsung Selesaikan Order
    if status == "EXACT_MATCH":
        if intent.get("tenant_id") == "digicorn":
            from app.tenants.digicorn.service import digicorn_service
            await digicorn_service.deliver_paid_order(intent)
            return web.json_response({
                "status": "SUCCESS",
                "action": "AUTO_FULFILLED_DIGICORN",
                "invoice": invoice_id,
                "tenant": "digicorn"
            })

        success_msg = (
            f"🎉 *PEMBAYARAN TERVERIFIKASI!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 *Invoice:* `{invoice_id}`\n"
            f"💰 *Nominal Masuk:* Rp{amount:,}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            "AI BoonTrack sedang memproses perombakan total CV Anda ke standar HR Senior. Hasil akan dikirimkan sesaat lagi! 🚀"
        )
        await send_whatsapp_text(user_id, success_msg)

        if user_id in GLOBAL_USER_STATES:
            GLOBAL_USER_STATES[user_id]["is_premium_paid"] = True
            GLOBAL_USER_STATES[user_id]["tier"] = "premium_unlocked"

        # 🎯 Funnel Metric: career_premium_hr_converted
        try:
            from app.services.analytics_service import analytics_service
            await analytics_service.log_funnel_event(
                event_name="career_premium_hr_converted",
                user_id=user_id,
                tenant_id="boontrack-career",
                utm_source="mutation_reader",
                metadata={
                    "sender_wa_id": user_id,
                    "amount": amount,
                    "invoice_id": invoice_id,
                    "verification_method": "reader_mutation"
                }
            )
        except Exception as e:
            logger.warning(f"Error logging career_premium_hr_converted from reader: {e}")

        return web.json_response({"status": "SUCCESS", "action": "AUTO_FULFILLED", "invoice": invoice_id})

    # 2. NEAR MATCH (Typo Terdeteksi): Beri Tahu User Secara Halus
    elif status == "NEAR_MATCH":
        if intent.get("tenant_id") == "digicorn":
            from app.core.channels.telegram import send_telegram_message
            from app.core.tenants.registry import tenant_registry
            bot_token = tenant_registry.get_telegram_token("digicorn")
            if bot_token:
                await send_telegram_message(
                    bot_token=bot_token,
                    chat_id=user_id,
                    text=(
                        f"⚠️ *PEMBAYARAN DITERIMA (SELISIH NOMINAL)*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 *Invoice:* `{invoice_id}`\n"
                        f"📌 *Tagihan:* Rp{expected_amount:,}\n"
                        f"📥 *Nominal Diterima:* Rp{amount:,} *(Selisih Rp{diff})*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        "Dana sudah masuk. Admin sedang memverifikasi secara kilat untuk mengirimkan link produk Anda. Mohon tunggu 1-2 menit ya! 🙏"
                    )
                )
            return web.json_response({"status": "REVIEW", "action": "NOTIFIED_USER_TELEGRAM", "invoice": invoice_id})

        notice_msg = (
            f"⚠️ *PEMBAYARAN DITERIMA (SELISIH NOMINAL)*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 *Invoice:* `{invoice_id}`\n"
            f"📌 *Tagihan:* Rp{expected_amount:,}\n"
            f"📥 *Nominal Diterima:* Rp{amount:,} *(Selisih Rp{diff})*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            "Tenang, dana Anda sudah kami terima dengan aman. Sistem sedang melakukan verifikasi pencocokan manual kilat (1-2 menit). Mohon tunggu sebentar ya! 🙏"
        )
        await send_whatsapp_text(user_id, notice_msg)
        return web.json_response({"status": "REVIEW", "action": "NOTIFIED_USER", "invoice": invoice_id})

    # 3. AMBIGUOUS MATCH: Butuh Review Admin
    elif status == "AMBIGUOUS":
        return web.json_response({"status": "AMBIGUOUS", "action": "HOLD_FOR_MANUAL_REVIEW"})

    return web.json_response({"status": "UNMATCHED", "action": "IGNORED"})


def register_payment_webhook_routes(app: web.Application):
    app.router.add_post("/api/webhook/payment-reader", handle_reader_mutation_webhook)
    app.router.add_post("/api/webhook/dana", handle_reader_mutation_webhook)