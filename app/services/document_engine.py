import os
import io
import re
import time
import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from app.services.pricing_engine import (
    calculate_document_metrics,
    calculate_pricing,
    compute_content_hash,
    check_anti_abuse_free_trial,
    register_free_trial_usage,
    COMPLIANCE_DISCLAIMER,
    OFFICIAL_PRODUCT_NAME,
    TASK_POLISH_REPHRASE,
    TASK_CV_POLISH_REWRITE,
    TASK_CAREER_PRO_BUNDLE,
    TASK_ATS_DIAGNOSTIC,
    TASK_CV_BUILD,
    TASK_CV_ATS,
    TASK_CV_REVIEW,
    LEGACY_TASK_MAPPING
)
from app.services.r2_storage_service import r2_storage_service
from app.services.doc_builder import build_document_result, chunk_document_text
from app.services.document_parser_service import extract_text_from_bytes
from app.services.ai_service import ai_gateway
from app.services.whatsapp_service import (
    get_supabase,
    send_whatsapp_text,
    send_whatsapp_document,
    safe_log_to_supabase_messages
)

logger = logging.getLogger(__name__)

# Valid Magic Bytes
MAGIC_BYTES_PDF = b"%PDF"
MAGIC_BYTES_ZIP = b"PK\x03\x04" # DOCX is a zipped XML container
MAGIC_BYTES_OLE = b"\xd0\xcf\x11\xe0" # DOC OLE container

# Legacy Task Constants for Backward Compatibility
TASK_ATS_REVIEW = "ATS_REVIEW"
TASK_CV_REWRITE = "CV_REWRITE"
TASK_PARAPHRASE = "PARAPHRASE"
TASK_DOCUMENT_POLISH = "DOCUMENT_POLISH"
TASK_BUNDLE_CAREER = "BUNDLE_CAREER"
TASK_PRO_BUNDLE = "PRO_BUNDLE"

# Canonical Mapping for 4 Core Products
CANONICAL_TASK_MAP = {
    # Service 1: CV_BUILD / CV_ATS
    "CV_BUILD": TASK_CV_ATS,
    "CV_ATS": TASK_CV_ATS,
    "CV_POLISH_REWRITE": TASK_CV_ATS,
    "CV_REWRITE": TASK_CV_ATS,

    # Service 2: CV_REVIEW
    "CV_REVIEW": TASK_CV_REVIEW,
    "ATS_DIAGNOSTIC": TASK_CV_REVIEW,
    "ATS_REVIEW": TASK_CV_REVIEW,

    # Service 3: POLISH_REPHRASE
    "POLISH_REPHRASE": TASK_POLISH_REPHRASE,
    "PARAPHRASE": TASK_POLISH_REPHRASE,
    "DOCUMENT_POLISH": TASK_POLISH_REPHRASE,

    # Service 4: CAREER_PRO_BUNDLE
    "CAREER_PRO_BUNDLE": TASK_CAREER_PRO_BUNDLE,
    "BUNDLE_CAREER": TASK_CAREER_PRO_BUNDLE,
    "PRO_BUNDLE": TASK_CAREER_PRO_BUNDLE
}

# Supported Tasks Set
SUPPORTED_TASKS = set(CANONICAL_TASK_MAP.keys()).union(set(CANONICAL_TASK_MAP.values()))


def validate_document_file(file_bytes: bytes, filename: str) -> Tuple[bool, str, str]:
    """Memvalidasi integritas file dokumen berdasarkan magic bytes dan ekstensi.
    
    Returns:
        (is_valid, mime_type, error_msg)
    """
    if not file_bytes or len(file_bytes) < 4:
        return False, "", "File kosong atau terlalu kecil"

    name_lower = str(filename or "").lower().strip()
    
    # 1. Validasi PDF
    if file_bytes.startswith(MAGIC_BYTES_PDF) or name_lower.endswith(".pdf"):
        if file_bytes.startswith(MAGIC_BYTES_PDF):
            return True, "application/pdf", ""
        return False, "", "File memiliki ekstensi .pdf tetapi header magic bytes bukan PDF yang valid"

    # 2. Validasi DOCX
    if file_bytes.startswith(MAGIC_BYTES_ZIP) or name_lower.endswith(".docx"):
        if file_bytes.startswith(MAGIC_BYTES_ZIP):
            return True, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ""
        return False, "", "File memiliki ekstensi .docx tetapi format berkas korup/tidak valid"

    # 3. Validasi DOC Legacy
    if file_bytes.startswith(MAGIC_BYTES_OLE) or name_lower.endswith(".doc"):
        if file_bytes.startswith(MAGIC_BYTES_OLE):
            return True, "application/msword", ""
        return False, "", "File memiliki ekstensi .doc tetapi format berkas bukan OLE valid"

    return False, "", "Format file tidak didukung. Mohon unggah dokumen berformat PDF atau DOCX."


