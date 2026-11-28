"""Core-owned SaaS billing API routes.

Catalog and quote preview are implemented as authenticated/read-only contract
surfaces. Payment mutations remain fail-closed until tax policy, durable quote
storage, SaaS Xendit settlement, and entitlement activation are approved and wired.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas.saas_billing import SaaSProduct, SaaSQuoteRequest
from app.services.saas_billing_auth import (
    SaaSBillingAuthorizationError,
    verify_internal_saas_billing_request,
)
from app.services.saas_billing_xendit import SaaSXenditProfileError, SaaSXenditProvider
from app.services.saas_billing_settlement import SaaSBillingSettlementRepository, SaaSSettlementError
from app.services.saas_billing_catalog import (
    CatalogError,
    TaxPolicy,
    get_catalog,
    quote_catalog_items,
)

saas_billing_router = APIRouter(
    prefix="/api/v1/saas-billing",
    tags=["Core SaaS Billing"],
)


def _error(code: str, status_code: int, *, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": code,
                "request_id": None,
                "retryable": retryable,
            }
        },
    )


def _quote_response(quote: Any, canonical_tenant_id: str) -> dict[str, Any]:
    return {
        "quote_id": quote.quote_id,
        "canonical_tenant_id": canonical_tenant_id,
        "product": quote.product.value,
        "catalog_version": quote.catalog_version,
        "lines": [
            {
                "sku": line.sku,
                "item_kind": line.item_kind.value,
                "cadence": line.cadence.value,
                "quantity": line.quantity,
                "unit_amount_idr": line.unit_amount_idr,
                "line_amount_idr": line.line_amount_idr,
                "entitlement_key": line.entitlement_key,
                "credit_units": line.credit_units,
                "entitlement_validity_days": line.entitlement_validity_days,
            }
            for line in quote.lines
        ],
        "subtotal_idr": quote.subtotal_idr,
        "tax_status": quote.tax_status,
        "tax_amount_idr": quote.tax_amount_idr,
        "total_idr": quote.total_idr,
        "currency": quote.currency,
        "quote_status": quote.quote_status,
        "payment_intent_allowed": quote.payment_intent_allowed,
    }


@saas_billing_router.get("/catalog")
async def read_saas_billing_catalog(product: str) -> JSONResponse:
    """Read-only public pricebook; contains no tenant, payment, or credential data."""
    try:
        selected_product = SaaSProduct(str(product).strip().upper())
    except ValueError:
        return _error("BILLING_PRODUCT_INVALID", 422)

    items = []
    for entry in get_catalog(selected_product):
        items.append(
            {
                "sku": entry.sku,
                "display_name": entry.display_name,
                "item_kind": entry.item_kind.value,
                "cadence": entry.cadence.value,
                "amount_idr": entry.amount_idr,
                "validity_days": entry.entitlement_validity_days,
                "entitlement_key": entry.entitlement_key,
                "credit_units": entry.credit_units,
                "sellable": entry.sellable and entry.approval_state.value == "APPROVED",
                "dependency_keys": list(entry.dependency_keys),
                "is_default_checkout": entry.is_default_checkout,
                "campaign_key": entry.campaign_key,
            }
        )
    from app.services.saas_billing_catalog import CATALOG_VERSION, CURRENCY

    return JSONResponse(
        content={
            "catalog_version": CATALOG_VERSION,
            "product": selected_product.value,
            "currency": CURRENCY,
            "items": items,
        }
    )


@saas_billing_router.post("/quotes")
async def create_saas_billing_quote(request: Request) -> JSONResponse:
    """Create an authenticated, deterministic quote; pending tax remains non-payable."""
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
        quote_request = SaaSQuoteRequest.from_mapping(payload)
        if not quote_request.request_reference or not quote_request.idempotency_key:
            return _error("BILLING_QUOTE_CONTEXT_REQUIRED", 422)
        quote = quote_catalog_items(
            product=quote_request.product,
            items=quote_request.items,
            catalog_version=quote_request.catalog_version,
            tax_policy=TaxPolicy.pending(),
        )
        auth_context = verify_internal_saas_billing_request(
            headers=request.headers,
            http_method="POST",
            canonical_path="/api/v1/saas-billing/quotes",
            raw_body=raw_body,
            quote_request=quote_request,
            quote=quote,
        )
        tenant_id = str(getattr(auth_context, "canonical_tenant_id", "")).strip()
        if not tenant_id:
            return _error("BILLING_CANONICAL_TENANT_UNAVAILABLE", 503, retryable=True)
        return JSONResponse(content=_quote_response(quote, tenant_id))
    except SaaSBillingAuthorizationError as exc:
        return _error(exc.code, exc.http_status, retryable=exc.http_status == 503)
    except CatalogError as exc:
        return _error(exc.code, 409 if exc.code == "BILLING_TAX_POLICY_PENDING" else 422)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _error(str(exc) or "BILLING_INVALID_REQUEST", 422)
    except Exception:
        return _error("CORE_BILLING_UNAVAILABLE", 503, retryable=True)


@saas_billing_router.post("/payment-intents")
async def create_saas_payment_intent(request: Request) -> JSONResponse:
    """Fail closed until quote persistence, approved tax policy, and provider pipeline exist."""
    try:
        payload = await request.json()
    except Exception:
        return _error("BILLING_INVALID_REQUEST", 400)
    if not isinstance(payload, dict):
        return _error("BILLING_INVALID_REQUEST", 400)
    if any(
        key in payload
        for key in (
            "amount", "subtotal", "tax", "tax_amount", "total", "currency",
            "provider", "merchant_account", "credential", "credential_profile_id",
            "tenant_id", "tenant_slug", "checkout_url",
        )
    ):
        return _error("BILLING_CLIENT_AUTHORITY_FIELD_PROHIBITED", 422)
    # Tax policy is still explicitly pending. No purchase, payment intent, or outbox
    # row is created while this hard gate remains in force.
    return _error("BILLING_TAX_POLICY_PENDING", 409)


@saas_billing_router.get("/payment-intents/{intent_id}")
async def read_saas_payment_intent(intent_id: str) -> JSONResponse:
    if not intent_id.strip():
        return _error("BILLING_PAYMENT_INTENT_ID_REQUIRED", 422)
    return _error("CORE_BILLING_UNAVAILABLE", 503, retryable=True)


@saas_billing_router.post("/webhooks/xendit")
async def receive_saas_xendit_webhook(request: Request) -> JSONResponse:
    """Verify the dedicated SaaS callback and atomically settle only its bound sandbox purchase."""
    try:
        provider = SaaSXenditProvider()
    except SaaSXenditProfileError:
        return _error("BILLING_PROVIDER_PROFILE_UNAVAILABLE", 503, retryable=True)
    supplied = str(request.headers.get("x-callback-token", "")).strip()
    if not provider.verify_callback_token(supplied):
        return _error("BILLING_PROVIDER_CALLBACK_UNAUTHORIZED", 403)
    try:
        payload = await request.json()
        result = SaaSBillingSettlementRepository().settle_xendit_paid_event(
            payload,
            credential_profile_id=provider.profile.profile_id,
            business_id=provider.profile.business_id,
        )
        return JSONResponse(content=result)
    except SaaSSettlementError as exc:
        return _error(exc.code, exc.status_code, retryable=exc.status_code >= 500)
    except Exception:
        return _error("BILLING_SETTLEMENT_PIPELINE_UNAVAILABLE", 503, retryable=True)


@saas_billing_router.post("/reconciliation/{intent_id}")
async def reconcile_saas_payment_intent(intent_id: str, request: Request) -> JSONResponse:
    return _error("BILLING_RECONCILIATION_NOT_AVAILABLE", 503, retryable=True)
