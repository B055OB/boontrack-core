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
import hmac
import hashlib
import asyncio
import logging
import threading
from decimal import Decimal
from datetime import datetime, timezone, date
from typing import Dict, Any, Mapping, Optional, Tuple
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from fastapi import APIRouter, Request, Header, HTTPException, status
from fastapi.responses import JSONResponse
from aiohttp import web

from app.core.database import get_db_connection, normalize_db_row
from app.services.xendit_service import xendit_service
from app.services.payment.gateway_xendit import XenditAdapter
from app.services.meta_capi_service import send_meta_capi_purchase
from app.services.whatsapp_service import send_whatsapp_text, send_ereceipt_whatsapp
from app.core.security.masking import sanitize_log_message
from app.payments.service import (
    get_payment_privileged_supabase,
    PaymentCredentialConfigurationError,
    PaymentPersistenceError,
    check_supabase_response_error,
)
from app.payments.schemas import validate_monetary_amount, MonetaryValidationError

# UNIT-P0-01A: Forward get_supabase to get_payment_privileged_supabase to enforce fail-closed
# privileged access and prevent anonymous key usage on payment settlement sync paths.
get_supabase = get_payment_privileged_supabase
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
    ProvenanceVerificationKeyring,
    SettlementProvenanceError,
    ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING,
    ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING,
    ENV_INTERNAL_HMAC_KEYRING,
    ENV_APP_MASTER_KEY,
    FORBIDDEN_LEGACY_PROVENANCE_ENV_ALIASES,
)

logger = logging.getLogger("XENDIT_WEBHOOK")

xendit_router = APIRouter(tags=["Xendit Payments"])
_adapter = XenditAdapter()

_PAID_STATUSES = {"PAID", "SETTLED", "COMPLETED", "SUCCEEDED"}

_PROV_CACHE_LOCK = threading.RLock()
_PROV_CACHE_FINGERPRINT: Optional[str] = None
_PROV_SIGNER: Optional[ProvenanceSigner] = None
_PROV_VERIFIER: Optional[ProvenanceVerifier] = None
_PROVENANCE_KEYPAIR_SELF_TEST_DOMAIN = b"boontrack:provenance-keyring-self-test:v1"


def _reset_provenance_signer_cache() -> None:
    """Clear cached provenance signer/verifier state safely under lock."""
    global _PROV_CACHE_FINGERPRINT, _PROV_SIGNER, _PROV_VERIFIER
    with _PROV_CACHE_LOCK:
        _PROV_CACHE_FINGERPRINT = None
        _PROV_SIGNER = None
        _PROV_VERIFIER = None


def _compute_provenance_env_fingerprint(environ: Mapping[str, str]) -> str:
    """Compute a SHA-256 fingerprint over provenance keyring & key-separation env configuration."""
    snapshot = {
        "priv": str(environ.get(ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, "")).strip(),
        "pub": str(environ.get(ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING, "")).strip(),
        "master": str(environ.get(ENV_APP_MASTER_KEY, "")).strip(),
        "hmac": str(environ.get(ENV_INTERNAL_HMAC_KEYRING, "")).strip(),
        "legacy": {
            alias: str(environ.get(alias, "")).strip()
            for alias in FORBIDDEN_LEGACY_PROVENANCE_ENV_ALIASES
        },
    }
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_keyring_json_mapping(raw_json: str, env_var_name: str) -> None:
    """Ensure configured keyring JSON is a non-empty JSON object mapping key_id -> object metadata."""
    if not raw_json:
        raise SettlementProvenanceError(
            f"{env_var_name} is not configured.",
            error_code="MISSING_PROVENANCE_KEYRING",
            http_status=503,
        )
    try:
        parsed = json.loads(raw_json)
    except Exception as exc:
        raise SettlementProvenanceError(
            f"Invalid JSON in {env_var_name}.",
            error_code="INVALID_PROVENANCE_KEYRING_JSON",
            http_status=503,
        ) from exc
    if not isinstance(parsed, Mapping) or not parsed:
        raise SettlementProvenanceError(
            f"{env_var_name} must be a non-empty JSON object mapping key_id to key metadata.",
            error_code="INVALID_PROVENANCE_KEYRING_STRUCTURE",
            http_status=503,
        )
    for kid, meta in parsed.items():
        if not isinstance(meta, Mapping):
            raise SettlementProvenanceError(
                f"Key entry '{kid}' in {env_var_name} must be a JSON object.",
                error_code="INVALID_PROVENANCE_KEYRING_STRUCTURE",
                http_status=503,
            )


def _verify_ed25519_keypair_match(
    signing_keyring: ProvenanceSigningKeyring,
    verify_keyring: ProvenanceVerificationKeyring,
) -> None:
    """Validate active signing key exists in public keyring and private/public keys form a valid Ed25519 pair."""
    active_sign_rec = signing_keyring.get_for_signing()
    active_pub_rec = verify_keyring.get_for_verification(active_sign_rec.key_id)

    for kid, sign_rec in signing_keyring._keys.items():
        if sign_rec.status == "ACTIVE":
            verify_keyring.get_for_verification(kid)
        if kid in verify_keyring._keys:
            pub_rec = verify_keyring._keys[kid]
            if not hmac.compare_digest(
                sign_rec.public_key_hex.lower(),
                pub_rec.public_key_hex.lower(),
            ):
                raise SettlementProvenanceError(
                    f"Provenance public/private keypair mismatch for key_id '{kid}'.",
                    error_code="PROVENANCE_KEYPAIR_MISMATCH",
                    http_status=503,
                )

    if not hmac.compare_digest(
        active_sign_rec.public_key_hex.lower(),
        active_pub_rec.public_key_hex.lower(),
    ):
        raise SettlementProvenanceError(
            f"Active provenance public/private keypair mismatch for key_id '{active_sign_rec.key_id}'.",
            error_code="PROVENANCE_KEYPAIR_MISMATCH",
            http_status=503,
        )

    probe_msg = _PROVENANCE_KEYPAIR_SELF_TEST_DOMAIN + b":" + active_sign_rec.key_id.encode("utf-8")
    try:
        priv_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(active_sign_rec.private_key_hex))
        pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(active_pub_rec.public_key_hex))
        sig_bytes = priv_key.sign(probe_msg)
        pub_key.verify(sig_bytes, probe_msg)
    except InvalidSignature as exc:
        raise SettlementProvenanceError(
            f"Ed25519 self-test verification failed for active key_id '{active_sign_rec.key_id}'.",
            error_code="PROVENANCE_KEYPAIR_MISMATCH",
            http_status=503,
        ) from exc


