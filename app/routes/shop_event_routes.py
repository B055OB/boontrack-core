import logging
import asyncio
from aiohttp import web
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
from app.services.transactional_event_service import (
    trigger_order_created,
    trigger_payment_success,
    trigger_cod_confirmation
)

logger = logging.getLogger("SHOP_EVENTS_ROUTER")

shop_event_aiohttp_routes = web.RouteTableDef()
shop_event_fastapi_router = APIRouter(prefix="/api/v1/shop/events", tags=["Shop Transactional Events"])


# --- Shared Dispatcher Logic ---
async def dispatch_event(event_type: str, data: Dict[str, Any]):
    event = str(event_type).upper()
    if event == "ORDER_CREATED":
        return await trigger_order_created(data)
    elif event == "PAYMENT_SUCCESS":
        return await trigger_payment_success(data)
    elif event == "COD_CONFIRMATION":
        return await trigger_cod_confirmation(data)
    else:
        logger.warning(f"[UNKNOWN EVENT TYPE] {event}")
        return False


# --- Aiohttp Endpoint ---
@shop_event_aiohttp_routes.post("/api/v1/shop/events/dispatch")
async def aiohttp_dispatch(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        event_type = body.get("event_type", "")
        data = body.get("data", {})
        asyncio.create_task(dispatch_event(event_type, data))
        return web.json_response({"status": "queued", "event_type": event_type}, status=200)
    except Exception as e:
        logger.error(f"[AIOHTTP EVENT DISPATCH ERROR] {e}")
        return web.json_response({"error": str(e)}, status=500)


def register_shop_event_routes(app: web.Application):
    app.add_routes(shop_event_aiohttp_routes)
    logger.info("[ROUTER] Shop Event routes registered (Aiohttp).")


# --- FastAPI Endpoint ---
class EventPayload(BaseModel):
    event_type: str
    data: Dict[str, Any]

@shop_event_fastapi_router.post("/dispatch")
async def fastapi_dispatch(payload: EventPayload, background_tasks: BackgroundTasks):
    background_tasks.add_task(dispatch_event, payload.event_type, payload.data)
    return {"status": "queued", "event_type": payload.event_type}