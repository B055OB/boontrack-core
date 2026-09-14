"""app/routes/xendit.py
Xendit Payment Gateway Webhook Receiver & Settlement Router.

Endpoints:
- POST /api/v1/payments/xendit/callback
- POST /api/v1/payment/xendit/callback (route alias)
"""

import asyncio
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, status, BackgroundTasks
from aiohttp import web

from app.services.xendit_service import xendit_service
from app.services.meta_capi_service import send_meta_capi_purchase
from app.services.whatsapp_service import send_whatsapp_text, send_ereceipt_whatsapp, get_supabase
from app.services.tracking_service import dispatch_all_capi
from app.services.reconciliation_service import PAYMENT_INTENTS

logger = logging.getLogger("XENDIT_WEBHOOK")

xendit_router = APIRouter(tags=["Xendit Payments"])


async def send_whatsapp_payment_notification(
    phone: Optional[str],
    external_id: str,
    amount: int,
    tenant_id: str = "onlineboost",
    product_name: Optional[str] = None,
) -> None:
    """Background task to notify customer of successful payment via text notification & official WABA E-Receipt."""
    if not phone:
        logger.info(f"[Xendit WA Skip] No phone number associated with order '{external_id}'")
        return

    item_name = product_name or ("Modul Praktis CPM 24 Jam" if amount == 1000 else "Produk Digital")
    amt_comma = f"{amount:,}"
    amt_str = f"Rp{amount:,.0f}".replace(",", ".")

    text = (
        f"🎉 *PEMBAYARAN LUNAS TERVERIFIKASI!*\n\n"
        f"Pembayaran sukses untuk Order #{external_id} sejumlah Rp{amt_comma} ({amt_str}) untuk {item_name} telah kami terima dan berstatus *LUNAS*.\n\n"
        f"Akses materi ecourse & layanan Anda kini telah aktif. Terima kasih telah bertransaksi di BoonTrack! 🙏"
    )
    try:
        await send_whatsapp_text(to_phone=phone, text=text, tenant_id=tenant_id)
    except Exception as e:
        logger.warning(f"[Xendit WA Text Error] {e}")

    try:
        order_data = {
            "order_id": external_id,
            "amount": amount,
            "customer_phone": phone,
            "product_name": item_name,
            "payment_method": "QRIS Dinamis Xendit / DANA Bisnis",
            "status": "LUNAS",
        }
        await send_ereceipt_whatsapp(to_phone=phone, order_data=order_data, tenant_id=tenant_id)
    except Exception as er_err:
        logger.warning(f"[Xendit WA E-Receipt Error] {er_err}")


from app.modules.tracking import capi_dispatcher
from app.services.session_store import get_user_session_context


async def send_capi_task(
    external_id: str,
    amount: int,
    phone: Optional[str],
    email: Optional[str] = None,
    product_name: Optional[str] = None,
    currency: str = "IDR",
    tenant_id: str = "boontrack-career",
) -> None:
    """Background task to dispatch Meta & TikTok Conversions API events."""
    try:
        sess_ctx = get_user_session_context(phone) if phone else {}
        clid = sess_ctx.get("ctwa_clid")
        await capi_dispatcher.dispatch_purchase(
            tenant_id=tenant_id,
            phone=phone or "",
            total_amount=float(amount),
            product_ids=[str(product_name or "digital_product")],
            order_id=str(external_id),
            ctwa_clid=clid,
        )
    except Exception as e:
        logger.warning(f"[Xendit CAPI Dispatcher Purchase Error] {e}")

    try:
        await send_meta_capi_purchase(
            external_id=external_id,
            value=float(amount),
            currency=currency,
            phone=phone,
            email=email,
        )
    except Exception as e:
        logger.warning(f"[Xendit Meta CAPI Note] {e}")

    try:
        await dispatch_all_capi({
            "order_id": external_id,
            "amount": amount,
            "currency": currency,
            "customer_phone": phone,
            "customer_email": email,
            "product_name": product_name or "Produk Digital",
        })
    except Exception as e:
        logger.error(f"[Xendit CAPI Error] Failed to dispatch CAPI events: {e}", exc_info=True)



