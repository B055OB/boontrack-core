import unittest

from app.schemas.saas_billing import BillingCadence, SaaSProduct, SaaSQuoteRequest
from app.services.saas_billing_catalog import (
    CATALOG_VERSION,
    SAAS_BILLING_LIVE_ENABLED,
    CatalogError,
    TaxPolicy,
    get_catalog_entry,
    quote_catalog_items,
)


class TestSaaSBillingCatalog(unittest.TestCase):
    def _quote(self, product, items, tax_policy=None):
        request = SaaSQuoteRequest.from_mapping({
            "product": product,
            "items": items,
            "catalog_version": CATALOG_VERSION,
        })
        return quote_catalog_items(
            product=request.product,
            items=request.items,
            catalog_version=request.catalog_version,
            tax_policy=tax_policy,
        )

    def test_founder_approved_studio_catalog_and_default_checkout(self):
        cases = {
            "STUDIO-MONTHLY-29K": (25, 29000, BillingCadence.MONTHLY, 30, False),
            "STUDIO-ANNUAL-99K": (100, 99000, BillingCadence.ANNUAL, 365, True),
            "STUDIO-ANNUAL-299K": (500, 299000, BillingCadence.ANNUAL, 365, False),
        }
        for sku, expected in cases.items():
            with self.subTest(sku=sku):
                quote = self._quote("STUDIO", [{"sku": sku}])
                line = quote.lines[0]
                self.assertEqual(
                    (line.credit_units, line.unit_amount_idr, line.cadence,
                     line.entitlement_validity_days),
                    expected[:4],
                )
                self.assertEqual(
                    get_catalog_entry(SaaSProduct.STUDIO, sku).is_default_checkout,
                    expected[4],
                )
                self.assertEqual(quote.currency, "IDR")
                self.assertEqual(quote.tax_status, "TAX_POLICY_PENDING")
                self.assertIsNone(quote.total_idr)
                self.assertFalse(quote.payment_intent_allowed)

        campaign = get_catalog_entry(SaaSProduct.STUDIO, "STUDIO-ANNUAL-299K")
        self.assertEqual(campaign.campaign_key, "ONLINEBOOST_CAMPAIGN")

    def test_shop_approved_staging_price_book(self):
        cases = {
            "SHOP_STARTER_GROWTH_BUNDLE": (99000, BillingCadence.MONTHLY),
            "SHOP_ADS_PERFORMANCE": (299000, BillingCadence.MONTHLY),
            "SHOP_ADDON_DYNAMIC_QRIS": (39000, BillingCadence.MONTHLY),
            "SHOP_ADDON_SMARTCHATBOX_MULTI_CS": (149000, BillingCadence.MONTHLY),
            "SHOP_ADDON_AI_AUTOREPLY_300": (199000, BillingCadence.MONTHLY),
            "SHOP_ADDON_BOOKING_PRO": (49000, BillingCadence.MONTHLY),
            "SHOP_ADDON_WABA_OFFICIAL": (149000, BillingCadence.MONTHLY),
        }
        for sku, expected in cases.items():
            with self.subTest(sku=sku):
                entry = get_catalog_entry(SaaSProduct.SHOP, sku)
                self.assertEqual((entry.amount_idr, entry.cadence), expected)
                self.assertTrue(entry.sellable)

    def test_existing_team_scale_tier4_is_sellable_and_keeps_enterprise_entitlement(self):
        entry = get_catalog_entry(SaaSProduct.SHOP, "TEAM_SCALE")
        self.assertEqual(entry.display_name, "Team Scale (Tier 4)")
        self.assertEqual(entry.amount_idr, 499000)
        self.assertEqual(entry.cadence, BillingCadence.MONTHLY)
        self.assertEqual(entry.entitlement_key, "ENTERPRISE")
        self.assertEqual(entry.item_kind.value, "SUBSCRIPTION")
        self.assertTrue(entry.sellable)

    def test_shop_waba_meta_fees_are_pass_through_dependency(self):
        entry = get_catalog_entry(SaaSProduct.SHOP, "SHOP_ADDON_WABA_OFFICIAL")
        self.assertIn("META_FEES_PASS_THROUGH", entry.dependency_keys)
        self.assertEqual(entry.amount_idr, 149000)

    def test_shop_free_forever_is_zero_and_never_creates_payment_intent(self):
        quote = self._quote("SHOP", [{"sku": "SHOP_FREE_FOREVER"}])
        self.assertEqual(quote.subtotal_idr, 0)
        self.assertIsNone(quote.total_idr)
        self.assertEqual(quote.quote_status, "FREE_ENTITLEMENT")
        self.assertFalse(quote.payment_intent_allowed)

    def test_hold_items_are_absent_from_purchasable_catalog(self):
        hold_skus = [
            "SHOP_ADDON_WHATSAPP_NON_WABA",
            "SHOP_TEMPLATE_FRONT_PAGE_ECOMMERCE",
            "SHOP_TEMPLATE_FRONT_PAGE_MICROSITE",
            "SHOP_TEMPLATE_FRONT_PAGE_WEB_PROFILE",
            "SHOP_ADDON_AFFILIATE_DOMAIN",
            "SHOP_ADDON_OFFLINE_EVENT_UPLOAD",
        ]
        for sku in hold_skus:
            with self.subTest(sku=sku):
                with self.assertRaises(CatalogError) as raised:
                    get_catalog_entry(SaaSProduct.SHOP, sku)
                self.assertEqual(raised.exception.code, "BILLING_SKU_NOT_FOUND")

    def test_package_and_addon_combination_fails_closed_until_bundle_map_is_ratified(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "SHOP",
            "items": [
                {"sku": "SHOP_STARTER_GROWTH_BUNDLE"},
                {"sku": "SHOP_ADDON_DYNAMIC_QRIS"},
            ],
        })
        with self.assertRaises(CatalogError) as raised:
            quote_catalog_items(product=request.product, items=request.items)
        self.assertEqual(raised.exception.code, "BILLING_BUNDLE_MAPPING_PENDING")

    def test_duplicate_entitlement_in_one_quote_is_rejected(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "STUDIO",
            "items": [
                {"sku": "STUDIO-MONTHLY-29K"},
                {"sku": "STUDIO-ANNUAL-99K"},
            ],
        })
        with self.assertRaises(CatalogError) as raised:
            quote_catalog_items(product=request.product, items=request.items)
        self.assertEqual(raised.exception.code, "BILLING_DUPLICATE_ENTITLEMENT")

    def test_approved_tax_policy_allows_quote_to_be_reviewed_for_nonprod_payment(self):
        quote = self._quote(
            "STUDIO",
            [{"sku": "STUDIO-MONTHLY-29K"}],
            tax_policy=TaxPolicy(
                status="APPROVED",
                mode="EXCLUSIVE",
                rate_bps=1000,
                policy_id="TEST-TAX-POLICY",
            ),
        )
        self.assertEqual(quote.subtotal_idr, 29000)
        self.assertEqual(quote.tax_amount_idr, 2900)
        self.assertEqual(quote.total_idr, 31900)
        self.assertTrue(quote.payment_intent_allowed)

    def test_client_cannot_supply_financial_or_tenant_authority(self):
        invalid_payloads = [
            {"product": "STUDIO", "items": [{"sku": "STUDIO-MONTHLY-29K"}], "amount": 1},
            {"product": "STUDIO", "items": [{"sku": "STUDIO-MONTHLY-29K", "amount": 1}]},
            {"product": "STUDIO", "items": [{"sku": "STUDIO-MONTHLY-29K"}], "tenant_id": "tenant-from-browser"},
            {"product": "STUDIO", "items": [{"sku": "STUDIO-MONTHLY-29K"}], "provider": "XENDIT"},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError) as raised:
                    SaaSQuoteRequest.from_mapping(payload)
                self.assertEqual(str(raised.exception), "BILLING_CLIENT_AUTHORITY_FIELD_PROHIBITED")

    def test_quote_rejects_cross_product_sku(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "SHOP",
            "items": [{"sku": "STUDIO-MONTHLY-29K"}],
        })
        with self.assertRaises(CatalogError) as raised:
            quote_catalog_items(product=request.product, items=request.items)
        self.assertEqual(raised.exception.code, "BILLING_SKU_NOT_FOUND")

    def test_quote_rejects_unknown_catalog_version(self):
        request = SaaSQuoteRequest.from_mapping({
            "product": "STUDIO",
            "items": [{"sku": "STUDIO-MONTHLY-29K"}],
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
                    {"sku": "STUDIO-MONTHLY-29K"},
                    {"sku": "STUDIO-MONTHLY-29K"},
                ],
            })
        self.assertEqual(str(duplicate.exception), "BILLING_DUPLICATE_SKU")

        with self.assertRaises(ValueError) as unknown:
            SaaSQuoteRequest.from_mapping({
                "product": "STUDIO",
                "items": [{"sku": "STUDIO-MONTHLY-29K"}],
                "client_debug": True,
            })
        self.assertEqual(str(unknown.exception), "BILLING_CLIENT_AUTHORITY_FIELD_PROHIBITED")

    def test_live_billing_is_disabled_in_this_contract_revision(self):
        self.assertFalse(SAAS_BILLING_LIVE_ENABLED)


if __name__ == "__main__":
    unittest.main()
