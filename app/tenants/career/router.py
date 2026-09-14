import io
import base64
import logging
from typing import Dict, Any, Optional
from aiohttp import web

from app.tenants.career.config import TENANT_ID, VERIFY_TOKEN, CAREER_PHONE_NUMBER_ID
from app.tenants.career.service import career_service, GLOBAL_USER_STATES
from app.services.whatsapp_service import extract_meta_whatsapp_event

logger = logging.getLogger(__name__)
career_routes = web.RouteTableDef()


@career_routes.get(f"/api/v1/tenants/{TENANT_ID}/webhook/whatsapp")
@career_routes.get(f"/webhook/{TENANT_ID}/whatsapp")
@career_routes.get("/api/whatsapp/webhook")
async def verify_webhook(request: web.Request) -> web.Response:
    """Verifikasi webhook Meta WhatsApp Cloud API untuk Career Assistant."""
    params = request.rel_url.query
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return web.Response(text=params.get("hub.challenge") or "", status=200)
    return web.Response(text="Verification failed", status=403)


@career_routes.post(f"/api/v1/tenants/{TENANT_ID}/webhook/whatsapp")
@career_routes.post(f"/webhook/{TENANT_ID}/whatsapp")
@career_routes.post("/api/whatsapp/webhook")
async def handle_incoming_whatsapp(request: web.Request) -> web.Response:
    """Handler event webhook masuk untuk BoonTrack Career."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(text="INVALID_PAYLOAD", status=400)

    event = extract_meta_whatsapp_event(data)
    if event["is_status"]:
        return web.Response(text="STATUS_IGNORED", status=200)

    if not event["is_message"]:
        return web.Response(text="EVENT_RECEIVED", status=200)

    # Strict Tenant Guard: Jika request masuk ke endpoint career tapi phone_number_id bukan nomor career, log peringatan
    incoming_phone_id = str(event.get("phone_id") or "").strip()
    if incoming_phone_id and CAREER_PHONE_NUMBER_ID and incoming_phone_id != CAREER_PHONE_NUMBER_ID:
        logger.warning(f"[TENANT ISOLATION] Rejected event for mismatched phone_id: {incoming_phone_id} (expected {CAREER_PHONE_NUMBER_ID})")
        return web.Response(text="EVENT_MISMATCHED_TENANT", status=200)

    sender_wa_id = event["from_phone"]
    msg_type = event["msg_type"]
    media_id = event["media_id"]
    filename = event["media_filename"] or "document.pdf"

    user_session = GLOBAL_USER_STATES.setdefault(sender_wa_id, {"step": 0, "mode": "menu", "data": {}})
    user_data = user_session.setdefault("data", {})

    contact_name = event["contact_name"]
    if contact_name and not user_data.get("nama_panggilan"):
        user_data["nama_panggilan"] = contact_name
        user_data["nama_lengkap"] = contact_name

    display_name = career_service.get_user_display_name(sender_wa_id) or contact_name or sender_wa_id

    try:
        # 1. Handling Gambar (Bukti Transfer)
        if msg_type == "image":
            await career_service.handle_image(
                sender_wa_id=sender_wa_id,
                display_name=display_name,
                media_id=media_id
            )
            return web.Response(text="EVENT_RECEIVED", status=200)

        # 2. Handling Dokumen CV (PDF / DOCX)
        if msg_type == "document":
            await career_service.handle_document(
                sender_wa_id=sender_wa_id,
                display_name=display_name,
                media_id=media_id,
                filename=filename
            )
            return web.Response(text="EVENT_RECEIVED", status=200)

        # 3. Handling Teks & Tombol Interaktif
        user_text = event["text"]
        button_id = event["button_id"] or ""

        if not user_text and msg_type not in ["text", "interactive", "button"]:
            await career_service.send_menu_buttons(sender_wa_id)
            return web.Response(text="EVENT_RECEIVED", status=200)

        await career_service.handle_text_or_button(
            sender_wa_id=sender_wa_id,
            display_name=display_name,
            user_text=user_text,
            button_id=button_id
        )

        return web.Response(text="EVENT_RECEIVED", status=200)
    except Exception as e:
        logger.exception(f"[CAREER WEBHOOK ISOLATION] Caught runtime error: {e}")
        return web.Response(text="EVENT_ERROR_ISOLATED", status=200)


# ============================================================================
# AIOHTTP CAREER DOCUMENT PIPELINE ENDPOINTS
# ============================================================================

@career_routes.post("/api/v1/career/upload-cv")
async def aiohttp_upload_cv(request: web.Request) -> web.Response:
    """Ingest raw CV via in-memory stream to Cloudflare R2 and Supabase metadata."""
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }
    try:
        content_type = request.headers.get("Content-Type", "")
        if "multipart/" in content_type:
            reader = await request.multipart()
            file_bytes = None
            filename = "resume.pdf"
            user_id = "anonymous"
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name == "file":
                    filename = part.filename or "resume.pdf"
                    file_bytes = await part.read()
                elif part.name == "user_id":
                    val = await part.text()
                    if val.strip():
                        user_id = val.strip()
            
            if not file_bytes:
                return web.json_response({"status": "error", "message": "No file uploaded"}, status=400, headers=cors_headers)
            
            result = await career_service.ingest_raw_cv(
                user_id=user_id,
                file_buffer=io.BytesIO(file_bytes),
                filename=filename
            )
            return web.json_response(result, status=200, headers=cors_headers)
        else:
            data = await request.json()
            user_id = str(data.get("user_id") or "anonymous").strip()
            filename = data.get("filename") or "resume.pdf"
            b64_data = data.get("file_base64")
            if not b64_data:
                return web.json_response({"status": "error", "message": "Missing file_base64 or multipart file"}, status=400, headers=cors_headers)
            
            file_bytes = base64.b64decode(b64_data)
            result = await career_service.ingest_raw_cv(
                user_id=user_id,
                file_buffer=io.BytesIO(file_bytes),
                filename=filename
            )
            return web.json_response(result, status=200, headers=cors_headers)
    except Exception as e:
        logger.exception(f"[CAREER ROUTER] Upload CV error: {e}")
        return web.json_response({"status": "error", "detail": str(e)}, status=500, headers=cors_headers)


@career_routes.post("/api/v1/career/generate-ats")
async def aiohttp_generate_ats(request: web.Request) -> web.Response:
    """Generate ATS PDF directly to Cloudflare R2 and update Supabase metadata."""
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }
    try:
        data = await request.json()
        user_id = data.get("user_id")
        if not user_id:
            return web.json_response({"status": "error", "message": "Missing user_id"}, status=400, headers=cors_headers)
        
        parsed_content = data.get("parsed_content") or data.get("cv_data") or {}
        analysis_result = data.get("analysis_result") or {}
        resume_id = data.get("resume_id")
        
        result = await career_service.generate_and_upload_ats(
            user_id=str(user_id),
            parsed_content=parsed_content,
            analysis_result=analysis_result,
            resume_id=resume_id
        )
        return web.json_response(result, status=200, headers=cors_headers)
    except Exception as e:
        logger.exception(f"[CAREER ROUTER] Generate ATS error: {e}")
        return web.json_response({"status": "error", "detail": str(e)}, status=500, headers=cors_headers)


# ============================================================================
# FASTAPI CAREER ROUTER
# ============================================================================

from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from pydantic import BaseModel

career_fastapi_router = APIRouter(prefix="/api/v1/career", tags=["Career Document Pipeline"])


class ATSGenerateRequest(BaseModel):
    user_id: str
    resume_id: Optional[str] = None
    parsed_content: Optional[Dict[str, Any]] = None
    analysis_result: Optional[Dict[str, Any]] = None
    cv_data: Optional[Dict[str, Any]] = None


class CVUploadBase64Request(BaseModel):
    user_id: Optional[str] = "anonymous"
    filename: Optional[str] = "resume.pdf"
    file_base64: str


@career_fastapi_router.post("/upload-cv", summary="Upload Raw CV to Cloudflare R2")
async def fastapi_upload_cv(
    file: Optional[UploadFile] = File(None),
    user_id: Optional[str] = Form(None),
):
    if not file:
        raise HTTPException(status_code=400, detail="Missing CV file multipart")
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty CV file")
    
    uid = str(user_id or "anonymous").strip()
    filename = file.filename or "resume.pdf"
    result = await career_service.ingest_raw_cv(
        user_id=uid,
        file_buffer=io.BytesIO(contents),
        filename=filename
    )
    return result


@career_fastapi_router.post("/upload-cv-json", summary="Upload Raw CV via Base64 JSON")
async def fastapi_upload_cv_json(payload: CVUploadBase64Request):
    try:
        raw_bytes = base64.b64decode(payload.file_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 payload")
    
    result = await career_service.ingest_raw_cv(
        user_id=payload.user_id or "anonymous",
        file_buffer=io.BytesIO(raw_bytes),
        filename=payload.filename or "resume.pdf"
    )
    return result


@career_fastapi_router.post("/generate-ats", summary="Generate ATS Resume to Cloudflare R2")
async def fastapi_generate_ats(payload: ATSGenerateRequest):
    parsed_content = payload.parsed_content or payload.cv_data or {}
    analysis_result = payload.analysis_result or {}
    result = await career_service.generate_and_upload_ats(
        user_id=payload.user_id,
        parsed_content=parsed_content,
        analysis_result=analysis_result,
        resume_id=payload.resume_id,
    )
    return result


def register_career_routes(app: web.Application):
    app.add_routes(career_routes)
    logger.info("[ROUTER] Career WhatsApp Webhook & Document Pipeline registered.")