async def update_job_status(
    job_id: str,
    status: str,
    error_message: Optional[str] = None,
    result_storage_key: Optional[str] = None,
    structured_output: Optional[Dict[str, Any]] = None,
    extra_fields: Optional[Dict[str, Any]] = None
) -> bool:
    """Mengupdate status job di Supabase public.document_jobs."""
    try:
        supabase = get_supabase()
        if not supabase:
            return False

        valid_cols = {
            "id", "job_id", "tenant_id", "user_id", "source_channel",
            "original_filename", "mime_type", "file_size", "word_count",
            "storage_key", "task_type", "status", "parser_version",
            "ai_model", "result_storage_key", "error_code", "created_at",
            "expires_at", "doc_hash", "price_amount", "payment_status", "pricing_tier"
        }
        payload: Dict[str, Any] = {
            "status": status,
        }
        if error_message is not None:
            payload["error_code"] = str(error_message)[:100]
        if result_storage_key is not None:
            payload["result_storage_key"] = result_storage_key
        if extra_fields:
            for k, v in extra_fields.items():
                if k in valid_cols:
                    payload[k] = v

        safe_payload = {k: v for k, v in payload.items() if k in valid_cols}
        supabase.table("document_jobs").update(safe_payload).eq("id", job_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DocumentEngine Error] update_job_status ({job_id}): {e}")
        return False


def _extract_json_from_llm_output(text: str) -> Optional[Dict[str, Any]]:
    """Mengekstrak dan mem-parse JSON dari respons LLM secara aman."""
    if not text:
        return None
    try:
        return json.loads(text.strip())
    except Exception:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace:last_brace + 1].strip())
        except Exception:
            pass

    return None


from app.engines.rephrase_engine import academic_rephrase_engine


async def execute_ai_document_task(
    task_type: str,
    raw_text: str,
    filename: str = "Dokumen",
    **kwargs
) -> Dict[str, Any]:
    """Memanggil AI Gateway / Rephrase Engine sesuai 4 Layanan Inti BoonTrack via modular prompt strategies."""
    from app.prompts import (
        get_prompt_for_task,
        get_fallback_for_task,
        normalize_prompt_task,
        TASK_POLISH_REPHRASE as STRATEGY_POLISH_TASK,
        CANONICAL_PROMPT_MAP
    )

    raw_normalized = str(task_type).upper().strip()
    if raw_normalized not in CANONICAL_PROMPT_MAP and raw_normalized not in SUPPORTED_TASKS:
        raise ValueError(f"Tipe task tidak didukung oleh Document Engine: '{task_type}'")

    canonical = normalize_prompt_task(raw_normalized)

    # 3. SERVICE: "POLISH_REPHRASE"
    # Ekstraksi naskah akademis -> sanitasi artefak PDF -> chunking & parafrase komprehensif via AcademicRephraseEngine.
    if canonical == STRATEGY_POLISH_TASK or canonical == TASK_POLISH_REPHRASE:
        return await academic_rephrase_engine.process_task(raw_text=raw_text, filename=filename, task_type=canonical)

    # Services 1, 2, 4: CV_ATS, CV_REVIEW, CAREER_PRO_BUNDLE
    prompt = get_prompt_for_task(canonical, raw_text=raw_text, filename=filename, **kwargs)
    ai_response = await ai_gateway.generate(prompt)
    structured = _extract_json_from_llm_output(ai_response or "")

    if structured:
        return structured

    logger.warning(f"[DocumentEngine] LLM JSON parsing fallback triggered for {canonical}.")
    return get_fallback_for_task(canonical, raw_text=raw_text)


