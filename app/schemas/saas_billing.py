"""Typed request and response shapes for the shared Core SaaS billing contract.

The request intentionally contains no amount, currency, tenant identifier, provider,
merchant account, credential, or entitlement result. Those values are authoritative
Core-side data and must be resolved server-side.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, Mapping, Tuple


class SaaSProduct(str, Enum):
    SHOP = "SHOP"
    STUDIO = "STUDIO"


class BillingItemKind(str, Enum):
    BASE_TIER = "BASE_TIER"
    SUBSCRIPTION = "SUBSCRIPTION"
    STANDALONE_ADDON = "STANDALONE_ADDON"
    BUNDLE_INCLUDED = "BUNDLE_INCLUDED"
    CREDIT_TOPUP = "CREDIT_TOPUP"
    LIFETIME_LICENSE = "LIFETIME_LICENSE"


class CatalogApprovalState(str, Enum):
    APPROVED = "APPROVED"
    PENDING_CFO_APPROVAL = "PENDING_CFO_APPROVAL"
    DEFERRED = "DEFERRED"


class BillingCadence(str, Enum):
    FREE = "FREE"
    ONE_TIME = "ONE_TIME"
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"
    LIFETIME = "LIFETIME"


@dataclass(frozen=True)
class SaaSQuoteLineRequest:
    sku: str
    quantity: int = 1


@dataclass(frozen=True)
class SaaSQuoteRequest:
    product: SaaSProduct
    items: Tuple[SaaSQuoteLineRequest, ...]
    catalog_version: str | None = None
    request_reference: str | None = None
    idempotency_key: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SaaSQuoteRequest":
        if not isinstance(payload, Mapping):
            raise ValueError("BILLING_INVALID_REQUEST")

        allowed = {"product", "items", "catalog_version", "request_reference", "idempotency_key"}
        forbidden = {
            "amount", "subtotal", "tax", "tax_amount", "total", "currency",
            "provider", "payment_provider", "merchant_account", "credential",
            "credential_profile_id", "tenant_id", "tenant_slug", "entitlement",
            "entitlement_status", "price", "unit_price",
        }
        keys = {str(key) for key in payload.keys()}
        if keys & forbidden or keys - allowed:
            raise ValueError("BILLING_CLIENT_AUTHORITY_FIELD_PROHIBITED")

        try:
            product = SaaSProduct(str(payload.get("product", "")).upper())
        except ValueError as exc:
            raise ValueError("BILLING_PRODUCT_INVALID") from exc

        raw_items = payload.get("items")
        if not isinstance(raw_items, (list, tuple)) or not raw_items:
            raise ValueError("BILLING_ITEMS_REQUIRED")

        items = []
        seen = set()
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise ValueError("BILLING_ITEM_INVALID")
            if set(raw.keys()) - {"sku", "quantity"}:
                raise ValueError("BILLING_CLIENT_AUTHORITY_FIELD_PROHIBITED")
            sku = str(raw.get("sku", "")).strip().upper()
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{1,95}", sku):
                raise ValueError("BILLING_SKU_INVALID")
            if sku in seen:
                raise ValueError("BILLING_DUPLICATE_SKU")
            seen.add(sku)
            quantity = raw.get("quantity", 1)
            if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 20:
                raise ValueError("BILLING_QUANTITY_INVALID")
            items.append(SaaSQuoteLineRequest(sku=sku, quantity=quantity))

        catalog_version = payload.get("catalog_version")
        if catalog_version is not None:
            catalog_version = str(catalog_version).strip()
            if not catalog_version or len(catalog_version) > 64:
                raise ValueError("BILLING_CATALOG_VERSION_INVALID")

        request_reference = payload.get("request_reference")
        if request_reference is not None:
            request_reference = str(request_reference).strip()
            if not request_reference or len(request_reference) > 128:
                raise ValueError("BILLING_REQUEST_REFERENCE_INVALID")

        idempotency_key = payload.get("idempotency_key")
        if idempotency_key is not None:
            idempotency_key = str(idempotency_key).strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", idempotency_key):
                raise ValueError("BILLING_IDEMPOTENCY_KEY_INVALID")

        return cls(
            product=product,
            items=tuple(items),
            catalog_version=catalog_version,
            request_reference=request_reference,
            idempotency_key=idempotency_key,
        )


@dataclass(frozen=True)
class SaaSQuoteLine:
    sku: str
    item_kind: BillingItemKind
    quantity: int
    unit_amount_idr: int
    line_amount_idr: int
    entitlement_key: str
    credit_units: int = 0
    credit_validity_months: int | None = None
    entitlement_validity_days: int | None = None


@dataclass(frozen=True)
class SaaSQuote:
    quote_id: str
    product: SaaSProduct
    catalog_version: str
    currency: str
    lines: Tuple[SaaSQuoteLine, ...]
    subtotal_idr: int
    tax_status: str
    tax_amount_idr: int | None
    total_idr: int | None
    quote_status: str
    payment_intent_allowed: bool
