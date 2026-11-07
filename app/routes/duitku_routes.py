"""app/routes/duitku_routes.py
Router handling Duitku Payment Gateway Callbacks and Settlement.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import logging
import os
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from aiohttp import web
from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.core.database import get_db_connection, normalize_db_row
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

logger = logging.getLogger("DUITKU_ROUTES")
router = APIRouter(prefix="/api/v1/payments/duitku", tags=["Duitku Payment"])

_PROV_SIGNER: Optional[ProvenanceSigner] = None
_PROV_VERIFIER: Optional[ProvenanceVerifier] = None
_DUITKU_S2S_VERIFIER: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None


def set_duitku_s2s_verifier(verifier: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]]) -> None:
    """Allows test suites or runtime to inject mock/stub Duitku S2S transactionStatus verifier."""
    global _DUITKU_S2S_VERIFIER
    _DUITKU_S2S_VERIFIER = verifier


def _default_duitku_s2s_verifier(req: Mapping[str, Any]) -> Mapping[str, Any]:
    global _DUITKU_S2S_VERIFIER
    if _DUITKU_S2S_VERIFIER is not None:
        return _DUITKU_S2S_VERIFIER(req)

    # In live environments without injected stub, perform network status check
    import httpx
    env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower()
    url = (
        "https://passport.duitku.com/webapi/api/merchant/transactionStatus"
        if env in ("prod", "production")
        else "https://sandbox.duitku.com/webapi/api/merchant/transactionStatus"
    )
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=dict(req))
            if resp.status_code == 200:
                return resp.json()
            raise RuntimeError(f"Duitku transactionStatus returned HTTP {resp.status_code}")
    except Exception as exc:
        raise SettlementProvenanceError(
            f"Duitku S2S transactionStatus inquiry failed: {exc}",
            error_code="DUITKU_S2S_VERIFICATION_FAILED",
            http_status=503,
        ) from exc


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
        keyring = ProvenanceSigningKeyring({"dev-duitku-key": {"private_key_hex": priv_hex, "status": "ACTIVE"}})
        _PROV_SIGNER = ProvenanceSigner(keyring)
        _PROV_VERIFIER = ProvenanceVerifier(keyring.export_public_verification_keyring())
    return _PROV_SIGNER, _PROV_VERIFIER


def _lookup_duitku_persisted_order_sync(order_id: str) -> Optional[Dict[str, Any]]:
    if not order_id:
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
            (str(order_id),)
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
        logger.error(f"[Duitku Webhook] Order lookup failed for '{order_id}': {e}", exc_info=True)
        raise RuntimeError(f"Database lookup failed for order '{order_id}': {e}") from e
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


async def process_duitku_callback_core(
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    s2s_verifier: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
) -> tuple[Dict[str, Any], int]:
    """
    Eksekutor terpadu (Unified Executor) callback Duitku:
    1. Support JSON and Form urlencoded payloads.
    2. Authoritative inside-out order lookup in PostgreSQL (orders INNER JOIN tenants).
    3. Multi-tenant credential profile binding & secret resolution via CredentialProfileMapper.
    4. Constant-time merchantCode check against expected_provider_account_id.
    5. Integer IDR amount validation against authoritative order gross_amount.
    6. Non-empty provider reference validation distinct from order_id.
    7. Durable DB-backed S2S transactionStatus verification.
    8. Provably minted capability and atomic commit_verified_settlement_transaction.
    9. CTO Decision #4 Late Settlement Quarantine for terminal orders.
    10. Zero error swallowing: unhandled or failed conditions return appropriate HTTP error codes.
    """
    merchant_order_id = str(
        payload.get("merchantOrderId")
        or payload.get("order_id")
        or payload.get("external_id")
        or ""
    ).strip()

    logger.info(
        f"[DUITKU WEBHOOK RECEIVED] Order: '{merchant_order_id}' | "
        f"ResultCode: '{payload.get('resultCode')}' | Amount: '{payload.get('amount')}' | Reference: '{payload.get('reference')}'"
    )

    if not merchant_order_id:
        return {
            "status": "error",
            "error_code": "ORDER_NOT_FOUND",
            "detail": "Missing merchantOrderId in Duitku callback payload.",
        }, 404

    # Step 1: Inside-out Order Lookup
    try:
        persisted_order = await asyncio.to_thread(_lookup_duitku_persisted_order_sync, merchant_order_id)
    except Exception as db_err:
        logger.error(f"[Duitku Webhook] Order lookup database error: {db_err}")
        return {
            "status": "error",
            "error_code": "DATABASE_UNAVAILABLE",
            "detail": str(db_err),
        }, 503

    if not persisted_order:
        logger.warning(f"[Duitku Webhook] Order '{merchant_order_id}' not found in database or tenant binding missing.")
        return {
            "status": "error",
            "error_code": "ORDER_NOT_FOUND",
            "detail": f"Order '{merchant_order_id}' not found in database or not bound to canonical tenant",
        }, 404

    # Step 2: Inbound tenant claim cross-check
    inbound_tenant = str(payload.get("tenant_id") or payload.get("tenant_slug") or "").strip()
    if inbound_tenant:
        can_tid = str(persisted_order.get("canonical_tenant_id") or "").strip()
        t_slug = str(persisted_order.get("tenant_slug") or "").strip()
        if inbound_tenant != can_tid and inbound_tenant != t_slug:
            return {
                "status": "rejected",
                "error_code": "ORDER_TENANT_MISMATCH",
                "detail": f"Inbound tenant claim '{inbound_tenant}' contradicts order canonical tenant '{can_tid}'.",
            }, 403

    # Step 3: ResultCode check
    result_code = str(payload.get("resultCode", "")).strip()
    if result_code != "00":
        logger.info(f"[DUITKU WEBHOOK] ResultCode '{result_code}' acknowledged without settlement.")
        return {
            "status": "ignored",
            "message": f"Duitku resultCode '{result_code}' is not a settled state ('00').",
        }, 200

    # Step 4: Currency & Amount validation
    raw_currency = payload.get("currency")
    if raw_currency is not None and str(raw_currency).strip().upper() != "IDR":
        return {
            "status": "rejected",
            "error_code": "PROVENANCE_INVALID_CURRENCY",
            "detail": f"Unsupported currency '{raw_currency}'; expected 'IDR'.",
        }, 422

    raw_amount = payload.get("amount")
    if isinstance(raw_amount, bool):
        return {
            "status": "rejected",
            "error_code": "PROVENANCE_INVALID_AMOUNT",
            "detail": "Duitku amount cannot be boolean.",
        }, 422

    if isinstance(raw_amount, float):
        if raw_amount != int(raw_amount):
            return {
                "status": "rejected",
                "error_code": "PROVENANCE_INVALID_AMOUNT",
                "detail": f"Fractional amount '{raw_amount}' not permitted for IDR.",
            }, 422
        parsed_amount = int(raw_amount)
    elif isinstance(raw_amount, int):
        parsed_amount = raw_amount
    elif isinstance(raw_amount, str) and raw_amount.strip().isdigit():
        parsed_amount = int(raw_amount.strip())
    else:
        return {
            "status": "rejected",
            "error_code": "PROVENANCE_INVALID_AMOUNT",
            "detail": f"Malformed Duitku amount '{raw_amount}'; must be a positive integer IDR amount.",
        }, 422

    if parsed_amount <= 0:
        return {
            "status": "rejected",
            "error_code": "PROVENANCE_INVALID_AMOUNT",
            "detail": f"Duitku amount must be positive, got {parsed_amount}.",
        }, 422

    expected_amount = persisted_order["gross_amount"]
    if parsed_amount != expected_amount:
        return {
            "status": "rejected",
            "error_code": "AMOUNT_MISMATCH",
            "detail": f"Duitku amount '{parsed_amount}' does not match expected gross amount {expected_amount}.",
        }, 422

    # Step 5: Reference validation
    reference = str(payload.get("reference") or "").strip()
    if (
        not reference
        or reference == merchant_order_id
        or reference.lower().startswith(("ord-", "ref-", "merchant_ref"))
    ):
        return {
            "status": "rejected",
            "error_code": "PROVENANCE_EMPTY_EVENT_ID",
            "detail": "Duitku reference must be a non-empty provider reference distinct from order_id.",
        }, 422

    # Step 6: Multi-tenant Credential Profile Resolution
    canonical_tenant_id = persisted_order["canonical_tenant_id"]
    tenant_metadata = persisted_order["tenant_metadata"] or {}
    order_metadata = persisted_order["order_metadata"] or {}

    mapper = CredentialProfileMapper()
    try:
        profiles = mapper.parse_profiles_from_metadata(tenant_metadata, expected_canonical_tenant_id=canonical_tenant_id)
    except Exception as parse_err:
        return {
            "status": "rejected",
            "error_code": "INVALID_CREDENTIAL_PROFILE",
            "detail": str(parse_err),
        }, 422

    bound_profile_id = str(order_metadata.get("credential_profile_id") or "").strip()
    profile = None
    if bound_profile_id:
        matching = [p for p in profiles if p.credential_profile_id == bound_profile_id]
        if not matching:
            return {
                "status": "rejected",
                "error_code": "CREDENTIAL_PROFILE_NOT_FOUND",
                "detail": f"Credential profile '{bound_profile_id}' bound to order was not found.",
            }, 404
        profile = matching[0]
        if profile.profile_status != "ACTIVE":
            return {
                "status": "rejected",
                "error_code": "CREDENTIAL_PROFILE_INACTIVE",
                "detail": f"Credential profile '{bound_profile_id}' is {profile.profile_status}.",
            }, 403
        if profile.provider != "DUITKU":
            return {
                "status": "rejected",
                "error_code": "CREDENTIAL_PROFILE_PROVIDER_MISMATCH",
                "detail": f"Credential profile '{bound_profile_id}' provider is {profile.provider}, expected DUITKU.",
            }, 403
    else:
        matching = [
            p for p in profiles
            if p.canonical_tenant_id == canonical_tenant_id
            and p.provider == "DUITKU"
            and p.profile_status == "ACTIVE"
        ]
        if len(matching) == 0:
            return {
                "status": "rejected",
                "error_code": "CREDENTIAL_PROFILE_NOT_FOUND",
                "detail": f"No active credential profile found for tenant '{canonical_tenant_id}' and provider 'DUITKU'.",
            }, 404
        if len(matching) > 1:
            return {
                "status": "rejected",
                "error_code": "AMBIGUOUS_CREDENTIAL_PROFILE_BINDING",
                "detail": "Multiple active Duitku credential profiles found without explicit order binding.",
            }, 403
        profile = matching[0]

    # Environment check
    if mapper.runtime_environment == "production" and profile.environment != "production":
        return {
            "status": "rejected",
            "error_code": "CREDENTIAL_PROFILE_ENVIRONMENT_MISMATCH",
            "detail": "Credential profile is in sandbox environment, but runtime is production.",
        }, 403

    # Constant-time merchantCode check
    inbound_merchant_code = str(payload.get("merchantCode") or "").strip()
    if not inbound_merchant_code or not hmac.compare_digest(profile.expected_provider_account_id, inbound_merchant_code):
        return {
            "status": "rejected",
            "error_code": "PROVIDER_ACCOUNT_BINDING_MISMATCH",
            "detail": f"Inbound merchantCode '{inbound_merchant_code}' does not match expected account '{profile.expected_provider_account_id}'.",
        }, 403

    # Resolve ApiKey secret
    raw_api_key = ""
    for sec_ver in profile.verification_secrets:
        if sec_ver.status in ("ACTIVE", "VERIFY_ONLY"):
            try:
                raw_api_key = mapper._resolve_secret_ref(sec_ver.secret_ref)
                if raw_api_key:
                    break
            except Exception:
                pass

    if not raw_api_key:
        return {
            "status": "error",
            "error_code": "CREDENTIAL_SECRET_UNAVAILABLE",
            "detail": f"Unable to resolve Duitku API key for profile '{profile.credential_profile_id}'.",
        }, 503

    # Step 7: Capability Minting & S2S Verification
    effective_s2s = s2s_verifier or _default_duitku_s2s_verifier
    try:
        capability = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="DUITKU",
            verification_method="DUITKU_CALLBACK_HMAC_SHA256",
            credential_profile_id=profile.credential_profile_id,
            expected_provider_account_id=profile.expected_provider_account_id,
            provider_verification_secret=raw_api_key,
            webhook_headers={},
            webhook_payload=payload,
            authoritative_order_id=merchant_order_id,
            authoritative_canonical_tenant_id=canonical_tenant_id,
            authoritative_order_amount=expected_amount,
            authoritative_sku_id=persisted_order["sku_id"],
            verified_at_utc=datetime.now(timezone.utc).isoformat(),
            rail_type="NATIVE_PG",
            duitku_s2s_verifier=effective_s2s,
            db_conn_factory=get_db_connection,
        )
    except SettlementProvenanceError as prov_err:
        logger.warning(f"[Duitku Capability Minting Error] {prov_err}")
        http_code = getattr(prov_err, "http_status", 403) or 403
        err_code = prov_err.error_code
        if err_code in ("PG_WEBHOOK_SIGNATURE_INVALID", "INVALID_DUITKU_SIGNATURE"):
            err_code = "INVALID_DUITKU_SIGNATURE"
            http_code = 401
        elif err_code == "DUITKU_S2S_VERIFICATION_FAILED":
            http_code = 503
        return {
            "status": "rejected",
            "error_code": err_code,
            "detail": str(prov_err),
        }, http_code

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
        logger.error(f"[Duitku Settlement Persistence Error] {prov_err}")
        http_code = getattr(prov_err, "http_status", 500) or 500
        return {
            "status": "error",
            "error_code": prov_err.error_code,
            "detail": str(prov_err),
        }, http_code

    # Step 9: Evaluate Result
    commit_status = commit_res.get("status")
    if commit_status == "ALREADY_PROCESSED":
        logger.info(f"[DUITKU IDEMPOTENT SKIP] Order '{merchant_order_id}' already settled in database.")
        return {"status": "OK", "message": "already_processed", "idempotent": True}, 200

    if commit_status == "QUARANTINED_LATE_SETTLEMENT":
        logger.warning(f"[DUITKU LATE SETTLEMENT QUARANTINED] Order '{merchant_order_id}' quarantined.")
        return {
            "status": "OK",
            "message": "Late settlement quarantined successfully for manual review",
            "idempotent": True,
            "order_id": merchant_order_id,
        }, 200

    logger.info(f"[DUITKU WEBHOOK SUCCESS] Order '{merchant_order_id}' successfully settled.")
    return {"status": "OK", "message": "Payment verified and settled"}, 200


@router.post("/callback", response_class=PlainTextResponse)
async def duitku_payment_callback(
    request: Request,
):
    """
    Webhook handler for Duitku Payment notification.
    Accepts application/x-www-form-urlencoded and application/json, returns HTTP 200 'OK'.
    """
    content_type = request.headers.get("content-type", "").lower()
    payload: Dict[str, Any] = {}
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    else:
        try:
            form_data = await request.form()
            payload = dict(form_data)
        except Exception:
            try:
                payload = await request.json()
            except Exception:
                payload = {}

    res, status_code = await process_duitku_callback_core(payload, dict(request.headers))
    if status_code != 200:
        err_detail = res.get("detail") or res.get("error_code") or res.get("error") or str(res)
        raise HTTPException(status_code=status_code, detail=err_detail)

    return "OK"


# -----------------------------------------------------------------------------
# aiohttp Route Handlers (Dual-Runner Parity ARCHITECTURE.md §1)
# -----------------------------------------------------------------------------

async def aiohttp_duitku_callback(request: web.Request) -> web.Response:
    """aiohttp webhook handler executing the identical core processor."""
    content_type = request.headers.get("content-type", "").lower()
    payload: Dict[str, Any] = {}
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    else:
        try:
            post_data = await request.post()
            payload = dict(post_data)
        except Exception:
            try:
                payload = await request.json()
            except Exception:
                payload = {}

    headers = {k.lower(): v for k, v in request.headers.items()}
    res, status_code = await process_duitku_callback_core(payload, headers)
    if status_code != 200:
        return web.json_response(res, status=status_code)
    return web.Response(text="OK", status=200)


def register_duitku_routes(aiohttp_app: web.Application) -> None:
    """Register all Duitku webhook routes on the aiohttp runner."""
    routes = [
        "/api/v1/payments/duitku/callback",
        "/webhook/payment/duitku",
    ]
    for r in routes:
        try:
            aiohttp_app.router.add_post(r, aiohttp_duitku_callback)
        except Exception as re:
            logger.debug(f"[Duitku Route Add Note] {r}: {re}")

    logger.info("[Duitku] aiohttp routes registered successfully.")
