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
    is_active: bool = True

class CreateTenantAgentRequest(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    role: str = "agent"  # 'owner' | 'supervisor' | 'agent' | 'admin'
    presence: str = "offline"  # 'active' | 'break' | 'offline'
    max_active_chats: int = 10
    is_active: bool = True

class UpdateTenantAgentRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None  # 'owner' | 'supervisor' | 'agent' | 'admin'
    presence: Optional[str] = None  # 'active' | 'break' | 'offline'
    max_active_chats: Optional[int] = None
    is_active: Optional[bool] = None

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
            max_active_chats=req.max_active_chats,
            is_active=req.is_active
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
# Multi-User / Team Access Tenant Endpoints (Opsi B)
# =====================================================================

@router.get("/{tenant_slug}/agents", summary="List Tenant Team Members / Agents")
async def list_tenant_agents(
    tenant_slug: str,
    include_inactive: bool = Query(True, description="Sertakan anggota tim yang dinonaktifkan")
):
    """
    Daftar seluruh anggota tim toko (Owner, Supervisor, CS Agent)
    beserta status presence, beban chat aktif, role, dan status aktifnya.
    Terisolasi ketat per tenant_slug.
    """
    try:
        agents = rotary_routing_service.get_tenant_agents(tenant_slug, include_inactive=include_inactive)
        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "count": len(agents),
            "agents": agents
        }
    except Exception as e:
        logger.error(f"[Inbox List Tenant Agents Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant_slug}/agents", summary="Create Tenant Team Member / Agent")
async def create_tenant_agent(tenant_slug: str, req: CreateTenantAgentRequest):
    """
    Menambahkan anggota tim operasional baru (Owner, Supervisor, CS Agent)
    untuk toko tertentu.
    """
    try:
        agent = rotary_routing_service.create_agent(
            tenant_id=tenant_slug,
            name=req.name,
            phone=req.phone,
            email=req.email,
            role=req.role,
            presence=req.presence,
            max_active_chats=req.max_active_chats,
            is_active=req.is_active
        )
        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "agent": agent
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Inbox Create Tenant Agent Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{tenant_slug}/agents/{agent_id}", summary="Update Tenant Team Member")
async def update_tenant_agent(
    tenant_slug: str,
    agent_id: str,
    req: UpdateTenantAgentRequest
):
    """
    Memperbarui konfigurasi anggota tim toko (role, max_active_chats, presence, is_active).
    Wajib validasi isolasi tenant: agent_id harus milik tenant_slug tersebut.
    """
    try:
        existing = rotary_routing_service.get_agent(agent_id, tenant_id=tenant_slug)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Anggota tim dengan ID {agent_id} tidak ditemukan untuk tenant '{tenant_slug}'."
            )

        updates = req.model_dump(exclude_unset=True)
        updated = rotary_routing_service.update_agent(
            agent_id=agent_id,
            tenant_id=tenant_slug,
            updates=updates
        )
        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "agent": updated
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Inbox Update Tenant Agent Error] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{tenant_slug}/agents/{agent_id}", summary="Delete / Deactivate Tenant Team Member")
async def delete_tenant_agent(
    tenant_slug: str,
    agent_id: str,
    hard_delete: bool = Query(False, description="Hapus permanen dari database jika True, nonaktifkan jika False")
):
    """
    Menonaktifkan (default soft-delete) atau menghapus permanen akses anggota tim.
    Wajib validasi isolasi tenant: agent_id harus milik tenant_slug tersebut.
    """
    try:
        existing = rotary_routing_service.get_agent(agent_id, tenant_id=tenant_slug)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Anggota tim dengan ID {agent_id} tidak ditemukan untuk tenant '{tenant_slug}'."
            )

        res = rotary_routing_service.delete_agent(
            agent_id=agent_id,
            tenant_id=tenant_slug,
            hard_delete=hard_delete
        )
        return {
            "success": True,
            "tenant_slug": tenant_slug,
            **res
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[Inbox Delete Tenant Agent Error] {e}", exc_info=True)
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


async def aiohttp_tenant_list_agents(request: web.Request):
    tenant_slug = request.match_info.get("tenant_slug")
    if not tenant_slug:
        return web.json_response({"success": False, "detail": "tenant_slug path param is required."}, status=400)
    include_inactive = request.query.get("include_inactive", "true").lower() in ("true", "1")
    try:
        agents = rotary_routing_service.get_tenant_agents(tenant_slug, include_inactive=include_inactive)
        return web.json_response({"success": True, "tenant_slug": tenant_slug, "count": len(agents), "agents": agents})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)


