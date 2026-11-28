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
    entitlement_validity_days: int | None = None
    is_default_checkout: bool = False
    campaign_key: str | None = None


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


# Founder-approved 2026-11-28 staging delta. Shop and Studio price books stay separate.
# HOLD items are intentionally absent from the purchasable catalog.
CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_FREE_FOREVER",
        display_name="Shop Free Forever", item_kind=BillingItemKind.BASE_TIER,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.FREE,
        amount_idr=0, entitlement_key="SHOP_FREE_FOREVER", sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_STARTER_GROWTH_BUNDLE",
        display_name="Starter / Shop Growth Bundle", item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=99000, entitlement_key="SHOP_STARTER_GROWTH_BUNDLE", sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_ADS_PERFORMANCE",
        display_name="Ads Performance", item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=299000, entitlement_key="SHOP_ADS_PERFORMANCE", sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_ADDON_DYNAMIC_QRIS",
        display_name="Dynamic QRIS", item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=39000, entitlement_key="SHOP_DYNAMIC_QRIS", sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_ADDON_SMARTCHATBOX_MULTI_CS",
        display_name="SmartChatbox / Multi-CS — All-in-One Channel Cockpit",
        item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=149000, entitlement_key="SHOP_SMARTCHATBOX_MULTI_CS", sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_ADDON_AI_AUTOREPLY_300",
        display_name="AI Auto-Reply — 300 replies", item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=199000, entitlement_key="SHOP_AI_AUTOREPLY_300", sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_ADDON_BOOKING_PRO",
        display_name="Booking Pro", item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=49000, entitlement_key="SHOP_BOOKING_PRO", sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.SHOP, sku="SHOP_ADDON_WABA_OFFICIAL",
        display_name="WABA Official — Meta fees billed separately",
        item_kind=BillingItemKind.STANDALONE_ADDON,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=149000, entitlement_key="SHOP_WABA_OFFICIAL", sellable=True,
        dependency_keys=("META_FEES_PASS_THROUGH",),
    ),
    CatalogEntry(
        product=SaaSProduct.STUDIO, sku="STUDIO-MONTHLY-29K",
        display_name="Studio Monthly — 25 credits", item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.MONTHLY,
        amount_idr=29000, entitlement_key="STUDIO_CREDITS",
        credit_units=25, entitlement_validity_days=30, sellable=True,
    ),
    CatalogEntry(
        product=SaaSProduct.STUDIO, sku="STUDIO-ANNUAL-99K",
        display_name="Studio Annual — 100 credits (default checkout)",
        item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.ANNUAL,
        amount_idr=99000, entitlement_key="STUDIO_CREDITS",
        credit_units=100, entitlement_validity_days=365, sellable=True,
        is_default_checkout=True,
    ),
    CatalogEntry(
        product=SaaSProduct.STUDIO, sku="STUDIO-ANNUAL-299K",
        display_name="Studio Annual — 500 credits (OnlineBoost Campaign)",
        item_kind=BillingItemKind.SUBSCRIPTION,
        approval_state=CatalogApprovalState.APPROVED, cadence=BillingCadence.ANNUAL,
        amount_idr=299000, entitlement_key="STUDIO_CREDITS",
        credit_units=500, entitlement_validity_days=365, sellable=True,
        campaign_key="ONLINEBOOST_CAMPAIGN",
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
                cadence=entry.cadence,
                quantity=item.quantity,
                unit_amount_idr=entry.amount_idr,
                line_amount_idr=line_amount,
                entitlement_key=entry.entitlement_key,
                credit_units=entry.credit_units * item.quantity,
                credit_validity_months=entry.credit_validity_months,
            )
        )

    if shop_has_package and shop_has_addon:
        raise CatalogError("BILLING_BUNDLE_MAPPING_PENDING")

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
