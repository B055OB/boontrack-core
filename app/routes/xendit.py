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
from decimal import Decimal
from datetime import datetime, timezone, date
from typing import Dict, Any, Optional, Tuple
from fastapi import APIRouter, Request, Header, HTTPException, status
from aiohttp import web

from app.core.database import get_db_connection, normalize_db_row
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
from app.core.security.payment_auth_guard import (
    CredentialProfileMapper,
    PaymentAuthorizationError,
    PaymentConfigurationError,
)
from app.core.security.provenance_authority import (
    TrustedSettlementVerificationBoundary,
    commit_verified_settlement_transaction,
    ProvenanceSigner,
    ProvenanceVerifier,
    ProvenanceSigningKeyring,
    SettlementProvenanceError,
)

logger = logging.getLogger("XENDIT_WEBHOOK")

xendit_router = APIRouter(tags=["Xendit Payments"])
_adapter = XenditAdapter()

_PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "SUCCEEDED"}

_PROV_SIGNER: Optional[ProvenanceSigner] = None
_PROV_VERIFIER: Optional[ProvenanceVerifier] = None


def _get_provenance_signer_and_verifier() -> Tuple[ProvenanceSigner, ProvenanceVerifier]:
    global _PROV_SIGNER, _PROV_VERIFIER
    raw_env = os.getenv("PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON", "").strip()
    if raw_env:
        try:
            keyring = ProvenanceSigningKeyring.from_env()
            verify_keyring = keyring.export_public_verification_keyring()
            return ProvenanceSigner(keyring), ProvenanceVerifier(verify_keyring)
        except Exception as exc:
            logger.warning(f"[Provenance Keyring Load Warning] {exc}")
    if _PROV_SIGNER is None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        priv = Ed25519PrivateKey.generate()
        priv_hex = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()
        keyring = ProvenanceSigningKeyring({"dev-xendit-key": {"private_key_hex": priv_hex, "status": "ACTIVE"}})
        _PROV_SIGNER = ProvenanceSigner(keyring)
        _PROV_VERIFIER = ProvenanceVerifier(keyring.export_public_verification_keyring())
    return _PROV_SIGNER, _PROV_VERIFIER


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
    """Background task to notify customer of successful payment via WhatsApp Evolution API & WABA with instant class access link."""
    if not phone:
        logger.info(f"[Xendit WA Skip] No phone number associated with order '{external_id}'")
        return

    amt_str = f"Rp{amount:,.0f}".replace(",", ".")
    clean_phone = "".join(c for c in str(phone) if c.isdigit())
    if clean_phone.startswith("0"):
        clean_phone = "62" + clean_phone[1:]

    # Dynamic Lookup from Tenant Catalog in Supabase
    item_name = product_name or "Paket Layanan Resmi"
    access_url = None
    store_name = "OnlineBoost"
    try:
        from app.services.onboarding_service import onboarding_service
        t_details = onboarding_service.get_tenant_details_by_slug(tenant_id) or {}
        store_name = (t_details.get("tenant") or {}).get("name") or tenant_id.title()
        t_meta = t_details.get("metadata") or {}
        t_prods = t_meta.get("products") or []
        for p in t_prods:
            p_price = int(float(p.get("promo_price") or p.get("price") or 0))
            p_name = str(p.get("name") or p.get("title") or "")
            if p_price == int(amount) or (product_name and str(product_name).lower() in p_name.lower()):
                item_name = p_name
                access_url = p.get("access_url")
                break
    except Exception as _p_err:
        logger.debug(f"[Xendit Product Match Note] {_p_err}")

    # Fallback product matching for onlineboost
    if not access_url and tenant_id == "onlineboost":
        if amount == 249000 or (248000 <= amount <= 249000):
            item_name = "Paket Lengkap Kelas Inkubasi CTWA Batch 1"
            access_url = "https://shop.boontrack.com/onlineboost/p/kelas-inkubasi-ctwa-batch-1-scale"
        elif amount == 1500 or (product_name and "penny" in str(product_name).lower()):
            item_name = "Verifikasi Internal Sistem OnlineBoost"
            access_url = None

    access_block = f"🔗 *Detail Link Akses Kelas Instan:*\n{access_url}\n\n" if access_url else ""
    text = (
        f"🎉 *PEMBAYARAN LUNAS TERVERIFIKASI!*\n\n"
        f"Halo Kak! Terima kasih banyak atas kepercayaan Kakak. Pembayaran untuk *{item_name}* senilai *{amt_str}* (No. Invoice: `{external_id}`) telah kami terima dan berstatus *LUNAS* via Xendit QRIS.\n\n"
        f"{access_block}"
        f"📌 *Panduan Akses:*\n"
        f"Silakan klik tautan resmi di atas untuk langsung mengakses materi kelas dan fasilitas eksklusif Kakak.\n\n"
        f"Jika membutuhkan bantuan atau pertanyaan teknis, silakan balas pesan ini kapan saja. Selamat belajar dan bertumbuh bersama *{store_name}*! 🚀"
    )

    # SPECIALIZED CTWA SINGLE-MESSAGE FULFILLMENT (OnlineBoost Batch 1)
    if tenant_id == "onlineboost":
        try:
            from app.services.ctwa_fulfillment_service import fulfill_onlineboost_ctwa_order
            await fulfill_onlineboost_ctwa_order(
                order_id=external_id,
                buyer_name=None,
                buyer_phone=clean_phone,
                amount=amount,
                tenant_id="onlineboost",
            )
            logger.info(f"[Xendit WA Fulfillment] Single verified message fulfilled for OnlineBoost order '{external_id}'")
            return
        except Exception as _ful_err:
            logger.error(f"[Xendit WA Fulfillment Error] {_ful_err}", exc_info=True)
            return

    # 1. Primary Dispatch via WhatsApp Evolution API Gateway (In-Chat Instant Delivery)
    try:
        import httpx
        from app.services.whatsapp.evolution import EVOLUTION_BASE_URL, get_evolution_headers
        target_instance = tenant_id or "onlineboost"
        send_url = f"{EVOLUTION_BASE_URL}/message/sendText/{target_instance}"
        headers = get_evolution_headers()
        send_payload = {
            "number": clean_phone,
            "text": text,
            "textMessage": {"text": text},
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            evo_res = await client.post(send_url, headers=headers, json=send_payload)
            logger.info(f"[Xendit WA Evolution API] Sent instant delivery to {clean_phone} via {target_instance}: status {evo_res.status_code}")
    except Exception as evo_err:
        logger.warning(f"[Xendit WA Evolution Error] {evo_err}")

    # 2. Secondary Dispatch via Meta Cloud API / WABA (if configured)
    try:
        await send_whatsapp_text(to_phone=phone, text=text, tenant_id=tenant_id)
    except Exception as e:
        logger.warning(f"[Xendit WA Text Error] {e}")

    # 3. Official E-Receipt Dispatch
    try:
        order_data = {
            "order_id": external_id,
            "amount": amount,
            "customer_phone": phone,
            "product_name": item_name,
            "payment_method": "Dynamic QRIS (Xendit)",
            "status": "LUNAS",
        }
        await send_ereceipt_whatsapp(to_phone=phone, order_data=order_data, tenant_id=tenant_id)
    except Exception as er_err:
        logger.warning(f"[Xendit WA E-Receipt Error] {er_err}")

    # 4. Trigger PAYMENT_CONFIRMED transactional event hook via WABA with Quick Replies
    try:
        from app.services.transactional_event_service import trigger_payment_confirmed
        await trigger_payment_confirmed({
            "tenant_slug": tenant_id,
            "order_id": external_id,
            "customer_phone": phone,
            "amount": amount,
            "items_summary": item_name,
            "payment_method": "Xendit",
            "payment_status": "PAID",
            "verified": True,
        })
    except Exception as _tx_err:
        logger.warning(f"[Xendit WA Transactional Hook Error] {_tx_err}")

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
    if amount == 1500 or str(product_name or "").upper() == "TEST-PENNY-1500" or "penny" in str(product_name or "").lower():
        logger.info(f"[Xendit CAPI] Skipping CAPI dispatch for penny test order '{external_id}' (amount={amount}, product={product_name}).")
        return

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
        row = normalize_db_row(cur.fetchone(), ("status",))
        if row and str(row.get("status") or "").upper() in ("PROCESSED", "SETTLED", "PROCESSED_DUPLICATE_ORDER"):
            return {"status": "ALREADY_PROCESSED", "reason": "event_already_processed"}

        # 2. Cek tabel orders
        cur.execute(
            "SELECT status, payment_status FROM orders WHERE id = %s LIMIT 1;",
            (str(external_id),)
        )
        order_row = normalize_db_row(cur.fetchone(), ("status", "payment_status"))
        if order_row:
            o_status = str(order_row.get("status") or "").upper()
            o_pay_status = str(order_row.get("payment_status") or "").upper()
            if o_status in _PAID_STATUSES or o_pay_status in _PAID_STATUSES:
                # Best-effort audit record for duplicate order replay:
                # Authoritative `orders` table check above has already confirmed the order is PAID.
                # If the audit INSERT fails, rollback the aborted statement, log a warning, and still
                # return ALREADY_PROCESSED so the replay never re-runs settlement or ledger mutations.
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
                except Exception as replay_audit_err:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    logger.warning(
                        f"[Xendit Replay Audit Warning] Failed to insert PROCESSED_DUPLICATE_ORDER into payment_events "
                        f"for replay event '{event_id}' on already-paid order '{external_id}': {replay_audit_err}"
                    )
                return {"status": "ALREADY_PROCESSED", "reason": "order_already_paid"}

    except Exception as e:
        logger.error(f"[DB Idempotency Check Error - Fail Closed] {e}", exc_info=True)
        raise RuntimeError(
            f"[SECURITY FAIL-CLOSED] Database idempotency lookup failed for event '{event_id}' / order '{external_id}': {e}"
        ) from e
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




def _lookup_persisted_order_sync(external_id: str) -> Optional[Dict[str, Any]]:
    """Authoritative lookup of persisted order in PostgreSQL for tenant resolution and amount verification.
    Strictly joins on canonical tenants table (orders INNER JOIN tenants t ON o.tenant_id = t.id::text).
    """
    if not external_id:
        return None
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                o.id,
                o.tenant_id,
                t.id::text AS canonical_tenant_id,
                t.metadata AS tenant_metadata,
                COALESCE(o.gross_amount, 0) AS gross_amount,
                COALESCE(NULLIF(TRIM(o.product_id), ''), 'prod_digital') AS sku_id,
                COALESCE(UPPER(TRIM(o.status)), '') AS status,
                COALESCE(UPPER(TRIM(o.payment_status)), '') AS payment_status,
                o.metadata AS order_metadata,
                o.customer_name,
                o.customer_phone,
                o.customer_email,
                o.product_title,
                t.slug AS tenant_slug
            FROM orders o
            INNER JOIN tenants t ON o.tenant_id::text = t.id::text
            WHERE o.id = %s
            LIMIT 1;
            """,
            (str(external_id),)
        )
        row = normalize_db_row(
            cur.fetchone(),
            (
                "id",
                "tenant_id",
                "canonical_tenant_id",
                "tenant_metadata",
                "gross_amount",
                "sku_id",
                "status",
                "payment_status",
                "order_metadata",
                "customer_name",
                "customer_phone",
                "customer_email",
                "product_title",
                "tenant_slug",
            ),
        )
        if row:
            raw_meta = row.get("order_metadata")
            t_meta = row.get("tenant_metadata")
            raw_amt = row.get("gross_amount")
            parsed_amt = 0
            if raw_amt is not None and not isinstance(raw_amt, bool):
                try:
                    parsed_amt = int(Decimal(str(raw_amt)))
                except Exception:
                    parsed_amt = 0
            return {
                "id": str(row.get("id")),
                "tenant_id": str(row.get("tenant_id")) if row.get("tenant_id") else None,
                "canonical_tenant_id": str(row.get("canonical_tenant_id")) if row.get("canonical_tenant_id") else None,
                "tenant_metadata": t_meta if isinstance(t_meta, dict) else {},
                "gross_amount": parsed_amt,
                "sku_id": str(row.get("sku_id") or "prod_digital"),
                "status": row.get("status"),
                "payment_status": row.get("payment_status"),
                "order_metadata": raw_meta if isinstance(raw_meta, dict) else {},
                "customer_name": row.get("customer_name"),
                "customer_phone": row.get("customer_phone"),
                "customer_email": row.get("customer_email"),
                "product_title": row.get("product_title"),
                "tenant_slug": str(row.get("tenant_slug")) if row.get("tenant_slug") else None,
            }
    except Exception as e:
        logger.error(f"[Xendit Webhook] Order lookup failed for '{external_id}': {e}", exc_info=True)
        raise RuntimeError(f"Database lookup failed for order '{external_id}': {e}") from e
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

        # 2. Update status orders menjadi PAID secara atomik (hanya jika belum PAID/LUNAS)
        cur.execute(
            """
            UPDATE orders
            SET status = 'PAID',
                payment_status = 'PAID',
                order_status = 'PAID',
                paid_at = COALESCE(orders.paid_at, %s),
                updated_at = %s
            WHERE id = %s
              AND (status IN ('PENDING', 'pending', 'WAITING_PAYMENT', 'unpaid') OR payment_status IN ('PENDING', 'pending', 'WAITING_PAYMENT', 'unpaid') OR status IS NULL)
              AND COALESCE(UPPER(status), '') NOT IN ('PAID', 'SETTLED', 'COMPLETED', 'SUCCEEDED', 'LUNAS');
            """,
            (now_utc, now_utc, str(external_id))
        )
        if cur.rowcount == 0:
            cur.execute("SELECT status, payment_status FROM orders WHERE id = %s LIMIT 1;", (str(external_id),))
            existing_ord = normalize_db_row(cur.fetchone(), ("status", "payment_status"))
            if existing_ord and (
                str(existing_ord.get("status") or "").upper() in _PAID_STATUSES
                or str(existing_ord.get("payment_status") or "").upper() in _PAID_STATUSES
            ):
                logger.info(f"[Xendit Atomic Check] Order '{external_id}' already PAID/LUNAS. Idempotency hit.")
                return {"status": "ALREADY_SETTLED"}


            # Phase 1 Step 2B.2: Ghost order auto-insert permanently eliminated (fail-closed)
            raise ValueError(
                f"[GHOST_ORDER_REJECTED] Order '{external_id}' does not exist in database. Auto-insertion is prohibited."
            )

        # 3. Catat Financial Transaction ke financial_ledger (Dibatasi Unique Index di Postgres)
        cur.execute(
            """
            INSERT INTO financial_ledger (
                order_id, tenant_id, provider, event_id, gross_amount, fee_amount, net_amount,
                currency, transaction_type, status, metadata, created_at
            ) VALUES (%s, %s, 'XENDIT', %s, %s, %s, %s, 'IDR', 'PAYMENT_CREDIT', 'SETTLED', %s, %s)
            ON CONFLICT (order_id) WHERE (transaction_type = 'PAYMENT_CREDIT') DO NOTHING;
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
        ord_info = normalize_db_row(cur.fetchone(), ("affiliate_code", "manager_id"))
        aff_code = (
            (ord_info.get("affiliate_code") if ord_info else None)
            or payload.get("affiliate_code")
            or data_obj_inner.get("affiliate_code")
        )
        mgr_id = (
            (ord_info.get("manager_id") if ord_info else None)
            or payload.get("manager_id")
            or data_obj_inner.get("manager_id")
        )


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
                )
                ON CONFLICT (reference_id) DO NOTHING;
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
        p_row = normalize_db_row(cur.fetchone(), ("product_id",))
        prod_ref = p_row.get("product_id") if p_row else None

        if prod_ref and prod_ref not in ("prod_digital", "generic_digital", "cpm-24jam"):
            try:
                from app.services.checkout_service import deduct_stock_atomic
                deduct_stock_atomic(product_id=prod_ref, quantity=1, cur=cur, conn=conn)
            except Exception as stk_err:
                logger.warning(f"[Xendit Settlement Stock Warning] {stk_err}")

        # 3d. Entitlement Activation in the same transaction with SAVEPOINT protection
        try:
            cur.execute("SAVEPOINT entitlement_sp;")
            cur.execute(
                """
                INSERT INTO tenant_entitlements (tenant_id, feature_code, status, updated_at)
                VALUES (
                    (SELECT id FROM tenants WHERE slug = %s LIMIT 1),
                    'APP_SHOP_INTERNAL_FLOW',
                    'ACTIVE',
                    %s
                )
                ON CONFLICT DO NOTHING;
                """,
                (tenant_id, now_utc)
            )
            cur.execute("RELEASE SAVEPOINT entitlement_sp;")
        except Exception as ent_err:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT entitlement_sp;")
            except Exception:
                pass
            logger.debug(f"[Xendit Entitlement Note] {ent_err}")

        conn.commit()
        logger.info(f"[Xendit Ledger Recorded] Event {event_id} & Order {external_id} saved to DB and financial_ledger.")

        # 3e. CRM SSOT: Idempotent contact sync from settled order (Fail-safe)
        try:
            from app.services.crm_service import sync_contact_from_order
            sync_contact_from_order({
                "order_id": str(external_id),
                "tenant_id": tenant_id,
                "tenant_slug": tenant_id,
                "customer_phone": customer_phone,
                "customer_name": "Customer",
                "customer_email": customer_email,
                "gross_amount": amount,
                "paid_at": now_utc,
                "status": "LUNAS",
            })
        except Exception as _crm_err:
            logger.warning(f"[Xendit CRM SSOT Fail-safe Note] {_crm_err}")

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
            supabase.table("payment_settlements").upsert({
                "provider_ref": f"xendit_{external_id}",
                "settled_amount": amount,
                "status": "PAID",
                "raw_payload": payload,
            }, on_conflict="provider_ref").execute()
            supabase.table("orders").update({
                "status": "LUNAS",
                "payment_status": "PAID",
            }).eq("id", str(external_id)).execute()
        except Exception as sb_err:
            logger.debug(f"[Xendit Supabase Settlement Note] {sb_err}")



