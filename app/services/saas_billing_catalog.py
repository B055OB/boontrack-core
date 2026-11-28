"""Core-owned SaaS catalog and deterministic server-side quote calculation.

This module is intentionally separate from buyer checkout and does not call a
payment provider. It is safe to import in tests and in preview environments.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

from app.schemas.saas_billing import (
    BillingCadence,
    BillingItemKind,
    CatalogApprovalState,
    SaaSProduct,
    SaaSQuote,
    SaaSQuoteLine,
    SaaSQuoteLineRequest,
)

CATALOG_VERSION = "saas-billing.v1-2026-11-28"
CURRENCY = "IDR"
SAAS_BILLING_LIVE_ENABLED = False
TAX_POLICY_PENDING = "TAX_POLICY_PENDING"


class CatalogError(ValueError):
    """Safe, stable catalog/quote error."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class CatalogEntry:
    product: SaaSProduct
    sku: str
    display_name: str
    item_kind: BillingItemKind
    approval_state: CatalogApprovalState
    cadence: BillingCadence
    amount_idr: int | None
    entitlement_key: str
    credit_units: int = 0
    credit_validity_months: int | None = None
    sellable: bool = True
    dependency_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaxPolicy:
    """Explicit tax policy. Pending is the safe default until ratified."""

    status: str = "PENDING"
    mode: str | None = None  # EXCLUSIVE or INCLUSIVE
    rate_bps: int | None = None
    policy_id: str | None = None

    @classmethod
    def pending(cls) -> "TaxPolicy":
        return cls()

    def calculate(self, subtotal_idr: int) -> tuple[int | None, int | None]:
        if self.status.upper() != "APPROVED":
            return None, None
        mode = str(self.mode or "").upper()
        if mode not in {"EXCLUSIVE", "INCLUSIVE"}:
            raise CatalogError("BILLING_TAX_POLICY_INVALID")
        if self.rate_bps is None or isinstance(self.rate_bps, bool) or self.rate_bps < 0:
            raise CatalogError("BILLING_TAX_POLICY_INVALID")
        if not self.policy_id:
            raise CatalogError("BILLING_TAX_POLICY_INVALID")

        rate = Decimal(self.rate_bps) / Decimal(10000)
        amount = Decimal(subtotal_idr)
        if mode == "EXCLUSIVE":
            tax = int((amount * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            return tax, subtotal_idr + tax

        denominator = Decimal(1) + rate
        tax = int((amount * rate / denominator).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return tax, subtotal_idr


# Founder-ratified Studio Pricing v3 top-up price map.
# Shop paid plans/add-ons intentionally carry no price until CFO approval is recorded.
CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_FREE_FOREVER",
        display_name="Shop Free Forever",
        item_kind=BillingItemKind.BASE_TIER,
        approval_state=CatalogApprovalState.APPROVED,
        cadence=BillingCadence.FREE,
        amount_idr=0,
        entitlement_key="SHOP_FREE_FOREVER",
        sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_GROWTH",
        display_name="Shop Growth",
        item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.PENDING_CFO_APPROVAL,
        cadence=BillingCadence.MONTHLY,
        amount_idr=None,
        entitlement_key="SHOP_GROWTH",
        sellable=False,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_ADS_PERFORMANCE",
        display_name="Ads Performance",
        item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.PENDING_CFO_APPROVAL,
        cadence=BillingCadence.MONTHLY,
        amount_idr=None,
        entitlement_key="SHOP_ADS_PERFORMANCE",
        sellable=False,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_TEAM_SCALE",
        display_name="Team Scale",
        item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.PENDING_CFO_APPROVAL,
        cadence=BillingCadence.MONTHLY,
        amount_idr=None,
        entitlement_key="SHOP_TEAM_SCALE",
        sellable=False,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_ADDON_CUSTOM_DOMAIN",
        display_name="Custom Domain",
        item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.PENDING_CFO_APPROVAL,
        cadence=BillingCadence.MONTHLY,
        amount_idr=None,
        entitlement_key="SHOP_CUSTOM_DOMAIN",
        sellable=False,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_ADDON_DIGITAL_DELIVERY_PRO",
        display_name="Digital Delivery Pro",
        item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.PENDING_CFO_APPROVAL,
        cadence=BillingCadence.MONTHLY,
        amount_idr=None,
        entitlement_key="SHOP_DIGITAL_DELIVERY_PRO",
        sellable=False,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_ADDON_BOOKING_PRO",
        display_name="Booking Pro",
        item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.PENDING_CFO_APPROVAL,
        cadence=BillingCadence.MONTHLY,
        amount_idr=None,
        entitlement_key="SHOP_BOOKING_PRO",
        sellable=False,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP,
        sku="SHOP_ADDON_MULTI_COURIER",
        display_name="Multi-Courier",
        item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.DEFERRED,
        cadence=BillingCadence.MONTHLY,
        amount_idr=None,
        entitlement_key="SHOP_MULTI_COURIER",
        sellable=False,
    ),
    CatalogEntry(
        product=SaaSProduct.STUDIO,
        sku="STUDIO_TOPUP_KETENGAN_50",
        display_name="Ketengan — 50 credits",
        item_kind=BillingItemKind.CREDIT_TOPUP,
        approval_state=CatalogApprovalState.APPROVED,
        cadence=BillingCadence.ONE_TIME,
        amount_idr=25000,
        entitlement_key="STUDIO_CREDITS",
        credit_units=50,
        credit_validity_months=12,
    ),
    CatalogEntry(
        product=SaaSProduct.STUDIO,
        sku="STUDIO_TOPUP_STARTER_200",
        display_name="Starter — 200 credits",
        item_kind=BillingItemKind.CREDIT_TOPUP,
        approval_state=CatalogApprovalState.APPROVED,
        cadence=BillingCadence.ONE_TIME,
        amount_idr=89000,
        entitlement_key="STUDIO_CREDITS",
        credit_units=200,
        credit_validity_months=12,
    ),
    CatalogEntry(
        product=SaaSProduct.STUDIO,
        sku="STUDIO_TOPUP_KREATOR_500",
        display_name="Kreator — 500 credits",
        item_kind=BillingItemKind.CREDIT_TOPUP,
        approval_state=CatalogApprovalState.APPROVED,
        cadence=BillingCadence.ONE_TIME,
        amount_idr=199000,
        entitlement_key="STUDIO_CREDITS",
        credit_units=500,
        credit_validity_months=12,
    ),
    CatalogEntry(
        product=SaaSProduct.STUDIO,
        sku="STUDIO_TOPUP_PRO_AGENCY_1000",
        display_name="Pro / Agency — 1,000 credits",
        item_kind=BillingItemKind.CREDIT_TOPUP,
        approval_state=CatalogApprovalState.APPROVED,
        cadence=BillingCadence.ONE_TIME,
        amount_idr=349000,
        entitlement_key="STUDIO_CREDITS",
        credit_units=1000,
        credit_validity_months=12,
    ),
)

_CATALOG_BY_KEY: Mapping[tuple[SaaSProduct, str], CatalogEntry] = {
    (entry.product, entry.sku): entry for entry in CATALOG
}


def get_catalog(product: SaaSProduct) -> tuple[CatalogEntry, ...]:
    """Return the Core catalog entries for one product; no cross-product rows."""
    return tuple(entry for entry in CATALOG if entry.product == product)


def get_catalog_entry(product: SaaSProduct, sku: str) -> CatalogEntry:
    key = (product, str(sku or "").strip().upper())
    entry = _CATALOG_BY_KEY.get(key)
    if entry is None:
        raise CatalogError("BILLING_SKU_NOT_FOUND")
    return entry


def quote_catalog_items(
    *,
    product: SaaSProduct,
    items: Sequence[SaaSQuoteLineRequest],
    catalog_version: str | None = None,
    tax_policy: TaxPolicy | None = None,
) -> SaaSQuote:
    """Create a server-calculated quote. Does not create an intent or contact a PSP."""
    if catalog_version and catalog_version != CATALOG_VERSION:
        raise CatalogError("BILLING_CATALOG_VERSION_UNAVAILABLE")
    if not items:
        raise CatalogError("BILLING_ITEMS_REQUIRED")

    tax_policy = tax_policy or TaxPolicy.pending()
    lines: list[SaaSQuoteLine] = []
    subtotal = 0
    contains_free_base = False

    for item in items:
        entry = get_catalog_entry(product, item.sku)
        if entry.approval_state != CatalogApprovalState.APPROVED or not entry.sellable:
            raise CatalogError("BILLING_SKU_NOT_SELLABLE")
        if entry.amount_idr is None:
            raise CatalogError("BILLING_SKU_NOT_SELLABLE")
        if item.quantity < 1 or item.quantity > 20:
            raise CatalogError("BILLING_QUANTITY_INVALID")

        line_amount = entry.amount_idr * item.quantity
        subtotal += line_amount
        contains_free_base = contains_free_base or (
            entry.cadence == BillingCadence.FREE and line_amount == 0
        )
        lines.append(
            SaaSQuoteLine(
                sku=entry.sku,
                item_kind=entry.item_kind,
                quantity=item.quantity,
                unit_amount_idr=entry.amount_idr,
                line_amount_idr=line_amount,
                entitlement_key=entry.entitlement_key,
                credit_units=entry.credit_units * item.quantity,
                credit_validity_months=entry.credit_validity_months,
            )
        )

    tax_amount, total = tax_policy.calculate(subtotal)
    tax_approved = tax_policy.status.upper() == "APPROVED"
    payment_allowed = subtotal > 0 and tax_approved and not contains_free_base
    quote_status = (
        "FREE_ENTITLEMENT"
        if contains_free_base
        else ("READY_FOR_NONPROD_PAYMENT_REVIEW" if payment_allowed else TAX_POLICY_PENDING)
    )

    return SaaSQuote(
        quote_id=f"sq_{uuid4().hex}",
        product=product,
        catalog_version=CATALOG_VERSION,
        currency=CURRENCY,
        lines=tuple(lines),
        subtotal_idr=subtotal,
        tax_status="APPROVED" if tax_approved else TAX_POLICY_PENDING,
        tax_amount_idr=tax_amount,
        total_idr=total,
        quote_status=quote_status,
        payment_intent_allowed=payment_allowed,
    )
