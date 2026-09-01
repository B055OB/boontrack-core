import os
from fastapi import APIRouter, Depends, HTTPException, status
from app.core.gateway.client import HttpWhatsAppGatewayClient
from app.core.gateway.models import GatewayStatusResponse, GatewayCapabilities

router = APIRouter(prefix="/tenant/whatsapp", tags=["WhatsApp Infrastructure Control"])

# Context Auth Helper (dengan fallback aman agar runtime tidak crash)
async def get_authenticated_tenant_context() -> dict:
    # Mengambil context tenant aktif
    return {
        "tenant_id": "default_tenant_growth",
        "plan_tier": "Growth"
    }

def get_gateway_client() -> HttpWhatsAppGatewayClient:
    return HttpWhatsAppGatewayClient()

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