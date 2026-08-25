import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from app.tenants.career.config import TENANT_ID
from app.tenants.career.messages import (
    WELCOME_CAREER_TEMPLATE,
    CAREER_MENU_BUTTONS,
    UPSELL_REWRITE_MSG,
    UPSELL_BUTTONS,
    LANG_SELECTION_BUTTONS,
    RECEIPT_UPLOAD_INFO_MSG,
    RECEIPT_INVALID_MSG,
    REVIEW_INTRO_MSG,
    DOC_READING_TEMPLATE,
    DOC_UNREADABLE_MSG,
    DOC_ERROR_MSG,
    TEXT_TOO_SHORT_MSG,
    format_diagnosis_message,
    format_invoice_caption
)
from app.services.whatsapp_service import (
    send_whatsapp_text,
    send_whatsapp_image,
    send_whatsapp_buttons,
    safe_log_to_supabase_messages
)
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes
from app.services.reconciliation_service import generate_unique_payment_intent, PAYMENT_INTENTS

logger = logging.getLogger(__name__)

# Safe import OCR service agar server tetap aman berjalan
try:
    from app.services.receipt_ocr_service import parse_receipt_image
except Exception as e:
    logger.warning(f"Receipt OCR service not loaded yet: {e}")
    async def parse_receipt_image(image_bytes: bytes):
        return None


