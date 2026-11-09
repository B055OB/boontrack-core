"""app/services/checkout_flow_service.py
D2C Retail Checkout Flow, Dual-Delivery QRIS Dispatch, and Idempotent Webhook Reconciler.
"""

import io
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import httpx

from app.services.whatsapp_service import (
    send_whatsapp_image,
    send_whatsapp_text,
    get_supabase,
    normalize_phone_number,
)
from app.services.xendit_service import xendit_service
from app.services.qris_generator import generate_qris_png_bytes
from app.core.tracing import log_structured_event, set_trace_context, get_trace_context

logger = logging.getLogger("CHECKOUT_FLOW_SERVICE")

PROCESSED_WEBHOOK_EVENTS = set()


def _is_definitive_provider_rejection(err: Exception) -> bool:
    """
    Evaluates whether an exception represents a definitive gateway rejection
    BEFORE transaction execution (e.g. 400 Bad Request, 401 Unauthorized,
    403 Forbidden, 422 Unprocessable Entity with explicit client validation error).

    Uses structured exception contracts (XenditAPIError, MidtransAPIError, DuitkuAPIError)
    and explicit status codes. Never relies on generic exception message parsing.
    """
    import asyncio

    # 1. Structured gateway error contract takes highest precedence
    if hasattr(err, "is_definitive_rejection"):
        return bool(err.is_definitive_rejection)

    # 2. Obvious network / socket / timeout ambiguities -> NEVER definitive rejection
    if isinstance(err, (asyncio.TimeoutError, TimeoutError, ConnectionError, ConnectionResetError, BrokenPipeError)):
        return False

    # 3. Check HTTP status code if present on exception or response
    status_code = getattr(err, "status_code", None)
    if status_code is None and hasattr(err, "response"):
        resp = getattr(err, "response", None)
        status_code = getattr(resp, "status_code", None)

    if status_code is not None:
        try:
            code = int(status_code)
            # 5xx Server errors are ambiguous (gateway could have processed request)
            if code >= 500:
                return False
            # 408 Request Timeout and 429 Rate Limited are ambiguous
            if code in (408, 429):
                return False
            # 400, 401, 403, 404, 422 are definitive client/provider rejections
            if code in (400, 401, 403, 404, 422):
                return True
        except (ValueError, TypeError):
            pass

    # 4. Default invariant: If outcome cannot be definitively proven, preserve slot!
    return False


