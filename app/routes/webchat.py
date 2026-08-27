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

_ai_gateway = AIGateway()
_lead_service = LeadService(ai_gateway=_ai_gateway)
_session_repo = SessionRepository()
_brain_engine = BrainEngine(session_repo=_session_repo, ai_gateway=_ai_gateway)
_webchat_service = WebChatService(brain_engine=_brain_engine, lead_service=_lead_service)


# 1. ENDPOINT WEBCHAT CAREER (career.boontrack.com)
@router.post("", response_model=WebChatResponse)
@router.post("/", response_model=WebChatResponse)
@router.post("/career", response_model=WebChatResponse)
async def handle_career_webchat(payload: WebChatRequest):
    try:
        tenant = "boontrack-career"

        # 1. Catat chat user
        await log_to_supabase_messages(
            sender=f"Visitor / {payload.session_id[:8]}",
            text=payload.message,
            tenant_id=tenant,
            channel="webchat",
            user_id=payload.session_id,
            user_name=f"Web Visitor #{payload.session_id[:5]}"
        )

        # 2. Respon AI Karir
        ai_reply = await ai_gateway.generate(
            user_message=payload.message,
            context={"user_id": payload.session_id, "feature": "career_webchat"},
            system_prompt="Kamu adalah BoonTrack Career Companion. Bantu konsultasi seputar CV ATS-friendly, persiapan interview, dan tips karir secara ringkas, ramah, dan solutif."
        )

        if not ai_reply:
            ai_reply = "Halo! Kunci utama CV yang efektif adalah berfokus pada pencapaian terukur dengan format ATS-friendly. Bagian CV mana yang ingin kamu konsultasikan?"

        # 3. Catat balasan bot
        await log_to_supabase_messages(
            sender="BoonTrack AI",
            text=ai_reply,
            tenant_id=tenant,
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


# 2. ENDPOINT WEBCHAT HOLDING / GROUP & B2B BUSINESS (boontrack.com)
@router.post("/business", response_model=WebChatResponse)
@router.post("/holding", response_model=WebChatResponse)
@router.post("/group", response_model=WebChatResponse)
async def handle_holding_webchat(payload: WebChatRequest):
    try:
        tenant = "boontrack-holding"

        # 1. Catat chat user holding
        await log_to_supabase_messages(
            sender=f"Visitor / {payload.session_id[:8]}",
            text=payload.message,
            tenant_id=tenant,
            channel="webchat",
            user_id=payload.session_id,
            user_name=f"Holding Visitor #{payload.session_id[:5]}"
        )

        result = await _webchat_service.process_business_chat(
            session_id=payload.session_id,
            message=payload.message
        )
        
        raw_reply = result.get("reply", "")
        
        if any(keyword in str(raw_reply).upper() for keyword in ["QUERY", "START", "FALLBACK", "GENERAL"]):
            reply = "Terima kasih atas pertanyaannya! BoonTrack Group siap membantu kebutuhan otomatisasi AI dan software kustom untuk bisnis Anda. Ada spesifikasi atau alur kerja khusus yang ingin kita diskusikan?"
        else:
            reply = raw_reply

        # 2. Catat balasan bot holding
        await log_to_supabase_messages(
            sender="BoonTrack AI",
            text=reply,
            tenant_id=tenant,
            channel="webchat",
            user_id=payload.session_id,
            user_name=f"Holding Visitor #{payload.session_id[:5]}"
        )

        return WebChatResponse(
            session_id=payload.session_id,
            reply=reply,
            is_lead_qualified=result.get("is_lead_qualified", False)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing holding webchat: {str(e)}"
        )