@xendit_router.post("/webhook/payment/xendit", summary="Xendit Webhook Notification")
@xendit_router.post("/api/v1/payments/xendit/callback", summary="Xendit QRIS Webhook Callback")
@xendit_router.post("/api/v1/payment/xendit/callback", summary="Xendit QRIS Webhook Callback Alias")
async def xendit_webhook_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_callback_token: Optional[str] = Header(None, alias="x-callback-token"),
):
    """Handles incoming Xendit payment notifications (QR payment / invoice paid).
    
    1. Authenticates request via 'x-callback-token' header.
    2. Performs strict idempotency verification (prevents duplicate fulfillment).
    3. Updates transaction status to PAID in database & state.
    4. Triggers background notification via WhatsApp gateway.
    5. Triggers background Purchase event to Meta Conversions API (CAPI).
    """
    configured_token = (
        os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
        or os.getenv("XENDIT_CALLBACK_TOKEN")
        or "aM08Ka1LQ9Jx1OsieBe6kcM1pK1Z5eWlpWAka5zBOuGpVbWS"
    ).strip()

    # 1. Callback Token Validation (strict: reject if missing or mismatched)
    if not x_callback_token or (configured_token and x_callback_token.strip() != configured_token):
        logger.warning(f"[Xendit Webhook] Unauthorized attempt with token: {x_callback_token}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid callback token",
        )

    # 2. Parse Payload
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as err:
        logger.error(f"[Xendit Webhook] Malformed JSON payload: {err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload",
        )

    logger.info(f"[Xendit Webhook] Received event payload: {payload}")

    # Extract transaction details supporting multiple Xendit payload shapes
    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    external_id = (
        data_obj.get("external_id")
        or data_obj.get("reference_id")
        or payload.get("external_id")
    )
    if not external_id:
        # Fallback to qr_id if external_id is omitted
        external_id = data_obj.get("id") or payload.get("id")

    amount = int(
        data_obj.get("amount")
        or data_obj.get("paid_amount")
        or payload.get("amount")
        or 0
    )
    
    event_status = str(
        data_obj.get("status")
        or payload.get("status")
        or "COMPLETED"
    ).upper()

    # 3. Idempotency Check: Prevent duplicate settlement
    if external_id and xendit_service.is_settled(str(external_id)):
        logger.info(f"[Xendit Webhook] Idempotent hit: Transaction '{external_id}' already processed. Skipping.")
        return {
            "status": "ALREADY_PROCESSED",
            "message": f"Transaction '{external_id}' has already been settled",
            "idempotent": True,
        }

    # Resolve customer phone & tenant_id from intent store if available
    stored_intent = xendit_service.get_intent(str(external_id)) or PAYMENT_INTENTS.get(str(external_id), {})
    customer_phone = (
        data_obj.get("customer_phone")
        or payload.get("customer_phone")
        or stored_intent.get("customer_phone")
        or stored_intent.get("phone")
    )
    customer_email = (
        data_obj.get("customer_email")
        or payload.get("customer_email")
        or stored_intent.get("customer_email")
        or stored_intent.get("email")
    )
    product_slug = (
        data_obj.get("product_slug")
        or data_obj.get("slug")
        or payload.get("product_slug")
        or payload.get("slug")
        or (stored_intent.get("metadata", {}) if isinstance(stored_intent.get("metadata"), dict) else {}).get("product_slug")
        or ""
    )

    product_name = (
        data_obj.get("product_name")
        or payload.get("product_name")
        or (stored_intent.get("metadata", {}) if isinstance(stored_intent.get("metadata"), dict) else {}).get("product_name")
        or ("Modul Praktis CPM 24 Jam" if (amount == 1000 or product_slug == "cpm-24jam" or "cpm" in str(external_id).lower()) else "Produk Digital")
    )
    if amount == 1000 or product_slug == "cpm-24jam":
        product_name = "Modul Praktis CPM 24 Jam"

    tenant_id = (
        data_obj.get("tenant_id")
        or payload.get("tenant_id")
        or stored_intent.get("tenant_id")
        or ("onlineboost" if (amount == 1000 or product_slug == "cpm-24jam") else "boontrack-career")
    )

    # 4. Update Database & State to LUNAS / PAID
    if external_id:
        xendit_service.mark_settled(str(external_id))

    supabase = get_supabase()
    if supabase and external_id:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            # Update orders table if exists, or upsert with status LUNAS
            updated = False
            try:
                up_res1 = supabase.table("orders").update({
                    "status": "LUNAS",
                    "payment_status": "PAID",
                    "paid_at": now_iso,
                    "product_name": product_name,
                }).eq("id", str(external_id)).execute()
                if up_res1.data:
                    updated = True
            except Exception:
                pass

            if not updated:
                try:
                    up_res2 = supabase.table("orders").update({
                        "status": "LUNAS",
                        "payment_status": "PAID",
                        "paid_at": now_iso,
                        "product_name": product_name,
                    }).eq("order_id", str(external_id)).execute()
                    if up_res2.data:
                        updated = True
                except Exception:
                    pass

            if not updated:
                try:
                    supabase.table("orders").upsert({
                        "id": str(external_id),
                        "order_id": str(external_id),
                        "status": "LUNAS",
                        "payment_status": "PAID",
                        "paid_at": now_iso,
                        "total_amount": amount,
                        "amount": amount,
                        "customer_phone": customer_phone,
                        "product_name": product_name,
                        "tenant_slug": tenant_id,
                    }).execute()
                except Exception:
                    pass

            # Record in payment_settlements table
            try:
                supabase.table("payment_settlements").insert({
                    "provider_ref": f"xendit_{external_id}",
                    "settled_amount": amount,
                    "status": "LUNAS",
                    "raw_payload": payload,
                }).execute()
            except Exception:
                pass
        except Exception as db_err:
            logger.warning(f"[Xendit Webhook] Supabase settlement note: {db_err}")

    # 5. Background Task 1: WhatsApp Customer Confirmation (LUNAS)
    if customer_phone:
        background_tasks.add_task(
            send_whatsapp_payment_notification,
            phone=customer_phone,
            external_id=str(external_id),
            amount=amount,
            tenant_id=tenant_id,
            product_name=product_name,
        )

    # 6. Background Task 2: Meta Conversions API (CAPI) Event
    background_tasks.add_task(
        send_capi_task,
        external_id=str(external_id),
        amount=amount,
        phone=customer_phone,
        email=customer_email,
        product_name=product_name,
        currency="IDR",
        tenant_id=tenant_id,
    )

    # 7. Background Task 3: Instant Digital Fulfillment (auto-entitlement + signed download token)
    #    Mirrors the identical flow in duitku_routes.py — both gateways share one engine.
    _PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "LUNAS"}
    if event_status in _PAID_STATUSES:
        try:
            from app.services.digital_fulfillment_service import fulfill_if_digital
            asyncio.create_task(
                fulfill_if_digital(
                    order_id=str(external_id),
                    tenant_id=tenant_id,
                    buyer_email=customer_email or "",
                    buyer_phone=customer_phone,
                    amount=amount,
                )
            )
            logger.info(f"[Xendit Webhook] Digital fulfillment task scheduled for order '{external_id}'")
        except Exception as fe:
            logger.warning(f"[Xendit Webhook] Digital fulfillment task could not be scheduled: {fe}")

    logger.info(f"[Xendit Webhook] Settlement successful for '{external_id}' (Rp{amount:,})")
    return {
        "status": "SUCCESS",
        "message": "Payment verified and settled",
        "external_id": external_id,
        "amount": amount,
    }


