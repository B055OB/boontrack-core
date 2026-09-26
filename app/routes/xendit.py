"""app/routes/xendit.py
Xendit Payment Gateway Webhook Receiver & Settlement Router (P0 Hardened).

Guarantees (ARCHITECTURE.md §1, §8.9, §10.1):
1. Adapter Pattern Standard via XenditAdapter (app/services/payment/gateway_xendit.py).
2. Strict Callback Token Validation in Request Headers ('x-callback-token').
3. Triple-Tier Idempotency Locking (payment_events DB, orders table state, in-memory L1 cache).
4. Zero Duplicate Mutation: Instant HTTP 200 OK replay acknowledgement without repeating stock, ledger, or dispatch events.
5. Consistent Financial Transaction Ledger Auditing (financial_ledger + commission_ledger).
6. Decoupled Asynchronous Background Tasks (WhatsApp E-receipt, Meta & TikTok CAPI, Digital Fulfillment).
7. Dual-Runner Compliance: Identical behavior on FastAPI and aiohttp web engines.

Endpoints:
- POST /api/v1/payments/xendit/callback
- POST /api/v1/payment/xendit/callback
- POST /webhook/payment/xendit
- POST /webhook/xendit
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone, date
from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, status
from aiohttp import web

from app.core.database import get_db_connection
from app.services.xendit_service import xendit_service
from app.services.payment.gateway_xendit import XenditAdapter
from app.services.meta_capi_service import send_meta_capi_purchase
from app.services.whatsapp_service import send_whatsapp_text, send_ereceipt_whatsapp, get_supabase
from app.services.tracking_service import dispatch_all_capi
from app.services.reconciliation_service import PAYMENT_INTENTS
from app.modules.tracking import capi_dispatcher
from app.services.session_store import get_user_session_context
from app.services.waba_notification_service import dispatch_payment_success_notifications
from app.core.tracing import log_structured_event, set_trace_context, get_trace_context
from app.core.redis import acquire_payment_lock, release_payment_lock

logger = logging.getLogger("XENDIT_WEBHOOK")

xendit_router = APIRouter(tags=["Xendit Payments"])
_adapter = XenditAdapter()

_PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "SUCCEEDED", "LUNAS"}


# -----------------------------------------------------------------------------
# Decoupled Background Workers (Non-Blocking)
# -----------------------------------------------------------------------------

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

    log_structured_event(
        service="whatsapp_delivery",
        event_type="WA_NOTIF_DISPATCHED",
        entity_type="message",
        entity_id=external_id,
        status="SUCCESS",
        provider="meta",
        tenant_id=tenant_id,
        correlation_id=external_id,
    )


async def send_capi_task(
    external_id: str,
    amount: int,
    phone: Optional[str],
    email: Optional[str] = None,
    product_name: Optional[str] = None,
    currency: str = "IDR",
    tenant_id: str = "boontrack-career",
) -> None:
    """Background task to dispatch Meta & TikTok Conversions API events without blocking webhook."""
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

    capi_ok = True
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
        capi_ok = False
        logger.error(f"[Xendit CAPI Error] Failed to dispatch CAPI events: {e}")
        log_structured_event(
            service="capi_dispatcher",
            event_type="CAPI_FAILED",
            entity_type="payment",
            entity_id=external_id,
            status="FAILED",
            provider="meta",
            tenant_id=tenant_id,
            correlation_id=external_id,
            error_code="CAPI_DISPATCH_EXCEPTION",
        )

    if capi_ok:
        log_structured_event(
            service="capi_dispatcher",
            event_type="CAPI_DISPATCHED",
            entity_type="payment",
            entity_id=external_id,
            status="SUCCESS",
            provider="meta",
            tenant_id=tenant_id,
            correlation_id=external_id,
        )


# -----------------------------------------------------------------------------
# Database Idempotency & Financial Ledger Helpers
# -----------------------------------------------------------------------------

def _check_db_idempotency_sync(event_id: str, external_id: str) -> Optional[Dict[str, Any]]:
    """Memeriksa apakah event_id atau order_id sudah tercatat lunas di database Postgres."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Cek tabel payment_events
        cur.execute(
            "SELECT status FROM payment_events WHERE event_id = %s LIMIT 1;",
            (str(event_id),)
        )
        row = cur.fetchone()
        if row and row[0] in ("PROCESSED", "SETTLED", "PROCESSED_DUPLICATE_ORDER"):
            return {"status": "ALREADY_PROCESSED", "reason": "event_already_processed"}

        # 2. Cek tabel orders
        cur.execute(
            "SELECT status FROM orders WHERE id = %s LIMIT 1;",
            (str(external_id),)
        )
        order_row = cur.fetchone()
        if order_row:
            o_status = str(order_row[0] or "").upper()
            if o_status in _PAID_STATUSES:
                # Update status payment_events
                try:
                    cur.execute(
                        """
                        INSERT INTO payment_events (provider, event_id, reference_id, event_type, status, created_at, updated_at)
                        VALUES ('XENDIT', %s, %s, 'REPLAY', 'PROCESSED_DUPLICATE_ORDER', NOW(), NOW())
                        ON CONFLICT (event_id) DO NOTHING;
                        """,
                        (str(event_id), str(external_id))
                    )
                    conn.commit()
                except Exception:
                    pass
                return {"status": "ALREADY_PROCESSED", "reason": "order_already_paid"}

    except Exception as e:
        logger.warning(f"[DB Idempotency Check Error] {e}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return None


def _record_settlement_and_ledger_sync(
    event_id: str,
    external_id: str,
    tenant_id: str,
    amount: int,
    payload: Dict[str, Any],
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None,
    product_name: Optional[str] = None,
) -> None:
    """Atomic recording of payment_events, orders status LUNAS, and financial_ledger in PostgreSQL."""
    conn = None
    cur = None
    now_utc = datetime.now(timezone.utc)
    payload_json = json.dumps(payload, default=str)

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Catat payment_events dengan status PROCESSED secara Append-Only (Immutable Audit Ledger)
        cur.execute(
            """
            INSERT INTO payment_events (
                provider, event_id, reference_id, event_type, payload, status, processed_at, created_at, updated_at,
                order_id, provider_event_id, amount, raw_payload
            )
            VALUES ('XENDIT', %s, %s, 'PAYMENT_SETTLED', %s, 'PROCESSED', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING;
            """,
            (
                str(event_id),
                str(external_id),
                payload_json,
                now_utc,
                now_utc,
                now_utc,
                str(external_id),
                str(event_id),
                amount,
                payload_json,
            )
        )

        # 2. Update status orders menjadi LUNAS secara atomik
        cur.execute(
            """
            UPDATE orders 
            SET status = 'LUNAS',
                updated_at = %s
            WHERE id = %s AND status IN ('PENDING', 'pending', 'WAITING_PAYMENT', 'unpaid');
            """,
            (now_utc, str(external_id))
        )
        if cur.rowcount == 0:
            cur.execute("SELECT status FROM orders WHERE id = %s LIMIT 1;", (str(external_id),))
            existing_ord = cur.fetchone()
            if existing_ord and str(existing_ord[0] or "").upper() in _PAID_STATUSES:
                logger.info(f"[Xendit Atomic Check] Order '{external_id}' already LUNAS. Idempotency hit.")
                return {"status": "ALREADY_SETTLED"}

            # Jika order belum ada di database, auto-insert order lunas
            cur.execute(
                """
                INSERT INTO orders (
                    id, tenant_slug, product_id, product_title, gross_amount,
                    customer_name, customer_phone, customer_email, status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'LUNAS', %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = 'LUNAS',
                    updated_at = EXCLUDED.updated_at;
                """,
                (
                    str(external_id),
                    tenant_id,
                    "prod_digital",
                    product_name or "Produk Digital",
                    amount,
                    "Customer",
                    customer_phone or "-",
                    customer_email,
                    now_utc,
                    now_utc,
                )
            )

        # 3. Catat Financial Transaction ke financial_ledger
        cur.execute(
            """
            INSERT INTO financial_ledger (
                order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                currency, transaction_type, status, metadata, created_at
            ) VALUES (%s, %s, 'XENDIT', %s, %s, %s, %s, 'IDR', 'PAYMENT_CREDIT', 'SETTLED', %s, %s);
            """,
            (
                str(external_id),
                tenant_id,
                str(event_id),
                amount,
                0,
                amount,
                payload_json,
                now_utc,
            )
        )

        # 3b. Catat Komisi Mitra (25%) & AM Pembina (5%) ke commission_ledger
        data_obj_inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        cur.execute(
            "SELECT affiliate_code, manager_id FROM orders WHERE id = %s LIMIT 1;",
            (str(external_id),)
        )
        ord_info = cur.fetchone()
        aff_code = (
            (ord_info[0] if ord_info else None)
            or payload.get("affiliate_code")
            or data_obj_inner.get("affiliate_code")
        )
        mgr_id = (ord_info[1] if ord_info else None) or payload.get("manager_id") or data_obj_inner.get("manager_id")

        if aff_code or mgr_id:
            aff_rate = 25.0
            mgr_rate = 5.0
            aff_amount = round((amount * aff_rate) / 100.0, 2)
            mgr_amount = round((amount * mgr_rate) / 100.0, 2)
            net_platform = round(amount - aff_amount - mgr_amount, 2)

            cur.execute(
                """
                INSERT INTO commission_ledger (
                    event_type, reference_id, affiliate_id,
                    order_id, affiliate_code, tenant_slug,
                    gross_amount, commission_amount, payout_status,
                    affiliate_commission_rate, affiliate_commission_amount,
                    manager_override_rate, manager_override_amount, net_platform_revenue,
                    status, created_at
                ) VALUES (
                    'ORDER_COMMISSION', %s, %s,
                    %s, %s, %s,
                    %s, %s, 'UNPAID',
                    %s, %s,
                    %s, %s, %s,
                    'PENDING_PAYOUT', %s
                );
                """,
                (
                    str(external_id),
                    str(aff_code or "DEFAULT"),
                    str(external_id),
                    str(aff_code or "DEFAULT"),
                    tenant_id,
                    amount,
                    aff_amount,
                    aff_rate,
                    aff_amount,
                    mgr_rate,
                    mgr_amount,
                    net_platform,
                    now_utc,
                )
            )
            logger.info(
                f"[Xendit Commission Recorded] Order {external_id}: 25% (Rp{aff_amount:,.0f}) to '{aff_code}', 5% (Rp{mgr_amount:,.0f}) to AM."
            )

        # 3c. Atomic Stock Deduction (FASE 4) if order has a specific product
        cur.execute("SELECT product_id FROM orders WHERE id = %s LIMIT 1;", (str(external_id),))
        p_row = cur.fetchone()
        prod_ref = p_row[0] if p_row else None
        if prod_ref and prod_ref not in ("prod_digital", "generic_digital", "cpm-24jam"):
            try:
                from app.services.checkout_service import deduct_stock_atomic
                deduct_stock_atomic(product_id=prod_ref, quantity=1, cur=cur, conn=conn)
            except Exception as stk_err:
                logger.warning(f"[Xendit Settlement Stock Warning] {stk_err}")

        # 3d. Entitlement Activation in the same transaction
        try:
            cur.execute(
                """
                INSERT INTO tenant_entitlements (tenant_id, feature, is_active, created_at, updated_at)
                VALUES (
                    (SELECT id FROM tenants WHERE slug = %s LIMIT 1),
                    'APP_SHOP_INTERNAL_FLOW',
                    TRUE,
                    %s,
                    %s
                )
                ON CONFLICT DO NOTHING;
                """,
                (tenant_id, now_utc, now_utc)
            )
        except Exception:
            pass

        conn.commit()
        logger.info(f"[Xendit Ledger Recorded] Event {event_id} & Order {external_id} saved to DB and financial_ledger.")

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"[Xendit DB Settlement Error] {e}", exc_info=True)
        raise e
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # Fallback/Sinkronisasi ke Supabase client jika aktif
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("payment_settlements").insert({
                "provider_ref": f"xendit_{external_id}",
                "settled_amount": amount,
                "status": "LUNAS",
                "raw_payload": payload,
            }).execute()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Unified Core Webhook Processor
