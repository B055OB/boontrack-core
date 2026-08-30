"""app/routes/d2c_order_routes.py
API Core Endpoints for D2C Orders and Payment Webhooks.
"""

from fastapi import APIRouter, HTTPException, Header, Request, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from app.services.checkout_flow_service import (
    create_d2c_order_and_dispatch_qris,
    reconcile_payment_webhook
)

d2c_router = APIRouter(tags=["D2C Checkout & Orders"])


class CheckoutItem(BaseModel):
    product_id: str
    title: str
    price: int
    quantity: int = 1


class CheckoutRequest(BaseModel):
    merchant_slug: str = Field(..., description="Store slug")
    customer_name: str
    customer_phone: str
    items: List[CheckoutItem]
    total_amount: int
    is_digital: bool = True
    delivery_asset_url: Optional[str] = None


@d2c_router.post("/v1/orders/checkout", summary="Submit Web Checkout & Trigger Dual QRIS")
async def submit_checkout_endpoint(payload: CheckoutRequest):
    try:
        result = await create_d2c_order_and_dispatch_qris(
            merchant_slug=payload.merchant_slug,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            items=[item.model_dump() for item in payload.items],
            total_amount=payload.total_amount,
            is_digital=payload.is_digital,
            delivery_asset_url=payload.delivery_asset_url,
        )
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@d2c_router.post("/webhooks/payment", summary="Payment Gateway Webhook Listener")
async def payment_webhook_listener(request: Request, x_callback_token: Optional[str] = Header(None)):
    try:
        body = await request.json()
        reconcile_result = await reconcile_payment_webhook(body)
        return reconcile_result
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Webhook processing error: {err}")