def _get_provenance_signer_and_verifier() -> Tuple[ProvenanceSigner, ProvenanceVerifier]:
    """Load, validate, and cache Ed25519 provenance signer and public verifier (strict fail-closed)."""
    global _PROV_CACHE_FINGERPRINT, _PROV_SIGNER, _PROV_VERIFIER

    with _PROV_CACHE_LOCK:
        env = os.environ
        fingerprint = _compute_provenance_env_fingerprint(env)
        if (
            _PROV_SIGNER is not None
            and _PROV_VERIFIER is not None
            and _PROV_CACHE_FINGERPRINT == fingerprint
        ):
            return _PROV_SIGNER, _PROV_VERIFIER

        _PROV_CACHE_FINGERPRINT = None
        _PROV_SIGNER = None
        _PROV_VERIFIER = None

        try:
            for legacy_var in FORBIDDEN_LEGACY_PROVENANCE_ENV_ALIASES:
                if str(env.get(legacy_var, "")).strip():
                    raise PaymentConfigurationError(
                        f"Deprecated provenance environment variable '{legacy_var}' is forbidden."
                    )

            raw_priv = str(env.get(ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING, "")).strip()
            raw_pub = str(env.get(ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING, "")).strip()
            _validate_keyring_json_mapping(raw_priv, ENV_PROVENANCE_SIGNING_PRIVATE_KEYRING)
            _validate_keyring_json_mapping(raw_pub, ENV_PROVENANCE_VERIFY_PUBLIC_KEYRING)

            signing_keyring = ProvenanceSigningKeyring.from_env(env)
            verify_keyring = ProvenanceVerificationKeyring.from_env(env)
            _verify_ed25519_keypair_match(signing_keyring, verify_keyring)

            signer = ProvenanceSigner(signing_keyring)
            verifier = ProvenanceVerifier(verify_keyring)
        except SettlementProvenanceError as exc:
            safe_msg = sanitize_log_message(str(exc))
            logger.critical(f"[SECURITY FAIL-CLOSED] PROVENANCE_SIGNING_UNAVAILABLE ({exc.error_code}): {safe_msg}")
            raise SettlementProvenanceError(
                f"[SECURITY FAIL-CLOSED] PROVENANCE_SIGNING_UNAVAILABLE ({exc.error_code}): {safe_msg}",
                error_code="PROVENANCE_SIGNING_UNAVAILABLE",
                http_status=503,
            ) from exc
        except PaymentConfigurationError as exc:
            safe_msg = sanitize_log_message(str(exc))
            logger.critical(f"[SECURITY FAIL-CLOSED] PROVENANCE_SIGNING_UNAVAILABLE ({exc.error_code}): {safe_msg}")
            raise SettlementProvenanceError(
                f"[SECURITY FAIL-CLOSED] PROVENANCE_SIGNING_UNAVAILABLE ({exc.error_code}): {safe_msg}",
                error_code="PROVENANCE_SIGNING_UNAVAILABLE",
                http_status=503,
            ) from exc
        except Exception as exc:
            safe_msg = sanitize_log_message(f"{type(exc).__name__}: {exc}")
            logger.critical(f"[SECURITY FAIL-CLOSED] PROVENANCE_SIGNING_UNAVAILABLE: {safe_msg}")
            raise SettlementProvenanceError(
                f"[SECURITY FAIL-CLOSED] PROVENANCE_SIGNING_UNAVAILABLE: {safe_msg}",
                error_code="PROVENANCE_SIGNING_UNAVAILABLE",
                http_status=503,
            ) from exc

        _PROV_SIGNER = signer
        _PROV_VERIFIER = verifier
        _PROV_CACHE_FINGERPRINT = fingerprint
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
        safe_err = sanitize_log_message(str(e))
        logger.error(f"[Xendit DB Settlement Error] {safe_err}", exc_info=True)
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

    # Fallback/Sinkronisasi ke Supabase client jika aktif (UNIT-P0-01A Privileged Hardening)
    sync_xendit_settlement_to_supabase_catchup(
        external_id=str(external_id),
        amount=amount,
        payload=payload,
        raise_on_error=True,
    )


