import unittest

from app.schemas.saas_billing import SaaSProduct
from app.services.saas_billing_catalog import TaxPolicy, quote_catalog_items
from app.services.saas_billing_repository import (
    SaaSBillingRepository,
    SaaSBillingRepositoryError,
)


class TestSaaSBillingRepositoryFailClosed(unittest.TestCase):
    def setUp(self):
        self.quote = quote_catalog_items(
            product=SaaSProduct.STUDIO,
            items=[
                __import__(
                    "app.schemas.saas_billing",
                    fromlist=["SaaSQuoteLineRequest"],
                ).SaaSQuoteLineRequest(sku="STUDIO-ANNUAL-99K")
            ],
            tax_policy=TaxPolicy(
                status="APPROVED",
                mode="EXCLUSIVE",
                rate_bps=0,
                policy_id="TEST-TAX-POLICY",
            ),
        )

    def test_purchase_creation_fails_closed_without_postgres(self):
        repository = SaaSBillingRepository(connection_factory=lambda: None)
        with self.assertRaises(SaaSBillingRepositoryError) as raised:
            repository.create_purchase(
                canonical_tenant_id="2c300000-0000-0000-0000-000000000088",
                product=SaaSProduct.STUDIO,
                request_reference="repo-test-purchase-0001",
                idempotency_key="repo-test-idempotency-0001",
                quote=self.quote,
                tax_policy_id="TEST-TAX-POLICY",
                credential_profile_id="xendit-staging-studio",
            )
        self.assertEqual(str(raised.exception), "BILLING_DATABASE_UNAVAILABLE")

    def test_entitlement_lookup_fails_closed_without_postgres(self):
        repository = SaaSBillingRepository(connection_factory=lambda: None)
        with self.assertRaises(SaaSBillingRepositoryError) as raised:
            repository.get_effective_tenant_entitlements(
                canonical_tenant_id="2c300000-0000-0000-0000-000000000088",
                product=SaaSProduct.SHOP,
            )
        self.assertEqual(str(raised.exception), "BILLING_DATABASE_UNAVAILABLE")

    def test_purchase_rejects_pending_tax_policy_before_database_access(self):
        pending_quote = quote_catalog_items(
            product=SaaSProduct.STUDIO,
            items=self.quote.lines and [
                __import__(
                    "app.schemas.saas_billing",
                    fromlist=["SaaSQuoteLineRequest"],
                ).SaaSQuoteLineRequest(sku="STUDIO-ANNUAL-99K")
            ],
        )
        repository = SaaSBillingRepository(connection_factory=lambda: None)
        with self.assertRaisesRegex(ValueError, "BILLING_QUOTE_NOT_SETTLEMENT_READY"):
            repository.create_purchase(
                canonical_tenant_id="2c300000-0000-0000-0000-000000000088",
                product=SaaSProduct.STUDIO,
                request_reference="repo-test-purchase-0002",
                idempotency_key="repo-test-idempotency-0002",
                quote=pending_quote,
                tax_policy_id="PENDING",
                credential_profile_id="xendit-staging-studio",
            )


if __name__ == "__main__":
    unittest.main()
