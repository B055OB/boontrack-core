import json
import unittest
from unittest.mock import patch

from app.schemas.saas_billing import SaaSQuoteRequest
from app.services.saas_billing_auth import (
    SaaSBillingAuthorizationError,
    verify_internal_saas_billing_request,
)
from app.services.saas_billing_catalog import TaxPolicy, quote_catalog_items


def _shop_request_and_quote():
    request = SaaSQuoteRequest.from_mapping({
        "product": "STUDIO",
        "items": [{"sku": "STUDIO_TOPUP_KETENGAN_50"}],
        "request_reference": "saas-test-purchase-001",
        "idempotency_key": "saas-test-idem-0001",
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
    return request, quote


class TestSaaSBillingAuth(unittest.TestCase):
    def setUp(self):
        self.request, self.quote = _shop_request_and_quote()
        self.headers = {
            "X-Tenant-ID": "tenant-preview",
            "X-Payment-Internal-Key-Id": "key-studio-preview",
            "X-Payment-Internal-Timestamp": "1795860000",
            "X-Payment-Internal-Nonce": "saas-test-nonce",
            "X-Payment-Internal-Signature": "signed-request",
            "X-Payment-Internal-Actor": "studio-service",
        }
        self.environ = {
            "SAAS_BILLING_TRUSTED_PRINCIPALS_JSON": json.dumps({
                "SHOP": ["shop-service"],
                "STUDIO": ["studio-service"],
            })
        }

    @patch("app.core.security.payment_auth_guard.verify_stage2_payment_initiation_request")
    def test_verified_studio_principal_is_accepted(self, verify):
        class AuthContext:
            verified_actor_principal = "studio-service"
            canonical_tenant_id = "2c300000-0000-0000-0000-000000000088"

        verify.return_value = AuthContext()
        result = verify_internal_saas_billing_request(
            headers=self.headers,
            http_method="POST",
            canonical_path="/api/v1/saas-billing/payment-intents",
            raw_body=b'{"product":"STUDIO","items":[{"sku":"STUDIO_TOPUP_KETENGAN_50"}],"request_reference":"saas-test-purchase-001","idempotency_key":"saas-test-idem-0001"}',
            quote_request=self.request,
            quote=self.quote,
            db_connection_factory=lambda: None,
            environ=self.environ,
        )
        self.assertIsInstance(result, AuthContext)
        verify.assert_called_once()
        self.assertEqual(
            verify.call_args.kwargs["tenant_id_or_slug"],
            "tenant-preview",
        )
        self.assertEqual(
            verify.call_args.kwargs["derived_amount"],
            27500,
        )

    @patch("app.core.security.payment_auth_guard.verify_stage2_payment_initiation_request")
    def test_wrong_product_principal_is_rejected(self, verify):
        class AuthContext:
            verified_actor_principal = "shop-service"

        verify.return_value = AuthContext()
        with self.assertRaises(SaaSBillingAuthorizationError) as raised:
            verify_internal_saas_billing_request(
                headers=self.headers,
                http_method="POST",
                canonical_path="/api/v1/saas-billing/payment-intents",
                raw_body=b'{"product":"STUDIO","items":[{"sku":"STUDIO_TOPUP_KETENGAN_50"}],"request_reference":"saas-test-purchase-001","idempotency_key":"saas-test-idem-0001"}',
                quote_request=self.request,
                quote=self.quote,
                db_connection_factory=lambda: None,
                environ=self.environ,
            )
        self.assertEqual(raised.exception.code, "BILLING_PRODUCT_PRINCIPAL_FORBIDDEN")

    def test_missing_tenant_context_is_rejected_before_hmac(self):
        with self.assertRaises(SaaSBillingAuthorizationError) as raised:
            verify_internal_saas_billing_request(
                headers={},
                http_method="POST",
                canonical_path="/api/v1/saas-billing/payment-intents",
                raw_body=b'{"product":"STUDIO","items":[{"sku":"STUDIO_TOPUP_KETENGAN_50"}],"request_reference":"saas-test-purchase-001","idempotency_key":"saas-test-idem-0001"}',
                quote_request=self.request,
                quote=self.quote,
                db_connection_factory=lambda: None,
                environ=self.environ,
            )
        self.assertEqual(raised.exception.code, "BILLING_TENANT_CONTEXT_REQUIRED")

    @patch("app.core.security.payment_auth_guard.verify_stage2_payment_initiation_request")
    def test_missing_product_principal_configuration_fails_closed(self, verify):
        class AuthContext:
            verified_actor_principal = "studio-service"

        verify.return_value = AuthContext()
        with self.assertRaises(SaaSBillingAuthorizationError) as raised:
            verify_internal_saas_billing_request(
                headers=self.headers,
                http_method="POST",
                canonical_path="/api/v1/saas-billing/payment-intents",
                raw_body=b'{"product":"STUDIO","items":[{"sku":"STUDIO_TOPUP_KETENGAN_50"}],"request_reference":"saas-test-purchase-001","idempotency_key":"saas-test-idem-0001"}',
                quote_request=self.request,
                quote=self.quote,
                db_connection_factory=lambda: None,
                environ={},
            )
        self.assertEqual(raised.exception.code, "BILLING_PRODUCT_PRINCIPALS_NOT_CONFIGURED")
        self.assertEqual(raised.exception.http_status, 503)


if __name__ == "__main__":
    unittest.main()
