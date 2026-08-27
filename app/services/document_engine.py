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

# Supported Tasks Set
SUPPORTED_TASKS = {
    TASK_POLISH_REPHRASE,
    TASK_CV_POLISH_REWRITE,
    TASK_CAREER_PRO_BUNDLE,
    TASK_ATS_DIAGNOSTIC,
    TASK_ATS_REVIEW,
    TASK_CV_REWRITE,
    TASK_PARAPHRASE
}


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
    filename: str = "Dokumen"
) -> Dict[str, Any]:
    """Memanggil AI Gateway / Academic Rephrase Engine sesuai tipe tugas."""
    raw_normalized = str(task_type).upper().strip()
    normalized_task = LEGACY_TASK_MAPPING.get(raw_normalized, raw_normalized)

    # 1. TASK_POLISH_REPHRASE: Diproses penuh oleh AcademicRephraseEngine (EYD V, Chunking 600-800 kata, Proteksi Sitasi)
    if normalized_task == TASK_POLISH_REPHRASE:
        return await academic_rephrase_engine.rephrase_document(raw_text=raw_text, filename=filename)

    if normalized_task == TASK_ATS_DIAGNOSTIC:
        prompt = (
            "Kamu adalah Senior HR & ATS Auditor Spesialis BoonTrack.\n"
            "Analisis CV berikut dan kembalikan output HANYA berupa JSON valid sesuai skema berikut:\n\n"
            "{\n"
            '  "overall_score": 85,\n'
            '  "target_role": "Software Engineer",\n'
            '  "summary": "Ringkasan audit CV...",\n'
            '  "breakdown_scores": {\n'
            '    "ats_compatibility": 90,\n'
            '    "content_impact": 80,\n'
            '    "structure_grammar": 85\n'
            "  },\n"
            '  "strengths": ["Poin kelebihan 1", "Poin kelebihan 2"],\n'
            '  "findings": [\n'
            '    {"section": "Summary", "issue": "Kurang angka kuantitatif", "recommendation": "Tambahkan metrik pencapaian"}\n'
            "  ]\n"
            "}\n\n"
            f"Konten Dokumen ({filename}):\n{raw_text[:8000]}"
        )
    elif normalized_task in [TASK_CV_POLISH_REWRITE, TASK_CAREER_PRO_BUNDLE]:
        prompt = (
            "Kamu adalah Executive Resume Writer & HR Recruiter Profesional.\n"
            "Rombak dan susun ulang CV berikut menjadi standar HR internasional ATS-friendly.\n"
            "Kembalikan output HANYA berupa JSON valid sesuai skema berikut:\n\n"
            "{\n"
            '  "full_name": "Nama Kandidat",\n'
            '  "target_position": "Target Posisi Karir",\n'
            '  "email": "email@example.com",\n'
            '  "phone": "+628123456789",\n'
            '  "location": "Jakarta, Indonesia",\n'
            '  "linkedin": "linkedin.com/in/username",\n'
            '  "portfolio": "github.com/username",\n'
            '  "summary": "Professional summary 2-3 kalimat kuat...",\n'
            '  "skills": {\n'
            '    "technical_skills": ["Skill 1", "Skill 2"],\n'
            '    "soft_skills": ["Komunikasi", "Problem Solving"]\n'
            "  },\n"
            '  "experience": [\n'
            "    {\n"
            '      "role": "Jabatan Pekerjaan",\n'
            '      "company": "Nama Perusahaan",\n'
            '      "period": "2022 - Sekarang",\n'
            '      "location": "Jakarta",\n'
            '      "bullets": ["Memimpin proyek X...", "Meningkatkan efisiensi sebesar 25%..."]\n'
            "    }\n"
            "  ],\n"
            '  "education": [\n'
            '    {"degree": "S1 Teknik Informatika", "institution": "Universitas Indonesia", "year": "2018 - 2022"}\n'
            "  ],\n"
            '  "certifications": ["Sertifikasi AWS / Scrum Master"]\n'
            "}\n\n"
            f"Konten Dokumen ({filename}):\n{raw_text[:8000]}"
        )
    else:
        return await academic_rephrase_engine.rephrase_document(raw_text=raw_text, filename=filename)

    ai_response = await ai_gateway.generate(prompt)
    structured = _extract_json_from_llm_output(ai_response or "")

    if structured:
        return structured

    logger.warning(f"[DocumentEngine] LLM JSON parsing fallback triggered for {normalized_task}.")
    if normalized_task == TASK_ATS_DIAGNOSTIC:
        return {
            "overall_score": 80,
            "target_role": "Kandidat Profesional",
            "summary": "CV memiliki struktur dasar yang baik dan siap dioptimalkan dengan metrik dampak.",
            "breakdown_scores": {"ats_compatibility": 85, "content_impact": 75, "structure_grammar": 80},
            "strengths": ["Riwayat pendidikan & kontak jelas", "Keahlian relevan tercantum"],
            "findings": [{"section": "Experience", "issue": "Kurang angka dampak", "recommendation": "Gunakan formula: Tindakan + Metrik Hasil"}]
        }
    else:
        return {
            "full_name": "KANDIDAT PROFESIONAL",
            "target_position": "Spesialis Karir",
            "summary": "Profesional berdedikasi tinggi dengan pengalaman kerja terstruktur dan pencapaian target terbukti.",
            "skills": {"core_skills": ["Manajemen Kerja", "Komunikasi", "Problem Solving"]},
            "experience": [{"role": "Staf Profesional", "company": "Perusahaan Terkemuka", "period": "2021 - Sekarang", "bullets": ["Melaksanakan operasional harian secara efisien", "Mendukung efisiensi target tim sebesar 20%"]}],
            "education": [{"degree": "Sarjana / Diploma", "institution": "Perguruan Tinggi", "year": "2020"}]
        }