async def create_d2c_order_and_dispatch_qris(
    merchant_slug: str,
    customer_name: str,
    customer_phone: str,
    items: list,
    total_amount: int,
    is_digital: bool = True,
    delivery_asset_url: Optional[str] = None,
    correlation_id: Optional[str] = None,
    customer_email: Optional[str] = None,
    provider_override: Optional[str] = None,
    credential_mapper: Optional[Any] = None,
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    1. Membuat record pesanan di Supabase & PostgreSQL dengan trace/correlation_id.
    2. Menghasilkan QRIS Dinamis via Native Payment Gateway (Xendit / Midtrans / Duitku).
    3. Phase 1 Stage 3 Step 2B.1:
       - Menggunakan CredentialProfileMapper untuk memilih profil checkout secara otoritatif.
       - active_provider bertindak sebagai default jika tidak ada provider_override.
       - Setiap order baru wajib menyimpan explicit binding provider dan credential_profile_id.
       - Zero plaintext secret di order metadata; kegagalan resolusi profil fail-closed sebelum transaksi dibuat.
       - Persistent atomic trial quota reservation backed by PostgreSQL (elimination of TOCTOU race condition).
    4. Mengirimkan Native QR Image + Ringkasan Pesanan ke WhatsApp Buyer.
    """
    import copy
    import json
    import uuid
    import asyncio
    from fastapi import HTTPException
    from app.services.tenant_context_resolver import tenant_context_resolver
    from app.services.payment.base import (
        PaymentAuthorizationError,
        PaymentConfigurationError,
    )
    from app.services.payment.factory import PaymentAdapterFactory
    from app.services.payment.manual_adapter import ManualTransferAdapter
    from app.core.security.payment_auth_guard import (
        CredentialProfileMapper,
        TenantCredentialProfile,
    )

    supabase = get_supabase()
    clean_phone = normalize_phone_number(customer_phone)
    if not clean_phone:
        raise ValueError("customer_phone tidak valid atau kosong.")
    if not customer_name or not str(customer_name).strip():
        raise ValueError("customer_name wajib diisi dan tidak boleh kosong.")

    order_id = order_id or f"ORD-{merchant_slug.upper()[:6]}-{uuid.uuid4().hex[:10].upper()}"
    active_corr = correlation_id or order_id

    set_trace_context(correlation_id=active_corr, tenant_id=merchant_slug)
    log_structured_event(
        service="checkout_flow",
        event_type="INBOUND_CHECKOUT",
        entity_type="order",
        entity_id=order_id,
        status="SUCCESS",
        tenant_id=merchant_slug,
        correlation_id=active_corr,
    )

    # 1. Resolve Tenant Context (Fail-Closed on Missing Tenant)
    tenant_ctx = await tenant_context_resolver.resolve_context(merchant_slug)
    if not tenant_ctx:
        raise HTTPException(
            status_code=422,
            detail="MERCHANT_QRIS_NOT_CONFIGURED",
        )

    # 1.5 CFO Hard-Cap Guardrail for trial accounts (Max 30 orders)
    is_trial = (
        getattr(tenant_ctx, "is_trial", False)
        or (bool(tenant_ctx.metadata) and tenant_ctx.metadata.get("is_trial") is True)
        or getattr(tenant_ctx, "status", "") == "TRIALING"
    )
    if is_trial:
        from app.core.trial_guardrail import trial_guardrail
        trial_guardrail.check_order_quota(merchant_slug, is_trial=True)

    # 1.6 Stage 3 Step 2B.1: Authoritative Credential Profile Resolution & Order Binding
    tenant_meta = tenant_ctx.metadata if isinstance(tenant_ctx.metadata, dict) else {}
    pay_cfg = tenant_meta.get("payment_config") if isinstance(tenant_meta.get("payment_config"), dict) else {}
    has_modern_profiles = bool(
        "credential_profiles" in tenant_meta
        or "credential_profiles" in pay_cfg
    )

    mapper: CredentialProfileMapper = credential_mapper or CredentialProfileMapper()
    checkout_profile: Optional[TenantCredentialProfile] = None
    bound_provider: str = ""
    bound_profile_id: Optional[str] = None
    canonical_tenant_uuid: Optional[str] = None
    resolved_secret: Optional[str] = None

    # Finding #1: Authoritative tenant identity must be a valid canonical UUID
    raw_tid = getattr(tenant_ctx, "tenant_id", None)
    if raw_tid and isinstance(raw_tid, str):
        try:
            parsed_u = uuid.UUID(raw_tid.strip())
            canonical_tenant_uuid = str(parsed_u).lower()
        except (ValueError, AttributeError):
            canonical_tenant_uuid = None

    if has_modern_profiles:
        # Reject missing, non-UUID, or guessed tenant IDs on modern profiles fail-closed
        if not canonical_tenant_uuid:
            raise HTTPException(
                status_code=422,
                detail="INVALID_CANONICAL_TENANT_ID: Authoritative tenant context lacks a valid canonical UUID.",
            )

        try:
            checkout_profile = mapper.resolve_checkout_profile(
                tenant_meta,
                requested_provider=provider_override,
            )
        except PaymentConfigurationError as cfg_err:
            err_code = getattr(cfg_err, "error_code", "PAYMENT_CONFIGURATION_ERROR")
            raise HTTPException(
                status_code=cfg_err.http_status if hasattr(cfg_err, "http_status") else 422,
                detail=f"{err_code}: {str(cfg_err)}",
            )
        except PaymentAuthorizationError as auth_err:
            err_code = getattr(auth_err, "error_code", "PAYMENT_AUTHORIZATION_ERROR")
            raise HTTPException(
                status_code=auth_err.http_status if hasattr(auth_err, "http_status") else 403,
                detail=f"{err_code}: {str(auth_err)}",
            )

        # Finding #1 & #8: Tenant A cannot use Tenant B's profile
        if checkout_profile.canonical_tenant_id != canonical_tenant_uuid:
            raise HTTPException(
                status_code=403,
                detail=f"CREDENTIAL_PROFILE_TENANT_MISMATCH: Profile '{checkout_profile.credential_profile_id}' "
                       f"belongs to tenant '{checkout_profile.canonical_tenant_id}', not authoritative tenant '{canonical_tenant_uuid}'.",
            )

        # Finding #3: Determine secret unambiguously; do not pick arbitrary ACTIVE secret
        active_secrets = [s for s in checkout_profile.verification_secrets if s.status == "ACTIVE"]
        if len(active_secrets) == 0:
            raise HTTPException(
                status_code=503,
                detail=f"CREDENTIAL_SECRET_UNAVAILABLE: No active secret version configured for profile '{checkout_profile.credential_profile_id}'.",
            )
        if len(active_secrets) > 1:
            raise HTTPException(
                status_code=403,
                detail=f"AMBIGUOUS_CREDENTIAL_SECRET_VERSION: Ambiguous active secret versions in profile '{checkout_profile.credential_profile_id}'. Multiple secrets marked ACTIVE.",
            )

        active_secret = active_secrets[0]
        try:
            resolved_secret = mapper._resolve_secret_ref(active_secret.secret_ref)
        except Exception:
            logger.error(
                f"[CHECKOUT_SECURITY] Credential secret resolution failed for tenant '{canonical_tenant_uuid}' "
                f"profile '{checkout_profile.credential_profile_id}' correlation_id '{active_corr}'"
            )
            raise HTTPException(
                status_code=503,
                detail="CREDENTIAL_SECRET_UNAVAILABLE: Payment credential secret is currently unavailable for checkout.",
            )

        # Finding #2: Zero global env fallback for modern profiles
        if not resolved_secret or not str(resolved_secret).strip():
            logger.error(
                f"[CHECKOUT_SECURITY] Resolved credential secret is empty for tenant '{canonical_tenant_uuid}' "
                f"profile '{checkout_profile.credential_profile_id}' correlation_id '{active_corr}'"
            )
            raise HTTPException(
                status_code=503,
                detail="CREDENTIAL_SECRET_UNAVAILABLE: Payment credential secret is currently unavailable for checkout.",
            )

        # Finding #5: Bound provider and credential_profile_id must be valid non-empty values
        bound_provider = str(checkout_profile.provider or "").strip().upper()
        bound_profile_id = str(checkout_profile.credential_profile_id or "").strip()
        if not bound_provider or not bound_profile_id:
            raise HTTPException(
                status_code=422,
                detail="INVALID_CREDENTIAL_PROFILE: Resolved profile possesses empty provider or credential_profile_id.",
            )
    else:
        # Finding #6: Legacy fallback path evaluated separately. Explicit profile binding is None.
        try:
            adapter = PaymentAdapterFactory.resolve(tenant_ctx, provider_override=provider_override)
        except PaymentConfigurationError as cfg_err:
            raise HTTPException(
                status_code=422,
                detail=str(cfg_err),
            )

        if isinstance(adapter, ManualTransferAdapter):
            raise HTTPException(
                status_code=422,
                detail="DIRECT_TENANT_RAIL_DISABLED: Manual transfer and static QRIS checkout are disabled.",
            )

        bound_provider = str(provider_override or getattr(adapter, "provider", None) or os.getenv("PAYMENT_GATEWAY_PROVIDER") or "XENDIT").upper()
        bound_profile_id = None

    meta_payload = {
        "merchant_slug": merchant_slug,
        "customer_name": customer_name,
        "correlation_id": active_corr,
        "provider": bound_provider,
        "credential_profile_id": bound_profile_id,
    }

    target_tenant_id = canonical_tenant_uuid or str(getattr(tenant_ctx, "tenant_id", None) or merchant_slug)

    # 1.6.5 Atomic persistent trial quota reservation before gateway dispatch
    if is_trial:
        from app.core.trial_guardrail import trial_guardrail
        if canonical_tenant_uuid:
            trial_guardrail.register_tenant_alias(merchant_slug, canonical_tenant_uuid)
        trial_guardrail.reserve_slot(
            tenant_id=target_tenant_id,
            order_id=order_id,
            is_trial=True,
            tenant_slug=merchant_slug,
        )

    # 1.7 Dispatch QRIS Generation via Selected Native Gateway using profile credentials
    # Wrapped with atomic release on definitive failure and quarantine on timeout
    try:
        if bound_provider == "MIDTRANS":
            from app.services.midtrans_service import midtrans_service
            mid_client = midtrans_service
            if checkout_profile and resolved_secret:
                mid_client = copy.copy(midtrans_service)
                mid_client.server_key = resolved_secret
                mid_client.client_key = checkout_profile.expected_provider_account_id
                mid_client.is_production = (checkout_profile.environment == "production")
                mid_client.api_base_url = (
                    "https://api.midtrans.com/v2" if mid_client.is_production else "https://api.sandbox.midtrans.com/v2"
                )

            qris_data = await mid_client.create_qris_charge(
                order_id=order_id,
                amount=total_amount,
                customer_name=customer_name,
                customer_phone=clean_phone,
                tenant_id=merchant_slug,
                metadata=meta_payload,
            )
            if qris_data.get("is_synthetic") and mid_client.is_production:
                from app.services.midtrans_service import MidtransAPIError
                raise MidtransAPIError(
                    status_code=502,
                    error_code="SYNTHETIC_SUCCESS_PROHIBITED",
                    message="Midtrans returned synthetic QRIS in production",
                    is_definitive_rejection=False,
                )
            qr_string = qris_data.get("qr_string", "")
            qr_code_url = qris_data.get("qr_code_url", "")
            qr_png_bytes = generate_qris_png_bytes(qr_string) if qr_string else b""
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        elif bound_provider == "DUITKU":
            from app.services.payment.gateway_duitku import DuitkuAdapter
            from app.services.payment.base import TransactionRequest

            duitku_merchant_code = (
                checkout_profile.expected_provider_account_id
                if checkout_profile
                else os.getenv("DUITKU_MERCHANT_CODE", "")
            )
            # Finding #2: Zero global env fallback for modern profiles
            duitku_api_key = resolved_secret if checkout_profile else os.getenv("DUITKU_API_KEY", "")

            duitku_adapter = DuitkuAdapter(
                merchant_code=duitku_merchant_code,
                api_key=duitku_api_key,
                is_sandbox=(checkout_profile.environment == "sandbox" if checkout_profile else None),
            )
            tx_req = TransactionRequest(
                order_id=order_id,
                amount=total_amount,
                customer_name=customer_name,
                customer_phone=clean_phone,
                customer_email=customer_email,
                payment_method="QRIS",
                metadata=meta_payload,
            )
            tx_resp = await duitku_adapter.create_transaction(tx_req)
            tx_id = getattr(tx_resp, "transaction_id", None)
            if isinstance(tx_id, str) and tx_id.startswith("DTK-REF-") and not duitku_adapter.is_sandbox:
                from app.services.payment.gateway_duitku import DuitkuAPIError
                raise DuitkuAPIError(
                    status_code=502,
                    error_code="SIMULATOR_SUCCESS_PROHIBITED",
                    message="Duitku returned simulator reference in production",
                    is_definitive_rejection=False,
                )
            qr_string = tx_resp.qr_string or ""
            qr_code_url = tx_resp.payment_url or ""
            qr_png_bytes = generate_qris_png_bytes(qr_string) if qr_string else b""
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        else:
            # Default XENDIT
            from app.services.xendit_service import xendit_service
            xen_client = xendit_service
            if checkout_profile and resolved_secret:
                xen_client = copy.copy(xendit_service)
                xen_client.secret_key = resolved_secret
                xen_client.env = checkout_profile.environment

            qris_data = await xen_client.create_dynamic_qris(
                external_id=order_id,
                amount=total_amount,
                tenant_id=merchant_slug,
                customer_phone=clean_phone,
                metadata=meta_payload,
            )
            qr_string = qris_data.get("qr_string", "")
            qr_code_url = qris_data.get("qr_code_url", "")
            qr_png_bytes = generate_qris_png_bytes(qr_string) if qr_string else b""
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    except Exception as gw_err:
        if is_trial:
            from app.core.trial_guardrail import trial_guardrail
            if _is_definitive_provider_rejection(gw_err):
                trial_guardrail.release_slot(
                    tenant_id=target_tenant_id,
                    order_id=order_id,
                    is_trial=True,
                    tenant_slug=merchant_slug,
                )
            else:
                trial_guardrail.quarantine_timeout_slot(
                    tenant_id=target_tenant_id,
                    order_id=order_id,
                    is_trial=True,
                    tenant_slug=merchant_slug,
                )
        raise

    # Commit trial order quota slot upon successful gateway dispatch
    if is_trial:
        from app.core.trial_guardrail import trial_guardrail
        trial_guardrail.commit_slot(
            tenant_id=target_tenant_id,
            order_id=order_id,
            is_trial=True,
            tenant_slug=merchant_slug,
        )

    # 2. Simpan order ke database PostgreSQL (Immutable Source of Truth)
    first_item = items[0] if items and isinstance(items, list) else {}
    prod_id = first_item.get("product_id") or "prod_sample"
    prod_title = first_item.get("title") or "Sample Product"

    order_metadata = {
        "provider": bound_provider,
        "credential_profile_id": bound_profile_id,
        "canonical_tenant_id": canonical_tenant_uuid,
        "merchant_slug": merchant_slug,
        "correlation_id": active_corr,
    }

    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (
                id, tenant_id, tenant_slug, product_id, product_title, gross_amount,
                customer_name, customer_phone, customer_email, status, correlation_id,
                metadata, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                tenant_id = COALESCE(EXCLUDED.tenant_id, orders.tenant_id),
                correlation_id = EXCLUDED.correlation_id,
                metadata = COALESCE(orders.metadata, '{}'::jsonb) || EXCLUDED.metadata,
                updated_at = NOW();
            """,
            (
                str(order_id),
                canonical_tenant_uuid or str(tenant_ctx.tenant_id or merchant_slug),
                merchant_slug,
                str(prod_id),
                str(prod_title),
                total_amount,
                customer_name,
                clean_phone,
                customer_email,
                correlation_id,
                json.dumps(order_metadata),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"[DB ORDER INSERT PG] Order {order_id} stored in Postgres with profile '{bound_profile_id}' and provider '{bound_provider}'.")
    except Exception as pg_err:
        logger.warning(f"[DB ORDER INSERT PG WARNING] {pg_err}")

    # 3. Simpan order ke database Supabase (Aligned with DB schema & Idempotent Upsert)
    if supabase:
        try:
            supabase.table("orders").upsert({
                "id": str(order_id),
                "tenant_id": canonical_tenant_uuid or str(tenant_ctx.tenant_id or merchant_slug),
                "tenant_slug": merchant_slug,
                "product_id": str(prod_id),
                "product_title": str(prod_title),
                "gross_amount": total_amount,
                "customer_name": customer_name,
                "customer_phone": clean_phone,
                "customer_email": customer_email,
                "status": "PENDING",
                "correlation_id": correlation_id,
                "metadata": order_metadata,
            }).execute()
        except Exception as db_err:
            logger.warning(f"[DB ORDER INSERT WARNING] {db_err}")

    # 4. Format Pesan WhatsApp Invoice Summary
    t_lower = str(prod_title or "").lower()
    if any(w in t_lower for w in ["dp", "uang muka", "tiket", "komitmen"]):
        scheme = "dp"
    elif "pelunasan" in t_lower:
        scheme = "pelunasan"
    else:
        scheme = "lunas"
    scheme_label = "Tagihan DP" if scheme == "dp" else ("Pelunasan" if scheme == "pelunasan" else "Lunas")

    amount_fmt = f"Rp{total_amount:,.0f}".replace(",", ".")
    caption = (
        f"Halo Kak *{customer_name}*, terima kasih telah melakukan pemesanan di *{merchant_slug}*! 🛍️\n\n"
        f"📄 *No. Pesanan:* `{order_id}`\n"
        f"💰 *Total Tagihan ({scheme_label}):* *{amount_fmt}*\n"
        f"⏱️ *Batas Waktu Bayar:* 15 Menit\n\n"
        f"Silakan scan kode QRIS di atas melalui m-Banking atau E-Wallet pilihan Anda."
    )

    # 5. Dispatch WhatsApp Native Image QRIS ke Buyer (Decoupled & Resilient)
    img_to_send = qr_png_bytes or qr_code_url
    if clean_phone:
        try:
            if img_to_send:
                try:
                    await send_whatsapp_image(
                        to_phone=clean_phone,
                        image_path_or_bytes=img_to_send,
                        caption=caption,
                        tenant_id=merchant_slug,
                    )
                except Exception as wa_err:
                    logger.warning(f"[WA QRIS Dispatch Warning] {wa_err}")
                    await send_whatsapp_text(to_phone=clean_phone, text=caption, tenant_id=merchant_slug)
            else:
                await send_whatsapp_text(to_phone=clean_phone, text=caption, tenant_id=merchant_slug)

            log_structured_event(
                service="whatsapp_delivery",
                event_type="WA_QRIS_DISPATCHED",
                entity_type="message",
                entity_id=order_id,
                status="SUCCESS",
                provider="meta",
                tenant_id=merchant_slug,
                correlation_id=active_corr,
            )
        except Exception as wa_outage_err:
            logger.error(f"[WA Dispatch Outage Isolated] WhatsApp API down: {wa_outage_err}")
            log_structured_event(
                service="whatsapp_delivery",
                event_type="WA_DISPATCH_OUTAGE",
                entity_type="message",
                entity_id=order_id,
                status="FAILED",
                error_code="EXTERNAL_API_DOWN",
                provider="meta",
                tenant_id=merchant_slug,
                correlation_id=active_corr,
            )

    log_structured_event(
        service="checkout_flow",
        event_type="QRIS_GENERATED",
        entity_type="payment",
        entity_id=order_id,
        status="SUCCESS",
        provider=bound_provider.lower() if bound_provider else (provider or "xendit"),
        tenant_id=merchant_slug,
        correlation_id=active_corr,
    )

    return {
        "order_id": order_id,
        "merchant_slug": merchant_slug,
        "tenant_id": canonical_tenant_uuid or str(tenant_ctx.tenant_id or merchant_slug),
        "total_amount": total_amount,
        "qr_string": qr_string,
        "qr_code_url": qr_code_url,
        "expires_at": expires_at,
        "status": "PENDING",
        "correlation_id": active_corr,
        "payment_method": "QRIS_DYNAMIC",
        "provider": bound_provider,
        "credential_profile_id": bound_profile_id,
        "metadata": order_metadata,
    }


async def reconcile_payment_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """P1 Stage 3 Step 2B.2: Internal Post-Verification Settlement Dispatch Helper.
    
    Invariants (Founder Decision 3 & FIN-RISK-04):
    1. May remain ONLY as an internal dispatcher when needed; never treats raw external data as settlement authority.
    2. Zero fallback updates: permanently eliminates `except Exception -> orders.update(status='PAID')`.
    3. Stage 4 Boundary Isolation: zero direct external WhatsApp dispatch during settlement.
    4. Fails closed on database transaction failure.
    """
    event_id = payload.get("id") or payload.get("external_id")
    external_id = payload.get("external_id") or payload.get("reference_id")
    payment_status = str(payload.get("status", "")).upper()

    # Distributed Lock via Redis: SET lock:payment:webhook:{external_id} NX EX 300
    from app.core.redis import acquire_payment_lock
    lock_key = external_id or event_id
    if lock_key and not acquire_payment_lock(lock_key, ttl_seconds=300):
        logger.info(f"[WEBHOOK IDEMPOTENT LOCK] Event {lock_key} currently locked/processing. Skipping.")
        return {"status": "skipped", "reason": "transaction_locked", "idempotent": True}

    if payment_status not in ("SUCCEEDED", "COMPLETED", "PAID", "SETTLED"):
        return {"status": "ignored", "payment_status": payment_status}

    supabase = get_supabase()
    order_data = None

    if supabase and external_id:
        try:
            res = supabase.table("orders").select("*").eq("id", external_id).execute()
            if res.data:
                order_data = res.data[0]
        except Exception:
            try:
                res = supabase.table("orders").select("*").eq("order_id", external_id).execute()
                if res.data:
                    order_data = res.data[0]
            except Exception as e2:
                logger.debug(f"[RECONCILE DB NOTE] {e2}")

        if not order_data:
            logger.warning(f"[RECONCILE FAIL-CLOSED] Order '{external_id}' not found in DB. Zero ghost orders.")
            return {"status": "rejected", "reason": "order_not_found", "order_id": external_id}

        # Persistent DB State Guard: If already PAID or CONFIRMED -> return ACK NO-OP
        if str(order_data.get("status") or "").upper() in ("PAID", "SETTLED", "COMPLETED", "LUNAS", "CONFIRMED"):
            logger.info(f"[WEBHOOK IDEMPOTENT DB] Order {external_id} already marked PAID in DB. Skipping.")
            return {"status": "skipped", "reason": "order_already_paid", "idempotent": True}

        # Single Database Transaction Settlement (Fail-Closed, Zero Bypass Update)
        try:
            from app.services.checkout_service import execute_order_settlement_transaction
            raw_gross = order_data.get("gross_amount") or payload.get("amount") or 0
            exact_amount = int(raw_gross)
            execute_order_settlement_transaction(
                event_id=str(event_id),
                external_id=str(external_id),
                tenant_id=order_data.get("tenant_slug") or "default",
                amount=exact_amount,
                payload=payload,
                provider="CHECKOUT_FLOW",
                customer_phone=order_data.get("customer_phone"),
                product_name=order_data.get("product_title"),
            )
        except Exception as tx_err:
            logger.error(f"[RECONCILE DB TX ERROR] Transaction aborted: {tx_err}")
            # P1 Stage 3 Step 2B.2 (FIN-RISK-04): Zero fallback update to PAID!
            raise tx_err

    merchant = (order_data or {}).get("tenant_slug") or payload.get("tenant_slug") or "default"

    log_structured_event(
        service="checkout_flow",
        event_type="ORDER_SETTLED",
        entity_type="order",
        entity_id=str(external_id),
        status="SUCCESS",
        tenant_id=merchant,
        correlation_id=str(external_id),
    )

    return {"status": "success", "order_id": external_id}
