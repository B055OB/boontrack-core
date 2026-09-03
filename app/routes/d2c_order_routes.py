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
from app.services.xendit_service import xendit_service

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


# Payload ringkas untuk modal keranjang etalase cepat
class QuickQrisRequest(BaseModel):
    merchant_slug: str
    merchant_name: Optional[str] = "Store"
    product_name: str
    customer_phone: str
    total_amount: int


@d2c_router.post("/api/v1/orders/qris-checkout", summary="Quick QRIS Creation from Storefront Cart")
@d2c_router.post("/v1/orders/qris-checkout", summary="Quick QRIS Creation from Storefront Cart Alias")
@d2c_router.post("/api/v1/orders/qris/create", summary="Order QRIS Creation Alias")
@d2c_router.post("/api/v1/order/qris-checkout", summary="Order QRIS Creation Alias 2")
async def quick_qris_checkout_endpoint(payload: QuickQrisRequest):
    """Endpoint yang dipanggil langsung saat buyer klik 'Bayar QRIS Sekarang' di etalase."""
    try:
        import os
        provider = os.getenv("PAYMENT_GATEWAY_PROVIDER", "").strip().lower()
        if provider == "midtrans" or (not provider and os.getenv("MIDTRANS_SERVER_KEY")):
            from app.services.midtrans_service import midtrans_service
            from uuid import uuid4
            order_id = f"INV-{payload.merchant_slug.upper()[:6]}-{uuid4().hex[:6].upper()}"
            qris_data = await midtrans_service.create_qris_charge(
                order_id=order_id,
                amount=payload.total_amount,
                customer_name=payload.merchant_name or "Buyer",
                customer_phone=payload.customer_phone,
                tenant_id=payload.merchant_slug,
                metadata={"product_name": payload.product_name, "tenant_slug": payload.merchant_slug}
            )
        else:
            qris_data = await xendit_service.create_qris_invoice(
                tenant_slug=payload.merchant_slug,
                amount=payload.total_amount,
                product_name=payload.product_name,
                customer_phone=payload.customer_phone
            )
        return {
            "status": "success",
            "order_id": qris_data.get("external_id"),
            "total_amount": qris_data.get("amount"),
            "qr_string": qris_data.get("qr_string"),
            "qr_code_url": qris_data.get("qr_code_url"),
            "expires_at": qris_data.get("expires_at")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@d2c_router.post("/api/v1/orders/checkout", summary="Submit Full Web Checkout & Trigger Dual QRIS")
@d2c_router.post("/v1/orders/checkout", summary="Submit Full Web Checkout & Trigger Dual QRIS Alias")
@d2c_router.post("/api/v1/order/checkout", summary="Submit Full Web Checkout Alias")
@d2c_router.post("/api/v1/checkout", summary="Direct Checkout Alias")
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
@d2c_router.post("/api/v1/webhooks/payment", summary="Payment Gateway Webhook Listener Alias")
@d2c_router.post("/api/v1/webhook/payment", summary="Payment Gateway Webhook Listener Alias 2")
async def payment_webhook_listener(request: Request, x_callback_token: Optional[str] = Header(None)):
    try:
        body = await request.json()
        reconcile_result = await reconcile_payment_webhook(body)
        return reconcile_result
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"Webhook processing error: {err}")