import os
import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Union, List

from app.services.whatsapp_service import (
    get_supabase,
    send_whatsapp_text,
    send_whatsapp_document,
    safe_log_to_supabase_messages
)
from app.services.reconciliation_service import PAYMENT_INTENTS
from app.services.cv_state_engine import GLOBAL_USER_STATES
from app.core.database import track_event

logger = logging.getLogger("PAYMENT_MATCHER")


def extract_clean_dana_amount(raw_input: Union[str, dict, Any]) -> int:
    """Mengekstrak nominal angka bersih (misal 25300 dari 'Rp25.300 diterima DANA...')
    dari teks notifikasi DANA Bisnis, SMS banking, atau payload JSON reader Android.

    Mendukung format DANA Bisnis riil:
      - "Rp25.300 diterima DANA dari Adi Kurnia"
      - "Rp25.300 telah dikirim ke BoonTrack"
      - title: "Pembayaran Masuk", body: "Rp25.300 diterima DANA dari Adi Kurnia"
    """
    if not raw_input:
        return 0

    text = ""
    if isinstance(raw_input, dict):
        raw_amt = raw_input.get("amount") or raw_input.get("nominal") or raw_input.get("price_amount")
        if raw_amt is not None:
            try:
                # Jika sudah integer atau angka murni
                clean_digits = re.sub(r"\D", "", str(raw_amt))
                if clean_digits:
                    return int(clean_digits)
            except Exception:
                pass
        # Gabungkan semua field teks yang mungkin mengandung nominal
        # Android Reader bisa mengirim title + body / notification_text / raw_text secara terpisah
        title_text = str(raw_input.get("title") or "")
        body_text = str(
            raw_input.get("body")
            or raw_input.get("raw_text")
            or raw_input.get("message")
            or raw_input.get("text")
            or raw_input.get("notification_text")
            or raw_input.get("keterangan")
            or ""
        )
        text = f"{title_text} {body_text}".strip()
    elif isinstance(raw_input, str):
        text = raw_input
    else:
        try:
            return int(raw_input)
        except Exception:
            return 0

    if not text:
        return 0

    # 1. Hapus tag HTML jika ada
    clean_text = re.sub(r"<[^>]+>", " ", text)

    # 2. Pola DANA Bisnis riil: "Rp25.300 diterima DANA" / "Rp25.300 telah dikirim ke"
    #    Regex fleksibel: Rp<spasi_opsional><angka_dengan_titik_atau_koma>
    match_dana = re.search(
        r"Rp\s*([\d][\d\.\,]*)(?:\s+(?:diterima|telah|masuk|dari|ke|berhasil|sukses))",
        clean_text,
        re.IGNORECASE
    )
    if match_dana:
        raw_num = match_dana.group(1).strip().rstrip(".")
        if raw_num.endswith(",00") or raw_num.endswith(".00"):
            raw_num = raw_num[:-3]
        digits = re.sub(r"\D", "", raw_num)
        if digits:
            return int(digits)

    # 3. Pola umum Rupiah eksplisit (Rp. 5.083, Rp5.083, IDR 5.083,00, Rp 5083)
    match_rp = re.search(r"(?:rp\.?|idr)\s*([\d\.,]+)", clean_text, re.IGNORECASE)
    if match_rp:
        raw_num = match_rp.group(1).strip()
        if raw_num.endswith(",00") or raw_num.endswith(".00"):
            raw_num = raw_num[:-3]
        digits = re.sub(r"\D", "", raw_num)
        if digits:
            return int(digits)

    # 4. Pola kata kunci nominal/sebesar/transfer diikuti angka
    match_kw = re.search(r"(?:sebesar|nominal|total|bayar|transfer|masuk)\s*(?:rp\.?)?\s*([\d\.,]+)", clean_text, re.IGNORECASE)
    if match_kw:
        raw_num = match_kw.group(1).strip()
        if raw_num.endswith(",00") or raw_num.endswith(".00"):
            raw_num = raw_num[:-3]
        digits = re.sub(r"\D", "", raw_num)
        if digits:
            return int(digits)

    # 5. Fallback: Angka 4 s.d. 8 digit langsung di dalam teks (misal 5083, 25000)
    match_digits = re.search(r"\b(\d{4,8})\b", clean_text)
    if match_digits:
        return int(match_digits.group(1))

    return 0