async def aiohttp_tenant_create_agent(request: web.Request):
    tenant_slug = request.match_info.get("tenant_slug")
    if not tenant_slug:
        return web.json_response({"success": False, "detail": "tenant_slug path param is required."}, status=400)
    try:
        body = await request.json()
        agent = rotary_routing_service.create_agent(
            tenant_id=tenant_slug,
            name=body.get("name", ""),
            phone=body.get("phone"),
            email=body.get("email"),
            role=body.get("role", "agent"),
            presence=body.get("presence", "offline"),
            max_active_chats=int(body.get("max_active_chats", 10)),
            is_active=bool(body.get("is_active", True)),
        )
        return web.json_response({"success": True, "tenant_slug": tenant_slug, "agent": agent})
    except ValueError as ve:
        return web.json_response({"success": False, "detail": str(ve)}, status=400)
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)


async def aiohttp_tenant_update_agent(request: web.Request):
    tenant_slug = request.match_info.get("tenant_slug")
    agent_id = request.match_info.get("agent_id")
    if not tenant_slug or not agent_id:
        return web.json_response({"success": False, "detail": "tenant_slug and agent_id are required."}, status=400)
    try:
        existing = rotary_routing_service.get_agent(agent_id, tenant_id=tenant_slug)
        if not existing:
            return web.json_response({"success": False, "detail": f"Agent {agent_id} not found for this tenant."}, status=404)
        body = await request.json()
        updated = rotary_routing_service.update_agent(agent_id=agent_id, tenant_id=tenant_slug, updates=body)
        return web.json_response({"success": True, "tenant_slug": tenant_slug, "agent": updated})
    except ValueError as ve:
        return web.json_response({"success": False, "detail": str(ve)}, status=400)
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)


async def aiohttp_tenant_delete_agent(request: web.Request):
    tenant_slug = request.match_info.get("tenant_slug")
    agent_id = request.match_info.get("agent_id")
    if not tenant_slug or not agent_id:
        return web.json_response({"success": False, "detail": "tenant_slug and agent_id are required."}, status=400)
    hard_delete = request.query.get("hard_delete", "false").lower() in ("true", "1")
    try:
        existing = rotary_routing_service.get_agent(agent_id, tenant_id=tenant_slug)
        if not existing:
            return web.json_response({"success": False, "detail": f"Agent {agent_id} not found for this tenant."}, status=404)
        res = rotary_routing_service.delete_agent(agent_id=agent_id, tenant_id=tenant_slug, hard_delete=hard_delete)
        return web.json_response({"success": True, "tenant_slug": tenant_slug, **res})
    except ValueError as ve:
        return web.json_response({"success": False, "detail": str(ve)}, status=400)
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)


def register_inbox_routes(app: web.Application):
    """Mendaftarkan seluruh endpoint Inbox ke runner aiohttp."""
    app.router.add_post("/api/v1/inbox/messages/send", aiohttp_send_manual_message)
    app.router.add_post("/api/v1/inbox/conversations/{conversation_id}/assign", aiohttp_assign_conversation)
    app.router.add_get("/api/v1/inbox/agents", aiohttp_list_agents)
    # Team member routes
    app.router.add_get("/api/v1/inbox/{tenant_slug}/agents", aiohttp_tenant_list_agents)
    app.router.add_post("/api/v1/inbox/{tenant_slug}/agents", aiohttp_tenant_create_agent)
    app.router.add_patch("/api/v1/inbox/{tenant_slug}/agents/{agent_id}", aiohttp_tenant_update_agent)
    app.router.add_delete("/api/v1/inbox/{tenant_slug}/agents/{agent_id}", aiohttp_tenant_delete_agent)
    logger.info("[ROUTER] Inbox & Rotary Routing routes registered under /api/v1/inbox.")

