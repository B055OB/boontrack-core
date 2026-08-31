import logging
from aiohttp import web
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.services.subscription_service import create_subscription_invoice, process_successful_subscription

logger = logging.getLogger("SHOP_SUBSCRIPTION_ROUTER")

# Router Aiohttp
shop_subscription_aiohttp_routes = web.RouteTableDef()

# Router FastAPI
shop_subscription_fastapi_router = APIRouter(prefix="/api/v1/shop/subscriptions", tags=["Shop Subscriptions"])


# --- Shared Webhook Logic ---
async def handle_xendit_subscription_webhook_logic(payload: dict):
    status = str(payload.get("status", "")).upper()
    metadata = payload.get("metadata", {}) or {}
    
    # Validasi bahwa ini callback untuk paket langganan SaaS toko
    if status == "PAID":
        tenant_slug = metadata.get("tenant_slug") or "onlineboost"
        plan_tier = metadata.get("plan_tier") or "growth"
        invoice_id = str(payload.get("id") or payload.get("external_id") or "")
        affiliate_id = metadata.get("affiliate_id")
        am_id = metadata.get("am_id")

        result = await process_successful_subscription(
            tenant_slug=tenant_slug,
            plan_tier=plan_tier,
            xendit_invoice_id=invoice_id,
            affiliate_id=affiliate_id,
            am_id=am_id
        )
        return result, 200

    return {"status": "ignored", "reason": f"Invoice status is {status}"}, 200


# --- Aiohttp Endpoints ---

@shop_subscription_aiohttp_routes.post("/api/v1/shop/subscriptions/create")
async def aiohttp_create_sub(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        res = await create_subscription_invoice(
            tenant_slug=body.get("tenant_slug", ""),
            plan_tier=body.get("plan_tier", "growth"),
            customer_email=body.get("customer_email", "merchant@boontrack.com"),
            affiliate_id=body.get("affiliate_id"),
            am_id=body.get("am_id")
        )
        return web.json_response(res, status=200)
    except Exception as e:
        logger.error(f"[CREATE SUB ERROR] {e}")
        return web.json_response({"error": str(e)}, status=500)


@shop_subscription_aiohttp_routes.post("/api/v1/shop/subscriptions/webhook/xendit")
async def aiohttp_xendit_sub_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        res, status = await handle_xendit_subscription_webhook_logic(data)
        return web.json_response(res, status=status)
    except Exception as e:
        logger.error(f"[XENDIT SUB WEBHOOK ERROR] {e}")
        return web.json_response({"error": str(e)}, status=500)


def register_shop_subscription_routes(app: web.Application):
    app.add_routes(shop_subscription_aiohttp_routes)
    logger.info("[ROUTER] Shop Subscription & Commission routes registered (Aiohttp).")


# --- FastAPI Endpoints ---

class CreateSubPayload(BaseModel):
    tenant_slug: str
    plan_tier: str = "growth"
    customer_email: Optional[str] = "merchant@boontrack.com"
    affiliate_id: Optional[str] = None
    am_id: Optional[str] = None

@shop_subscription_fastapi_router.post("/create")
async def fastapi_create_sub(payload: CreateSubPayload):
    return await create_subscription_invoice(
        tenant_slug=payload.tenant_slug,
        plan_tier=payload.plan_tier,
        customer_email=payload.customer_email or "merchant@boontrack.com",
        affiliate_id=payload.affiliate_id,
        am_id=payload.am_id
    )

@shop_subscription_fastapi_router.post("/webhook/xendit")
async def fastapi_xendit_sub_webhook(payload: dict):
    res, _ = await handle_xendit_subscription_webhook_logic(payload)
    return res