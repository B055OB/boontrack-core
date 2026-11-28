"""Server-to-server authorization boundary for SaaS billing mutations.

This deliberately reuses Core's payment HMAC verifier (canonical tenant resolution,
bound principal, timestamp/nonce checks, and PostgreSQL anti-replay). It does not
accept browser identity or trust a tenant header by itself.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping

from app.schemas.saas_billing import SaaSProduct, SaaSQuoteRequest
from app.services.saas_billing_catalog import SaaSQuote, CatalogError


class SaaSBillingAuthorizationError(PermissionError):
    def __init__(self, code: str, http_status: int = 403):
        self.code = code
        self.http_status = http_status
        super().__init__(code)


def _trusted_principals(
    product: SaaSProduct,
    environ: Mapping[str, str],
) -> frozenset[str]:
    raw = str(environ.get("SAAS_BILLING_TRUSTED_PRINCIPALS_JSON", "")).strip()
    if not raw:
        raise SaaSBillingAuthorizationError("BILLING_PRODUCT_PRINCIPALS_NOT_CONFIGURED", 503)
    try:
        config = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise SaaSBillingAuthorizationError("BILLING_PRODUCT_PRINCIPALS_INVALID", 503) from exc
    if not isinstance(config, dict):
        raise SaaSBillingAuthorizationError("BILLING_PRODUCT_PRINCIPALS_INVALID", 503)
    values = config.get(product.value)
    if not isinstance(values, list):
        raise SaaSBillingAuthorizationError("BILLING_PRODUCT_PRINCIPALS_INVALID", 503)
    principals = frozenset(str(value).strip() for value in values if str(value).strip())
    if not principals:
        raise SaaSBillingAuthorizationError("BILLING_PRODUCT_PRINCIPALS_INVALID", 503)
    return principals


def verify_internal_saas_billing_request(
    *,
    headers: Mapping[str, Any],
    http_method: str,
    canonical_path: str,
    raw_body: bytes,
    quote_request: SaaSQuoteRequest,
    quote: SaaSQuote,
    db_connection_factory: Any = None,
    environ: Mapping[str, str] | None = None,
) -> Any:
    """Verify a signed product-server mutation and enforce product principal binding.

    The request body is verified byte-for-byte by Core's Stage 2 payment HMAC helper.
    The x-tenant-id header is only a lookup hint; the verifier resolves the canonical
    tenant from PostgreSQL and checks it against the HMAC key's bound tenant identity.
    """
    env = environ if environ is not None else os.environ
    if quote.product != quote_request.product:
        raise SaaSBillingAuthorizationError("BILLING_PRODUCT_MISMATCH", 403)
    if not quote.payment_intent_allowed or quote.total_idr is None:
        raise CatalogError("BILLING_TAX_POLICY_PENDING")

    normalized_headers = {str(k).strip().lower(): str(v).strip() for k, v in headers.items()}
    tenant_hint = normalized_headers.get("x-tenant-id", "")
    if not tenant_hint:
        raise SaaSBillingAuthorizationError("BILLING_TENANT_CONTEXT_REQUIRED", 401)

    request_reference = str(quote_request.request_reference or "").strip()
    if not request_reference:
        raise SaaSBillingAuthorizationError("BILLING_REQUEST_REFERENCE_REQUIRED", 422)
    idempotency_key = str(quote_request.idempotency_key or "").strip()
    if not idempotency_key:
        raise SaaSBillingAuthorizationError("BILLING_IDEMPOTENCY_KEY_REQUIRED", 422)

    if db_connection_factory is None:
        from app.core.database import get_db_connection
        db_connection_factory = get_db_connection

    from app.core.security.payment_auth_guard import (
        PaymentAuthorizationError,
        verify_stage2_payment_initiation_request,
    )

    try:
        auth_context = verify_stage2_payment_initiation_request(
            headers=headers,
            http_method=http_method,
            canonical_path=canonical_path,
            order_id=request_reference,
            tenant_id_or_slug=tenant_hint,
            derived_amount=quote.total_idr,
            sku_id=",".join(line.sku for line in quote.lines),
            raw_body=raw_body,
            db_connection_factory=db_connection_factory,
            environ=env,
        )
    except PaymentAuthorizationError as exc:
        raise SaaSBillingAuthorizationError(
            getattr(exc, "error_code", "BILLING_AUTH_REQUIRED"),
            getattr(exc, "http_status", 403),
        ) from exc

    allowed = _trusted_principals(quote_request.product, env)
    principal = str(getattr(auth_context, "verified_actor_principal", "")).strip()
    if not principal or principal not in allowed:
        raise SaaSBillingAuthorizationError("BILLING_PRODUCT_PRINCIPAL_FORBIDDEN", 403)

    return auth_context
