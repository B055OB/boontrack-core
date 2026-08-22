from fastapi import APIRouter, HTTPException, status
from app.schemas.webchat import WebChatRequest, WebChatResponse
from app.services.webchat_service import WebChatService
from app.services.brain_engine import BrainEngine
from app.services.lead_service import LeadService
from app.services.ai_gateway import AIGateway
from app.repositories.session_repository import SessionRepository
from app.services.whatsapp_service import log_to_supabase_messages
from app.services.ai_service import ai_gateway

router = APIRouter(prefix="/api/webchat", tags=["WebChat Multi-Channel"])

# Inisialisasi Service
_ai_gateway = AIGateway()
_lead_service = LeadService(ai_gateway=_ai_gateway)
_session_repo = SessionRepository()
_brain_engine = BrainEngine(session_repo=_session_repo, ai_gateway=_ai_gateway)
_webchat_service = WebChatService(brain_engine=_brain_engine, lead_service=_lead_service)

# 1. ENDPOINT WEBCHAT CAREER (Untuk Widget di career.boontrack.com)
@router.post("", response_model=WebChatResponse)
@router.post("/", response_model=WebChatResponse)
@router.post("/career", response_model=WebChatResponse)
async def handle_career_webchat(payload: WebChatRequest):
    try:
        # Catat pesan masuk pengunjung web karir
        await log_to_supabase_messages(
            sender=f"Visitor / {payload.session_id[:8]}",
            text=payload.message,
            tenant_id="boontrack-career",
            channel="webchat",
            user_id=payload.session_id,
            user_name=f"Web Visitor #{payload.session_id[:5]}"
        )

        # Generate balasan AI Karir
        ai_reply = await ai_gateway.generate(
            user_message=payload.message,
            context={"user_id": payload.session_id, "feature": "career_webchat"},
            system_prompt="Kamu adalah BoonTrack Career Companion. Bantu pengunjung konsultasi seputar pembuatan CV ATS-friendly, persiapan interview, dan tips karir secara ringkas, solutif, dan ramah."
        )

        if not ai_reply:
            ai_reply = "Halo! Kunci utama CV yang efektif adalah berfokus pada pencapaian terukur dengan format simpel (ATS-friendly). Bagian CV mana yang ingin kamu diskusikan?"

        # Catat balasan bot ke Supabase
        await log_to_supabase_messages(
            sender="BoonTrack AI",
            text=ai_reply,
            tenant_id="boontrack-career",
            channel="webchat",
            user_id=payload.session_id,
            user_name=f"Web Visitor #{payload.session_id[:5]}"
        )

        return WebChatResponse(
            session_id=payload.session_id,
            reply=ai_reply,
            is_lead_qualified=False
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing career webchat: {str(e)}"
        )

# 2. ENDPOINT WEBCHAT B2B BUSINESS
@router.post("/business", response_model=WebChatResponse)
async def handle_business_webchat(payload: WebChatRequest):
    try:
        # Catat chat masuk dari web visitor ke Supabase
        await log_to_supabase_messages(
            sender=f"Visitor / {payload.session_id[:8]}",
            text=payload.message,
            tenant_id="boontrack-career",
            channel="webchat",
            user_id=payload.session_id,
            user_name=f"Web Visitor #{payload.session_id[:5]}"
        )

        result = await _webchat_service.process_business_chat(
            session_id=payload.session_id,
            message=payload.message
        )
        
        raw_reply = result["reply"]
        
        # Lapisan pengaman router
        if any(keyword in str(raw_reply).upper() for keyword in ["QUERY", "START", "FALLBACK", "GENERAL"]):
            reply = "Terima kasih atas pertanyaannya! BoonTrack Group siap membantu kebutuhan otomatisasi AI dan software kustom untuk bisnis Anda. Ada spesifikasi atau alur kerja khusus yang ingin kita diskusikan?"
        else:
            reply = raw_reply

        # Catat balasan bot webchat ke Supabase
        await log_to_supabase_messages(
            sender="BoonTrack AI",
            text=reply,
            tenant_id="boontrack-career",
            channel="webchat",
            user_id=payload.session_id,
            user_name=f"Web Visitor #{payload.session_id[:5]}"
        )

        return WebChatResponse(
            session_id=payload.session_id,
            reply=reply,
            is_lead_qualified=result["is_lead_qualified"]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing business chat: {str(e)}"
        )