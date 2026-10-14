import asyncio
import logging
from typing import Optional, Dict, Any, List
from aiohttp import web
import json
import uuid
from fastapi import APIRouter, HTTPException, status, Query, Header, Request
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor
from app.core.database import get_db_connection

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
    idempotency_key: Optional[str] = None

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
# Idempotency Helpers
# =====================================================================

def get_idempotency_record(tenant_id: str, key: str) -> Optional[Dict[str, Any]]:
    """Mengecek apakah idempotency key sudah pernah diproses untuk tenant ini."""
    if not key or not tenant_id:
        return None
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, key, tenant_id, conversation_id, response_payload, status, created_at
                FROM inbox_idempotency_keys
                WHERE tenant_id = %s AND key = %s
                LIMIT 1;
                """,
                (tenant_id, key.strip())
            )
            row = cur.fetchone()
            if row:
                res = dict(row)
                res["id"] = str(res["id"])
                return res
            return None
    except Exception as e:
        logger.warning(f"[Idempotency] Error checking key {key}: {e}")
        return None
    finally:
        conn.close()


def save_idempotency_record(
    tenant_id: str,
    key: str,
    conversation_id: str,
    response_payload: Dict[str, Any],
    status_val: str = "COMPLETED"
):
    """Menyimpan atau memperbarui hasil eksekusi ke tabel idempotency."""
    if not key or not tenant_id:
        return
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inbox_idempotency_keys (id, key, tenant_id, conversation_id, response_payload, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, key)
                DO UPDATE SET response_payload = EXCLUDED.response_payload,
                              status = EXCLUDED.status,
                              conversation_id = EXCLUDED.conversation_id;
                """,
                (
                    str(uuid.uuid4()),
                    key.strip(),
                    tenant_id,
                    str(conversation_id),
                    json.dumps(response_payload, default=str),
                    status_val
                )
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"[Idempotency] Error saving key {key}: {e}")
    finally:
        conn.close()


# =====================================================================
# Outbound Channel Lock & Cross-Tenant Leak Prevention
# =====================================================================

def validate_and_lock_outbound_channel(tenant_id: str, conv: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mengambil channel_type, provider, dan channel_connection_id langsung dari row percakapan di database.
    - Menolak jika percakapan bukan milik tenant aktif (403 Forbidden).
    - Memvalidasi bahwa koneksi pengirim benar milik tenant_id aktif (403 Forbidden).
    - Menolak jika kanal tidak memiliki binding eksplisit / channel_connection_id kosong (422 Unprocessable Entity).
    - Menolak jika kanal tujuan offline (422 Unprocessable Entity) tanpa fallback otomatis.
    - Zero Channel Guessing: DILARANG menebak kanal berdasarkan tenant_id atau tenant_slug.
    """
    # 1. Validasi kepemilikan percakapan terhadap tenant aktif (Anti Cross-Tenant Leak)
    tenant_identifiers = rotary_routing_service._resolve_tenant_identifiers(tenant_id)
    if not tenant_identifiers:
        tenant_identifiers = [tenant_id]

    conv_tenant_id = str(conv.get("tenant_id") or "").strip()
    conv_tenant_slug = str(conv.get("tenant_slug") or "").strip()
    is_owner = (conv_tenant_id in tenant_identifiers) or (conv_tenant_slug in tenant_identifiers)
    if not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: Percakapan ini bukan milik tenant aktif (Cross-Tenant Leak Guard)."
        )

    # 2. Cek apakah ini Webchat (storefront widget)
    raw_channel = str(conv.get("channel_type") or "").strip().upper()
    cust_phone = str(conv.get("customer_phone") or conv.get("phone_number") or "").strip()
    if raw_channel == "WEBCHAT" or cust_phone.startswith("webchat_"):
        return {
            "channel_type": "WEBCHAT",
            "provider": "WEBCHAT",
            "channel_connection_id": None,
            "connection": None,
            "is_online": True
        }

    # 3. Strict Channel Binding: HANYA membaca channel_connection_id (Zero Channel Guessing)
    channel_connection_id = conv.get("channel_connection_id")
    if not channel_connection_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Percakapan tidak memiliki binding kanal (channel_connection_id). Zero Channel Guessing melarang penebakan kanal berdasarkan tenant."
        )

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, tenant_id, tenant_slug, provider, channel_type, status, is_connected,
                       phone_number, phone_number_id, waba_id, api_key, gateway_node_url
                FROM whatsapp_connections
                WHERE id = %s
                LIMIT 1;
                """,
                (str(channel_connection_id),)
            )
            conn_row = cur.fetchone()
            if not conn_row:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Koneksi kanal dengan ID {channel_connection_id} tidak ditemukan di sistem."
                )

            # Validasi kepemilikan koneksi pengirim terhadap tenant aktif (Anti Cross-Tenant Leak)
            conn_tid = str(conn_row.get("tenant_id") or "").strip()
            conn_tslug = str(conn_row.get("tenant_slug") or "").strip()
            if not (conn_tid in tenant_identifiers or conn_tslug in tenant_identifiers):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Akses ditolak: Koneksi pengirim bukan milik tenant aktif (Cross-Tenant Leak Guard)."
                )

            # Resolusi channel_type dan provider dari data whatsapp_connections
            conn_provider = str(conn_row.get("provider") or "").strip().upper()
            conn_ctype = str(conn_row.get("channel_type") or "").strip().upper()

            if conn_provider in ("OFFICIAL_META", "META_API", "META") or conn_ctype in ("WABA", "META_API", "META"):
                channel_type = "WABA"
                provider = "OFFICIAL_META"
            elif conn_provider in ("EVOLUTION", "EVOLUTION_API", "BAILEYS") or conn_ctype in ("BAILEYS", "ENGINE", "EVOLUTION", "WAHA", "BOONTRACK_ENGINE"):
                channel_type = "BAILEYS"
                provider = "EVOLUTION"
            else:
                channel_type = conn_ctype or "WABA"
                provider = conn_provider or "OFFICIAL_META"

            # 4. Validasi status online (Tolak eksplisit jika offline, TANPA fallback otomatis)
            is_connected = bool(conn_row.get("is_connected"))
            status_str = str(conn_row.get("status") or "").strip().upper()
            is_online = is_connected or (status_str in ("CONNECTED", "OPEN", "ACTIVE"))

            if not is_online:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Kanal tujuan ({channel_type}) sedang offline atau terputus. Pengiriman pesan ditolak tanpa fallback otomatis."
                )

            return {
                "channel_type": channel_type,
                "provider": provider,
                "channel_connection_id": str(conn_row["id"]),
                "connection": dict(conn_row),
                "is_online": True
            }
    finally:
        conn.close()


