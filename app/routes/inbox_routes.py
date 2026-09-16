import asyncio
import logging
from typing import Optional, Dict, Any, List
from aiohttp import web
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel

from app.services.rotary_routing_service import rotary_routing_service
from app.services.whatsapp_service import log_to_supabase_messages, send_whatsapp_text, normalize_phone_number, get_supabase
from app.services.adapters import WhatsAppAdapter
from app.services.waba_notification_service import dispatch_payment_success_notifications

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/inbox", tags=["BoonTrack Inbox & Rotary Engine"])

# =====================================================================
# Pydantic Schemas
# =====================================================================

class SendManualMessageRequest(BaseModel):
    tenant_id: str
    conversation_id: str
    text: str
    agent_id: Optional[str] = None
    phone_number: Optional[str] = None

class AssignChatRequest(BaseModel):
    tenant_id: str

class UpdateBotModeRequest(BaseModel):
    bot_mode: str  # 'AI_ACTIVE' | 'HUMAN_ACTIVE'
    bot_paused: Optional[bool] = None

class CreateAgentRequest(BaseModel):
    tenant_id: str
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    role: str = "agent"
    presence: str = "offline"
    max_active_chats: int = 10

class UpdateAgentPresenceRequest(BaseModel):
    presence: str  # 'active' | 'break' | 'offline'

class MarkPaidRequest(BaseModel):
    agent_id: Optional[str] = None
    notes: Optional[str] = None

# =====================================================================
# Helper: Dispatch WhatsApp Message to Customer
# =====================================================================

async def _dispatch_whatsapp_message(tenant_id: str, to_phone: str, text: str) -> Dict[str, Any]:
    """Mengirim pesan via adapter WhatsApp (Meta API atau Evolution API)."""
    clean_digits = normalize_phone_number(to_phone)
    if not clean_digits:
        return {"success": False, "error": f"Invalid phone number: {to_phone}"}

    # 1. Coba kirim via Meta API resmi
    try:
        res = await send_whatsapp_text(to_phone=clean_digits, text=text, tenant_id=tenant_id)
        if res:
            return {"success": True, "provider": "META_API", "response": res}
    except Exception as meta_err:
        logger.debug(f"[Inbox Dispatch] Meta API note: {meta_err}")

    # 2. Fallback via Evolution API (WhatsAppAdapter)
    try:
        adapter = WhatsAppAdapter()
        res = await adapter.send_message(tenant_id=tenant_id, to_phone=clean_digits, message=text)
        return {"success": True, "provider": "EVOLUTION_API", "response": res}
    except Exception as evo_err:
        logger.warning(f"[Inbox Dispatch] Evolution API error: {evo_err}")
        return {"success": False, "error": str(evo_err)}


# =====================================================================
# FastAPI Endpoints
# =====================================================================