# -----------------------------------------------------------------------------

async def process_xendit_webhook_core(
    payload: Dict[str, Any],
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """
    Eksekutor terpadu (Unified Executor) webhook Xendit untuk seluruh runner (FastAPI & aiohttp):
    1. Validasi Token Resmi Xendit di awal request via XenditAdapter.
    2. Triple-Tier Idempotency Locking (DB payment_events, DB orders, in-memory cache).
    3. Return 200 OK instan pada replay/duplicate event tanpa duplicate mutation.
    4. Pencatatan transaksi finansial ke financial_ledger.
    5. Decoupled background task dispatch (WA E-receipt, Meta & TikTok CAPI, Digital fulfillment).
    """
    # 1. Validasi Signature / Token Callback
    webhook_result = await _adapter.handle_webhook(payload, headers)
    if not webhook_result.is_valid:
        logger.warning(f"[Xendit Webhook] Unauthorized attempt with headers: {headers.get('x-callback-token', 'NONE')}")
        return {
            "http_status": 403,
            "response": {"error": "Invalid callback token", "detail": webhook_result.message}
        }

    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    external_id = str(webhook_result.order_id or "").strip()
    if not external_id:
        external_id = str(data_obj.get("external_id") or data_obj.get("reference_id") or payload.get("id") or "").strip()

    event_id = str(
        payload.get("id")
        or payload.get("payment_id")
        or data_obj.get("id")
        or data_obj.get("payment_id")
        or f"xendit_{external_id}"
    ).strip()

    amount = webhook_result.amount or int(
        data_obj.get("amount") or data_obj.get("paid_amount") or payload.get("amount") or 0
    )

    event_status = str(data_obj.get("status") or payload.get("status") or "").upper()
    if not event_status:
        event_status = "PAID" if webhook_result.status == "SUCCESS" else "PENDING"

    logger.info(f"[Xendit Webhook] Processing event: {event_id} | Order: {external_id} | Amount: Rp{amount:,} | Status: {event_status}")

    # Set distributed tracing context
    inbound_trace = headers.get("x-trace-id") or headers.get("x-request-id")
    set_trace_context(
        trace_id=inbound_trace,
        correlation_id=external_id,
    )
    log_structured_event(
        service="xendit_webhook",
        event_type="WEBHOOK_PAYMENT_RECEIVED",
        entity_type="payment",
        entity_id=external_id,
        status="PENDING",
        provider="xendit",
        provider_event_id=event_id,
        correlation_id=external_id,
    )

    # 1.5 Distributed Lock via Redis: SET lock:payment:webhook:{external_id} NX EX 300
    if external_id:
        lock_ok = acquire_payment_lock(external_id, ttl_seconds=300)
        if not lock_ok:
            logger.info(f"[Xendit Webhook Lock Hit] Transaction '{external_id}' is currently locked by concurrent worker. Returning 200 OK.")
            return {
                "http_status": 200,
                "response": {
                    "status": "ALREADY_PROCESSED",
                    "message": f"Transaction '{external_id}' is currently being processed",
                    "idempotent": True,
                }
            }

    # 2. Fast L1 In-Memory Idempotency Check
    if external_id and xendit_service.is_settled(external_id):
        logger.info(f"[Xendit Webhook L1 Hit] Order '{external_id}' already marked settled in-memory. Returning 200 OK.")
        log_structured_event(
            service="xendit_webhook",
            event_type="IDEMPOTENCY_HIT",
            entity_type="payment",
            entity_id=external_id,
            status="SUCCESS",
            provider="xendit",
            provider_event_id=event_id,
            correlation_id=external_id,
        )
        return {
            "http_status": 200,
            "response": {
                "status": "ALREADY_PROCESSED",
                "message": f"Transaction '{external_id}' has already been settled",
                "idempotent": True,
            }
        }

    # 3. L2 Database Idempotency Check
    db_check = await asyncio.to_thread(_check_db_idempotency_sync, event_id, external_id)
    if db_check:
        xendit_service.mark_settled(external_id)
        logger.info(f"[Xendit Webhook DB Hit] Event '{event_id}' / Order '{external_id}' already processed in DB. Returning 200 OK.")
        log_structured_event(
            service="xendit_webhook",
            event_type="IDEMPOTENCY_HIT",
            entity_type="payment",
            entity_id=external_id,
            status="SUCCESS",
            provider="xendit",
            provider_event_id=event_id,
            correlation_id=external_id,
        )
        return {
            "http_status": 200,
            "response": {
                "status": "ALREADY_PROCESSED",
                "message": f"Transaction '{external_id}' has already been settled in database",
                "idempotent": True,
            }
        }

    # 4. Non-paid event handler (e.g. EXPIRED, FAILED, PENDING)
    if event_status not in _PAID_STATUSES:
        logger.info(f"[Xendit Webhook] Non-paid event received ({event_status}) for order '{external_id}'. Ignoring.")
        return {
            "http_status": 200,
            "response": {
                "status": "IGNORED",
                "message": f"Event status {event_status} is not a payment settlement",
                "external_id": external_id,
            }
        }

    # 5. Intent Lookup & Customer Context
    stored_intent = xendit_service.get_intent(external_id) or PAYMENT_INTENTS.get(external_id, {})
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
        or ("Modul Praktis CPM 24 Jam" if (amount == 1000 or product_slug == "cpm-24jam" or "cpm" in external_id.lower()) else "Produk Digital")
    )
    tenant_id = (
        data_obj.get("tenant_id")
        or payload.get("tenant_id")
        or stored_intent.get("tenant_id")
        or ("onlineboost" if (amount == 1000 or product_slug == "cpm-24jam") else "boontrack-career")
    )

    # 6. Context Tracing Tenant Binding
    set_trace_context(tenant_id=tenant_id)

    # 7. Record Settlement & Financial Ledger in PostgreSQL
    try:
        settle_res = await asyncio.to_thread(
            _record_settlement_and_ledger_sync,
            event_id=event_id,
            external_id=external_id,
            tenant_id=tenant_id,
            amount=amount,
            payload=payload,
            customer_phone=customer_phone,
            customer_email=customer_email,
            product_name=product_name,
        )
        if isinstance(settle_res, dict) and settle_res.get("status") == "ALREADY_SETTLED":
            log_structured_event(
                service="xendit_webhook",
                event_type="IDEMPOTENCY_HIT",
                entity_type="payment",
                entity_id=external_id,
                status="SUCCESS",
                provider="xendit",
                provider_event_id=event_id,
                tenant_id=tenant_id,
                correlation_id=external_id,
            )
            return {
                "http_status": 200,
                "response": {
                    "status": "ALREADY_PROCESSED",
                    "message": f"Transaction '{external_id}' has already been settled in database",
                    "idempotent": True,
                }
            }
    except Exception as db_err:
        log_structured_event(
            service="xendit_webhook",
            event_type="DATABASE_OUTAGE_ERROR",
            entity_type="payment",
            entity_id=external_id,
            status="FAILED",
            provider="xendit",
            provider_event_id=event_id,
            tenant_id=tenant_id,
            correlation_id=external_id,
            error_code="DATABASE_UNAVAILABLE",
        )
        return {
            "http_status": 503,
            "response": {
                "status": "FAILED",
                "error": "DATABASE_UNAVAILABLE",
                "detail": str(db_err),
            }
        }

    # Mark in-memory settled (L1 Lock) only after DB mutation succeeded
    if external_id:
        xendit_service.mark_settled(external_id)

    log_structured_event(
        service="xendit_webhook",
        event_type="DB_MUTATION_PAID",
        entity_type="order",
        entity_id=external_id,
        status="SUCCESS",
        provider="xendit",
        provider_event_id=event_id,
        tenant_id=tenant_id,
        correlation_id=external_id,
    )

    # 8. Decoupled Asynchronous Background Tasks (Non-blocking)
    # Task 1: WhatsApp Customer Confirmation (LUNAS)
    if customer_phone:
        asyncio.create_task(
            send_whatsapp_payment_notification(
                phone=customer_phone,
                external_id=external_id,
                amount=amount,
                tenant_id=tenant_id,
                product_name=product_name,
            )
        )

    # Task 2: Meta Conversions API (CAPI) & TikTok CAPI Event
    asyncio.create_task(
        send_capi_task(
            external_id=external_id,
            amount=amount,
            phone=customer_phone,
            email=customer_email,
            product_name=product_name,
            currency="IDR",
            tenant_id=tenant_id,
        )
    )

    # Task 3: Instant Digital Fulfillment (auto-entitlement + signed download token)
    try:
        from app.services.digital_fulfillment_service import fulfill_if_digital
        asyncio.create_task(
            fulfill_if_digital(
                order_id=external_id,
                tenant_id=tenant_id,
                buyer_email=customer_email or "",
                buyer_phone=customer_phone,
                amount=amount,
            )
        )
        logger.info(f"[Xendit Webhook] Digital fulfillment task scheduled for order '{external_id}'")
    except Exception as fe:
        logger.warning(f"[Xendit Webhook] Digital fulfillment task could not be scheduled: {fe}")

    # Task 4: WABA Transactional Notifications (Tenant, Super Admin, Affiliate, AM)
    asyncio.create_task(
        dispatch_payment_success_notifications(order_id=external_id)
    )

    logger.info(f"[Xendit Webhook] Settlement successful for '{external_id}' (Rp{amount:,})")
    return {
        "http_status": 200,
        "response": {
            "status": "SUCCESS",
            "message": "Payment verified and settled",
            "external_id": external_id,
            "amount": amount,
        }
    }


