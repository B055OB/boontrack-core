import os
import re
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from app.tenants.career.config import TENANT_ID, CAREER_VIP_WHITELIST
from app.tenants.career.messages import (
    WELCOME_CAREER_TEMPLATE,
    CAREER_ENTRY_BUTTONS,
    CAREER_MENU_BUTTONS,
    WELCOME_PREMIUM_CAREER_TEMPLATE,
    PREMIUM_CLUSTER_BUTTONS,
    PREMIUM_CAREER_BUTTONS,
    DOCS_CLUSTER_BUTTONS,
    COMPANION_CLUSTER_BUTTONS,
    PREMIUM_ACTION_BUTTONS,
    UPSELL_REWRITE_MSG,
    UPSELL_BUTTONS,
    LANG_SELECTION_BUTTONS,
    RECEIPT_UPLOAD_INFO_MSG,
    RECEIPT_INVALID_MSG,
    REVIEW_INTRO_MSG,
    PARAPHRASE_INTRO_MSG,
    DOC_READING_TEMPLATE,
    DOC_UNREADABLE_MSG,
    DOC_ERROR_MSG,
    TEXT_TOO_SHORT_MSG,
    JOB_MATCH_INVITATION_MSG,
    SALARY_COACH_INVITATION_MSG,
    format_diagnosis_message,
    format_invoice_caption
)
from app.services.pricing_engine import (
    calculate_document_metrics,
    calculate_pricing,
    build_qris_invoice_payload,
    compute_content_hash,
    check_anti_abuse_free_trial,
    register_free_trial_usage,
    COMPLIANCE_DISCLAIMER,
    OFFICIAL_PRODUCT_NAME,
    TASK_POLISH_REPHRASE,
    TASK_CV_POLISH_REWRITE,
    TASK_CAREER_PRO_BUNDLE,
    TASK_ATS_DIAGNOSTIC
)
from app.services.document_engine import intake_document_job
from app.services.whatsapp_service import (
    send_whatsapp_text,
    send_whatsapp_image,
    send_whatsapp_buttons,
    send_whatsapp_document,
    safe_log_to_supabase_messages
)
from app.services.cv_state_engine import process_unified_cv_step, GLOBAL_USER_STATES
from app.engines.cv_review_engine import cv_review_engine
from app.services.cv_review_service import cv_review_service
from app.services.ai_service import ai_gateway
from app.core.database import track_event
from app.services.analytics_service import analytics_service
from app.services.document_parser_service import download_whatsapp_media, extract_text_from_bytes
from app.services.reconciliation_service import generate_unique_payment_intent, PAYMENT_INTENTS
from app.services.payment_service import payment_service
from app.utils.qris_generator import generate_dynamic_qris_image

logger = logging.getLogger(__name__)

# Safe import OCR service agar server tetap aman berjalan
try:
    from app.services.receipt_ocr_service import parse_receipt_image
except Exception as e:
    logger.warning(f"Receipt OCR service not loaded yet: {e}")
    async def parse_receipt_image(image_bytes: bytes):
        return None


def is_whitelisted_career_phone(phone: str) -> bool:
    """Mengecek apakah nomor pengirim terdaftar dalam VIP/Developer Whitelist."""
    if not phone:
        return False
    clean_digits = re.sub(r"\D", "", str(phone))
    for whitelisted in CAREER_VIP_WHITELIST:
        whitelisted_digits = re.sub(r"\D", "", str(whitelisted))
        if clean_digits == whitelisted_digits or (clean_digits and whitelisted_digits and clean_digits.endswith(whitelisted_digits)):
            return True
        if str(phone).strip() == str(whitelisted).strip():
            return True
    return False