class CareerService:
    """Service pemrosesan pesan dan logika bisnis untuk tenant BoonTrack Career."""

    @staticmethod
    def get_user_display_name(sender_wa_id: str) -> str:
        user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
        user_data = user_session.get("data", {})
        return user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""

    async def send_menu_buttons(self, sender_wa_id: str):
        """Kirim menu utama BoonTrack Career"""
        nama = self.get_user_display_name(sender_wa_id)
        greeting = f", *{nama}*" if nama else ""
        body = WELCOME_CAREER_TEMPLATE.format(greeting=greeting)

        await send_whatsapp_buttons(
            to_phone=sender_wa_id,
            body_text=body,
            buttons=CAREER_MENU_BUTTONS,
            header_text="BOONTRACK CAREER",
            footer_text="Pilih salah satu opsi di atas",
            tenant_id=TENANT_ID
        )

    async def deliver_review_and_trigger_upsell(self, sender_wa_id: str, filtered_data: dict, filename: str = "Dokumen CV"):
        """Kirim hasil audit CV dan picu penawaran upsell Premium CV Rewrite"""
        overall_score = filtered_data.get("overall_score", 0)
        breakdown_scores = filtered_data.get("breakdown_scores", {})
        findings = filtered_data.get("findings", [])

        diagnosis_msg = format_diagnosis_message(overall_score, breakdown_scores, findings)
        await send_whatsapp_text(sender_wa_id, diagnosis_msg, tenant_id=TENANT_ID)
        await track_event(sender_wa_id, "review_completed", meta={"score": overall_score, "file": filename})

        await asyncio.sleep(6)

        await send_whatsapp_buttons(
            to_phone=sender_wa_id,
            body_text=UPSELL_REWRITE_MSG,
            buttons=UPSELL_BUTTONS,
            footer_text="Pilih opsi untuk melanjutkan",
            tenant_id=TENANT_ID
        )
        await track_event(sender_wa_id, "rewrite_offer_shown")

    async def handle_image(self, sender_wa_id: str, display_name: str, media_id: Optional[str]):
        """Handler untuk pesan gambar (OCR bukti pembayaran transfer QRIS)"""
        user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})

        safe_log_to_supabase_messages(
            sender="user",
            text="[Mengirim Gambar Bukti Transfer]",
            tenant_id=TENANT_ID,
            channel="whatsapp",
            user_phone=sender_wa_id,
            user_name=display_name,
            user_id=sender_wa_id,
            conversation_id=sender_wa_id,
            metadata={"media_id": media_id, "msg_type": "image"}
        )

        if user_session.get("mode") == "awaiting_rewrite_payment":
            await send_whatsapp_text(
                sender_wa_id,
                "🔍 *Mendeteksi bukti transfer...* AI sedang memverifikasi struk pembayaran Anda. Mohon tunggu sebentar ⏳",
                tenant_id=TENANT_ID
            )

            try:
                image_bytes = await download_whatsapp_media(media_id)
                receipt_data = await parse_receipt_image(image_bytes)

                if not receipt_data or not receipt_data.get("is_transfer_receipt"):
                    await send_whatsapp_text(
                        sender_wa_id,
                        RECEIPT_INVALID_MSG,
                        tenant_id=TENANT_ID
                    )
                    return

                amount = int(receipt_data.get("amount", 0))
                active_invoice = user_session.get("active_invoice")
                target_intent = PAYMENT_INTENTS.get(active_invoice) if active_invoice else None
                base_price = target_intent.get("base_amount", 25000) if target_intent else 25000

                min_allowed = base_price
                max_allowed = base_price + 999

                if min_allowed <= amount <= max_allowed:
                    if target_intent:
                        target_intent["status"] = "PAID"
                        target_intent["paid_at"] = datetime.now()
                        target_intent["transaction_reference"] = f"OCR_VERIFIED: Rp{amount:,}"

                    user_session["is_premium_paid"] = True
                    user_session["mode"] = "post_review"

                    success_msg = (
                        f"🎉 *BUKTI TRANSFER TERVERIFIKASI!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 *Invoice:* `{active_invoice or '-'}`\n"
                        f"💰 *Nominal Terbaca:* Rp{amount:,}\n"
                        f"📊 *Status:* Sah (Masuk Rentang Rp{min_allowed:,} - Rp{max_allowed:,})\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        "Terima kasih! AI BoonTrack sedang memproses perombakan CV Anda ke standar HR Senior. Hasil akan segera dikirimkan! 🚀"
                    )
                    await send_whatsapp_text(sender_wa_id, success_msg, tenant_id=TENANT_ID)
                else:
                    await send_whatsapp_text(
                        sender_wa_id,
                        f"⚠️ Nominal transfer yang terbaca (*Rp{amount:,}*) berada di luar rentang harga paket (*Rp{min_allowed:,} - Rp{max_allowed:,}*).\n\n"
                        "Silakan cek kembali nominal transfer Anda atau hubungi admin jika terdapat kesalahan.",
                        tenant_id=TENANT_ID
                    )

            except Exception as e:
                logger.error(f"[Receipt Image OCR Error] {e}")
                await send_whatsapp_text(sender_wa_id, "⚠️ Terjadi kesalahan saat membaca gambar. Silakan coba unggah kembali.", tenant_id=TENANT_ID)

    async def handle_document(self, sender_wa_id: str, display_name: str, media_id: Optional[str], filename: str):
        """Handler untuk dokumen CV (PDF / DOCX)"""
        user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})

        safe_log_to_supabase_messages(
            sender="user",
            text=f"[Mengirim Dokumen: {filename}]",
            tenant_id=TENANT_ID,
            channel="whatsapp",
            user_phone=sender_wa_id,
            user_name=display_name,
            user_id=sender_wa_id,
            conversation_id=sender_wa_id,
            metadata={"media_id": media_id, "filename": filename, "msg_type": "document"}
        )

        await send_whatsapp_text(
            sender_wa_id,
            DOC_READING_TEMPLATE.format(filename=filename),
            tenant_id=TENANT_ID
        )

        try:
            file_bytes = await download_whatsapp_media(media_id)
            extracted_text = extract_text_from_bytes(file_bytes, filename)

            if not extracted_text or len(extracted_text) < 50:
                await send_whatsapp_text(
                    sender_wa_id,
                    DOC_UNREADABLE_MSG,
                    tenant_id=TENANT_ID
                )
                return

            user_session["parsed_cv_text"] = extracted_text
            eval_result = cv_review_engine.evaluate_cv(extracted_text, target_position="General Professional")
            filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)

            user_session["mode"] = "post_review"
            user_session["step"] = 0
            user_session.setdefault("data", {})["has_completed_cv"] = True

            asyncio.create_task(self.deliver_review_and_trigger_upsell(sender_wa_id, filtered_data, filename))

        except Exception as e:
            logger.error(f"[Upload Document Error] {e}")
            await send_whatsapp_text(
                sender_wa_id,
                DOC_ERROR_MSG,
                tenant_id=TENANT_ID
            )

    async def handle_text_or_button(self, sender_wa_id: str, display_name: str, user_text: str, button_id: str):
        """Handler untuk input teks dan klik tombol interaktif"""
        user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
        user_text_clean = (user_text or "").lower().strip()

        # Log Inbound
        if user_text:
            safe_log_to_supabase_messages(
                sender="user",
                text=user_text,
                tenant_id=TENANT_ID,
                channel="whatsapp",
                user_phone=sender_wa_id,
                user_name=display_name,
                user_id=sender_wa_id,
                conversation_id=sender_wa_id,
                metadata={"button_id": button_id, "msg_type": "interactive" if button_id else "text"}
            )

        # 1. Reset / Navigation
        if button_id == "btn_menu" or user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
            current_data = user_session.get("data", {})
            GLOBAL_USER_STATES[sender_wa_id] = {
                "step": 0,
                "mode": "menu",
                "data": current_data
            }
            await self.send_menu_buttons(sender_wa_id)
            return

        # 2. Info Unggah Bukti Struk
        if button_id == "btn_upload_receipt_info":
            await send_whatsapp_text(
                sender_wa_id,
                RECEIPT_UPLOAD_INFO_MSG,
                tenant_id=TENANT_ID
            )
            return

        # 3. Trigger Rewrite (QRIS + Kode Unik)
        if button_id == "btn_rewrite" or user_text_clean in ["rewrite", "perbaiki", "mau rewrite", "ambil rewrite", "🚀 ambil rewrite"]:
            await track_event(sender_wa_id, "rewrite_clicked")

            intent = generate_unique_payment_intent(
                tenant_id="boontrack_career",
                base_amount=25000,
                product_id="premium_cv_rewrite",
                user_id=sender_wa_id
            )

            exact_amount = intent["total_amount"]
            unique_code = intent["unique_code"]
            invoice_id = intent["invoice_id"]

            user_session["mode"] = "awaiting_rewrite_payment"
            user_session["active_invoice"] = invoice_id

            caption_text = format_invoice_caption(invoice_id, exact_amount, unique_code)

            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            asset_candidates = [
                os.path.join(base_dir, "assets", "qris.jpg"),
                os.path.join(base_dir, "assets", "qris.png"),
                os.path.join(base_dir, "assets", "qris_boontrack.png"),
                os.path.join(os.getcwd(), "assets", "qris.jpg"),
                os.path.join(os.getcwd(), "assets", "qris.png"),
            ]
            found_file = next((p for p in asset_candidates if os.path.exists(p)), None)

            if found_file:
                await send_whatsapp_image(sender_wa_id, image_path_or_bytes=found_file, caption=caption_text, tenant_id=TENANT_ID)
            else:
                await send_whatsapp_text(sender_wa_id, caption_text, tenant_id=TENANT_ID)

            await asyncio.sleep(1)

            action_buttons = [
                {"id": "btn_upload_receipt_info", "title": "📸 Kirim Bukti Struk"},
                {"id": "btn_menu", "title": "🏠 Menu Utama"}
            ]
            await send_whatsapp_buttons(
                to_phone=sender_wa_id,
                body_text="Jika ada salah transfer atau mutasi belum terdeteksi otomatis, Anda bisa mengirimkan foto screenshot bukti transfer ke chat ini.",
                buttons=action_buttons,
                footer_text="BoonTrack Payment Assistant",
                tenant_id=TENANT_ID
            )
            return

        current_mode = user_session.get("mode", "menu")

        # 4. Review Menu Button
        if button_id == "btn_review" or "review" in user_text_clean or "bedah cv" in user_text_clean or user_text_clean in ["1", "review cv", "🔍 review cv"]:
            user_session["mode"] = "review"
            await send_whatsapp_text(sender_wa_id, REVIEW_INTRO_MSG, tenant_id=TENANT_ID)
            return

        # 5. Builder Menu Button
        if button_id == "btn_builder" or (current_mode == "menu" and user_text_clean in ["2", "bikin cv", "📝 bikin cv dasar"]):
            user_session["mode"] = "builder"
            user_session["step"] = 0
            result = await process_unified_cv_step(sender_wa_id, "", platform="whatsapp")

            await send_whatsapp_buttons(
                to_phone=sender_wa_id,
                body_text=result["reply_text"],
                buttons=LANG_SELECTION_BUTTONS,
                footer_text="Klik pilihan bahasa di atas",
                tenant_id=TENANT_ID
            )
            return

        # 6. CV Builder Language Selection
        if button_id.startswith("lang_"):
            lang_choice = "1" if button_id == "lang_en_id" else ("2" if button_id == "lang_id" else "3")
            result = await process_unified_cv_step(sender_wa_id, lang_choice, platform="whatsapp")
            await send_whatsapp_text(sender_wa_id, result["reply_text"], tenant_id=TENANT_ID)
            return

        # 7. CV Builder Wizard Steps
        if current_mode == "builder" or user_session.get("step", 0) > 0:
            result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
            messages_to_send = result.get("messages", [])
            if not messages_to_send and result.get("reply_text"):
                messages_to_send = [result["reply_text"]]

            for msg in messages_to_send:
                await send_whatsapp_text(sender_wa_id, msg, tenant_id=TENANT_ID)

            if result.get("is_completed"):
                user_session["mode"] = "post_cv"
                user_session["step"] = 0
                user_session.setdefault("data", {})["has_completed_cv"] = True
            return

        # 8. Review via Manual Text Input
        if current_mode == "review":
            if len(user_text.split()) < 6:
                await send_whatsapp_text(
                    sender_wa_id,
                    TEXT_TOO_SHORT_MSG,
                    tenant_id=TENANT_ID
                )
                return

            nama = self.get_user_display_name(sender_wa_id)
            sapaan = f", *{nama}*" if nama else ""
            await send_whatsapp_text(sender_wa_id, f"⏳ *Sedang menganalisis struktur & skor ATS CV kamu{sapaan}...*", tenant_id=TENANT_ID)
            try:
                user_session["parsed_cv_text"] = user_text
                eval_result = cv_review_engine.evaluate_cv(user_text, target_position="General Professional")
                filtered_data = cv_review_service.filter_entitlement_response(eval_result, is_premium=False)

                user_session["step"] = 0
                user_session["mode"] = "post_review"
                user_session.setdefault("data", {})["has_completed_cv"] = True

                asyncio.create_task(self.deliver_review_and_trigger_upsell(sender_wa_id, filtered_data, "Manual Text Input"))
            except Exception as e:
                logger.error(f"[WA Review Error] {e}")
                await send_whatsapp_text(sender_wa_id, "⚠️ Gagal menganalisis teks CV.", tenant_id=TENANT_ID)
            return

        # 9. Fallback AI Consultation
        ai_reply = await ai_gateway.generate(
            user_message=user_text,
            context={"user_id": sender_wa_id, "feature": "career_consultation"}
        )
        if ai_reply:
            await send_whatsapp_text(sender_wa_id, ai_reply, tenant_id=TENANT_ID)
        else:
            await self.send_menu_buttons(sender_wa_id)


career_service = CareerService()
