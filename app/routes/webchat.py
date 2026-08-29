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


# 3. ENDPOINT WEBCHAT DYNAMIC COMMERCE TENANT ({slug}.boontrack.com)
@router.post("/tenant/{slug}", response_model=WebChatResponse, summary="Interactive Webchat for Specific Tenant Slug")
@router.post("/{slug}", response_model=WebChatResponse, summary="Interactive Webchat for Specific Tenant Slug Alias")
async def handle_dynamic_tenant_webchat(slug: str, payload: WebChatRequest):
    """Processes interactive webchat for a specific merchant tenant using CommerceAIEngine."""
    from app.services.ai_engine import commerce_ai_engine
    from app.services.onboarding_service import onboarding_service

    clean_slug = str(slug).strip().lower()
    details = onboarding_service.get_tenant_details_by_slug(clean_slug)
    if not details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with slug '{slug}' not found",
        )

    reply = await commerce_ai_engine.generate_commerce_response(
        tenant_slug=clean_slug,
        user_message=payload.message,
        user_phone=payload.session_id,
        user_name=f"Web Visitor #{payload.session_id[:5]}",
    )

    await log_to_supabase_messages(
        sender="bot",
        text=reply,
        tenant_id=clean_slug,
        channel="webchat",
        user_id=payload.session_id,
        user_name=f"Web Visitor #{payload.session_id[:5]}",
    )

    return WebChatResponse(
        session_id=payload.session_id,
        reply=reply,
        is_lead_qualified=False,
    )