@router.post("/messages/send")
async def send_manual_cs_message(req: SendManualMessageRequest):
    """
    Kirim Pesan Manual CS & Trigger Human Takeover:
    1. Mengubah percakapan menjadi bot_mode = 'HUMAN_ACTIVE' dan bot_paused = TRUE.
    2. Menghubungkan agen CS ke percakapan (jika agent_id diberikan).
    3. Meneruskan pesan WhatsApp ke nomor telepon pelanggan.
    4. Menyimpan riwayat pesan ke Supabase dengan sender = 'agent'.
    """
    try:
        # 1. Ambil data percakapan yang ada
        conv = rotary_routing_service.get_conversation(req.conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail=f"Percakapan {req.conversation_id} tidak ditemukan.")

        target_phone = req.phone_number or conv.get("phone_number")
        if not target_phone:
            raise HTTPException(status_code=400, detail="Nomor telepon pelanggan tidak ditemukan pada percakapan.")

        # 2. Trigger Human Takeover: bot_mode = 'HUMAN_ACTIVE', bot_paused = TRUE
        updated_conv = rotary_routing_service.set_human_takeover(
            conversation_id=req.conversation_id,
            agent_id=req.agent_id
        )

        # 3. Log pesan ke database/Supabase dengan sender = 'agent'
        await log_to_supabase_messages(
            sender="agent",
            text=req.text,
            tenant_id=req.tenant_id,
            channel="whatsapp",
            user_phone=target_phone,
            conversation_id=req.conversation_id,
            message_text=req.text,
            metadata={"agent_id": req.agent_id, "mode": "HUMAN_ACTIVE"}
        )

        # 4. Dispatch WhatsApp message ke pelanggan
        dispatch_res = await _dispatch_whatsapp_message(
            tenant_id=req.tenant_id,
            to_phone=target_phone,
            text=req.text
        )

        return {
            "success": True,
            "message": "Pesan manual CS terkirim dan Human Takeover aktif.",
            "conversation": updated_conv,
            "dispatch": dispatch_res
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Inbox Send Message Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/assign")
async def assign_conversation(conversation_id: str, req: AssignChatRequest):
    """
    Rotary Routing: Menugaskan percakapan ke agen aktif berikutnya yang paling sedikit beban chat-nya.
    Jika tidak ada agen online, percakapan menjadi 'unassigned' dan ditangani bot ('AI_ACTIVE').
    """
    try:
        res = rotary_routing_service.assign_inbound_chat(
            tenant_id=req.tenant_id,
            conversation_id=conversation_id
        )
        if not res.get("success"):
            raise HTTPException(status_code=400, detail=res.get("error", "Gagal melakukan rotary assignment."))
        return res
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Inbox Assign Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/bot-mode")
async def update_bot_mode(conversation_id: str, req: UpdateBotModeRequest):
    """Mengubah mode bot ('AI_ACTIVE' | 'HUMAN_ACTIVE') dan flag bot_paused."""
    try:
        updated = rotary_routing_service.set_bot_mode(
            conversation_id=conversation_id,
            bot_mode=req.bot_mode,
            bot_paused=req.bot_paused
        )
        return {"success": True, "conversation": updated}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Inbox Bot Mode Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/resolve")
async def resolve_conversation(conversation_id: str):
    """Menyelesaikan sesi percakapan dan mengembalikan mode ke AI_ACTIVE."""
    try:
        updated = rotary_routing_service.resolve_conversation(conversation_id)
        return {"success": True, "conversation": updated}
    except Exception as e:
        logger.error(f"[Inbox Resolve Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents")
async def list_agents(tenant_id: str = Query(..., description="ID / Slug Tenant")):
    """Mengambil daftar seluruh agen CS beserta status presence dan beban chat aktif."""
    try:
        agents = rotary_routing_service.get_tenant_agents(tenant_id)
        return {"success": True, "tenant_id": tenant_id, "agents": agents}
    except Exception as e:
        logger.error(f"[Inbox List Agents Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents")
async def create_agent(req: CreateAgentRequest):
    """Membuat profil agen CS baru untuk tenant."""
    try:
        agent = rotary_routing_service.create_agent(
            tenant_id=req.tenant_id,
            name=req.name,
            phone=req.phone,
            email=req.email,
            role=req.role,
            presence=req.presence,
            max_active_chats=req.max_active_chats
        )
        return {"success": True, "agent": agent}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Inbox Create Agent Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/agents/{agent_id}/presence")
async def update_agent_presence(agent_id: str, req: UpdateAgentPresenceRequest):
    """Mengubah status presence agen ('active', 'break', 'offline')."""
    try:
        agent = rotary_routing_service.update_agent_presence(
            agent_id=agent_id,
            presence=req.presence
        )
        return {"success": True, "agent": agent}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Inbox Update Presence Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# aiohttp Handlers & Registration (Dual-Runner Railway Compliance)
# =====================================================================

async def aiohttp_send_manual_message(request: web.Request):
    try:
        body = await request.json()
        tenant_id = body.get("tenant_id")
        conversation_id = body.get("conversation_id")
        text = body.get("text")
        agent_id = body.get("agent_id")
        phone_number = body.get("phone_number")

        if not tenant_id or not conversation_id or not text:
            return web.json_response({"success": False, "detail": "tenant_id, conversation_id, and text are required."}, status=400)

        conv = rotary_routing_service.get_conversation(conversation_id)
        if not conv:
            return web.json_response({"success": False, "detail": "Conversation not found."}, status=404)

        target_phone = phone_number or conv.get("phone_number")
        if not target_phone:
            return web.json_response({"success": False, "detail": "No phone number for conversation."}, status=400)

        # Trigger Human Takeover
        updated_conv = rotary_routing_service.set_human_takeover(conversation_id=conversation_id, agent_id=agent_id)

        # Log to Supabase
        await log_to_supabase_messages(
            sender="agent",
            text=text,
            tenant_id=tenant_id,
            channel="whatsapp",
            user_phone=target_phone,
            conversation_id=conversation_id,
            message_text=text,
            metadata={"agent_id": agent_id, "mode": "HUMAN_ACTIVE"}
        )

        dispatch_res = await _dispatch_whatsapp_message(tenant_id=tenant_id, to_phone=target_phone, text=text)

        return web.json_response({
            "success": True,
            "message": "Pesan manual CS terkirim dan Human Takeover aktif.",
            "conversation": updated_conv,
            "dispatch": dispatch_res
        })
    except Exception as e:
        logger.error(f"[aiohttp Inbox Send Error] {e}")
        return web.json_response({"success": False, "detail": str(e)}, status=500)


async def aiohttp_assign_conversation(request: web.Request):
    try:
        conversation_id = request.match_info.get("conversation_id")
        body = await request.json()
        tenant_id = body.get("tenant_id")

        if not tenant_id or not conversation_id:
            return web.json_response({"success": False, "detail": "tenant_id and conversation_id are required."}, status=400)

        res = rotary_routing_service.assign_inbound_chat(tenant_id=tenant_id, conversation_id=conversation_id)
        status_code = 200 if res.get("success") else 400
        return web.json_response(res, status=status_code)
    except Exception as e:
        logger.error(f"[aiohttp Inbox Assign Error] {e}")
        return web.json_response({"success": False, "detail": str(e)}, status=500)


async def aiohttp_list_agents(request: web.Request):
    tenant_id = request.query.get("tenant_id")
    if not tenant_id:
        return web.json_response({"success": False, "detail": "tenant_id query param is required."}, status=400)
    try:
        agents = rotary_routing_service.get_tenant_agents(tenant_id)
        return web.json_response({"success": True, "tenant_id": tenant_id, "agents": agents})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)


def register_inbox_routes(app: web.Application):
    """Mendaftarkan seluruh endpoint Inbox ke runner aiohttp."""
    app.router.add_post("/api/v1/inbox/messages/send", aiohttp_send_manual_message)
    app.router.add_post("/api/v1/inbox/conversations/{conversation_id}/assign", aiohttp_assign_conversation)
    app.router.add_get("/api/v1/inbox/agents", aiohttp_list_agents)
    logger.info("[ROUTER] Inbox & Rotary Routing routes registered under /api/v1/inbox.")