TASK_DISPLAY_NAMES = {
    "CV_BUILD": "CV ATS & Optimasi Karir",
    "CV_ATS": "CV ATS & Optimasi Karir",
    "CV_POLISH_REWRITE": "CV ATS & Optimasi Karir",
    "CV_REWRITE": "CV ATS & Optimasi Karir",
    "CV_REVIEW": "Evaluasi & Review CV HR",
    "ATS_DIAGNOSTIC": "Evaluasi & Review CV HR",
    "ATS_REVIEW": "Evaluasi & Review CV HR",
    "POLISH_REPHRASE": "Penyempurnaan & Parafrase Naskah",
    "PARAPHRASE": "Penyempurnaan & Parafrase Naskah",
    "DOCUMENT_POLISH": "Penyempurnaan & Parafrase Naskah",
    "CAREER_PRO_BUNDLE": "Paket Lengkap Karir Pro (CV + Rekomendasi HR + Cover Letter)",
    "BUNDLE_CAREER": "Paket Lengkap Karir Pro (CV + Rekomendasi HR + Cover Letter)",
    "PRO_BUNDLE": "Paket Lengkap Karir Pro (CV + Rekomendasi HR + Cover Letter)"
}


def format_payment_confirmation_text(
    task_name: str,
    invoice_id: str,
    amount: int
) -> str:
    """Format pesan ringkasan status pembayaran dan notifikasi selesai."""
    display_task = TASK_DISPLAY_NAMES.get(str(task_name).upper().strip(), task_name or "Polish & Rephrase Dokumen")
    amt_val = amount or 0
    return (
        "💳 *PEMBAYARAN TERVERIFIKASI & LUNAS*\n\n"
        f"📋 *Layanan:* {display_task}\n"
        f"🆔 *Invoice:* `{invoice_id}`\n"
        f"💰 *Total:* *Rp{amt_val:,}* (Lunas via DANA QRIS)\n\n"
        "⚙️ Dokumen Anda telah selesai diproses. File hasil berformat Word (.docx) siap diunduh di bawah ini 👇"
    )


def get_output_document_filename(task_type: str, original_filename: Optional[str] = None) -> str:
    """Menentukan nama file output .docx berdasarkan 4 Layanan Inti BoonTrack.
    
    1. 'CV_BUILD' / 'CV_ATS' -> 'CV_ATS_Optimasi.docx'
    2. 'CV_REVIEW' -> 'Laporan_Review_CV_HR.docx'
    3. 'POLISH_REPHRASE' -> 'Naskah_Hasil_Parafrase.docx' (atau {clean_base}_Hasil_Parafrase.docx jika nama asli tersedia)
    4. 'CAREER_PRO_BUNDLE' -> 'Paket_Lengkap_Karir_Pro.docx'
    """
    raw_task = str(task_type or "").upper().strip()
    canonical = CANONICAL_TASK_MAP.get(raw_task, raw_task)

    # 4. SERVICE: "CAREER_PRO_BUNDLE"
    if canonical == TASK_CAREER_PRO_BUNDLE or raw_task in ("CAREER_PRO_BUNDLE", "BUNDLE_CAREER", "PRO_BUNDLE"):
        return "Paket_Lengkap_Karir_Pro.docx"

    # 2. SERVICE: "CV_REVIEW"
    if canonical == TASK_CV_REVIEW or raw_task in ("CV_REVIEW", "ATS_DIAGNOSTIC", "ATS_REVIEW"):
        return "Laporan_Review_CV_HR.docx"

    # 1. SERVICE: "CV_BUILD" / "CV_ATS"
    if canonical == TASK_CV_ATS or raw_task in ("CV_BUILD", "CV_ATS", "CV_POLISH_REWRITE", "CV_REWRITE"):
        return "CV_ATS_Optimasi.docx"

    # 3. SERVICE: "POLISH_REPHRASE"
    if canonical == TASK_POLISH_REPHRASE or raw_task in ("POLISH_REPHRASE", "PARAPHRASE", "DOCUMENT_POLISH"):
        if original_filename:
            base_name = os.path.splitext(os.path.basename(original_filename))[0]
            clean_base = re.sub(r'[^a-zA-Z0-9_\-]', '_', base_name).strip('_')
            generic_names = {"document", "dokumen", "file", "naskah_input", "untitled", "test", ""}
            if clean_base and clean_base.lower() not in generic_names:
                return f"{clean_base}_Hasil_Parafrase.docx"
        return "Naskah_Hasil_Parafrase.docx"

    # Fallback umum
    return "Dokumen_Hasil_Polish.docx"