def _parse_table_exists_result(res: Any, table_name: str, external_id: str) -> bool:
    """
    Strictly validates the result of `SELECT EXISTS (...)` from information_schema.tables.
    
    Security & Integrity Invariants (BT-SEC-2026-001 / UNIT-P0-01A):
    1. Must return exactly one non-empty tuple/sequence with length == 1.
    2. Missing row (None) is an operational anomaly, NOT a genuine absence -> FAILS CLOSED.
    3. Element 0 must be strictly of type bool (True or False).
    4. Only a verified bool False constitutes genuine schema/table absence.
    5. Any other type (None, int, str, dict) or malformed tuple fails closed.
    """
    if res is None:
        err_msg = (
            f"[SECURITY FAIL-CLOSED] Failed to inspect '{table_name}' table existence for order '{external_id}': "
            f"query returned no result row (None)."
        )
        logger.error(err_msg)
        raise PaymentPersistenceError(err_msg)

    if not isinstance(res, (tuple, list)) or len(res) != 1:
        err_msg = (
            f"[SECURITY FAIL-CLOSED] Failed to inspect '{table_name}' table existence for order '{external_id}': "
            f"query returned malformed result row (expected sequence of length 1, got {type(res).__name__})."
        )
        logger.error(err_msg)
        raise PaymentPersistenceError(err_msg)

    exists_val = res[0]
    if not isinstance(exists_val, bool):
        err_msg = (
            f"[SECURITY FAIL-CLOSED] Failed to inspect '{table_name}' table existence for order '{external_id}': "
            f"expected boolean result, got {type(exists_val).__name__} ({exists_val!r})."
        )
        logger.error(err_msg)
        raise PaymentPersistenceError(err_msg)

    return exists_val


def _lookup_authoritative_pg_settlement_sync(external_id: str) -> Optional[Dict[str, Any]]:
    """
    Queries PostgreSQL (Primary Financial SSOT) for authoritative committed
    order status, gross_amount, ledger records, and settlement details.
    """
    if not external_id:
        return None
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Authoritative order row
        cur.execute(
            """
            SELECT id, gross_amount, status, payment_status, tenant_id
            FROM orders
            WHERE id = %s
            LIMIT 1;
            """,
            (str(external_id),)
        )
        ord_row = normalize_db_row(
            cur.fetchone(),
            ("id", "gross_amount", "status", "payment_status", "tenant_id")
        )

        # 2. Authoritative financial_ledger row (Primary Financial SSOT)
        cur.execute(
            """
            SELECT id, gross_amount, status, metadata, event_id, tenant_id, order_id
            FROM financial_ledger
            WHERE order_id = %s
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (str(external_id),)
        )
        ledger_row = normalize_db_row(
            cur.fetchone(),
            ("id", "gross_amount", "status", "metadata", "event_id", "tenant_id", "order_id")
        )

        # 3. Authoritative payment_settlements row if present (Secondary Financial SSOT)
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'payment_settlements'
            );
        """)
        has_settle_table = _parse_table_exists_result(cur.fetchone(), "payment_settlements", external_id)
        settle_row = None

        if has_settle_table:
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                  AND table_name = 'payment_settlements'
                  AND column_name IN ('tenant_id', 'order_id');
            """)
            settle_cols = {r[0] for r in cur.fetchall()}

            col_tenant = "tenant_id" if "tenant_id" in settle_cols else "NULL as tenant_id"
            col_order = "order_id" if "order_id" in settle_cols else "NULL as order_id"

            cur.execute(
                f"""
                SELECT id, settled_amount, status, raw_payload, provider_ref, {col_tenant}, {col_order}
                FROM payment_settlements
                WHERE provider_ref = %s
                LIMIT 1;
                """,
                (f"xendit_{external_id}",)
            )
            settle_row = normalize_db_row(
                cur.fetchone(),
                ("id", "settled_amount", "status", "raw_payload", "provider_ref", "tenant_id", "order_id")
            )
            if settle_row:
                raw_pl = settle_row.get("raw_payload") or {}
                if isinstance(raw_pl, dict):
                    if not settle_row.get("tenant_id"):
                        settle_row["tenant_id"] = raw_pl.get("tenant_id")
                    if not settle_row.get("order_id"):
                        settle_row["order_id"] = raw_pl.get("order_id") or raw_pl.get("external_id")

        # 4. Authoritative payment_intents row if present
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'payment_intents'
            );
        """)
        has_intents_table = _parse_table_exists_result(cur.fetchone(), "payment_intents", external_id)
        intent_row = None
        if has_intents_table:
            cur.execute(
                """
                SELECT id, total_amount, status, tenant_id, order_id
                FROM payment_intents
                WHERE order_id = %s
                LIMIT 1;
                """,
                (str(external_id),)
            )
            intent_row = normalize_db_row(
                cur.fetchone(),
                ("id", "total_amount", "status", "tenant_id", "order_id")
            )

        if not ord_row and not ledger_row and not settle_row and not intent_row:
            return None

        return {
            "order": ord_row,
            "ledger": ledger_row,
            "settlement": settle_row,
            "intent": intent_row,
        }
    except PaymentPersistenceError:
        raise
    except Exception as e:
        safe_e = sanitize_log_message(str(e))
        logger.error(f"[Authoritative PG Lookup Error] Query error for '{external_id}': {safe_e}")
        raise PaymentPersistenceError(f"Failed to query authoritative PostgreSQL SSOT for order '{external_id}': {safe_e}") from None
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