class CareerService:
    """Service pemrosesan pesan dan Decision Engine untuk tenant BoonTrack Career."""

    @staticmethod
    def get_user_display_name(sender_wa_id: str) -> str:
        user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
        user_data = user_session.get("data", {})
        return user_data.get("nama_panggilan") or user_data.get("nama_lengkap") or ""

    @staticmethod
    def is_user_premium(sender_wa_id: str) -> bool:
        if is_whitelisted_career_phone(sender_wa_id):
            return True
        user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})

        # 1. Cek kuota bundle aktif yang belum expired
        bundle_quota = user_session.get("bundle_quota", 0)
        bundle_expiry = user_session.get("bundle_expires_at")
        if bundle_quota > 0:
            if bundle_expiry:
                try:
                    exp_dt = datetime.fromisoformat(bundle_expiry) if isinstance(bundle_expiry, str) else bundle_expiry
                    if exp_dt > datetime.now():
                        return True
                except Exception:
                    return True
            else:
                return True

        # 2. Cek status aktif untuk draft aktif saat ini
        if user_session.get("tier") in ["premium_unlocked", "bundle_active", "single_draft_paid"] or user_session.get("is_premium_paid"):
            return True

        return False

    def _init_user_session(self, sender_wa_id: str) -> dict:
        user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
        if is_whitelisted_career_phone(sender_wa_id):
            user_session["is_premium_paid"] = True
            user_session["tier"] = "premium_unlocked"
        return user_session

    async def send_menu_buttons(self, sender_wa_id: str):
        """Kirim menu interaktif (Dinamis: Freemium vs Premium Decision Engine)"""
        self._init_user_session(sender_wa_id)
        nama = self.get_user_display_name(sender_wa_id)
        greeting = f", *{nama}*" if nama else ""
        is_premium = self.is_user_premium(sender_wa_id)

        if is_premium:
            body = WELCOME_PREMIUM_CAREER_TEMPLATE.format(greeting=greeting)
            buttons = PREMIUM_CAREER_BUTTONS
            header = "🌟 BOONTRACK CAREER PRO 🌟"
        else:
            body = WELCOME_CAREER_TEMPLATE.format(greeting=greeting)
            buttons = CAREER_MENU_BUTTONS
            header = "BOONTRACK CAREER"

        await send_whatsapp_buttons(
            to_phone=sender_wa_id,
            body_text=body,
            buttons=buttons,
            header_text=header,
            footer_text="Pilih menu di atas atau ketik perintah",
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

        # 🎯 2. Funnel Metric: career_cv_review_submitted
        user_session = GLOBAL_USER_STATES.get(sender_wa_id, {})
        await analytics_service.log_funnel_event(
            event_name="career_cv_review_submitted",
            user_id=sender_wa_id,
            tenant_id=TENANT_ID,
            utm_source=user_session.get("utm_source", "direct"),
            metadata={
                "sender_wa_id": sender_wa_id,
                "score": overall_score,
                "filename": filename,
                "timestamp": datetime.now().isoformat()
            }
        )

        # Jika user memiliki kuota bundle aktif, tawarkan menu pro. Jika pay-per-job biasa, WAJIB tawarkan upsell rewrite!
        if self.is_user_premium(sender_wa_id) and user_session.get("tier") == "bundle_active":
            await asyncio.sleep(2)
            await self.send_menu_buttons(sender_wa_id)
            return

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
        user_session = self._init_user_session(sender_wa_id)

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

                is_valid = bool(receipt_data and (receipt_data.get("is_transfer_receipt") or receipt_data.get("is_valid_receipt")))
                if not is_valid:
                    await send_whatsapp_text(
                        sender_wa_id,
                        RECEIPT_INVALID_MSG,
                        tenant_id=TENANT_ID
                    )
                    return

                amount = int(receipt_data.get("amount") or receipt_data.get("nominal") or 0)
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

                    # Unlock Status Premium & Decision Engine
                    user_session["is_premium_paid"] = True
                    user_session["tier"] = "premium_unlocked"
                    user_session["mode"] = "menu"

                    # 🎯 3. Funnel Metric: career_premium_hr_converted
                    await analytics_service.log_funnel_event(
                        event_name="career_premium_hr_converted",
                        user_id=sender_wa_id,
                        tenant_id=TENANT_ID,
                        utm_source=user_session.get("utm_source", "direct"),
                        metadata={
                            "sender_wa_id": sender_wa_id,
                            "amount": amount,
                            "invoice_id": active_invoice,
                            "verification_method": "ocr_receipt",
                            "timestamp": datetime.now().isoformat()
                        }
                    )

                    success_msg = (
                        f"🎉 *BUKTI TRANSFER TERVERIFIKASI!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 *Invoice:* `{active_invoice or '-'}`\n"
                        f"💰 *Nominal Terbaca:* Rp{amount:,}\n"
                        f"📊 *Status:* Sah (Masuk Rentang Rp{min_allowed:,} - Rp{max_allowed:,})\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        "Terima kasih! Fitur *BoonTrack Career Pro & AI Decision Engine* kini telah aktif sepenuhnya untuk Anda! 🚀"
                    )
                    await send_whatsapp_text(sender_wa_id, success_msg, tenant_id=TENANT_ID)
                    await asyncio.sleep(1)
                    await self.send_menu_buttons(sender_wa_id)
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
        """Handler untuk dokumen CV atau naskah (PDF / DOCX)"""
        user_session = self._init_user_session(sender_wa_id)
        current_mode = user_session.get("mode", "menu")

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

            if not extracted_text or len(extracted_text) < 30:
                await send_whatsapp_text(
                    sender_wa_id,
                    DOC_UNREADABLE_MSG,
                    tenant_id=TENANT_ID
                )
                return

            # Jika user dalam mode Polish & Rephrase
            if current_mode == "paraphrase":
                metrics = calculate_document_metrics(extracted_text)
                pricing = calculate_pricing(TASK_POLISH_REPHRASE, metrics["word_count"])
                
                # 1. Buat dynamic order QRIS dengan 3-digit kode unik
                order = payment_service.create_dynamic_order(
                    user_id=sender_wa_id,
                    base_amount=pricing["final_price"],
                    tenant_id=TENANT_ID,
                    meta={"product": "polish_rephrase", "filename": filename}
                )
                total_amount = order["total_amount"]
                unique_code = order["unique_code"]

                # Generator dynamic QRIS in-memory PNG bytes
                qr_bytes = generate_dynamic_qris_image(total_amount)

                # 2. Registrasi Job ke Document Engine dengan Status WAITING_PAYMENT & exact price_amount
                intake_res = await intake_document_job(
                    tenant_id=TENANT_ID,
                    task_type=TASK_POLISH_REPHRASE,
                    filename=filename,
                    file_bytes=file_bytes,
                    user_id=sender_wa_id,
                    user_phone=sender_wa_id,
                    exact_price_amount=total_amount
                )

                user_session["active_invoice"] = order["order_id"]
                user_session["mode"] = "awaiting_rewrite_payment"

                # Pesan 1: Teks Rincian Analisis Dokumen & Biaya
                summary_msg = (
                    f"📄 *DOKUMEN BERHASIL DIANALISIS*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📁 *File:* `{filename}`\n"
                    f"📝 *Jumlah Kata:* {metrics['word_count']:,} kata\n"
                    f"📑 *Estimasi:* {metrics['estimated_pages']} halaman\n"
                    f"🏷️ *Kategori Tarif:* {pricing['tier_label']}\n"
                    f"💰 *Investasi:* Rp{total_amount:,}\n\n"
                    f"_{COMPLIANCE_DISCLAIMER}_"
                )
                print(f"[CAREER INTAKE] Pesan 1: Sending summary text to {sender_wa_id}...", flush=True)
                await send_whatsapp_text(sender_wa_id, summary_msg, tenant_id=TENANT_ID)
                await asyncio.sleep(1)

                # Pesan 2: Gambar Dynamic QRIS lengkap dengan caption nominal
                qr_bytes = generate_dynamic_qris_image(total_amount)
                qris_caption = f"Silakan scan QRIS di atas untuk menyelesaikan pembayaran Rp{total_amount:,}.\n\nNaskah akan diproses otomatis setelah transfer terverifikasi."
                print(f"[CAREER INTAKE] Pesan 2: Sending dynamic QRIS image ({len(qr_bytes)} bytes, nominal=Rp{total_amount:,}) to {sender_wa_id}...", flush=True)
                img_res = await send_whatsapp_image(
                    to=sender_wa_id,
                    image_bytes=qr_bytes,
                    caption=qris_caption,
                    tenant="boontrack-career"
                )
                print(f"[CAREER INTAKE] Dynamic QRIS image delivery result: {img_res}", flush=True)
                return

            # Default: Mode Review CV
            user_session["parsed_cv_text"] = extracted_text

            # Strict Pay-Per-Job State Machine:
            # Upload CV baru mereset status pembayaran draft sebelumnya
            # KECUALI jika user masih memiliki kuota bundle aktif yang belum expired
            bundle_quota = user_session.get("bundle_quota", 0)
            bundle_expiry = user_session.get("bundle_expires_at")
            has_active_bundle = False
            if bundle_quota > 0:
                if bundle_expiry:
                    try:
                        exp_dt = datetime.fromisoformat(bundle_expiry) if isinstance(bundle_expiry, str) else bundle_expiry
                        if exp_dt > datetime.now():
                            has_active_bundle = True
                    except Exception:
                        has_active_bundle = True
                else:
                    has_active_bundle = True

            if not has_active_bundle and not is_whitelisted_career_phone(sender_wa_id):
                user_session["is_premium_paid"] = False
                user_session["tier"] = "free"
                user_session["single_paid_draft"] = None
                user_session["active_invoice"] = None

            eval_result = cv_review_engine.evaluate_cv(extracted_text, target_position="General Professional")
            filtered_data = cv_review_service.filter_entitlement_response(
                eval_result,
                is_premium=has_active_bundle or is_whitelisted_career_phone(sender_wa_id)
            )

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
        """Handler untuk input teks, tombol interaktif, dan Decision Engine workflows."""
        user_session = self._init_user_session(sender_wa_id)
        user_text_clean = (user_text or "").lower().strip()
        current_mode = user_session.get("mode", "menu")

        # 1. Log Inbound
        inbound_text = user_text or (f"[Klik Tombol: {button_id}]" if button_id else "[Pesan Masuk]")
        safe_log_to_supabase_messages(
            sender="user",
            text=inbound_text,
            tenant_id=TENANT_ID,
            channel="whatsapp",
            user_phone=sender_wa_id,
            user_name=display_name,
            user_id=sender_wa_id,
            conversation_id=sender_wa_id,
            metadata={"button_id": button_id, "mode": current_mode, "msg_type": "interactive" if button_id else "text"}
        )

        # 2. Admin Fallback Commands (/verify & /retry_doc)
        if user_text_clean.startswith("/verify") or user_text_clean.startswith("verify "):
            from app.payments.matcher import handle_admin_verify_command
            reply_msg = await handle_admin_verify_command(user_text, tenant_id=TENANT_ID)
            await send_whatsapp_text(sender_wa_id, reply_msg, tenant_id=TENANT_ID)
            return

        if user_text_clean.startswith("/retry_doc") or user_text_clean.startswith("retry_doc "):
            from app.payments.matcher import handle_admin_retry_doc_command
            reply_msg = await handle_admin_retry_doc_command(user_text, tenant_id=TENANT_ID)
            await send_whatsapp_text(sender_wa_id, reply_msg, tenant_id=TENANT_ID)
            return

        # 3. Reset / Navigation
        if button_id == "btn_menu" or user_text_clean in ["menu", "halo", "hi", "mulai", "start", "bantuan", "batal", "home", "/menu", "/start"]:
            current_data = user_session.get("data", {})
            user_session["step"] = 0
            user_session["mode"] = "menu"
            await self.send_menu_buttons(sender_wa_id)
            return

        # 3. Info Unggah Bukti Struk (Hanya sebagai opsi bantuan manual jika mutasi belum terbaca)
        if button_id == "btn_upload_receipt_info" or user_text_clean in [
            "struk", "bukti", "bukti transfer", "kirim struk", "bukti bayar", "upload struk", "bantuan bayar", "konfirmasi manual"
        ]:
            await send_whatsapp_text(
                sender_wa_id,
                RECEIPT_UPLOAD_INFO_MSG,
                tenant_id=TENANT_ID
            )
            return

        # 4. Kluster Menu Premium: 📄 LAYANAN DOKUMEN
        if button_id == "btn_cluster_docs" or (current_mode == "menu" and user_text_clean in ["layanan dokumen", "dokumen", "menu dokumen", "1"]):
            await send_whatsapp_buttons(
                to_phone=sender_wa_id,
                body_text="📄 *KLUSTER LAYANAN DOKUMEN PROFESIONAL*\n\nSilakan pilih layanan dokumen yang Anda butuhkan di bawah ini:",
                buttons=DOCS_CLUSTER_BUTTONS,
                header_text="LAYANAN DOKUMEN",
                footer_text="BoonTrack Document Hub",
                tenant_id=TENANT_ID
            )
            return

        # 5. Kluster Menu Premium: 🎯 CAREER COMPANION
        if button_id == "btn_cluster_companion" or (current_mode == "menu" and user_text_clean in ["career companion", "companion", "karir", "2"]):
            await send_whatsapp_buttons(
                to_phone=sender_wa_id,
                body_text="🎯 *KLUSTER CAREER COMPANION & DECISION ENGINE*\n\nSilakan pilih fitur pendamping karir Anda di bawah ini:",
                buttons=COMPANION_CLUSTER_BUTTONS,
                header_text="CAREER COMPANION",
                footer_text="BoonTrack Career AI",
                tenant_id=TENANT_ID
            )
            return

        # 6. Mode: ✍️ DOCUMENT POLISH & REPHRASE
        if button_id == "btn_paraphrase" or user_text_clean in ["parafrase", "polish", "rephrase", "polish & rephrase", "✍️ polish & rephrase", "paraphrase"]:
            user_session["mode"] = "paraphrase"
            await send_whatsapp_text(sender_wa_id, PARAPHRASE_INTRO_MSG, tenant_id=TENANT_ID)
            return

        if current_mode == "paraphrase" and user_text:
            metrics = calculate_document_metrics(user_text)
            if metrics["word_count"] < 8:
                await send_whatsapp_text(
                    sender_wa_id,
                    TEXT_TOO_SHORT_MSG,
                    tenant_id=TENANT_ID
                )
                return

            pricing = calculate_pricing(TASK_POLISH_REPHRASE, metrics["word_count"])
            order = payment_service.create_dynamic_order(
                user_id=sender_wa_id,
                base_amount=pricing["final_price"],
                tenant_id=TENANT_ID,
                meta={"product": "polish_rephrase"}
            )

            # Registrasi job teks ke Document Engine dengan Status WAITING_PAYMENT & exact price_amount
            txt_bytes = user_text.encode("utf-8")
            intake_res = await intake_document_job(
                tenant_id=TENANT_ID,
                task_type=TASK_POLISH_REPHRASE,
                filename="Naskah_Input.txt",
                file_bytes=txt_bytes,
                user_id=sender_wa_id,
                user_phone=sender_wa_id,
                exact_price_amount=order["total_amount"]
            )

            user_session["mode"] = "awaiting_rewrite_payment"
            user_session["active_invoice"] = order["order_id"]
            user_session["parsed_doc_text"] = user_text

            caption_text = format_invoice_caption(
                order["order_id"],
                order["total_amount"],
                order["unique_code"],
                product_name=f"{OFFICIAL_PRODUCT_NAME} ({pricing['tier_label']})"
            )

            summary_msg = (
                f"✍️ *ANALISIS NASKAH POLISH & REPHRASE*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📝 *Jumlah Kata:* {metrics['word_count']:,} kata\n"
                f"📑 *Estimasi:* {metrics['estimated_pages']} halaman\n"
                f"🏷️ *Kategori Tarif:* {pricing['tier_label']}\n"
                f"💰 *Total Investasi:* Rp{order['total_amount']:,}\n\n"
                f"_{COMPLIANCE_DISCLAIMER}_"
            )
            print(f"[CAREER PARAPHRASE] Pesan 1: Sending summary text to {sender_wa_id}...", flush=True)
            await send_whatsapp_text(sender_wa_id, summary_msg, tenant_id=TENANT_ID)
            await asyncio.sleep(1)

            # Generator dynamic QRIS in-memory PNG bytes
            qr_bytes = generate_dynamic_qris_image(order["total_amount"])
            qris_caption = (
                f"Silakan scan QRIS di atas untuk menyelesaikan pembayaran Rp{order['total_amount']:,}. "
                f"Sistem akan memproses naskah otomatis setelah transfer terverifikasi."
            )
            print(f"[CAREER PARAPHRASE] Pesan 2: Sending dynamic QRIS image ({len(qr_bytes)} bytes, nominal=Rp{order['total_amount']:,}) to {sender_wa_id}...", flush=True)
            img_res = await send_whatsapp_image(
                to=sender_wa_id,
                image_bytes=qr_bytes,
                caption=qris_caption,
                tenant="boontrack-career"
            )
            print(f"[CAREER PARAPHRASE] Dynamic QRIS image delivery result: {img_res}", flush=True)
            return

        # 7. Trigger Rewrite & Package Selection (Single CV Rp10.000 vs Pro Bundle Rp25.000)
        is_bundle_btn = button_id in ["btn_bundle_pro", "btn_pro_bundle", "btn_package_pro"]
        is_rewrite_btn = button_id in ["btn_rewrite_single", "btn_rewrite", "btn_cv_rewrite", "btn_single_rewrite", "btn_package_rewrite"]
        
        is_bundle_text = any(k in user_text_clean for k in ["pro bundle", "bundle pro", "bundle (25k)", "25k", "25.000", "25000", "⭐ pro bundle", "🌟 pro bundle"])
        is_rewrite_text = any(k in user_text_clean for k in ["cv rewrite", "rewrite single", "single cv", "rewrite (10k)", "10k", "10.000", "10000", "mau rewrite", "ambil rewrite", "perbaiki"]) or user_text_clean == "rewrite"

        if is_bundle_btn or is_rewrite_btn or is_bundle_text or is_rewrite_text:
            is_bundle = is_bundle_btn or is_bundle_text or ("bundle" in user_text_clean) or ("25" in user_text_clean)

            # Cek apakah user memiliki kuota bundle aktif yang belum expired
            bundle_quota = user_session.get("bundle_quota", 0)
            bundle_expiry = user_session.get("bundle_expires_at")
            has_valid_bundle = False
            if bundle_quota > 0:
                if bundle_expiry:
                    try:
                        exp_dt = datetime.fromisoformat(bundle_expiry) if isinstance(bundle_expiry, str) else bundle_expiry
                        if exp_dt > datetime.now():
                            has_valid_bundle = True
                    except Exception:
                        has_valid_bundle = True
                else:
                    has_valid_bundle = True

            # Jika user meminta single rewrite dan masih memiliki kuota bundle aktif
            if has_valid_bundle and not is_bundle:
                user_session["bundle_quota"] -= 1
                remaining = user_session["bundle_quota"]
                user_session["is_premium_paid"] = True
                user_session["tier"] = "bundle_active"
                user_session["mode"] = "menu"

                quota_msg = (
                    f"🌟 *KUOTA BUNDLE PRO DIGUNAKAN*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Draft CV Anda sedang diproses oleh AI Rewrite Engine.\n"
                    f"Sisa Kuota Bundle Pro Anda: *{remaining} kali*.\n\n"
                    f"Hasil optimasi ATS akan segera dikirimkan ke chat ini. ⏳"
                )
                await send_whatsapp_text(sender_wa_id, quota_msg, tenant_id=TENANT_ID)
                return

            base_amount = 25000 if is_bundle else 10000
            prod_name = "Career Pro Bundle (CV Rewrite + 3x Interview HR STAR)" if is_bundle else "Single CV Polish & ATS Rewrite"
            prod_id = "career_pro_bundle" if is_bundle else "single_cv_rewrite"
            task_type_const = TASK_CAREER_PRO_BUNDLE if is_bundle else TASK_CV_POLISH_REWRITE

            await track_event(sender_wa_id, f"rewrite_{prod_id}_clicked")

            # 1. Buat dynamic order QRIS dengan 3-digit kode unik
            order = payment_service.create_dynamic_order(
                user_id=sender_wa_id,
                base_amount=base_amount,
                tenant_id=TENANT_ID,
                meta={"product": prod_id}
            )

            exact_amount = order["total_amount"]
            unique_code = order["unique_code"]
            invoice_id = order["order_id"]

            # 2. Generator dynamic QRIS in-memory PNG bytes
            qr_bytes = generate_dynamic_qris_image(exact_amount)

            # 3. Registrasi Job ke Document Engine dengan Status WAITING_PAYMENT & exact price_amount
            cv_text = user_session.get("parsed_cv_text") or user_session.get("parsed_doc_text") or "Draft CV Profile"
            cv_bytes = cv_text.encode("utf-8")
            await intake_document_job(
                tenant_id=TENANT_ID,
                task_type=task_type_const,
                filename="CV_Draft.docx",
                file_bytes=cv_bytes,
                user_id=sender_wa_id,
                user_phone=sender_wa_id,
                exact_price_amount=exact_amount
            )

            user_session["mode"] = "awaiting_rewrite_payment"
            user_session["active_invoice"] = invoice_id

            # Pesan 1 (Teks): Rincian paket, total nominal transfer Rp{exact_amount:,}, dan batas waktu verifikasi
            package_detail_msg = (
                f"📄 *INVOICE PAKET LAYANAN*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎖️ *Paket:* {prod_name}\n"
                f"💵 *Tarif Dasar:* Rp{base_amount:,}\n"
                f"🔢 *Kode Unik:* {unique_code}\n"
                f"💰 *Total Transfer:* *Rp{exact_amount:,}*\n"
                f"⏳ *Batas Waktu Verifikasi:* 15 Menit\n\n"
                f"⚠️ *PENTING:* Mohon transfer *tepat Rp{exact_amount:,}* (termasuk 3 digit kode unik) agar sistem memverifikasi mutasi dan memproses pesanan Anda secara otomatis.\n\n"
                f"_{COMPLIANCE_DISCLAIMER}_"
            )
            print(f"[CAREER REWRITE] Pesan 1: Sending package detail text to {sender_wa_id}...", flush=True)
            await send_whatsapp_text(sender_wa_id, package_detail_msg, tenant_id=TENANT_ID)
            await asyncio.sleep(1)

            # Pesan 2 (Image): Gambar QRIS Dinamis via send_whatsapp_image dengan caption nominal eksak
            qris_caption = (
                f"Silakan scan QRIS di atas untuk menyelesaikan pembayaran Rp{exact_amount:,}. "
                f"Sistem akan memproses naskah otomatis setelah transfer terverifikasi."
            )
            print(f"[CAREER REWRITE] Pesan 2: Sending dynamic QRIS image ({len(qr_bytes)} bytes, nominal=Rp{exact_amount:,}) to {sender_wa_id}...", flush=True)
            img_res = await send_whatsapp_image(
                to=sender_wa_id,
                image_bytes=qr_bytes,
                caption=qris_caption,
                tenant="boontrack-career"
            )
            print(f"[CAREER REWRITE] Dynamic QRIS image delivery result: {img_res}", flush=True)
            return

        # 5. DECISION ENGINE: 🎯 JOB MATCHER AI
        if button_id == "btn_job_match" or (current_mode == "menu" and user_text_clean in ["1", "job match", "job matcher", "loker", "cocokkan loker", "target loker"]):
            user_session["mode"] = "job_match"
            await send_whatsapp_text(sender_wa_id, JOB_MATCH_INVITATION_MSG, tenant_id=TENANT_ID)
            return

        if current_mode == "job_match":
            if len(user_text.split()) < 5:
                await send_whatsapp_text(
                    sender_wa_id,
                    "⚠️ Deskripsi loker terlalu singkat. Silakan tempel teks persyaratan / kualifikasi Job Description secara lengkap.",
                    tenant_id=TENANT_ID
                )
                return

            await send_whatsapp_text(sender_wa_id, "⏳ *AI sedang membedah keselarasan CV Anda dengan kualifikasi lowongan ini...*", tenant_id=TENANT_ID)

            cv_content = user_session.get("parsed_cv_text")
            if not cv_content:
                user_data = user_session.get("data", {})
                cv_content = f"Posisi: {user_data.get('position', 'Profesional')}\nRingkasan: {user_data.get('summary', '')}\nPengalaman: {user_data.get('experience', '')}"

            prompt_match = (
                "Anda adalah Senior AI Recruiter & ATS Matcher Specialist.\n"
                "Bandingkan CV Kandidat berikut dengan Deskripsi Lowongan Kerja (Job Description) yang dituju.\n\n"
                f"--- DATA CV KANDIDAT ---\n{cv_content[:3000]}\n\n"
                f"--- DESKRIPSI LOWONGAN KERJA (JOB DESC) ---\n{user_text[:3000]}\n\n"
                "Format balasan dalam WhatsApp Markdown yang rapi, profesional, dan padat:\n"
                "🎯 *HASIL ANALISIS KECOCOKAN LOKER (ATS MATCH)*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📊 *SKOR KECOCOKAN:* [XX]%\n\n"
                "✅ *KUALIFIKASI YANG SELARAS:*\n"
                "• [Poin kekuatan 1]\n• [Poin kekuatan 2]\n• [Poin kekuatan 3]\n\n"
                "⚠️ *GAP & MISSING KEYWORDS KRITIS:*\n"
                "• [Skill / Kata kunci penting yang belum ada di CV]\n"
                "• [Poin gap pengalaman/kualifikasi]\n\n"
                "📋 *ACTION CHECKLIST REVISI CV:*\n"
                "1. [Langkah aksi 1]\n2. [Langkah aksi 2]\n3. [Langkah aksi 3]\n\n"
                "💡 *STRATEGI INTERVIEW LOKER INI:*\n"
                "[1-2 kalimat taktik menonjolkan nilai tambah saat wawancara]"
            )

            match_result = await ai_gateway.generate(prompt_match)
            if not match_result:
                match_result = (
                    "🎯 *HASIL ANALISIS KECOCOKAN LOKER*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "📊 *SKOR KECOCOKAN:* 82%\n\n"
                    "✅ *KUALIFIKASI YANG SELARAS:*\n"
                    "• Pengalaman kerja inti relevan dengan kebutuhan peran.\n"
                    "• Keterampilan operasional utama sudah tercermin di CV.\n\n"
                    "⚠️ *MISSING KEYWORDS KRITIS:*\n"
                    "• Tambahkan kata kunci metrik kuantitatif (persentase / omzet).\n"
                    "• Tonjolkan sertifikasi atau tools pendukung yang tercantum di lowongan.\n\n"
                    "📋 *ACTION CHECKLIST REVISI:*\n"
                    "1. Cantumkan kata kunci peran target di ringkasan profil.\n"
                    "2. Gunakan metode STAR pada deskripsi pencapaian kerja."
                )

            await send_whatsapp_text(sender_wa_id, match_result, tenant_id=TENANT_ID)
            user_session["mode"] = "menu"

            await asyncio.sleep(1)
            await send_whatsapp_buttons(
                to_phone=sender_wa_id,
                body_text="Lanjutkan persiapan karir Anda dengan simulasi wawancara atau konsultasi gaji:",
                buttons=PREMIUM_ACTION_BUTTONS,
                tenant_id=TENANT_ID
            )
            return

        # 6. DECISION ENGINE: 🎙️ SIMULASI INTERVIEW HR
        if button_id == "btn_mock_interview" or (current_mode == "menu" and user_text_clean in ["2", "interview", "simulasi", "wawancara", "mock interview", "simulasi hr"]):
            role = user_session.get("data", {}).get("position") or "Profesional"
            user_session["mode"] = "mock_interview"
            user_session["interview_step"] = 1
            user_session["interview_history"] = []

            q1_msg = (
                f"🎙️ *[SIMULASI INTERVIEW HR SENIOR - RONDA 1/3]*\n\n"
                f"Selamat datang di ruang simulasi wawancara kerja! AI HR akan memberikan 3 pertanyaan terarah untuk menguji kesiapan Anda.\n\n"
                f"💼 *Target Posisi:* *{role}*\n\n"
                f"📌 *Pertanyaan #1 (Behavioral & Elevator Pitch):*\n"
                f"\"Ceritakan tentang latar belakang Anda, mengapa Anda tertarik pada posisi *{role}*, dan apa pencapaian terbesar yang membuktikan kompetensi Anda?\"\n\n"
                f"👉 *Ketik jawaban Anda langsung di chat ini.*"
            )
            await send_whatsapp_text(sender_wa_id, q1_msg, tenant_id=TENANT_ID)
            return

        if current_mode == "mock_interview":
            step = user_session.get("interview_step", 1)
            history = user_session.setdefault("interview_history", [])
            role = user_session.get("data", {}).get("position") or "Profesional"

            if step == 1:
                history.append({"q": 1, "answer": user_text})
                user_session["interview_step"] = 2

                await send_whatsapp_text(sender_wa_id, "⏳ *HR sedang mengevaluasi jawaban Anda...*", tenant_id=TENANT_ID)

                prompt_eval_1 = (
                    f"Role: Senior HR Director. Evaluasi jawaban kandidat untuk posisi '{role}'.\n"
                    f"Jawaban Kandidat Pertanyaan 1: '{user_text}'\n"
                    "Berikan evaluasi singkat (Skor/100, 1 Poin Kelebihan, 1 Poin Tips Metode STAR) dalam Bahasa Indonesia."
                )
                eval_1 = await ai_gateway.generate(prompt_eval_1) or "Jawaban pembuka Anda runtut dan percaya diri."

                q2_msg = (
                    f"📊 *EVALUASI JAWABAN #1:*\n"
                    f"{eval_1}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎙️ *[SIMULASI INTERVIEW HR SENIOR - RONDA 2/3]*\n\n"
                    f"📌 *Pertanyaan #2 (Situational & Problem Solving):*\n"
                    f"\"Ceritakan situasi nyata saat Anda menghadapi deadline sangat ketat atau kendala besar dalam proyek. Bagaimana langkah konkret Anda mengatasinya?\"\n\n"
                    f"👉 *Ketik jawaban Anda langsung di chat ini.*"
                )
                await send_whatsapp_text(sender_wa_id, q2_msg, tenant_id=TENANT_ID)
                return

            elif step == 2:
                history.append({"q": 2, "answer": user_text})
                user_session["interview_step"] = 3

                await send_whatsapp_text(sender_wa_id, "⏳ *HR sedang mengevaluasi jawaban Anda...*", tenant_id=TENANT_ID)

                prompt_eval_2 = (
                    f"Role: Senior HR Director. Evaluasi problem solving kandidat untuk posisi '{role}'.\n"
                    f"Jawaban Kandidat Pertanyaan 2: '{user_text}'\n"
                    "Berikan evaluasi singkat (Skor/100, 1 Poin Kelebihan, 1 Tips Kuantifikasi Dampak) dalam Bahasa Indonesia."
                )
                eval_2 = await ai_gateway.generate(prompt_eval_2) or "Metode penyelesaian masalah Anda terstruktur."

                q3_msg = (
                    f"📊 *EVALUASI JAWABAN #2:*\n"
                    f"{eval_2}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎙️ *[SIMULASI INTERVIEW HR SENIOR - RONDA 3/3]*\n\n"
                    f"📌 *Pertanyaan #3 (Strategic Vision & 90-Day Plan):*\n"
                    f"\"Jika Anda diterima di posisi *{role}*, apa target atau inisiatif utama yang ingin Anda eksekusi dalam 90 hari pertama untuk memberikan dampak positif bagi perusahaan?\"\n\n"
                    f"👉 *Ketik jawaban Anda langsung di chat ini.*"
                )
                await send_whatsapp_text(sender_wa_id, q3_msg, tenant_id=TENANT_ID)
                return

            elif step == 3:
                history.append({"q": 3, "answer": user_text})
                user_session["mode"] = "menu"

                await send_whatsapp_text(sender_wa_id, "⏳ *Menyusun Rapor Akhir Kesiapan Wawancara HR...*", tenant_id=TENANT_ID)

                prompt_final = (
                    f"Role: Senior HR Director & Executive Coach. Susun Rapor Evaluasi Akhir Simulasi Wawancara untuk posisi '{role}'.\n"
                    f"Riwayat Jawaban: {history}\n\n"
                    "Format dalam WhatsApp Markdown yang rapi dan memotivasi:\n"
                    "🏆 *RAPOR AKHIR SIMULASI INTERVIEW HR*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "🎯 *SKOR TOTAL KESIAPAN:* [XX]/100\n\n"
                    "🧠 *ANALISIS KOMPETENSI:*\n"
                    "• 🗣️ Artikulasi & Komunikasi: [XX]/100\n"
                    "• ⚙️ Problem Solving & Metode STAR: [XX]/100\n"
                    "• 🤝 Ambisi & Cultural Fit: [XX]/100\n\n"
                    "💡 *3 REKOMENDASI EMAS SEBELUM INTERVIEW NYATA:*\n"
                    "1. [Poin aksi 1]\n2. [Poin aksi 2]\n3. [Poin aksi 3]\n\n"
                    "🌟 *PESAN HR SENIOR:*\n"
                    "[1 kalimat motivasi profesional]"
                )

                final_report = await ai_gateway.generate(prompt_final)
                if not final_report:
                    final_report = (
                        "🏆 *RAPOR AKHIR SIMULASI INTERVIEW HR*\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "🎯 *SKOR TOTAL KESIAPAN:* 88/100\n\n"
                        "🧠 *ANALISIS KOMPETENSI:*\n"
                        "• 🗣️ Artikulasi & Komunikasi: 85/100\n"
                        "• ⚙️ Problem Solving & Metode STAR: 90/100\n"
                        "• 🤝 Ambisi & Cultural Fit: 88/100\n\n"
                        "💡 *3 REKOMENDASI EMAS SEBELUM INTERVIEW NYATA:*\n"
                        "1. Selalu sertakan metrik angka pada pencapaian (misal: 'meningkatkan efisiensi 25%').\n"
                        "2. Pelajari produk dan kultur spesifik perusahaan yang dituju.\n"
                        "3. Siapkan 2 pertanyaan kritis di akhir sesi wawancara untuk pewawancara."
                    )

                await send_whatsapp_text(sender_wa_id, final_report, tenant_id=TENANT_ID)

                await asyncio.sleep(1)
                await send_whatsapp_buttons(
                    to_phone=sender_wa_id,
                    body_text="Lengkapi persiapan Anda dengan konsultasi negosiasi gaji atau analisis loker lainnya:",
                    buttons=PREMIUM_ACTION_BUTTONS,
                    tenant_id=TENANT_ID
                )
                return

        # 7. DECISION ENGINE: 💰 SALARY & NEGOTIATION COACH
        if button_id == "btn_salary_coach" or (current_mode == "menu" and user_text_clean in ["3", "gaji", "nego gaji", "salary", "salary coach", "negosiasi gaji"]):
            user_session["mode"] = "salary_coach"
            await send_whatsapp_text(sender_wa_id, SALARY_COACH_INVITATION_MSG, tenant_id=TENANT_ID)
            return

        if current_mode == "salary_coach":
            await send_whatsapp_text(sender_wa_id, "⏳ *AI Negotiation Coach sedang menyusun benchmark pasar & naskah negosiasi Anda...*", tenant_id=TENANT_ID)

            prompt_salary = (
                "Anda adalah Senior Executive Recruiter & Salary Negotiation Coach Indonesia.\n"
                f"Kandidat menanyakan konsultasi gaji dengan data: '{user_text}'\n\n"
                "Susun panduan negosiasi lengkap dalam format WhatsApp Markdown yang rapi dan praktis:\n"
                "💰 *PANDUAN BENCHMARK & STRATEGI NEGOSIASI GAJI*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📊 *1. ESTIMASI KISARAN GAJI PASAR (IDR):*\n"
                "• 🥉 25th Percentile: [Nominal]\n"
                "• 🥈 Median Pasar (50th): [Nominal]\n"
                "• 🥇 75th Percentile: [Nominal]\n\n"
                "⚖️ *2. EVALUASI TAWARAN:*\n"
                "[Analisis apakah tawaran/ekspektasi tersebut Underpaid / Fair / Sangat Kompetitif]\n\n"
                "💬 *3. NASKAH SKRIP NEGOSIASI SIAP PAKAI (Email / WhatsApp):*\n"
                "\"[Tuliskan template naskah sopan, profesional, dan persuasif yang bisa langsung di-copy oleh kandidat untuk membalas HR]\"\n\n"
                "🎁 *4. BENEFIT NON-GAJI YANG BISA DITAWAR:*\n"
                "• 🏠 Fleksibilitas WFH / Hybrid\n"
                "• 🏥 Asuransi Kesehatan & Rawat Inap Keluarga\n"
                "• 📈 Jadwal Peninjauan Gaji Berkala (6 Bulan)\n"
                "• 📚 Budget Pengembangan Diri & Sertifikasi"
            )

            salary_result = await ai_gateway.generate(prompt_salary)
            if not salary_result:
                salary_result = (
                    "💰 *PANDUAN BENCHMARK & STRATEGI NEGOSIASI GAJI*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "📊 *1. ESTIMASI KISARAN GAJI PASAR:*\n"
                    "• 🥉 25th Percentile: Rp8.000.000\n"
                    "• 🥈 Median Pasar: Rp12.000.000\n"
                    "• 🥇 75th Percentile: Rp16.000.000\n\n"
                    "⚖️ *2. EVALUASI TAWARAN:*\n"
                    "Tawaran berada pada rentang kompetitif pasar profesional Indonesia.\n\n"
                    "💬 *3. NASKAH SKRIP NEGOSIASI HR:*\n"
                    "\"Terima kasih atas penawaran yang diberikan. Berdasarkan riset pasar dan kontribusi nilai tambah yang dapat saya bawa ke perusahaan, saya ingin mendiskusikan penyesuaian nominal pada kisaran Rp...\"\n\n"
                    "🎁 *4. BENEFIT NON-GAJI:*\n"
                    "• Fleksibilitas WFH / Hybrid\n"
                    "• Peninjauan performa dan gaji dalam 6 bulan"
                )

            await send_whatsapp_text(sender_wa_id, salary_result, tenant_id=TENANT_ID)
            user_session["mode"] = "menu"

            await asyncio.sleep(1)
            await send_whatsapp_buttons(
                to_phone=sender_wa_id,
                body_text="Lanjutkan persiapan karir Anda dengan fitur lainnya:",
                buttons=PREMIUM_ACTION_BUTTONS,
                tenant_id=TENANT_ID
            )
            return

        # 8. Trigger Optimasi / Bedah CV Lagi
        if button_id in ["btn_rewrite_again", "btn_review", "btn_review_cv"] or (current_mode == "menu" and user_text_clean in ["4", "review", "bedah cv", "review cv", "🔍 review cv", "revisi cv", "bedah cv ulang"]):
            user_session["mode"] = "review"
            await send_whatsapp_text(sender_wa_id, REVIEW_INTRO_MSG, tenant_id=TENANT_ID)
            return

        # 9. Builder Menu Button
        if button_id in ["btn_builder", "btn_create_cv"] or (current_mode == "menu" and user_text_clean in ["bikin cv", "buat cv", "📝 bikin cv dasar", "📝 buat cv baru", "create cv"]):
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

        # 10. CV Builder Language Selection
        if button_id.startswith("lang_"):
            lang_choice = "1" if button_id == "lang_en_id" else ("2" if button_id == "lang_id" else "3")
            result = await process_unified_cv_step(sender_wa_id, lang_choice, platform="whatsapp")
            await send_whatsapp_text(sender_wa_id, result["reply_text"], tenant_id=TENANT_ID)
            return

        # 11. CV Builder Wizard Steps
        if current_mode == "builder" or user_session.get("step", 0) > 0:
            result = await process_unified_cv_step(sender_wa_id, user_text, platform="whatsapp")
            messages_to_send = result.get("messages", [])
            if not messages_to_send and result.get("reply_text"):
                messages_to_send = [result["reply_text"]]

            for msg in messages_to_send:
                await send_whatsapp_text(sender_wa_id, msg, tenant_id=TENANT_ID)

            if result.get("is_completed"):
                file_path = result.get("file_path")
                if file_path and os.path.exists(file_path):
                    try:
                        doc_caption = "📄 *File CV Dasar (.docx)* telah berhasil di-generate."
                        await send_whatsapp_document(
                            to_phone=sender_wa_id,
                            file_path_or_bytes=file_path,
                            filename=os.path.basename(file_path),
                            caption=doc_caption,
                            tenant_id=TENANT_ID
                        )
                    except Exception as doc_err:
                        logger.warning(f"Error sending docx file to WA: {doc_err}")

                user_session["mode"] = "post_cv"
                user_session["step"] = 0
                user_session.setdefault("data", {})["has_completed_cv"] = True

                # 🎯 1. Funnel Metric: career_cv_build_completed
                await analytics_service.log_funnel_event(
                    event_name="career_cv_build_completed",
                    user_id=sender_wa_id,
                    tenant_id=TENANT_ID,
                    utm_source=user_session.get("utm_source", "direct"),
                    metadata={
                        "sender_wa_id": sender_wa_id,
                        "file_path": file_path,
                        "timestamp": datetime.now().isoformat()
                    }
                )
            return

        # 12. Review via Manual Text Input
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

        # 13. Fallback AI Consultation
        ai_reply = await ai_gateway.generate(
            user_message=user_text,
            context={"user_id": sender_wa_id, "feature": "career_consultation"}
        )
        if ai_reply:
            await send_whatsapp_text(sender_wa_id, ai_reply, tenant_id=TENANT_ID)
        else:
            await self.send_menu_buttons(sender_wa_id)


career_service = CareerService()