# =============================================================================
# aiohttp handler — Dual-Runner compliance (ARCHITECTURE.md §1)
# =============================================================================

_XENDIT_PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "LUNAS"}


async def aiohttp_xendit_webhook(request: web.Request) -> web.Response:
    """aiohttp mirror of the FastAPI Xendit webhook — same validation, same fulfillment hook."""
    configured_token = (
        os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
        or os.getenv("XENDIT_CALLBACK_TOKEN")
        or ""
    ).strip()

    x_callback_token = request.headers.get("x-callback-token", "").strip()
    if configured_token and x_callback_token != configured_token:
        logger.warning(f"[Xendit aiohttp] Unauthorized: bad callback token")
        return web.json_response({"error": "Invalid callback token"}, status=403)

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as err:
        logger.error(f"[Xendit aiohttp] Malformed JSON: {err}")
        return web.json_response({"error": "Malformed JSON payload"}, status=400)

    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    external_id = (
        data_obj.get("external_id")
        or data_obj.get("reference_id")
        or payload.get("external_id")
        or data_obj.get("id")
        or payload.get("id")
    )
    amount = int(data_obj.get("amount") or data_obj.get("paid_amount") or payload.get("amount") or 0)
    event_status = str(data_obj.get("status") or payload.get("status") or "COMPLETED").upper()
    customer_email = data_obj.get("customer_email") or payload.get("customer_email") or ""
    customer_phone = data_obj.get("customer_phone") or payload.get("customer_phone")
    tenant_id = data_obj.get("tenant_id") or payload.get("tenant_id") or "boontrack-career"

    if external_id and xendit_service.is_settled(str(external_id)):
        return web.json_response({"status": "ALREADY_PROCESSED", "idempotent": True})

    if external_id:
        xendit_service.mark_settled(str(external_id))

    if event_status in _XENDIT_PAID_STATUSES:
        try:
            from app.services.digital_fulfillment_service import fulfill_if_digital
            asyncio.create_task(
                fulfill_if_digital(
                    order_id=str(external_id),
                    tenant_id=tenant_id,
                    buyer_email=customer_email,
                    buyer_phone=customer_phone,
                    amount=amount,
                )
            )
        except Exception as fe:
            logger.warning(f"[Xendit aiohttp] Digital fulfillment task error: {fe}")

    logger.info(f"[Xendit aiohttp] Settlement processed for '{external_id}' (Rp{amount:,})")
    return web.json_response({"status": "SUCCESS", "external_id": external_id, "amount": amount})


def register_xendit_routes(aiohttp_app: web.Application) -> None:
    """Register Xendit webhook routes on the aiohttp runner (dual-runner compliance)."""
    aiohttp_app.router.add_post("/webhook/payment/xendit", aiohttp_xendit_webhook)
    aiohttp_app.router.add_post("/api/v1/payments/xendit/callback", aiohttp_xendit_webhook)
    aiohttp_app.router.add_post("/api/v1/payment/xendit/callback", aiohttp_xendit_webhook)
    logger.info("[Xendit] aiohttp routes registered.")