# -----------------------------------------------------------------------------
# Unified Core Webhook Processor
# -----------------------------------------------------------------------------

async def process_xendit_webhook_core(
    payload: Dict[str, Any],
    headers: Dict[str, str],
) -> Dict[str, Any]:
    """
    Eksekutor terpadu (Unified Executor) webhook Xendit untuk seluruh runner (FastAPI & aiohttp):
    1. Rejection of SaaS AI Quota Top-Up webhooks with HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD.
    2. Authoritative inside-out order lookup in PostgreSQL (orders INNER JOIN tenants).
    3. Multi-tenant credential profile binding & secret verification via CredentialProfileMapper.
    4. Strict IDR currency and integer amount verification against authoritative order gross_amount.
    5. Provably minted settlement capability via TrustedSettlementVerificationBoundary.
    6. Atomic persistence via commit_verified_settlement_transaction with 6-point composite idempotency.
    7. CTO Decision #4 Late Settlement Quarantine for terminal orders (EXPIRED, CANCELLED, FAILED).
    8. Decoupled background task dispatch (WA, CAPI) only on verified non-quarantined settlements.
    """
    data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    external_id = str(
        data_obj.get("external_id")
        or data_obj.get("reference_id")
        or payload.get("external_id")
        or payload.get("id")
        or ""
    ).strip()

    # Step 1: SaaS Billing / Quota Top-Up Hold (CTO Decision #2)
    if external_id.startswith("TOPUP-") or external_id.startswith("TOPUP_"):
        logger.warning(f"[Xendit Webhook] Blocked SaaS Billing Quota Top-Up webhook: {external_id}")
        return {
            "http_status": 403,
            "response": {
                "status": "REJECTED",
                "error": "SAAS_BILLING_WEBHOOK_STAGE3_HOLD",
                "error_code": "SAAS_BILLING_WEBHOOK_STAGE3_HOLD",
                "detail": "SAAS_BILLING_WEBHOOK_STAGE3_HOLD: SaaS billing and quota top-up webhooks are deferred to dedicated milestone.",
            }
        }

    # Step 2: Authoritative Order Lookup inside-out
    if not external_id:
        return {
            "http_status": 404,
            "response": {
                "status": "ORDER_NOT_FOUND",
                "error": "ORDER_NOT_FOUND",
                "error_code": "ORDER_NOT_FOUND",
                "detail": "Missing external_id in Xendit webhook payload.",
            }
        }

    try:
        persisted_order = await asyncio.to_thread(_lookup_persisted_order_sync, external_id)
    except Exception as db_err:
        logger.error(f"[Xendit Webhook] Order lookup database error: {db_err}")
        return {
            "http_status": 503,
            "response": {
                "status": "FAILED",
                "error": "DATABASE_UNAVAILABLE",
                "error_code": "DATABASE_UNAVAILABLE",
                "detail": str(db_err),
            }
        }

    if not persisted_order:
        logger.warning(f"[Xendit Webhook] Order '{external_id}' not found or canonical tenant binding missing.")
        return {
            "http_status": 404,
            "response": {
                "status": "ORDER_NOT_FOUND",
                "error": "ORDER_NOT_FOUND",
                "error_code": "ORDER_NOT_FOUND",
                "detail": f"Order '{external_id}' not found in database or not bound to canonical tenant",
                "external_id": external_id,
            }
        }

    # Step 3: Tenant claim verification
    inbound_tenant = str(
        payload.get("tenant_id")
        or payload.get("tenant_slug")
        or data_obj.get("tenant_id")
        or data_obj.get("tenant_slug")
        or ""
    ).strip()
    if inbound_tenant:
        ord_can_tenant = str(persisted_order.get("canonical_tenant_id") or "").strip()
        ord_slug = str(persisted_order.get("tenant_slug") or "").strip()
        if inbound_tenant != ord_can_tenant and inbound_tenant != ord_slug:
            logger.warning(f"[Xendit Webhook] Inbound tenant '{inbound_tenant}' conflicts with order tenant '{ord_can_tenant}' / '{ord_slug}'.")
            return {
                "http_status": 403,
                "response": {
                    "status": "REJECTED",
                    "error": "ORDER_TENANT_MISMATCH",
                    "error_code": "ORDER_TENANT_MISMATCH",
                    "detail": f"Inbound tenant '{inbound_tenant}' conflicts with order canonical tenant '{ord_can_tenant}'.",
                }
            }

    # Step 4: Event status & non-paid handling
    event_status = str(data_obj.get("status") or payload.get("status") or "").strip().upper()
    if not event_status:
        event_status = "PAID"
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

    # Step 5: Currency & Amount validation
    raw_currency = data_obj.get("currency") if "currency" in data_obj else payload.get("currency")
    if raw_currency is not None and str(raw_currency).strip().upper() != "IDR":
        return {
            "http_status": 422,
            "response": {
                "status": "REJECTED",
                "error": "PROVENANCE_INVALID_CURRENCY",
                "error_code": "PROVENANCE_INVALID_CURRENCY",
                "detail": f"Unsupported currency '{raw_currency}'; expected 'IDR'.",
            }
        }

    raw_amount = data_obj.get("amount") if "amount" in data_obj else payload.get("amount")
    if isinstance(raw_amount, bool):
        return {
            "http_status": 422,
            "response": {
                "status": "REJECTED",
                "error": "PROVENANCE_INVALID_AMOUNT",
                "error_code": "PROVENANCE_INVALID_AMOUNT",
                "detail": "Payment amount cannot be a boolean.",
            }
        }
    if isinstance(raw_amount, float):
        if raw_amount != int(raw_amount):
            return {
                "http_status": 422,
                "response": {
                    "status": "REJECTED",
                    "error": "PROVENANCE_INVALID_AMOUNT",
                    "error_code": "PROVENANCE_INVALID_AMOUNT",
                    "detail": f"Fractional amount '{raw_amount}' not permitted for IDR.",
                }
            }
        parsed_amount = int(raw_amount)
    elif isinstance(raw_amount, int):
        parsed_amount = raw_amount
    elif isinstance(raw_amount, str) and raw_amount.strip().isdigit():
        parsed_amount = int(raw_amount.strip())
    else:
        return {
            "http_status": 422,
            "response": {
                "status": "REJECTED",
                "error": "PROVENANCE_INVALID_AMOUNT",
                "error_code": "PROVENANCE_INVALID_AMOUNT",
                "detail": f"Malformed amount '{raw_amount}'; must be an integer IDR amount.",
            }
        }

    if parsed_amount <= 0:
        return {
            "http_status": 422,
            "response": {
                "status": "REJECTED",
                "error": "PROVENANCE_INVALID_AMOUNT",
                "error_code": "PROVENANCE_INVALID_AMOUNT",
                "detail": f"Payment amount must be positive, got {parsed_amount}.",
            }
        }

    expected_amount = persisted_order["gross_amount"]
    if parsed_amount != expected_amount:
        logger.warning(f"[Xendit Webhook] Amount mismatch: got {parsed_amount}, expected {expected_amount}")
        return {
            "http_status": 400,
            "response": {
                "status": "AMOUNT_MISMATCH",
                "error": "AMOUNT_MISMATCH",
                "error_code": "AMOUNT_MISMATCH",
                "message": f"Payment amount Rp{parsed_amount:,} does not match expected gross amount Rp{expected_amount:,}",
                "external_id": external_id,
            }
        }

    persisted_sku = persisted_order.get("sku_id") or ""
    if parsed_amount == 1500 and persisted_sku != "TEST-PENNY-1500":
        return {
            "http_status": 400,
            "response": {
                "status": "AMOUNT_MISMATCH",
                "error": "Penny settlement (Rp1.500) is strictly restricted to orders with persisted_sku == TEST-PENNY-1500.",
                "external_id": external_id,
            }
        }
    if persisted_sku == "TEST-PENNY-1500" and parsed_amount != 1500:
        return {
            "http_status": 400,
            "response": {
                "status": "AMOUNT_MISMATCH",
                "error": "TEST-PENNY-1500 order requires exact Rp1,500 settlement.",
                "external_id": external_id,
            }
        }

    # Step 6: Inbound account ID & Candidate Secret Verification via CredentialProfileMapper
    inbound_business_id = str(
        payload.get("business_id")
        or data_obj.get("business_id")
        or payload.get("user_id")
        or ""
    ).strip()
    candidate_token = str(headers.get("x-callback-token") or "").strip()

    mapper = CredentialProfileMapper()
    try:
        cred_res = mapper.resolve_and_verify_callback_secret(
            canonical_tenant_id=persisted_order["canonical_tenant_id"],
            tenant_metadata=persisted_order["tenant_metadata"] or {},
            order_metadata=persisted_order["order_metadata"] or {},
            provider="XENDIT",
            inbound_account_id=inbound_business_id,
            candidate_secret=candidate_token,
        )
    except (PaymentAuthorizationError, PaymentConfigurationError) as auth_err:
        logger.warning(f"[Xendit Webhook Auth Error] {auth_err}")
        return {
            "http_status": getattr(auth_err, "http_status", 403) or 403,
            "response": {
                "status": "REJECTED",
                "error": auth_err.error_code,
                "error_code": auth_err.error_code,
                "detail": str(auth_err),
            }
        }

    # Step 7: Capability Minting
    normalized_headers = {str(k).lower(): str(v) for k, v in headers.items()}
    if "x-callback-token" not in normalized_headers and candidate_token:
        normalized_headers["x-callback-token"] = candidate_token

    try:
        capability = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="XENDIT",
            verification_method="XENDIT_CALLBACK_TOKEN",
            credential_profile_id=cred_res.credential_profile_id,
            expected_provider_account_id=cred_res.expected_provider_account_id,
            provider_verification_secret=candidate_token,
            webhook_headers=normalized_headers,
            webhook_payload=payload,
            authoritative_order_id=external_id,
            authoritative_canonical_tenant_id=persisted_order["canonical_tenant_id"],
            authoritative_order_amount=expected_amount,
            authoritative_sku_id=persisted_sku,
            verified_at_utc=datetime.now(timezone.utc).isoformat(),
            rail_type="NATIVE_PG",
        )
    except SettlementProvenanceError as prov_err:
        logger.warning(f"[Xendit Capability Minting Error] {prov_err}")
        return {
            "http_status": getattr(prov_err, "http_status", 403) or 403,
            "response": {
                "status": "REJECTED",
                "error": prov_err.error_code,
                "error_code": prov_err.error_code,
                "detail": str(prov_err),
            }
        }

    # Step 8: Atomic Settlement Persistence
    signer, verifier = _get_provenance_signer_and_verifier()
    try:
        commit_res = commit_verified_settlement_transaction(
            capability=capability,
            signer=signer,
            verifier=verifier,
            raw_webhook_payload=payload,
            db_conn_factory=get_db_connection,
        )
    except SettlementProvenanceError as prov_err:
        logger.error(f"[Xendit Settlement Error] {prov_err}")
        http_status = getattr(prov_err, "http_status", 500) or 500
        return {
            "http_status": http_status,
            "response": {
                "status": "FAILED",
                "error": prov_err.error_code,
                "error_code": prov_err.error_code,
                "detail": str(prov_err),
            }
        }

    # Step 9: Evaluate Commit Result
    commit_status = commit_res.get("status")
    if commit_status == "ALREADY_PROCESSED":
        logger.info(f"[Xendit Idempotency Hit] Order '{external_id}' already processed.")
        return {
            "http_status": 200,
            "response": {
                "status": "ALREADY_PROCESSED",
                "message": f"Transaction '{external_id}' has already been settled in database",
                "idempotent": True,
                "order_id": external_id,
            }
        }
    if commit_status == "QUARANTINED_LATE_SETTLEMENT":
        logger.warning(f"[Xendit Late Settlement Quarantine] Order '{external_id}' quarantined.")
        return {
            "http_status": 200,
            "response": {
                "status": "QUARANTINED_LATE_SETTLEMENT",
                "message": "Late settlement quarantined successfully for manual review",
                "idempotent": True,
                "order_id": external_id,
            }
        }

    # Normal Settlement (status == "PERSISTED")
    xendit_service.mark_settled(external_id)

    customer_phone = persisted_order.get("customer_phone")
    customer_email = persisted_order.get("customer_email")
    product_name = persisted_order.get("product_title") or "Produk Digital"
    canonical_tenant_slug = persisted_order.get("tenant_slug") or "onlineboost"

    if customer_phone and canonical_tenant_slug != "onlineboost":
        asyncio.create_task(
            send_whatsapp_payment_notification(
                phone=customer_phone,
                external_id=external_id,
                amount=parsed_amount,
                tenant_id=canonical_tenant_slug,
                product_name=product_name,
            )
        )

    if persisted_sku != "TEST-PENNY-1500" and parsed_amount != 1500:
        asyncio.create_task(
            send_capi_task(
                external_id=external_id,
                amount=parsed_amount,
                phone=customer_phone,
                email=customer_email,
                product_name=product_name,
                currency="IDR",
                tenant_id=canonical_tenant_slug,
            )
        )

    return {
        "http_status": 200,
        "response": {
            "status": "SUCCESS",
            "message": "Payment verified and settled",
            "external_id": external_id,
            "amount": parsed_amount,
        }
    }


# -----------------------------------------------------------------------------
# FastAPI Route Handlers
# -----------------------------------------------------------------------------

@xendit_router.post("/api/v1/webhooks/xendit", summary="Xendit Official Webhook")
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
        err_detail = response_body.get("detail") or response_body.get("error") or response_body.get("error_code") or response_body
        raise HTTPException(status_code=http_code, detail=err_detail)

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