async def find_matching_unpaid_job(amount: int, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Mencari job dokumen dengan exact price_amount dan payment_status == 'UNPAID'/'PENDING' di Supabase."""
    if amount <= 0:
        return None

    supabase = get_supabase()
    if supabase:
        for status_val in ["UNPAID", "PENDING", "WAITING_PAYMENT"]:
            try:
                query = (
                    supabase.table("document_jobs")
                    .select("*")
                    .eq("price_amount", amount)
                    .eq("payment_status", status_val)
                )
                if tenant_id and tenant_id not in ["all", ""]:
                    query = query.eq("tenant_id", tenant_id)
                res = query.order("created_at", desc=True).limit(1).execute()
                if res and hasattr(res, "data") and res.data and len(res.data) > 0:
                    job = res.data[0]
                    logger.info(
                        f"[PAYMENT MATCHER] Found job {job.get('id')} with status={status_val} "
                        f"price_amount={amount} tenant={tenant_id}"
                    )
                    return job
            except Exception as e:
                logger.warning(f"[PAYMENT MATCHER] Supabase query ({status_val}) warning: {e}")

    logger.info(f"[PAYMENT MATCHER] No unpaid job found for amount={amount} tenant={tenant_id}")
    return None


async def match_and_fulfill_payment(
    amount: int,
    raw_text: str = "",
    tenant_id: str = "boontrack-career",
    source: str = "dana_reader",
    direct_phone: Optional[str] = None,
    raw_payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Mencocokkan mutasi pembayaran DANA Bisnis secara realtime:
    1. Mencari job dokumen di document_jobs dengan price_amount == amount dan payment_status == 'UNPAID'/'PENDING'.
    2. Mencari Payment Intent di PAYMENT_INTENTS (misal Invoice BT-51877-183).
    3. Mengubah status job menjadi PAID & QUEUED.
    4. Mengirimkan file attachment (.docx) ke WhatsApp user secara otomatis.
    """
    logger.info(
        f"[PAYMENT MATCHING] Reader Webhook Received: raw_payload={raw_payload} | "
        f"amount=Rp{amount:,} | source={source} | direct_phone={direct_phone} | tenant={tenant_id}"
    )

    if amount <= 0:
        return {
            "status": "IGNORED",
            "reason": "invalid_amount",
            "amount": 0
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase()

    # 1. Cek matching ke document_jobs (Exact Price Matching)
    matched_job = await find_matching_unpaid_job(amount, tenant_id=tenant_id)

    # 2. Cek matching ke PAYMENT_INTENTS memori
    matched_intent = None
    for inv_id, intent in list(PAYMENT_INTENTS.items()):
        if intent.get("status") in ("PENDING", "UNPAID") and (intent.get("total_amount") == amount or intent.get("amount") == amount):
            matched_intent = intent
            break


    # 3. Jika cocok dengan document_jobs:
    if matched_job:
        job_id = matched_job["id"]
        user_phone = matched_job.get("user_phone") or matched_job.get("user_id") or direct_phone
        task_type = matched_job.get("task_type", "POLISH_REPHRASE")
        current_status = matched_job.get("status", "QUEUED")

        logger.info(f"[PAYMENT MATCHED] Job {job_id} matched for exact amount Rp{amount:,} (Phone: {user_phone})")

        # Update status job -> PAID di Supabase
        if supabase:
            try:
                supabase.table("document_jobs").update({
                    "payment_status": "PAID",
                    "status": "QUEUED" if current_status in ("WAITING_PAYMENT", "PENDING") else current_status
                }).eq("id", job_id).execute()
            except Exception as upd_err:
                logger.error(f"[PAYMENT MATCHER] Failed to update job {job_id} to PAID: {upd_err}")

        # Update in-memory session
        if user_phone:
            user_session = GLOBAL_USER_STATES.setdefault(user_phone, {"step": 0, "mode": "menu", "data": {}})
            user_session["is_premium_paid"] = True
            user_session["tier"] = "premium_unlocked"

        # Kirim file dokumen attachment jika job sudah COMPLETED atau proses & kirim jika WAITING_PAYMENT
        from app.services.document_engine import deliver_completed_document_job, process_document_job_async
        from app.services.r2_storage_service import r2_storage_service
        from app.services.document_parser_service import extract_text_from_bytes
        delivery_success = False
        if user_phone:
            try:
                matched_job["payment_status"] = "PAID"
                invoice_id = (
                    (matched_intent.get("invoice_id") if matched_intent else None)
                    or matched_job.get("invoice_id")
                    or f"INV-{str(job_id)[:8].upper()}"
                )
                if current_status == "COMPLETED":
                    delivery_success = await deliver_completed_document_job(
                        job_id=job_id,
                        tenant_id=tenant_id,
                        user_phone=user_phone,
                        is_paid=True,
                        amount=amount,
                        invoice_id=invoice_id
                    )
                else:
                    # Job berstatus WAITING_PAYMENT / QUEUED -> Proses naskah & kirimkan hasil sekarang
                    raw_key = matched_job.get("raw_storage_key") or matched_job.get("storage_key")
                    doc_filename = matched_job.get("original_filename") or matched_job.get("filename", "Dokumen.pdf")
                    raw_text = ""

                    # 1. Ambil dari in-memory text cache
                    from app.services.document_engine import JOB_RAW_TEXT_CACHE
                    if job_id in JOB_RAW_TEXT_CACHE:
                        raw_text = JOB_RAW_TEXT_CACHE[job_id]
                    elif str(job_id) in JOB_RAW_TEXT_CACHE:
                        raw_text = JOB_RAW_TEXT_CACHE[str(job_id)]

                    # 2. Ambil dari R2 raw text backup
                    if not raw_text:
                        backup_text_key = f"incoming/{tenant_id}/{job_id}_raw_text.txt"
                        backup_bytes = await r2_storage_service.download_file(backup_text_key)
                        if backup_bytes:
                            try:
                                raw_text = backup_bytes.decode("utf-8").strip()
                            except Exception:
                                raw_text = backup_bytes.decode("latin-1", errors="ignore").strip()

                    # 3. Ambil dari R2 raw file download & ekstraksi
                    if not raw_text and raw_key:
                        raw_bytes = await r2_storage_service.download_file(raw_key)
                        if raw_bytes:
                            raw_text = extract_text_from_bytes(raw_bytes, doc_filename)

                    # 4. Ambil dari user_session jika masih ada di memori
                    if not raw_text and user_phone:
                        sess = GLOBAL_USER_STATES.get(user_phone, {})
                        raw_text = sess.get("raw_text") or sess.get("parsed_cv_text") or ""
                    
                    await process_document_job_async(
                        job_id=job_id,
                        tenant_id=tenant_id,
                        task_type=task_type,
                        filename=doc_filename,
                        raw_text=raw_text,
                        user_phone=user_phone,
                        amount=amount,
                        invoice_id=invoice_id
                    )
                    delivery_success = True
            except Exception as deliv_err:
                logger.error(f"[PAYMENT MATCHER] Delivery error for job {job_id}: {deliv_err}")

        # Update payment intent jika ada yang berasosiasi
        if matched_intent:
            matched_intent["status"] = "PAID"
            matched_intent["paid_at"] = datetime.now()

        # Track event
        if user_phone:
            await track_event(
                user_phone,
                "document_payment_verified",
                meta={"amount": amount, "job_id": job_id, "method": "DANA_QRIS"}
            )

        return {
            "status": "SUCCESS",
            "action": "JOB_PAID_AND_DELIVERED",
            "job_id": job_id,
            "amount": amount,
            "user_phone": user_phone,
            "delivered": delivery_success
        }

    # 4. Jika cocok dengan PAYMENT_INTENTS (misal Single CV Rewrite / Bundle / Digicorn)
    if matched_intent:
        invoice_id = matched_intent["invoice_id"]
        user_id = matched_intent.get("user_id") or direct_phone
        matched_intent["status"] = "PAID"
        matched_intent["paid_at"] = datetime.now()

        logger.info(f"[PAYMENT MATCHED] Intent {invoice_id} matched for exact amount Rp{amount:,} (User: {user_id})")

        # Handle fulfillment sesuai produk
        if matched_intent.get("tenant_id") == "atmosfitnes" or matched_intent.get("product") == "gym_membership_renewal":
            from app.services.gym_access_service import gym_access_service
            member_id = str(matched_intent.get("member_id") or matched_intent.get("user_id") or "")
            renewal_res = await gym_access_service.process_gym_membership_renewal(
                tenant_id=matched_intent.get("tenant_id", "atmosfitnes"),
                member_id=member_id,
                amount=amount,
                invoice_id=invoice_id
            )
            return {
                "status": "SUCCESS",
                "action": "GYM_MEMBERSHIP_RENEWED",
                "invoice_id": invoice_id,
                "tenant": "atmosfitnes",
                "amount": amount,
                "member_id": member_id,
                "renewal_details": renewal_res
            }
        elif matched_intent.get("tenant_id") == "digicorn":
            from app.tenants.digicorn.service import digicorn_service
            await digicorn_service.deliver_paid_order(matched_intent)
            return {
                "status": "SUCCESS",
                "action": "AUTO_FULFILLED_DIGICORN",
                "invoice": invoice_id,
                "tenant": "digicorn",
                "amount": amount
            }
        elif user_id:
            user_session = GLOBAL_USER_STATES.setdefault(str(user_id), {"step": 0, "mode": "menu", "data": {}})
            prod = matched_intent.get("product") or matched_intent.get("product_id") or matched_intent.get("meta", {}).get("product")

            if prod == "career_pro_bundle":
                user_session["bundle_quota"] = 3
                user_session["bundle_expires_at"] = (datetime.now() + timedelta(days=30)).isoformat()
                user_session["tier"] = "bundle_active"
                user_session["is_premium_paid"] = True
                user_session["active_payment"] = None
                custom_desc = "Paket *Career Pro Bundle (CV Rewrite + 3x Simulasi HR STAR)* aktif 30 hari (Kuota: 3x)."
            elif prod == "single_cv_rewrite":
                user_session["single_paid_draft"] = invoice_id
                user_session["tier"] = "single_draft_paid"
                user_session["is_premium_paid"] = True
                user_session["active_payment"] = None
                custom_desc = "Layanan *Single CV Polish & ATS Rewrite* untuk draft Anda telah aktif."
            else:
                user_session["is_premium_paid"] = True
                user_session["tier"] = "premium_unlocked"
                user_session["active_payment"] = None
                custom_desc = "Layanan *BoonTrack Pro & AI CV Assistant* kini telah aktif! 🚀"

            success_msg = (
                f"🎉 *PEMBAYARAN TERVERIFIKASI!*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🧾 *Invoice:* `{invoice_id}`\n"
                f"💰 *Nominal Masuk:* Rp{amount:,}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Terima kasih! Pembayaran Anda telah kami terima. {custom_desc}"
            )
            await send_whatsapp_text(user_id, success_msg, tenant_id=tenant_id)

        return {
            "status": "SUCCESS",
            "action": "INTENT_PAID",
            "invoice_id": invoice_id,
            "amount": amount,
            "user_id": user_id
        }

    # 5. Direct Phone / Active User Session Matching
    if direct_phone:
        user_session = GLOBAL_USER_STATES.setdefault(str(direct_phone), {"step": 0, "mode": "menu", "data": {}})
        user_session["is_premium_paid"] = True
        user_session["tier"] = "premium_unlocked"
        user_session["active_payment"] = None

        success_msg = (
            f"🎉 *PEMBAYARAN BERHASIL DIVERIFIKASI!*\n\n"
            f"Pembayaran sebesar *Rp{amount:,}* telah berhasil diverifikasi oleh sistem BoonTrack.\n"
            "Akses fitur Pro Anda telah aktif."
        )
        await send_whatsapp_text(str(direct_phone), success_msg, tenant_id=tenant_id)
        return {
            "status": "SUCCESS",
            "action": "DIRECT_PHONE_FULFILLED",
            "amount": amount,
            "user_phone": direct_phone
        }

    logger.warning(f"[PAYMENT UNMATCHED] Nominal Rp{amount:,} tidak cocok dengan order/job/intent pending manapun.")
    return {
        "status": "UNMATCHED",
        "amount": amount,
        "note": "No active pending job or invoice for this exact amount"
    }


# ==========================================
# ADMIN MANUAL TRIGGER HANDLERS
# ==========================================
async def handle_admin_verify_command(cmd_text: str, tenant_id: str = "boontrack-career") -> str:
    """Handler fallback manual command admin: /verify <nominal> (contoh: /verify 5083)."""
    clean_cmd = cmd_text.strip()
    match = re.search(r"(?:/verify|verify)\s*([\d\.,]+)", clean_cmd, re.IGNORECASE)
    if not match:
        return "⚠️ *Format Salah:* Gunakan `/verify <nominal>` (contoh: `/verify 5083`)."

    amount = extract_clean_dana_amount(match.group(1))
    if amount <= 0:
        return "⚠️ *Nominal Tidak Valid:* Masukkan nominal angka positif (contoh: `/verify 5083`)."

    res = await match_and_fulfill_payment(
        amount=amount,
        raw_text=f"ADMIN_MANUAL_TRIGGER: {clean_cmd}",
        tenant_id=tenant_id,
        source="admin_command"
    )

    if res.get("status") == "SUCCESS":
        return (
            f"✅ *Verifikasi Manual Berhasil!*\n"
            f"💰 *Nominal:* Rp{amount:,}\n"
            f"📋 *Action:* `{res.get('action')}`\n"
            f"🆔 *ID:* `{res.get('job_id') or res.get('invoice_id') or '-'}`\n"
            f"📱 *Penerima:* `{res.get('user_phone') or res.get('user_id') or '-'}`"
        )
    else:
        return (
            f"⚠️ *Verifikasi Gagal:* Tidak ditemukan job/invoice pending untuk nominal *Rp{amount:,}*.\n"
            f"Pastikan nominal sesuai atau gunakan `/retry_doc <job_id>`."
        )


async def handle_admin_retry_doc_command(cmd_text: str, tenant_id: str = "boontrack-career") -> str:
    """Handler fallback manual command admin: /retry_doc <job_id>."""
    clean_cmd = cmd_text.strip()
    match = re.search(r"(?:/retry_doc|retry_doc)\s+([a-zA-Z0-9_-]+)", clean_cmd, re.IGNORECASE)
    if not match:
        return "⚠️ *Format Salah:* Gunakan `/retry_doc <job_id>` (contoh: `/retry_doc 7963301b-4306-4c61-a054-bdf4a0f6e8a0`)."

    job_id = match.group(1).strip()
    from app.services.document_engine import deliver_completed_document_job
    try:
        delivered = await deliver_completed_document_job(job_id=job_id, tenant_id=tenant_id)
        if delivered:
            return f"✅ *Pengiriman Ulang Berhasil!* Dokumen untuk job `{job_id}` telah dikirimkan ke WhatsApp user."
        else:
            return f"⚠️ *Pengiriman Gagal:* Tidak dapat menemukan file hasil atau nomor WhatsApp untuk job `{job_id}`."
    except Exception as e:
        logger.error(f"[Admin Retry Doc Error] {e}")
        return f"⚠️ *Terjadi Kesalahan:* {str(e)}"


# Alias for backward compatibility & semantic naming
match_and_process_payment = match_and_fulfill_payment