def sync_xendit_settlement_to_supabase_catchup(
    external_id: str,
    amount: Optional[Any] = None,
    payload: Optional[Dict[str, Any]] = None,
    raise_on_error: bool = False,
) -> bool:
    """
    Executes an idempotent catch-up replication to Supabase (Secondary Target)
    strictly from PostgreSQL (Primary Financial SSOT).

    Security & Financial Invariants (UNIT-P0-01A / BT-SEC-2026-001):
    1. Designated ONE Explicit Authoritative Source (Strict SSOT Hierarchy):
       - Primary: Committed financial_ledger record.
       - Secondary: Committed payment_settlements record (ONLY if financial_ledger is absent).
       - FAIL CLOSED: Zero fallback to orders or payment_intents for nominal designation.
    2. Strict Monetary Precision (Decimal Exactness):
       - Zero float() usage; parses and validates all amounts as Decimal integer minor-units.
       - Rejects NaN, Infinity, -Infinity, zero, negative amounts, fractional decimals, and overflow.
    3. Strict Cross-Table Status & Identity Validation:
       - No loose `any(...)`. Every present record must be in its explicit committed status whitelist.
       - orders.status AND orders.payment_status are validated independently (both must be committed).
       - Missing/null status on any present record fails closed.
       - tenant_id must be non-empty and matching across all present records.
       - order_id and provider_ref must be non-empty and match external_id.
    4. Zero Webhook Fallback:
       - Never falls back to webhook replay payloads or caller input for authoritative values.
    5. Fail-Closed Durability:
       - Inspects Supabase response objects (.error / status_code) on every write.
    """
    try:
        privileged_sb = get_payment_privileged_supabase()
        if not privileged_sb:
            return False

        # Step 1: Query authoritative data directly from PostgreSQL SSOT
        auth_data = _lookup_authoritative_pg_settlement_sync(str(external_id))
        if not auth_data:
            err_msg = (
                f"[SECURITY FAIL-CLOSED] Cannot synchronize order '{external_id}' to Supabase: "
                f"no authoritative committed record exists in PostgreSQL SSOT."
            )
            logger.error(f"[Xendit Supabase Catch-Up Sync Security Block] {err_msg}")
            if raise_on_error:
                raise PaymentPersistenceError(err_msg)
            return False

        ord_info = auth_data.get("order") or {}
        ledger_info = auth_data.get("ledger") or {}
        settle_info = auth_data.get("settlement") or {}
        intents_info = auth_data.get("intent") or {}

        # Step 2: Designate ONE explicit authoritative source for settlement nominal (Blocker A1)
        # Hierarchy: Primary = financial_ledger, Secondary = payment_settlements.
        # Fallback to orders.gross_amount or payment_intents.total_amount is STRICTLY PROHIBITED.
        designated_source = None
        designated_nominal_raw = None

        if ledger_info and ledger_info.get("gross_amount") is not None:
            designated_source = "financial_ledger"
            designated_nominal_raw = ledger_info.get("gross_amount")
        elif settle_info and settle_info.get("settled_amount") is not None:
            designated_source = "payment_settlements"
            designated_nominal_raw = settle_info.get("settled_amount")
        else:
            err_msg = (
                f"[SECURITY FAIL-CLOSED] Cannot synchronize order '{external_id}' to Supabase: "
                f"authoritative settlement nominal is missing from designated SSOT sources "
                f"(neither committed financial_ledger nor payment_settlements is available). "
                f"Fallback to orders.gross_amount or payment_intents.total_amount is strictly prohibited."
            )
            logger.critical(f"[Xendit Supabase Catch-Up Sync SSOT Violation] {err_msg}")
            if raise_on_error:
                raise PaymentPersistenceError(err_msg)
            return False

        # Step 3: Validate Monetary Precision of Designated Nominal (NO FLOAT)
        try:
            authoritative_nominal = validate_monetary_amount(
                designated_nominal_raw,
                field_name=f"{designated_source}.nominal",
                allow_fractional=False,
            )
        except MonetaryValidationError as mve:
            err_msg = (
                f"[SECURITY FAIL-CLOSED] Cannot synchronize order '{external_id}' to Supabase: "
                f"authoritative nominal '{designated_nominal_raw}' in {designated_source} "
                f"failed monetary validation: {mve}"
            )
            logger.error(f"[Xendit Supabase Catch-Up Sync Monetary Rejection] {err_msg}")
            if raise_on_error:
                raise PaymentPersistenceError(err_msg) from mve
            return False

        # Step 4: Strict Cross-Table Status & Identity Validation (Blocker A2)
        # 4a. Per-Record-Type Status Validation (Fail Closed on null, empty, uncommitted, or contradictory status)
        ORDER_VALID_STATUSES = {"LUNAS", "PAID", "SETTLED"}
        ORDER_VALID_PAYMENT_STATUSES = {"PAID", "SETTLED", "LUNAS"}
        LEDGER_VALID_STATUSES = {"SETTLED", "COMPLETED", "PAID", "SUCCESS"}
        SETTLEMENT_VALID_STATUSES = {"PAID", "SETTLED"}
        INTENT_VALID_STATUSES = {"SETTLED", "PAID"}

        # Validate orders record independently on both status and payment_status
        if ord_info:
            ord_status = ord_info.get("status")
            if ord_status is None or not str(ord_status).strip():
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record exists in orders table "
                    f"but 'status' is missing or null."
                )
                logger.error(f"[Xendit Catch-Up Status Error] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

            ord_status_clean = str(ord_status).strip().upper()
            if ord_status_clean not in ORDER_VALID_STATUSES:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' source 'orders' has "
                    f"uncommitted status '{ord_status}' (expected one of {ORDER_VALID_STATUSES})."
                )
                logger.error(f"[Xendit Catch-Up Status Conflict] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

            ord_payment_status = ord_info.get("payment_status")
            if ord_payment_status is None or not str(ord_payment_status).strip():
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record exists in orders table "
                    f"but 'payment_status' is missing or null."
                )
                logger.error(f"[Xendit Catch-Up Status Error] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

            ord_payment_status_clean = str(ord_payment_status).strip().upper()
            if ord_payment_status_clean not in ORDER_VALID_PAYMENT_STATUSES:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' source 'orders' has "
                    f"contradictory/uncommitted payment_status '{ord_payment_status}' (status is '{ord_status}')."
                )
                logger.error(f"[Xendit Catch-Up Status Conflict] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        # Validate financial_ledger record
        if ledger_info:
            ledger_status = ledger_info.get("status")
            if ledger_status is None or not str(ledger_status).strip():
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record exists in financial_ledger "
                    f"but 'status' is missing or null."
                )
                logger.error(f"[Xendit Catch-Up Status Error] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

            ledger_status_clean = str(ledger_status).strip().upper()
            if ledger_status_clean not in LEDGER_VALID_STATUSES:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' source 'financial_ledger' has "
                    f"uncommitted status '{ledger_status}' (expected one of {LEDGER_VALID_STATUSES})."
                )
                logger.error(f"[Xendit Catch-Up Status Conflict] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        # Validate payment_settlements record
        if settle_info:
            settle_status = settle_info.get("status")
            if settle_status is None or not str(settle_status).strip():
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record exists in payment_settlements "
                    f"but 'status' is missing or null."
                )
                logger.error(f"[Xendit Catch-Up Status Error] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

            settle_status_clean = str(settle_status).strip().upper()
            if settle_status_clean not in SETTLEMENT_VALID_STATUSES:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' source 'payment_settlements' has "
                    f"uncommitted status '{settle_status}' (expected one of {SETTLEMENT_VALID_STATUSES})."
                )
                logger.error(f"[Xendit Catch-Up Status Conflict] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        # Validate payment_intents record
        if intents_info:
            intent_status = intents_info.get("status")
            if intent_status is None or not str(intent_status).strip():
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record exists in payment_intents "
                    f"but 'status' is missing or null."
                )
                logger.error(f"[Xendit Catch-Up Status Error] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

            intent_status_clean = str(intent_status).strip().upper()
            if intent_status_clean not in INTENT_VALID_STATUSES:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' source 'payment_intents' has "
                    f"uncommitted status '{intent_status}' (expected one of {INTENT_VALID_STATUSES})."
                )
                logger.error(f"[Xendit Catch-Up Status Conflict] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        # 4b. Cross-verify nominal consistency across all records (Decimal exactness)
        record_nominals = {}
        if ord_info and ord_info.get("gross_amount") is not None:
            record_nominals["orders"] = ord_info.get("gross_amount")
        if ledger_info and ledger_info.get("gross_amount") is not None:
            record_nominals["financial_ledger"] = ledger_info.get("gross_amount")
        if settle_info and settle_info.get("settled_amount") is not None:
            record_nominals["payment_settlements"] = settle_info.get("settled_amount")
        if intents_info and intents_info.get("total_amount") is not None:
            record_nominals["payment_intents"] = intents_info.get("total_amount")

        for src, raw_nom in record_nominals.items():
            try:
                dec_nom = validate_monetary_amount(raw_nom, f"{src}.nominal", allow_fractional=False)
            except MonetaryValidationError as mve:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Monetary validation failed for order '{external_id}' "
                    f"in record '{src}': {mve}"
                )
                logger.error(f"[Xendit Catch-Up Monetary Conflict] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg) from mve
                return False

            if dec_nom != authoritative_nominal:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Cross-table nominal mismatch for order '{external_id}': "
                    f"designated nominal from {designated_source} ({authoritative_nominal}) != "
                    f"{src} nominal ({dec_nom})."
                )
                logger.critical(f"[Xendit Catch-Up Nominal Discrepancy Alert] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        # 4c. Cross-verify tenant_id presence and consistency across records
        tenants = {}
        if ord_info:
            ord_tenant = str(ord_info.get("tenant_id") or "").strip()
            if not ord_tenant:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record in 'orders' table "
                    f"is missing mandatory 'tenant_id'."
                )
                logger.critical(f"[Xendit Catch-Up Missing Tenant Alert] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            tenants["orders"] = ord_tenant

        if ledger_info:
            ledger_tenant = str(ledger_info.get("tenant_id") or "").strip()
            if not ledger_tenant:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record in 'financial_ledger' "
                    f"is missing mandatory 'tenant_id'."
                )
                logger.critical(f"[Xendit Catch-Up Missing Tenant Alert] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            tenants["financial_ledger"] = ledger_tenant

        if settle_info:
            settle_tenant = str(settle_info.get("tenant_id") or "").strip()
            if not settle_tenant and isinstance(settle_info.get("raw_payload"), dict):
                settle_tenant = str(settle_info["raw_payload"].get("tenant_id") or "").strip()
            if not settle_tenant:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record in 'payment_settlements' "
                    f"is missing mandatory 'tenant_id' (checked column and raw_payload)."
                )
                logger.critical(f"[Xendit Catch-Up Missing Tenant Alert] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            settle_info["tenant_id"] = settle_tenant
            tenants["payment_settlements"] = settle_tenant

        if intents_info:
            intent_tenant = str(intents_info.get("tenant_id") or "").strip()
            if not intent_tenant:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Order '{external_id}' record in 'payment_intents' "
                    f"is missing mandatory 'tenant_id'."
                )
                logger.critical(f"[Xendit Catch-Up Missing Tenant Alert] {err_msg}")
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            tenants["payment_intents"] = intent_tenant

        unique_tenants = set(tenants.values())
        if len(unique_tenants) > 1:
            err_msg = (
                f"[SECURITY FAIL-CLOSED] Cross-record tenant conflict for order '{external_id}': "
                f"conflicting tenants detected across records: {tenants}."
            )
            logger.critical(f"[Xendit Catch-Up Tenant Conflict Alert] {err_msg}")
            if raise_on_error:
                raise PaymentPersistenceError(err_msg)
            return False

        # 4d. Cross-verify order_id and provider_reference consistency across records
        if ord_info:
            ord_oid = str(ord_info.get("id") or "").strip()
            if not ord_oid:
                err_msg = f"[SECURITY FAIL-CLOSED] orders record is missing 'id' for order '{external_id}'."
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            if ord_oid != str(external_id):
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Cross-record order_id mismatch for order '{external_id}': "
                    f"orders record has id '{ord_oid}'."
                )
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        if ledger_info:
            ledger_oid = str(ledger_info.get("order_id") or "").strip()
            if not ledger_oid:
                err_msg = f"[SECURITY FAIL-CLOSED] financial_ledger record is missing 'order_id' for order '{external_id}'."
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            if ledger_oid != str(external_id):
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Cross-record order_id mismatch for order '{external_id}': "
                    f"financial_ledger record references unexpected order_id '{ledger_oid}'."
                )
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        if settle_info:
            settle_oid = str(settle_info.get("order_id") or "").strip()
            if not settle_oid and isinstance(settle_info.get("raw_payload"), dict):
                settle_oid = str(
                    settle_info["raw_payload"].get("order_id") 
                    or settle_info["raw_payload"].get("external_id") 
                    or ""
                ).strip()
            if not settle_oid:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] payment_settlements record for '{external_id}' "
                    f"is missing mandatory 'order_id' (checked column and raw_payload)."
                )
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            if settle_oid != str(external_id):
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Cross-record order_id mismatch for order '{external_id}': "
                    f"payment_settlements record references unexpected order_id '{settle_oid}'."
                )
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

            settle_pref = str(settle_info.get("provider_ref") or "").strip()
            if not settle_pref:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] payment_settlements record for '{external_id}' "
                    f"is missing mandatory 'provider_ref'."
                )
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False
            expected_provider_ref = f"xendit_{external_id}"
            if settle_pref != expected_provider_ref:
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] payment_settlements provider_ref '{settle_pref}' "
                    f"does not match exact canonical provider_reference '{expected_provider_ref}'."
                )
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        if intents_info:
            intent_oid = str(intents_info.get("order_id") or "").strip()
            if intent_oid and intent_oid != str(external_id):
                err_msg = (
                    f"[SECURITY FAIL-CLOSED] Cross-record order_id mismatch for order '{external_id}': "
                    f"payment_intents record references unexpected order_id '{intent_oid}'."
                )
                logger.critical(err_msg)
                if raise_on_error:
                    raise PaymentPersistenceError(err_msg)
                return False

        # Step 5: Webhook Replay Protection & Replicating to Supabase (ZERO WEBHOOK FALLBACK)
        if amount is not None:
            try:
                caller_dec = validate_monetary_amount(amount, "caller.amount", allow_fractional=True)
                if caller_dec != authoritative_nominal:
                    logger.warning(
                        f"[Xendit Catch-Up Security Override] Webhook caller amount ({caller_dec}) "
                        f"conflicts with authoritative PostgreSQL SSOT amount ({authoritative_nominal}). "
                        f"Discarding caller amount and strictly enforcing PostgreSQL SSOT value."
                    )
            except Exception as e:
                logger.warning(
                    f"[Xendit Catch-Up Security Discard] Webhook caller amount '{amount}' is invalid ({e}). "
                    f"Discarding caller input and strictly enforcing PostgreSQL SSOT value."
                )

        target_tenant = list(unique_tenants)[0] if unique_tenants else "onlineboost"

        authoritative_payload = (
            ledger_info.get("metadata")
            or settle_info.get("raw_payload")
            or {
                "order_id": external_id,
                "gross_amount": int(authoritative_nominal),
                "tenant_id": target_tenant,
                "source": "pg_ssot",
            }
        )

        settled_int = int(authoritative_nominal)
        upsert_res = privileged_sb.table("payment_settlements").upsert({
            "provider_ref": f"xendit_{external_id}",
            "settled_amount": settled_int,
            "status": "PAID",
            "raw_payload": authoritative_payload,
        }, on_conflict="provider_ref").execute()

        check_supabase_response_error(upsert_res, f"Supabase payment_settlements upsert for '{external_id}'")

        # Step 6: Update orders status in Supabase
        update_res = privileged_sb.table("orders").update({
            "status": "LUNAS",
            "payment_status": "PAID",
        }).eq("id", str(external_id)).execute()

        check_supabase_response_error(update_res, f"Supabase orders update for '{external_id}'")

        logger.info(
            f"[Xendit Supabase Catch-Up Sync] Successfully reconciled order '{external_id}' "
            f"to Supabase using authoritative PostgreSQL SSOT data (nominal: {settled_int})."
        )
        return True

    except PaymentCredentialConfigurationError as pce:
        logger.warning(f"[Xendit Supabase Catch-Up Sync Privileged Guard] {pce}")
        if raise_on_error:
            raise
        return False
    except PaymentPersistenceError as ppe:
        safe_ppe = sanitize_log_message(str(ppe))
        logger.error(f"[Xendit Supabase Catch-Up Sync Persistence Error] {safe_ppe}")
        if raise_on_error:
            raise
        return False
    except Exception as sb_err:
        safe_sb_err = sanitize_log_message(str(sb_err))
        logger.error(f"[Xendit Supabase Catch-Up Sync Error] {safe_sb_err}")
        if raise_on_error:
            raise PaymentPersistenceError(f"Failed to synchronize settlement to Supabase: {safe_sb_err}") from None
        return False



