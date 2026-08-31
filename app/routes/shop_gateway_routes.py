import logging
import os
import httpx
from aiohttp import web
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("SHOP_WA_GATEWAY")

# Router untuk Aiohttp Web App
shop_gateway_aiohttp_routes = web.RouteTableDef()

# Router untuk FastAPI App
shop_gateway_fastapi_router = APIRouter(prefix="/api/v1/shop/wa", tags=["Shop WA Gateway"])

WA_ENGINE_BASE_URL = os.getenv("WA_ENGINE_BASE_URL", "http://localhost:8080")
WA_ENGINE_API_KEY = os.getenv("WA_ENGINE_API_KEY", "boontrack_secret_engine_key_2026")


# ---------------------------------------------------------------------------
# 1. HANDLER LOGIC (Shared)
# ---------------------------------------------------------------------------

async def handle_create_instance_logic(tenant_slug: str):
    clean_slug = str(tenant_slug or "").strip().lower()
    if not clean_slug:
        return {"error": "tenant_slug wajib diisi"}, 400

    instance_name = f"boontrack_shop_{clean_slug}"
    supabase = get_supabase()

    instance_payload = {
        "tenant_slug": clean_slug,
        "instance_name": instance_name,
        "session_status": "QR_READY",
        "updated_at": "now()"
    }

    if supabase:
        try:
            supabase.table("shop_wa_instances").upsert(
                instance_payload, 
                on_conflict="tenant_slug"
            ).execute()
        except Exception as db_err:
            logger.warning(f"[DB INSTANCE UPSERT] {db_err}")

    qr_code_base64 = None
    try:
        headers = {"apikey": WA_ENGINE_API_KEY}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{WA_ENGINE_BASE_URL}/instance/create",
                headers=headers,
                json={"instanceName": instance_name, "qrcode": True}
            )
            if resp.status_code in (200, 201):
                res_data = resp.json()
                qr_code_base64 = res_data.get("qrcode", {}).get("base64")
    except Exception as engine_err:
        logger.info(f"[WA Engine Call Offline/Mock] {engine_err}")

    return {
        "status": "success",
        "message": f"Instance untuk store '{clean_slug}' berhasil diinisialisasi.",
        "tenant_slug": clean_slug,
        "instance_name": instance_name,
        "session_status": "QR_READY",
        "qr_code_base64": qr_code_base64
    }, 200


async def handle_get_status_logic(tenant_slug: str):
    clean_slug = str(tenant_slug or "").strip().lower()
    if not clean_slug:
        return {"error": "Query param 'tenant_slug' wajib disertakan"}, 400

    supabase = get_supabase()
    result = {
        "tenant_slug": clean_slug,
        "session_status": "DISCONNECTED",
        "instance_name": f"boontrack_shop_{clean_slug}",
        "qr_code_base64": None
    }

    if supabase:
        try:
            res = supabase.table("shop_wa_instances").select("*").eq("tenant_slug", clean_slug).execute()
            if res.data:
                row = res.data[0]
                result["session_status"] = row.get("session_status", "DISCONNECTED")
                result["qr_code_base64"] = row.get("qr_code_base64")
                result["instance_name"] = row.get("instance_name", result["instance_name"])
        except Exception as db_err:
            logger.warning(f"[DB INSTANCE FETCH] {db_err}")

    return result, 200


# ---------------------------------------------------------------------------
# 2. AIOHTTP ENDPOINTS
# ---------------------------------------------------------------------------

@shop_gateway_aiohttp_routes.post("/api/v1/shop/wa/instance/create")
async def aiohttp_create_instance(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        data, status = await handle_create_instance_logic(body.get("tenant_slug", ""))
        return web.json_response(data, status=status)
    except Exception as e:
        logger.error(f"[AIOHTTP CREATE INSTANCE ERROR] {e}")
        return web.json_response({"error": str(e)}, status=500)


@shop_gateway_aiohttp_routes.get("/api/v1/shop/wa/instance/status")
async def aiohttp_get_instance_status(request: web.Request) -> web.Response:
    try:
        tenant_slug = request.query.get("tenant_slug", "")
        data, status = await handle_get_status_logic(tenant_slug)
        return web.json_response(data, status=status)
    except Exception as e:
        logger.error(f"[AIOHTTP INSTANCE STATUS ERROR] {e}")
        return web.json_response({"error": str(e)}, status=500)


def register_shop_gateway_routes(app: web.Application):
    app.add_routes(shop_gateway_aiohttp_routes)
    logger.info("[ROUTER] Shop WhatsApp Gateway routes registered (Aiohttp).")


# ---------------------------------------------------------------------------
# 3. FASTAPI ENDPOINTS
# ---------------------------------------------------------------------------

class CreateInstancePayload(BaseModel):
    tenant_slug: str

@shop_gateway_fastapi_router.post("/instance/create")
async def fastapi_create_instance(payload: CreateInstancePayload):
    data, _ = await handle_create_instance_logic(payload.tenant_slug)
    return data

@shop_gateway_fastapi_router.get("/instance/status")
async def fastapi_get_instance_status(tenant_slug: str):
    data, _ = await handle_get_status_logic(tenant_slug)
    return data