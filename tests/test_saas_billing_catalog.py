import unittest

from app.schemas.saas_billing import SaaSProduct, SaaSQuoteRequest
from app.services.saas_billing_catalog import (
    CATALOG_VERSION,
    SAAS_BILLING_LIVE_ENABLED,
    CatalogError,
    TaxPolicy,
    quote_catalog_items,
)


class TestSaaSBillingCatalog(unittest.TestCase):
    def test_founder_ratified_studio_topups_have_exact_price_and_credit_mapping(self):
        cases = {
            "STUDIO_TOPUP_KETENGAN_50": (50, 25000),
            "STUDIO_TOPUP_STARTER_200": (200, 89000),
            "STUDIO_TOPUP_KREATOR_500": (500, 199000),
            "STUDIO_TOPUP_PRO_AGENCY_1000": (1000, 349000),
        }
        for sku, expected in cases.items():
            with self.subTest(sku=sku):
                request = SaaSQuoteRequest.from_mapping({
                    "product": "STUDIO",
                    "items": [{"sku": sku}],
                    "catalog_version": CATALOG_VERSION,
                })
                quote = quote_catalog_items(
                    product=request.product,
                    items=request.items,
                    catalog_version=request.catalog_version,
                )
                line = quote.lines[0]
                self.assertEqual((line.credit_units, line.unit_amount_idr), expected)
                self.assertEqual(line.credit_validity_months, 12)
                self.assertEqual(quote.currency, "IDR")
                self.assertEqual(quote.tax_status, "TAX_POLICY_PENDING")
                self.assertIsNone(quote.total_idr)
                self.assertFalse(quote.payment_intent_allowed)

    def test_approved_tax_policy_allows_quote_to_be_reviewed_for_nonprod_payment(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "STUDIO",
            "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
        })
        quote = quote_catalog_items(
            product=request.product,
            items=request.items,
            tax_policy=TaxPolicy(
                status="APPROVED",
                mode="EXCLUSIVE",
                rate_bps=1000,
                policy_id="TEST-TAX-POLICY",
            ),
        )
        self.assertEqual(quote.subtotal_idr, 25000)
        self.assertEqual(quote.tax_amount_idr, 2500)
        self.assertEqual(quote.total_idr, 27500)
        self.assertTrue(quote.payment_intent_allowed)

    def test_shop_free_forever_is_zero_and_never_creates_payment_intent(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "SHOP",
            "items": [{"sku": "SHOP_FREE_FOREVER"}],
        })
        quote = quote_catalog_items(product=request.product, items=request.items)
        self.assertEqual(quote.subtotal_idr, 0)
        self.assertEqual(quote.total_idr, None)
        self.assertEqual(quote.quote_status, "FREE_ENTITLEMENT")
        self.assertFalse(quote.payment_intent_allowed)

    def test_shop_paid_tier_without_cfo_approval_is_not_sellable(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "SHOP",
            "items": [{"sku": "SHOP_GROWTH"}],
        })
        with self.assertRaises(CatalogError) as raised:
            quote_catalog_items(product=request.product, items=request.items)
        self.assertEqual(raised.exception.code, "BILLING_SKU_NOT_SELLABLE")

    def test_client_cannot_supply_financial_or_tenant_authority(self):
        invalid_payloads = [
            {
                "product": "STUDIO",
                "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
                "amount": 1,
            },
            {
                "product": "STUDIO",
                "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50", "amount": 1}],
            },
            {
                "product": "STUDIO",
                "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
                "tenant_id": "tenant-from-browser",
            },
            {
                "product": "STUDIO",
                "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
                "provider": "XENDIT",
            },
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError) as raised:
                    SaaSQuoteRequest.from_mapping(payload)
                self.assertEqual(
                    str(raised.exception),
                    "BILLING_CLIENT_AUTHORITY_FIELD_PROHIBITED",
                )

    def test_quote_rejects_cross_product_sku(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "SHOP",
            "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
        })
        with self.assertRaises(CatalogError) as raised:
            quote_catalog_items(product=request.product, items=request.items)
        self.assertEqual(raised.exception.code, "BILLING_SKU_NOT_FOUND")

    def test_quote_rejects_unknown_catalog_version(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "STUDIO",
            "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
            "catalog_version": "obsolete",
        })
        with self.assertRaises(CatalogError) as raised:
            quote_catalog_items(
                product=request.product,
                items=request.items,
                catalog_version=request.catalog_version,
            )
        self.assertEqual(raised.exception.code, "BILLING_CATALOG_VERSION_UNAVAILABLE")

    def test_request_rejects_duplicate_skus_and_unknown_fields(self):
        with self.assertRaises(ValueError) as duplicate:
            SaaSQuoteRequest.from_mapping({
                "product": "STUDIO",
                "items": [
                    {"sku": "STUDIO_TOPUP_KETENGAN_50"},
                    {"sku": "STUDIO_TOPUP_KETENGAN_50"},
                ],
            })
        self.assertEqual(str(duplicate.exception), "BILLING_DUPLICATE_SKU")

        with self.assertRaises(ValueError) as unknown:
            SaaSQuoteRequest.from_mapping({
                "product": "STUDIO",
                "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
                "client_debug": True,
            })
        self.assertEqual(
            str(unknown.exception),
            "BILLING_CLIENT_AUTHORITY_FIELD_PROHIBITED",
        )

    def test_live_billing_is_disabled_in_this_contract_revision(self):
        self.assertFalse(SAAS_BILLING_LIVE_ENABLED)


if __name__ == "__main__":
    unittest.main()