# -----------------------------------------------------------------------------
# Unified Core Webhook Processor
# -----------------------------------------------------------------------------


def _build_invalid_json_payload_response() -> Dict[str, Any]:
    """Return canonical HTTP 400 error envelope for non-object or malformed JSON payloads."""
    return {
        "http_status": 400,
        "response": {
            "status": "REJECTED",
            "error": "INVALID_JSON_PAYLOAD",
            "error_code": "INVALID_JSON_PAYLOAD",
            "detail": "Webhook JSON payload must be a valid JSON object.",
        },
    }


def _build_auth_failure_response() -> Dict[str, Any]:
    """Return indistinguishable HTTP 403 error envelope for all webhook auth failures."""
    return {
        "http_status": 403,
        "response": {
            "status": "REJECTED",
            "error": "INVALID_WEBHOOK_TOKEN",
            "error_code": "INVALID_WEBHOOK_TOKEN",
            "detail": "Webhook authentication failed.",
        },
    }


def _verify_unmatched_order_caller_token_sync(
    candidate_token: str,
    inbound_business_id: str = "",
    inbound_tenant: str = "",
) -> bool:
    """Verify x-callback-token in constant time when external_id has no persisted order.

    Fail-closed: requires authoritative inbound_tenant identity. If inbound_tenant is
    missing, empty, or unverified, immediately returns False without scanning tenant metadata
    or accepting any tenant credential as global authentication.
    """
    if not candidate_token or not inbound_tenant or not inbound_tenant.strip():
        return False

    clean_tenant = inbound_tenant.strip()
    mapper = CredentialProfileMapper()
    current_epoch = int(datetime.now(timezone.utc).timestamp())
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id::text, metadata FROM tenants WHERE (id::text = %s OR slug = %s) AND metadata IS NOT NULL;",
            (clean_tenant, clean_tenant),
        )
        rows = cur.fetchall() or []
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

    if not rows:
        return False

    matched = False
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            continue
        t_id = str(row[0] or "").strip()
        raw_meta = row[1]
        if isinstance(raw_meta, str):
            try:
                raw_meta = json.loads(raw_meta)
            except Exception:
                continue
        if not t_id or not isinstance(raw_meta, dict):
            continue

        try:
            profiles = mapper.parse_profiles_from_metadata(
                raw_meta,
                expected_canonical_tenant_id=t_id,
            )
        except Exception:
            continue

        for profile in profiles:
            if profile.provider != "XENDIT" or profile.profile_status != "ACTIVE":
                continue
            if mapper.runtime_environment == "production" and profile.environment != "production":
                continue
            if inbound_business_id and not hmac.compare_digest(
                profile.expected_provider_account_id,
                inbound_business_id,
            ):
                continue

            for secret_ver in profile.verification_secrets:
                if secret_ver.status == "REVOKED":
                    continue
                if secret_ver.status == "VERIFY_ONLY":
                    if secret_ver.not_after_epoch is not None and current_epoch > secret_ver.not_after_epoch:
                        continue
                elif secret_ver.status != "ACTIVE":
                    continue
                try:
                    raw_secret = mapper._resolve_secret_ref(secret_ver.secret_ref)
                except Exception:
                    continue
                if raw_secret and hmac.compare_digest(raw_secret, candidate_token):
                    matched = True

    return matched