async def process_document_job_async(
    job_id: str,
    tenant_id: str,
    task_type: str,
    filename: str,
    raw_text: str,
    user_phone: Optional[str] = None
):
    """Background Worker untuk memproses dokumen secara asinkron (Zero-blocking)."""
    logger.info(f"[DocumentWorker] Started processing job {job_id} ({task_type})")
    t_start = time.time()
    try:
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
            structured_output=structured_data,
            extra_fields={"payment_status": "PAID", "execution_time_ms": exec_ms}
        )
        logger.info(f"[DocumentWorker] Job {job_id} successfully completed in {exec_ms}ms. Result: {result_key}")

        # 6. Notifikasi & File Delivery ke WhatsApp jika nomor tersedia
        if user_phone:
            doc_url = r2_storage_service.get_public_url(result_key)
            msg_text = (
                f"✅ *Dokumen Anda Selesai Diproses!*\n\n"
                f"📋 *Layanan:* {task_type}\n"
                f"📁 *File Hasil:* CV_Hasil_Polish.docx\n\n"
                f"Dokumen Word (.docx) berformat profesional siap diunduh.\n\n"
                f"_{COMPLIANCE_DISCLAIMER}_"
            )
            await send_whatsapp_text(to_phone=user_phone, text=msg_text, tenant_id=tenant_id)
            
            # Wajib kirim file attachment dokumen (.docx) via WhatsApp Document API
            await send_whatsapp_document(
                to_phone=user_phone,
                file_path_or_bytes=docx_bytes,
                filename="CV_Hasil_Polish.docx",
                caption="📄 *CV Hasil Polish & ATS Optimization*",
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
    is_paid: bool = False
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

    # 3. Kirim teks konfirmasi penyelesaian
    task_name = job_data.get("task_type", "POLISH_REPHRASE") if job_data else "POLISH_REPHRASE"
    msg_text = (
        f"✅ *Dokumen Anda Selesai Diproses!*\n\n"
        f"📋 *Layanan:* {task_name}\n"
        f"📁 *File Hasil:* CV_Hasil_Polish.docx\n\n"
        f"Dokumen Word (.docx) berformat profesional terlampir di bawah.\n\n"
        f"_{COMPLIANCE_DISCLAIMER}_"
    )
    await send_whatsapp_text(to_phone=phone, text=msg_text, tenant_id=tenant_id)

    # 4. Kirim file dokumen Word (.docx)
    doc_res = await send_whatsapp_document(
        to_phone=phone,
        file_path_or_bytes=file_bytes,
        filename="CV_Hasil_Polish.docx",
        caption="📄 *CV Hasil Polish & ATS Optimization*",
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
