import os
import logging
from typing import Optional, Dict, Any
from aiohttp import web
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.services.whatsapp_service import get_or_create_evolution_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenant/whatsapp", tags=["WhatsApp Infrastructure Control"])

# =====================================================================
# Pydantic Schemas
# =====================================================================
class GatewayCapabilities(BaseModel):
    qr_pairing: bool = True
    pairing_code: bool = True
    multi_agent: bool = False

class GatewayStatusResponse(BaseModel):
    success: bool
    plan_tier: str = "Growth"
    gateway_type: str = "QR_SESSION"
    status: str = "DISCONNECTED"
    phone_number: Optional[str] = None
    last_heartbeat: Optional[str] = None
    pending_messages: int = 0
    disconnect_reason: Optional[str] = None
    qr_raw: Optional[str] = None
    qr_image: Optional[str] = None
    capabilities: GatewayCapabilities = GatewayCapabilities()

# Context Auth Helper
async def get_authenticated_tenant_context() -> dict:
    return {
        "tenant_id": "onlineboost",
        "plan_tier": "Growth"
    }

# =====================================================================
# FastAPI Endpoints
# =====================================================================
@router.get("/status", response_model=GatewayStatusResponse)
async def get_tenant_whatsapp_status(
    auth_context: dict = Depends(get_authenticated_tenant_context)
):
    tenant_id = auth_context.get("tenant_id", "onlineboost")
    plan_tier = auth_context.get("plan_tier", "Growth")

    try:
        session_data = await get_or_create_evolution_session(tenant_id)
        return {
            "plan_tier": plan_tier,
            "gateway_type": "QR_SESSION",
            "pending_messages": 0,
            **session_data
        }
    except Exception as e:
        logger.error(f"[FastAPI WA Status Error] {e}")
        return {
            "success": False,
            "plan_tier": plan_tier,
            "gateway_type": "QR_SESSION",
            "status": "DEGRADED",
            "pending_messages": 0,
            "disconnect_reason": "GATEWAY_UNREACHABLE",
            "capabilities": GatewayCapabilities()
        }

@router.post("/reconnect")
async def trigger_whatsapp_reconnect(
    auth_context: dict = Depends(get_authenticated_tenant_context)
):
    tenant_id = auth_context.get("tenant_id", "onlineboost")
    try:
        session_data = await get_or_create_evolution_session(tenant_id)
        if not session_data.get("success"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
                detail="Gagal memicu reconnect gateway session. Cluster tidak merespons."
            )
        return {"success": True, "message": "Perintah reconnect berhasil dikirim ke gateway.", "data": session_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================================
# aiohttp Handlers & Registration (Runner Aktif Server Railway)
# =====================================================================
async def aiohttp_get_whatsapp_status(request: web.Request):
    tenant_id = request.query.get("tenant", "onlineboost")
    plan_tier = "Growth"
    
    try:
        session_data = await get_or_create_evolution_session(tenant_id)
        return web.json_response({
            "plan_tier": plan_tier,
            "gateway_type": "QR_SESSION",
            "pending_messages": 0,
            **session_data
        })
    except Exception as e:
        logger.error(f"[aiohttp WA Status Error] {e}")
        return web.json_response({
            "success": False,
            "plan_tier": plan_tier,
            "gateway_type": "QR_SESSION",
            "status": "DEGRADED",
            "pending_messages": 0,
            "disconnect_reason": "GATEWAY_UNREACHABLE",
            "capabilities": {
                "qr_pairing": True,
                "pairing_code": True,
                "multi_agent": False
            }
        })

async def aiohttp_trigger_reconnect(request: web.Request):
    tenant_id = request.query.get("tenant", "onlineboost")
    try:
        session_data = await get_or_create_evolution_session(tenant_id)
        if not session_data.get("success"):
            return web.json_response({"success": False, "detail": "Cluster gateway tidak merespons."}, status=503)
        return web.json_response({"success": True, "message": "Perintah reconnect berhasil dikirim ke gateway."})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=503)

def register_whatsapp_control_routes(app: web.Application):
    app.router.add_get("/tenant/whatsapp/status", aiohttp_get_whatsapp_status)
    app.router.add_get("/api/v1/tenant/whatsapp/status", aiohttp_get_whatsapp_status)
    app.router.add_post("/tenant/whatsapp/reconnect", aiohttp_trigger_reconnect)
    app.router.add_post("/api/v1/tenant/whatsapp/reconnect", aiohttp_trigger_reconnect)
    logger.info("[ROUTER] WhatsApp Control full routes registered to aiohttp.")