def format_document_caption(file_name: str) -> str:
    """Format caption media pengiriman binary dokumen Word."""
    clean_name = file_name or "Dokumen_Hasil_Polish.docx"
    return (
        f"📄 *{clean_name}*\n"
        "📌 _Alat ini membantu keterbacaan dan struktur naskah — penggunaannya tetap mengikuti kebijakan integritas profesional dan akademik institusi Anda._"
    )


# In-memory fast text cache across worker life-cycle
JOB_RAW_TEXT_CACHE: Dict[str, str] = {}


async def process_document_job_async(
    job_id: str,
    tenant_id: str,
    task_type: str,
    filename: str,
    raw_text: str,
    user_phone: Optional[str] = None,
    amount: Optional[int] = None,
    invoice_id: Optional[str] = None
):
    """Background Worker untuk memproses dokumen secara asinkron (Zero-blocking)."""
    logger.info(f"[DocumentWorker] Started processing job {job_id} ({task_type})")
    t_start = time.time()
    try:
        # 0. Validasi & Pemulihan raw_text jika kosong
        effective_text = str(raw_text or "").strip()
        if not effective_text:
            effective_text = JOB_RAW_TEXT_CACHE.get(job_id, "").strip()

        if not effective_text:
            backup_text_key = f"incoming/{tenant_id}/{job_id}_raw_text.txt"
            backup_bytes = await r2_storage_service.download_file(backup_text_key)
            if backup_bytes:
                try:
                    effective_text = backup_bytes.decode("utf-8").strip()
                except Exception:
                    effective_text = backup_bytes.decode("latin-1", errors="ignore").strip()

        if not effective_text:
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table("document_jobs").select("storage_key, original_filename").eq("id", job_id).execute()
                    if res.data and len(res.data) > 0:
                        raw_s_key = res.data[0].get("storage_key")
                        orig_name = res.data[0].get("original_filename") or filename
                        if raw_s_key:
                            raw_file_bytes = await r2_storage_service.download_file(raw_s_key)
                            if raw_file_bytes:
                                effective_text = extract_text_from_bytes(raw_file_bytes, orig_name).strip()
                except Exception as rec_err:
                    logger.error(f"[DocumentWorker] Failed to recover raw_text from DB/R2 for {job_id}: {rec_err}")

        if not effective_text:
            err_msg = f"Naskah kosong: Teks dokumen tidak dapat diekstrak atau hilang untuk job {job_id} ({filename}). Pemrosesan AI dibatalkan."
            logger.error(f"[DocumentWorker Error] {err_msg}")
            await update_job_status(job_id, status="FAILED", error_message="Teks dokumen kosong / gagal diekstrak")
            raise ValueError(err_msg)

        raw_text = effective_text

        # 1. Update status -> PROCESSING
        await update_job_status(job_id, status="PROCESSING")

        # 2. Panggil AI Gateway untuk Structured Output
        structured_data = await execute_ai_document_task(task_type, raw_text, filename)

        # 3. Render dokumen Word (.docx)
        docx_bytes = build_document_result(task_type, structured_data)

        # 4. Upload hasil (.docx) ke Cloudflare R2
        clean_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(filename)[0])
        result_key = f"output/{tenant_id}/{job_id}_{clean_filename}_result.docx"
        await r2_storage_service.upload_file(
            file_bytes=docx_bytes,
            storage_key=result_key,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        # 5. Update status -> COMPLETED & PAID dengan execution_time_ms
        exec_ms = int((time.time() - t_start) * 1000)
        await update_job_status(
            job_id=job_id,
            status="COMPLETED",
            result_storage_key=result_key,
            extra_fields={"payment_status": "PAID"}
        )
        logger.info(f"[DocumentWorker] Job {job_id} successfully completed in {exec_ms}ms. Result: {result_key}")

        # 6. Notifikasi & File Delivery ke WhatsApp jika nomor tersedia
        if user_phone:
            inv_id = invoice_id or f"INV-{str(job_id)[:8].upper()}"
            amt_val = amount or 0
            output_doc_name = get_output_document_filename(task_type=task_type, original_filename=filename)

            # Pesan 1: Ringkasan Status Pembayaran & Notifikasi Selesai
            msg_text = format_payment_confirmation_text(
                task_name=task_type,
                invoice_id=inv_id,
                amount=amt_val
            )
            await send_whatsapp_text(to_phone=user_phone, text=msg_text, tenant_id=tenant_id)
            
            # Pesan 2: Pengiriman Binary Media API (.docx)
            caption = format_document_caption(output_doc_name)
            await send_whatsapp_document(
                to_phone=user_phone,
                file_path_or_bytes=docx_bytes,
                filename=output_doc_name,
                caption=caption,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                tenant_id=tenant_id
            )

    except Exception as err:
        logger.error(f"[DocumentWorker Error] Job {job_id} failed: {err}")
        await update_job_status(job_id, status="FAILED", error_message=str(err))


async def deliver_completed_document_job(
    job_id: str,
    tenant_id: str = "boontrack-career",
    user_phone: Optional[str] = None,
    is_paid: bool = False,
    amount: Optional[int] = None,
    invoice_id: Optional[str] = None
) -> bool:
    """Mengirim file attachment dokumen .docx untuk job yang sudah COMPLETED/PAID ke WhatsApp user."""
    supabase = get_supabase()
    job_data: Optional[Dict[str, Any]] = None
    if supabase:
        try:
            res = supabase.table("document_jobs").select("*").eq("id", job_id).execute()
            if res.data and len(res.data) > 0:
                job_data = res.data[0]
        except Exception as e:
            logger.error(f"[DocumentEngine] deliver_completed_document_job query error for {job_id}: {e}")

    # Strict Payment Lock Check
    effective_paid = is_paid
    if job_data:
        payment_status = job_data.get("payment_status", "UNPAID")
        price_amount = job_data.get("price_amount", 0) or job_data.get("price", 0)
        if payment_status == "PAID" or price_amount == 0:
            effective_paid = True
        elif price_amount > 0 and not effective_paid:
            logger.warning(f"[PAYMENT LOCK] Delivery rejected: Job {job_id} is UNPAID (payment_status: {payment_status})")
            return False

    phone = user_phone or (job_data.get("user_phone") if job_data else None)
    if not phone:
        logger.error(f"[DocumentEngine] No target phone number for job {job_id}")
        return False

    result_key = job_data.get("result_storage_key") if job_data else None
    if not result_key:
        result_key = f"output/{tenant_id}/{job_id}_result.docx"

    # 1. Unduh file bytes dari R2 Storage Service (mendukung mock & live)
    file_bytes = await r2_storage_service.download_file(result_key)
    if not file_bytes:
        alt_key = f"output/{tenant_id}/{job_id}_result.docx"
        file_bytes = await r2_storage_service.download_file(alt_key)

    # 2. Cek local storage output buffer
    if not file_bytes:
        local_candidates = [
            os.path.join(os.getcwd(), "output", tenant_id, f"{job_id}_result.docx"),
            os.path.join(os.getcwd(), "data", "r2_mock_storage", "output", tenant_id, f"{job_id}_result.docx")
        ]
        for p in local_candidates:
            if os.path.exists(p):
                with open(p, "rb") as f:
                    file_bytes = f.read()
                break

    if not file_bytes:
        logger.error(f"[DocumentEngine] Failed to retrieve document bytes for job {job_id} (key: {result_key})")
        return False

    # 3. Kirim Pesan 1: Ringkasan Status Pembayaran & Notifikasi Selesai
    task_name = job_data.get("task_type", "POLISH_REPHRASE") if job_data else "POLISH_REPHRASE"
    inv_id = invoice_id or (job_data.get("invoice_id") if job_data else None) or f"INV-{str(job_id)[:8].upper()}"
    amt_val = amount or (job_data.get("price_amount") if job_data else None) or 0
    orig_file = (job_data.get("original_filename") if job_data else None) or (job_data.get("filename") if job_data else None)
    output_doc_name = get_output_document_filename(task_type=task_name, original_filename=orig_file)

    msg_text = format_payment_confirmation_text(
        task_name=task_name,
        invoice_id=inv_id,
        amount=amt_val
    )
    await send_whatsapp_text(to_phone=phone, text=msg_text, tenant_id=tenant_id)

    # 4. Kirim Pesan 2: Pengiriman Binary Media API (.docx)
    caption = format_document_caption(output_doc_name)
    doc_res = await send_whatsapp_document(
        to_phone=phone,
        file_path_or_bytes=file_bytes,
        filename=output_doc_name,
        caption=caption,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        tenant_id=tenant_id
    )
    return bool(doc_res)


async def intake_document_job(
    tenant_id: str,
    task_type: str,
    filename: str,
    file_bytes: bytes,
    user_id: Optional[str] = None,
    user_phone: Optional[str] = None,
    exact_price_amount: Optional[int] = None
) -> Dict[str, Any]:
    """Endpoint Intake Dokumen Terpadu (Zero-Blocking & Strict Payment Lock)."""
    job_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)
    raw_task = str(task_type).upper().strip()
    if raw_task not in CANONICAL_TASK_MAP and raw_task not in SUPPORTED_TASKS:
        return {
            "status": "REJECTED",
            "job_id": job_id,
            "error": f"Tipe tugas dokumen '{task_type}' tidak didukung oleh Document Engine.",
            "is_valid": False
        }
    normalized_task = LEGACY_TASK_MAPPING.get(raw_task, raw_task)

    # 1. Validasi Magic Bytes & Format File
    is_valid, mime_type, err_msg = validate_document_file(file_bytes, filename)
    if not is_valid:
        # Jika file tidak valid tapi exact_price_amount tersedia (order QRIS sudah dibuat),
        # tetap INSERT record minimal ke document_jobs agar payment matcher bisa menemukan order.
        if exact_price_amount and exact_price_amount > 0:
            supabase_fallback = get_supabase()
            if supabase_fallback:
                fallback_record = {
                    "id": job_id,
                    "job_id": job_id,
                    "tenant_id": tenant_id or "boontrack-career",
                    "user_id": str(user_id or user_phone or "guest"),
                    "source_channel": "whatsapp",
                    "original_filename": filename or "document.docx",
                    "mime_type": "application/pdf",
                    "file_size": len(file_bytes) if file_bytes else 0,
                    "storage_key": f"inbox/{job_id}",
                    "task_type": str(task_type).upper().strip(),
                    "status": "WAITING_PAYMENT",
                    "payment_status": "UNPAID",
                    "price_amount": exact_price_amount,
                }
                try:
                    supabase_fallback.table("document_jobs").insert(fallback_record).execute()
                    logger.info(
                        f"[DocumentEngine] Fallback document_jobs insert (file invalid): "
                        f"job_id={job_id} price_amount={exact_price_amount} user={user_id}"
                    )
                except Exception as fb_err:
                    logger.error(f"[DocumentEngine] Fallback insert failed: {fb_err}")
        return {
            "status": "REJECTED",
            "job_id": job_id,
            "error": err_msg,
            "is_valid": False
        }

    # 2. Upload file mentah ke Cloudflare R2
    clean_tenant = tenant_id or "boontrack-career"
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    raw_storage_key = f"incoming/{clean_tenant}/{job_id}_{safe_name}"
    await r2_storage_service.upload_file(file_bytes, raw_storage_key, content_type=mime_type)

    # 3. Ekstraksi teks cepat untuk metrics kata, SHA-256 hash, & kalkulasi harga
    extracted_text = extract_text_from_bytes(file_bytes, filename)
    if not extracted_text or not extracted_text.strip():
        logger.error(
            f"[DocumentEngine] CRITICAL: Extracted text is empty for {filename} "
            f"({len(file_bytes)} bytes). Rejecting intake."
        )
        if exact_price_amount and exact_price_amount > 0:
            supabase_fallback = get_supabase()
            if supabase_fallback:
                fallback_record = {
                    "id": job_id,
                    "job_id": job_id,
                    "tenant_id": clean_tenant,
                    "user_id": str(user_id or user_phone or "guest"),
                    "source_channel": "whatsapp",
                    "original_filename": filename or "document.docx",
                    "mime_type": mime_type,
                    "file_size": len(file_bytes) if file_bytes else 0,
                    "storage_key": raw_storage_key,
                    "task_type": normalized_task,
                    "status": "WAITING_PAYMENT",
                    "payment_status": "UNPAID",
                    "price_amount": exact_price_amount,
                }
                try:
                    supabase_fallback.table("document_jobs").insert(fallback_record).execute()
                except Exception as fb_err:
                    logger.error(f"[DocumentEngine] Fallback insert failed: {fb_err}")
        return {
            "status": "REJECTED",
            "job_id": job_id,
            "error": "Teks naskah tidak dapat terbaca dari berkas dokumen (ekstraksi teks kosong). Pastikan dokumen memuat teks digital yang dapat dibaca.",
            "is_valid": False
        }

    # Simpan ke in-memory cache & cadangkan raw text ke R2
    JOB_RAW_TEXT_CACHE[job_id] = extracted_text
    try:
        raw_text_key = f"incoming/{clean_tenant}/{job_id}_raw_text.txt"
        await r2_storage_service.upload_file(
            file_bytes=extracted_text.encode("utf-8"),
            storage_key=raw_text_key,
            content_type="text/plain; charset=utf-8"
        )
    except Exception as txt_err:
        logger.warning(f"[DocumentEngine] Backup raw text upload note: {txt_err}")

    metrics = calculate_document_metrics(extracted_text)
    pricing = calculate_pricing(normalized_task, metrics["word_count"])
    doc_hash = metrics["doc_hash"]

    # Nominal harga final (mendukung exact amount dengan 3-digit kode unik dari payment order)
    final_price = exact_price_amount if exact_price_amount is not None else pricing["final_price"]
    is_free = (final_price == 0)
    initial_status = "QUEUED" if is_free else "WAITING_PAYMENT"
    payment_status = "PAID" if is_free else "UNPAID"

    # 4. Registrasi Job ke Supabase DB (Status: WAITING_PAYMENT untuk berbayar)
    supabase = get_supabase()
    unique_code = (final_price % 1000) if final_price >= 1000 else 0
    job_record = {
        "id": job_id,
        "job_id": job_id,
        "tenant_id": clean_tenant,
        "user_id": str(user_id or user_phone or "guest"),
        "source_channel": "whatsapp",
        "original_filename": filename,
        "file_size": len(file_bytes),
        "mime_type": mime_type,
        "word_count": metrics["word_count"],
        "storage_key": raw_storage_key,
        "task_type": normalized_task,
        "status": initial_status,
        "payment_status": payment_status,
        "doc_hash": doc_hash,
        "price_amount": final_price,
        "pricing_tier": pricing.get("pricing_tier"),
    }

    if supabase:
        try:
            supabase.table("document_jobs").insert(job_record).execute()
            logger.info(
                f"[DocumentEngine] document_jobs INSERT OK: job_id={job_id} "
                f"price_amount={final_price} payment_status={payment_status} user={user_id}"
            )
        except Exception as db_err:
            logger.error(f"[DocumentEngine] CRITICAL: document_jobs INSERT FAILED: {db_err}")

    # 5. JANGAN PERNAH dispatch worker/delivery sebelum status PAID!
    # Hanya dispatch worker otomatis jika dokumen GRATIS (Free Trial).
    if is_free:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(process_document_job_async(
                job_id=job_id,
                tenant_id=clean_tenant,
                task_type=normalized_task,
                filename=filename,
                raw_text=extracted_text,
                user_phone=user_phone
            ))
        except RuntimeError:
            asyncio.create_task(process_document_job_async(
                job_id=job_id,
                tenant_id=clean_tenant,
                task_type=normalized_task,
                filename=filename,
                raw_text=extracted_text,
                user_phone=user_phone
            ))

    # 6. Kembalikan respons instan
    return {
        "status": initial_status,
        "job_id": job_id,
        "tenant_id": clean_tenant,
        "task_type": normalized_task,
        "filename": filename,
        "doc_hash": doc_hash,
        "word_count": metrics["word_count"],
        "estimated_pages": metrics["estimated_pages"],
        "pricing": pricing,
        "price_amount": final_price,
        "unique_code": unique_code,
        "payment_status": payment_status,
        "raw_storage_key": raw_storage_key,
        "disclaimer": COMPLIANCE_DISCLAIMER,
        "message": "Dokumen berhasil dianalisis. Menunggu pembayaran QRIS." if not is_free else "Dokumen dalam proses."
    }