async def process_xendit_webhook_core(
    payload: Any,
    headers: Optional[Mapping[str, str]],
) -> Dict[str, Any]:
    """
    Eksekutor terpadu (Unified Executor) webhook Xendit untuk seluruh runner (FastAPI & aiohttp):
    1. Strict JSON object (dict) payload validation (HTTP 400 INVALID_JSON_PAYLOAD).
    2. Mandatory constant-time x-callback-token & expected_provider_account_id auth BEFORE any
       response or error that could leak order existence, amount match/mismatch, or settlement status.
    3. Rejection of SaaS AI Quota Top-Up webhooks with HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD.
    4. Authoritative inside-out order lookup in PostgreSQL (orders INNER JOIN tenants).
    5. Strict IDR currency and integer amount verification against authoritative order gross_amount.
    6. Provably minted settlement capability via TrustedSettlementVerificationBoundary.
    7. Atomic persistence via commit_verified_settlement_transaction with 6-point composite idempotency.
    8. CTO Decision #4 Late Settlement Quarantine for terminal orders (EXPIRED, CANCELLED, FAILED).
    9. Decoupled background task dispatch (WA, CAPI) only on verified non-quarantined settlements.
    """
    # Step 0: Strict JSON object validation (reject [], str, int, bool, None)
    if not isinstance(payload, dict):
        logger.warning(f"[Xendit Webhook] Rejected non-object payload type: {type(payload).__name__}")
        return _build_invalid_json_payload_response()

    normalized_headers: Dict[str, str] = {}
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if k is not None and v is not None:
                normalized_headers[str(k).strip().lower()] = str(v).strip()

    candidate_token = normalized_headers.get("x-callback-token", "")

    # Step 1: Fail-closed immediately when x-callback-token is missing or empty
    if not candidate_token:
        logger.warning("[Xendit Webhook] Missing or empty x-callback-token.")
        return _build_auth_failure_response()

    raw_data = payload.get("data")
    data_obj = raw_data if isinstance(raw_data, dict) else payload

    external_id = str(
        data_obj.get("external_id")
        or data_obj.get("reference_id")
        or payload.get("external_id")
        or payload.get("id")
        or ""
    ).strip()

    # Step 2: SaaS Billing / Quota Top-Up Hold (CTO Decision #2) — prefix guard without DB lookup
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

    top_biz = str(payload.get("business_id") or "").strip()
    data_biz = str(raw_data.get("business_id") or "").strip() if isinstance(raw_data, dict) else ""
    if top_biz and data_biz and not hmac.compare_digest(top_biz, data_biz):
        logger.warning("[Xendit Webhook] Conflicting top-level business_id and data.business_id.")
        return _build_auth_failure_response()

    inbound_business_id = str(
        top_biz
        or data_biz
        or payload.get("user_id")
        or ""
    ).strip()

    inbound_tenant = str(
        payload.get("tenant_id")
        or payload.get("tenant_slug")
        or data_obj.get("tenant_id")
        or data_obj.get("tenant_slug")
        or ""
    ).strip()

    # Step 3: Internal authoritative order lookup (NEVER emit 404/400/422/200 before auth passes)
    persisted_order: Optional[Dict[str, Any]] = None
    if external_id:
        try:
            persisted_order = await asyncio.to_thread(_lookup_persisted_order_sync, external_id)
        except Exception as db_err:
            safe_db_err = sanitize_log_message(str(db_err))
            logger.error(f"[Xendit Webhook] Order lookup database error: {safe_db_err}")
            return {
                "http_status": 503,
                "response": {
                    "status": "FAILED",
                    "error": "DATABASE_UNAVAILABLE",
                    "error_code": "DATABASE_UNAVAILABLE",
                    "detail": safe_db_err,
                }
            }

    # Step 4: Mandatory x-callback-token & expected_provider_account_id verification BEFORE any oracle response
    if persisted_order is not None:
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
            safe_auth_err = sanitize_log_message(str(auth_err))
            logger.warning(
                f"[Xendit Webhook Auth Error] code={getattr(auth_err, 'error_code', 'AUTH_FAILED')} detail={safe_auth_err}"
            )
            return _build_auth_failure_response()
    else:
        try:
            caller_authenticated = await asyncio.to_thread(
                _verify_unmatched_order_caller_token_sync,
                candidate_token,
                inbound_business_id,
                inbound_tenant,
            )
        except Exception as db_err:
            safe_db_err = sanitize_log_message(str(db_err))
            logger.error(f"[Xendit Webhook] Unmatched-order auth lookup database error: {safe_db_err}")
            return {
                "http_status": 503,
                "response": {
                    "status": "FAILED",
                    "error": "DATABASE_UNAVAILABLE",
                    "error_code": "DATABASE_UNAVAILABLE",
                    "detail": safe_db_err,
                }
            }

        if not caller_authenticated:
            logger.warning("[Xendit Webhook Auth Error] Unmatched order rejected fail-closed due to invalid token or account.")
            return _build_auth_failure_response()

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

    # Step 5: Post-auth tenant claim verification
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

    # Step 6: Post-auth event status & non-paid handling
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

    # Step 7: Post-auth currency & amount validation
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

    # Step 7b: Capability Minting
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
        safe_prov_err = sanitize_log_message(str(prov_err))
        logger.warning(f"[Xendit Capability Minting Error] {safe_prov_err}")
        return {
            "http_status": getattr(prov_err, "http_status", 403) or 403,
            "response": {
                "status": "REJECTED",
                "error": prov_err.error_code,
                "error_code": prov_err.error_code,
                "detail": safe_prov_err,
            }
        }

    # Step 8: Atomic Settlement Persistence
    try:
        signer, verifier = _get_provenance_signer_and_verifier()
        commit_res = commit_verified_settlement_transaction(
            capability=capability,
            signer=signer,
            verifier=verifier,
            raw_webhook_payload=payload,
            db_conn_factory=get_db_connection,
        )
    except SettlementProvenanceError as prov_err:
        safe_prov_err = sanitize_log_message(str(prov_err))
        logger.error(f"[Xendit Settlement Error] {safe_prov_err}")
        http_status = getattr(prov_err, "http_status", 500) or 500
        return {
            "http_status": http_status,
            "response": {
                "status": "FAILED",
                "error": prov_err.error_code,
                "error_code": prov_err.error_code,
                "detail": safe_prov_err,
            }
        }

    # Step 9: Evaluate Commit Result
    commit_status = commit_res.get("status")
    if commit_status == "ALREADY_PROCESSED":
        logger.info(f"[Xendit Idempotency Hit] Order '{external_id}' already processed in PostgreSQL SSOT. Running idempotent Supabase catch-up sync.")
        sync_xendit_settlement_to_supabase_catchup(
            external_id=str(external_id),
            amount=parsed_amount,
            payload=payload,
        )
        return {
            "http_status": 200,
            "response": {
                "status": "ALREADY_PROCESSED",
                "message": f"Transaction '{external_id}' has already been settled in database; Supabase catch-up sync reconciled",
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
    sync_xendit_settlement_to_supabase_catchup(
        external_id=str(external_id),
        amount=parsed_amount,
        payload=payload,
    )
    xendit_service.mark_settled(external_id)

    customer_phone = persisted_order.get("customer_phone")
    customer_email = persisted_order.get("customer_email")
    product_name = persisted_order.get("product_title") or "Produk Digital"
    canonical_tenant_slug = persisted_order.get("tenant_slug") or "onlineboost"

    if customer_phone:
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
    if isinstance(x_callback_token, str):
        headers_dict["x-callback-token"] = x_callback_token

    try:
        payload = await request.json()
    except Exception as err:
        logger.error(f"[Xendit Webhook] Malformed JSON: {err}")
        bad = _build_invalid_json_payload_response()
        return JSONResponse(status_code=bad["http_status"], content=bad["response"])

    if not isinstance(payload, dict):
        logger.warning(f"[Xendit Webhook] Rejected non-object JSON payload: {type(payload).__name__}")
        bad = _build_invalid_json_payload_response()
        return JSONResponse(status_code=bad["http_status"], content=bad["response"])

    result = await process_xendit_webhook_core(payload, headers_dict)
    http_code = result.get("http_status", 200)
    response_body = result.get("response", {})

    if http_code != 200:
        return JSONResponse(status_code=http_code, content=response_body)

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
        bad = _build_invalid_json_payload_response()
        return web.json_response(bad["response"], status=bad["http_status"])

    if not isinstance(payload, dict):
        logger.warning(f"[Xendit aiohttp] Rejected non-object JSON payload: {type(payload).__name__}")
        bad = _build_invalid_json_payload_response()
        return web.json_response(bad["response"], status=bad["http_status"])

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
    existing = {
        getattr(getattr(r, "resource", None), "canonical", "")
        for r in aiohttp_app.router.routes()
        if getattr(r, "method", None) == "POST"
    }
    for r in routes:
        if r in existing:
            continue
        try:
            aiohttp_app.router.add_post(r, aiohttp_xendit_webhook)
        except Exception as re:
            logger.debug(f"[Xendit Route Add Note] {r}: {re}")

    logger.info("[Xendit] aiohttp routes registered successfully.")
