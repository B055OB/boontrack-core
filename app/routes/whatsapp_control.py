import os
from aiohttp import web
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.gateway.client import HttpWhatsAppGatewayClient
from app.core.gateway.models import GatewayStatusResponse, GatewayCapabilities

router = APIRouter(prefix="/tenant/whatsapp", tags=["WhatsApp Infrastructure Control"])

# Context Auth Helper (dengan fallback aman)
async def get_authenticated_tenant_context() -> dict:
    return {
        "tenant_id": "default_tenant_growth",
        "plan_tier": "Growth"
    }

def get_gateway_client() -> HttpWhatsAppGatewayClient:
    return HttpWhatsAppGatewayClient()

# =====================================================================
# FastAPI Endpoints
# =====================================================================
@router.get("/status", response_model=GatewayStatusResponse)
async def get_tenant_whatsapp_status(
    auth_context: dict = Depends(get_authenticated_tenant_context),
    gateway: HttpWhatsAppGatewayClient = Depends(get_gateway_client)
):
    tenant_id = auth_context["tenant_id"]
    plan_tier = auth_context.get("plan_tier", "Growth")

    try:
        status_data = await gateway.get_session_status(tenant_id)
        return {
            "success": True,
            "plan_tier": plan_tier,
            "gateway_type": status_data.get("gateway_type", "QR_SESSION"),
            "status": status_data.get("status", "DISCONNECTED"),
            "phone_number": status_data.get("phone_number"),
            "last_heartbeat": status_data.get("last_heartbeat"),
            "pending_messages": status_data.get("pending_messages", 0),
            "disconnect_reason": status_data.get("disconnect_reason"),
            "capabilities": GatewayCapabilities(
                qr_pairing=(plan_tier != "Pro Scale"),
                pairing_code=(plan_tier != "Pro Scale"),
                multi_agent=(plan_tier == "Pro Scale")
            )
        }
    except Exception:
        # ARSITEKTUR KEJUJURAN: Gateway mati mengembalikan success=False & DEGRADED
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
    auth_context: dict = Depends(get_authenticated_tenant_context),
    gateway: HttpWhatsAppGatewayClient = Depends(get_gateway_client)
):
    tenant_id = auth_context["tenant_id"]
    success = await gateway.restart_session(tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Gagal memicu reconnect gateway session. Cluster tidak merespons."
        )
    return {"success": True, "message": "Perintah reconnect berhasil dikirim ke gateway."}

# =====================================================================
# aiohttp Handlers & Registration (Runner Aktif Server Railway)
# =====================================================================
async def aiohttp_get_whatsapp_status(request: web.Request):
    client = HttpWhatsAppGatewayClient()
    tenant_id = "default_tenant_growth"
    plan_tier = "Growth"
    
    try:
        status_data = await client.get_session_status(tenant_id)
        return web.json_response({
            "success": True,
            "plan_tier": plan_tier,
            "gateway_type": status_data.get("gateway_type", "QR_SESSION"),
            "status": status_data.get("status", "DISCONNECTED"),
            "phone_number": status_data.get("phone_number"),
            "last_heartbeat": status_data.get("last_heartbeat"),
            "pending_messages": status_data.get("pending_messages", 0),
            "disconnect_reason": status_data.get("disconnect_reason"),
            "capabilities": {
                "qr_pairing": (plan_tier != "Pro Scale"),
                "pairing_code": (plan_tier != "Pro Scale"),
                "multi_agent": (plan_tier == "Pro Scale")
            }
        })
    except Exception:
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
    client = HttpWhatsAppGatewayClient()
    tenant_id = "default_tenant_growth"
    try:
        success = await client.restart_session(tenant_id)
        if not success:
            return web.json_response({"success": False, "detail": "Cluster gateway tidak merespons."}, status=503)
        return web.json_response({"success": True, "message": "Perintah reconnect berhasil dikirim ke gateway."})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=503)

def register_whatsapp_control_routes(app: web.Application):
    app.router.add_get("/tenant/whatsapp/status", aiohttp_get_whatsapp_status)
    app.router.add_get("/api/v1/tenant/whatsapp/status", aiohttp_get_whatsapp_status)
    app.router.add_post("/tenant/whatsapp/reconnect", aiohttp_trigger_reconnect)
    app.router.add_post("/api/v1/tenant/whatsapp/reconnect", aiohttp_trigger_reconnect)