# =====================================================================
# Strict Outbound Dispatch (Zero Fallback)
# =====================================================================

async def dispatch_locked_message(
    channel_info: Dict[str, Any],
    tenant_id: str,
    to_phone: str,
    text: str
) -> Dict[str, Any]:
    """
    Mengirim pesan CS strictly melalui kanal yang terkunci.
    Dilarang keras melakukan auto-fallback ke kanal lain bila terjadi error (FAIL-CLOSED).
    """
    channel_type = channel_info["channel_type"]
    provider = channel_info.get("provider") or ("OFFICIAL_META" if channel_type == "WABA" else "EVOLUTION")
    clean_digits = normalize_phone_number(to_phone)
    if not clean_digits and channel_type != "WEBCHAT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Nomor telepon tujuan tidak valid: {to_phone}"
        )

    if channel_type == "WABA":
        conn_data = channel_info.get("connection") or {}
        phone_number_id = conn_data.get("phone_number_id")
        try:
            res = await send_whatsapp_text(
                to_phone=clean_digits,
                text=text,
                tenant_id=tenant_id,
                phone_number_id=phone_number_id
            )
            if not res:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Gagal mengirim pesan melalui Meta Cloud API (WABA): pengiriman ditolak atau gagal. Tidak ada fallback otomatis."
                )
            return {"success": True, "provider": provider, "channel_type": "WABA", "response": res}
        except HTTPException:
            raise
        except Exception as meta_err:
            logger.error(f"[Outbound Lock] Meta API dispatch error: {meta_err}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gagal mengirim pesan via WABA: {meta_err}. Tidak ada fallback otomatis."
            )

    elif channel_type == "BAILEYS":
        try:
            adapter = WhatsAppAdapter()
            res = await adapter.send_message(tenant_id=tenant_id, to_phone=clean_digits, message=text)
            if isinstance(res, dict) and (res.get("error") or res.get("success") is False):
                err_msg = res.get("error") or "Pesan ditolak oleh WhatsApp Engine"
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Gagal mengirim pesan melalui BoonTrack Engine (Baileys): {err_msg}. Tidak ada fallback otomatis."
                )
            return {"success": True, "provider": provider, "channel_type": "BAILEYS", "response": res}
        except HTTPException:
            raise
        except Exception as evo_err:
            logger.error(f"[Outbound Lock] Evolution API dispatch error: {evo_err}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Gagal mengirim pesan via BoonTrack Engine: {evo_err}. Tidak ada fallback otomatis."
            )

    elif channel_type == "WEBCHAT":
        return {"success": True, "provider": "WEBCHAT", "channel_type": "WEBCHAT"}

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Kanal tujuan '{channel_type}' belum didukung untuk outbound CS."
        )


# =====================================================================
# Core Handler for CS Manual Send (Shared by FastAPI and aiohttp)
# =====================================================================

