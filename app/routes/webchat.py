from fastapi import APIRouter, HTTPException, status
from app.schemas.webchat import WebChatRequest, WebChatResponse
from app.services.webchat_service import WebChatService
from app.services.brain_engine import BrainEngine
from app.services.lead_service import LeadService
from app.services.ai_gateway import AIGateway
from app.repo.session_repo import SessionRepository

router = APIRouter(prefix="/api/webchat", tags=["WebChat B2B"])

# Inisialisasi Service
_ai_gateway = AIGateway()
_lead_service = LeadService(ai_gateway=_ai_gateway)
_session_repo = SessionRepository()
_brain_engine = BrainEngine(session_repo=_session_repo, ai_gateway=_ai_gateway)
_webchat_service = WebChatService(brain_engine=_brain_engine, lead_service=_lead_service)

@router.post("/business", response_model=WebChatResponse)
async def handle_business_webchat(payload: WebChatRequest):
    try:
        result = await _webchat_service.process_business_chat(
            session_id=payload.session_id,
            message=payload.message
        )
        return WebChatResponse(
            session_id=payload.session_id,
            reply=result["reply"],
            is_lead_qualified=result["is_lead_qualified"]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing business chat: {str(e)}"
        )