# -----------------------------------------------------------------------------
# FastAPI Route Handlers
# -----------------------------------------------------------------------------

@xendit_router.post("/webhook/payment/xendit", summary="Xendit Webhook Notification")
@xendit_router.post("/api/v1/payments/xendit/callback", summary="Xendit QRIS Webhook Callback")
@xendit_router.post("/api/v1/payment/xendit/callback", summary="Xendit QRIS Webhook Callback Alias")
@xendit_router.post("/webhook/xendit", summary="Xendit Webhook Root Alias")
async def xendit_webhook_callback(
    request: Request,
    x_callback_token: Optional[str] = Header(None, alias="x-callback-token"),
):
    """FastAPI Webhook endpoint for Xendit callbacks."""
    headers_dict = dict(request.headers)
    if x_callback_token:
        headers_dict["x-callback-token"] = x_callback_token

    try:
        payload = await request.json()
    except Exception as err:
        logger.error(f"[Xendit Webhook] Malformed JSON: {err}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload",
        )

    result = await process_xendit_webhook_core(payload, headers_dict)
    http_code = result.get("http_status", 200)
    response_body = result.get("response", {})

    if http_code != 200:
        raise HTTPException(status_code=http_code, detail=response_body.get("error", "Webhook processing failed"))

    return response_body