async def execute_send_cs_message(
    tenant_id: str,
    conversation_id: str,
    text: str,
    agent_id: Optional[str] = None,
    phone_number: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    # 1. Idempotency Check
    if idempotency_key:
        idemp_record = get_idempotency_record(tenant_id, idempotency_key)
        if idemp_record:
            if idemp_record.get("status") == "COMPLETED" and idemp_record.get("response_payload"):
                logger.info(f"[Idempotency Hit] Returning cached response for key '{idempotency_key}' (tenant '{tenant_id}').")
                cached = idemp_record["response_payload"]
                if isinstance(cached, str):
                    try:
                        cached = json.loads(cached)
                    except Exception:
                        pass
                return cached
            elif idemp_record.get("status") == "PROCESSING":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Permintaan dengan idempotency key ini sedang diproses."
                )

    # 2. Ambil data percakapan dari database
    conv = rotary_routing_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Percakapan {conversation_id} tidak ditemukan."
        )

    # 3. Validasi Outbound Routing Lock & Anti Cross-Tenant Leak
    channel_info = validate_and_lock_outbound_channel(tenant_id=tenant_id, conv=conv)

    target_phone = phone_number or conv.get("customer_phone") or conv.get("phone_number")
    if not target_phone and channel_info["channel_type"] != "WEBCHAT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nomor telepon pelanggan tidak ditemukan pada percakapan."
        )

    # 4. Trigger Human Takeover: bot_mode = 'HUMAN_ACTIVE', bot_paused = TRUE
    updated_conv = rotary_routing_service.set_human_takeover(
        conversation_id=conversation_id,
        agent_id=agent_id
    )

    # 5. Log pesan ke Supabase dengan sender = 'agent' dan channel terkunci
    channel_name = channel_info["channel_type"].lower()
    await log_to_supabase_messages(
        sender="agent",
        text=text,
        tenant_id=tenant_id,
        channel=channel_name,
        user_phone=target_phone or "webchat_user",
        conversation_id=conversation_id,
        message_text=text,
        metadata={
            "agent_id": agent_id,
            "mode": "HUMAN_ACTIVE",
            "channel_type": channel_info["channel_type"],
            "channel_connection_id": channel_info.get("channel_connection_id")
        }
    )

    # 6. Dispatch locked message (tanpa fallback otomatis)
    dispatch_res = await dispatch_locked_message(
        channel_info=channel_info,
        tenant_id=tenant_id,
        to_phone=target_phone or "",
        text=text
    )

    response_payload = {
        "success": True,
        "message": "Pesan manual CS terkirim dan Human Takeover aktif.",
        "conversation": updated_conv,
        "channel_type": channel_info["channel_type"],
        "channel_connection_id": channel_info.get("channel_connection_id"),
        "provider": channel_info.get("provider"),
        "dispatch": dispatch_res
    }

    # 7. Simpan hasil ke idempotency record
    if idempotency_key:
        save_idempotency_record(
            tenant_id=tenant_id,
            key=idempotency_key,
            conversation_id=conversation_id,
            response_payload=response_payload,
            status_val="COMPLETED"
        )

    return response_payload


# =====================================================================
# FastAPI Endpoints
# =====================================================================

@router.post("/messages/send")
async def send_manual_cs_message(
    req: SendManualMessageRequest,
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
    x_idempotency_key_header: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """
    Kirim Pesan Manual CS & Outbound Routing Lock:
    1. Mengambil channel_type dan channel_connection_id langsung dari database percakapan.
    2. Validasi pencegahan cross-tenant leak.
    3. Tolak jika kanal offline (tanpa auto fallback).
    4. Cek & catat Idempotency Key.
    5. Trigger Human Takeover (bot_mode = 'HUMAN_ACTIVE', bot_paused = TRUE).
    """
    idemp_key = req.idempotency_key or idempotency_key_header or x_idempotency_key_header
    return await execute_send_cs_message(
        tenant_id=req.tenant_id,
        conversation_id=req.conversation_id,
        text=req.text,
        agent_id=req.agent_id,
        phone_number=req.phone_number,
        idempotency_key=idemp_key
    )


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
        idempotency_key = (
            body.get("idempotency_key")
            or request.headers.get("Idempotency-Key")
            or request.headers.get("X-Idempotency-Key")
        )

        if not tenant_id or not conversation_id or not text:
            return web.json_response(
                {"success": False, "detail": "tenant_id, conversation_id, and text are required."},
                status=400
            )

        res = await execute_send_cs_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            text=text,
            agent_id=agent_id,
            phone_number=phone_number,
            idempotency_key=idempotency_key
        )
        return web.json_response(res)
    except HTTPException as he:
        return web.json_response({"success": False, "detail": he.detail}, status=he.status_code)
    except Exception as e:
        logger.error(f"[aiohttp Inbox Send Error] {e}", exc_info=True)
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