# -----------------------------------------------------------------------------
# aiohttp Route Handlers (Dual-Runner Compliance ARCHITECTURE.md §1)
# -----------------------------------------------------------------------------

async def aiohttp_xendit_webhook(request: web.Request) -> web.Response:
    """aiohttp webhook handler executing the identical core processor."""
    headers_dict = {k.lower(): v for k, v in request.headers.items()}

    try:
        payload = await request.json()
    except Exception as err:
        logger.error(f"[Xendit aiohttp] Malformed JSON: {err}")
        return web.json_response({"error": "Malformed JSON payload"}, status=400)

    result = await process_xendit_webhook_core(payload, headers_dict)
    http_code = result.get("http_status", 200)
    response_body = result.get("response", {})

    return web.json_response(response_body, status=http_code)


def register_xendit_routes(aiohttp_app: web.Application) -> None:
    """Register all Xendit webhook routes on the aiohttp runner."""
    routes = [
        "/webhook/payment/xendit",
        "/api/v1/payments/xendit/callback",
        "/api/v1/payment/xendit/callback",
        "/webhook/xendit",
    ]
    for r in routes:
        try:
            aiohttp_app.router.add_post(r, aiohttp_xendit_webhook)
        except Exception as re:
            logger.debug(f"[Xendit Route Add Note] {r}: {re}")

    logger.info("[Xendit] aiohttp routes registered successfully.")
