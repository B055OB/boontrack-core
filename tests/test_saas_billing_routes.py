import json
import unittest
from unittest.mock import patch

from app.services.payment.base import TransactionResponse
from app.services.saas_billing_xendit import SaaSXenditProfileError, SaaSXenditProvider, SaaSXenditSandboxProfile
from app.routes.saas_billing_routes import (
    create_saas_payment_intent,
    read_saas_billing_catalog,
    receive_saas_xendit_webhook,
    saas_billing_router,
)


class _Request:
    def __init__(self, payload=None, headers=None):
        self._payload = payload or {}
        self.headers = headers or {}

    async def json(self):
        return self._payload


class TestSaaSBillingRoutesFailClosed(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_route_exposes_team_scale_but_not_hold_items(self):
        response = await read_saas_billing_catalog("SHOP")
        payload = json.loads(response.body)
        skus = {item["sku"] for item in payload["items"]}
        self.assertIn("TEAM_SCALE", skus)
        self.assertNotIn("SHOP_ADDON_NON_WABA_SCAN_BARCODE", skus)
        self.assertEqual(payload["currency"], "IDR")

    async def test_payment_intent_route_keeps_tax_policy_hard_gate(self):
        response = await create_saas_payment_intent(
            _Request({"product": "STUDIO", "quote_id": "sq_ci_test"})
        )
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["error"]["code"], "BILLING_TAX_POLICY_PENDING")

    async def test_xendit_webhook_fails_closed_without_dedicated_saas_profile(self):
        with patch.dict("os.environ", {"SAAS_XENDIT_SANDBOX_CALLBACK_TOKEN": ""}):
            response = await receive_saas_xendit_webhook(_Request({}, {}))
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "BILLING_PROVIDER_PROFILE_UNAVAILABLE")


    def test_saas_xendit_profile_is_separate_from_onlineboost_credentials(self):
        env = {
            "SAAS_XENDIT_ENV": "sandbox",
            "SAAS_XENDIT_SANDBOX_PROFILE_ID": "saas-staging-xendit",
            "SAAS_XENDIT_SANDBOX_SECRET_KEY": "saas_sandbox_secret_key_123456",
            "SAAS_XENDIT_SANDBOX_CALLBACK_TOKEN": "saas_sandbox_callback_token_123456",
            "SAAS_XENDIT_SANDBOX_BUSINESS_ID": "business_saas_staging",
            "SAAS_XENDIT_SANDBOX_API_URL": "https://api.xendit.co",
            "SAAS_XENDIT_SANDBOX_WEBHOOK_URL": "https://api-staging.boontrack.com/api/v1/saas-billing/webhooks/xendit",
            "XENDIT_SECRET_KEY": "onlineboost_secret_key_123456",
            "XENDIT_CALLBACK_TOKEN": "onlineboost_callback_token_123456",
        }
        profile = SaaSXenditSandboxProfile.from_env(env)
        self.assertEqual(profile.environment, "sandbox")
        self.assertNotEqual(profile.secret_key, env["XENDIT_SECRET_KEY"])
        self.assertNotEqual(profile.callback_token, env["XENDIT_CALLBACK_TOKEN"])

    def test_saas_xendit_profile_rejects_onlineboost_secret_reuse(self):
        env = {
            "SAAS_XENDIT_ENV": "sandbox",
            "SAAS_XENDIT_SANDBOX_PROFILE_ID": "saas-staging-xendit",
            "SAAS_XENDIT_SANDBOX_SECRET_KEY": "onlineboost_secret_key_123456",
            "SAAS_XENDIT_SANDBOX_CALLBACK_TOKEN": "saas_sandbox_callback_token_123456",
            "SAAS_XENDIT_SANDBOX_BUSINESS_ID": "business_saas_staging",
            "XENDIT_SECRET_KEY": "onlineboost_secret_key_123456",
        }
        with self.assertRaisesRegex(SaaSXenditProfileError, "BILLING_ONLINEBOOST_CREDENTIAL_REUSE_FORBIDDEN"):
            SaaSXenditSandboxProfile.from_env(env)


    async def test_saas_provider_reuses_adapter_for_dynamic_qris_and_sandbox_callback(self):
        env = {
            "SAAS_XENDIT_ENV": "sandbox",
            "SAAS_XENDIT_SANDBOX_PROFILE_ID": "saas-staging-xendit",
            "SAAS_XENDIT_SANDBOX_SECRET_KEY": "saas_sandbox_secret_key_123456",
            "SAAS_XENDIT_SANDBOX_CALLBACK_TOKEN": "saas_sandbox_callback_token_123456",
            "SAAS_XENDIT_SANDBOX_BUSINESS_ID": "business_saas_staging",
            "SAAS_XENDIT_SANDBOX_API_URL": "https://api.xendit.co",
            "SAAS_XENDIT_SANDBOX_WEBHOOK_URL": "https://api-staging.boontrack.com/api/v1/saas-billing/webhooks/xendit",
            "XENDIT_SECRET_KEY": "onlineboost_secret_key_123456",
            "XENDIT_CALLBACK_TOKEN": "onlineboost_callback_token_123456",
        }
        profile = SaaSXenditSandboxProfile.from_env(env)
        captured = {}

        class FakeAdapter:
            def __init__(self, **kwargs):
                captured["adapter_kwargs"] = kwargs
                self.api_url = ""

            async def create_transaction(self, request):
                captured["request"] = request
                return TransactionResponse(
                    transaction_id="qr_ci_123",
                    order_id=request.order_id,
                    status="PENDING",
                    payment_method="DYNAMIC_QRIS",
                    amount=request.amount,
                    payment_url="https://checkout.xendit.co/qr-ci",
                    qr_string="000201010212",
                    qr_image_url="https://cdn.example.test/qr.png",
                    raw_response={
                        "reference_id": request.order_id,
                        "currency": "IDR",
                    },
                )

        provider = SaaSXenditProvider(profile=profile, adapter_factory=FakeAdapter)
        result = await provider.create_dynamic_qris(
            purchase_reference="saas-ci-reference-001",
            amount_idr=99000,
            description="Studio Annual",
        )
        self.assertEqual(result["provider"], "XENDIT")
        self.assertEqual(result["amount_idr"], 99000)
        self.assertEqual(captured["request"].metadata["callback_url"], profile.webhook_url)
        self.assertEqual(captured["adapter_kwargs"]["env"], "sandbox")

    def test_router_registers_core_saas_billing_contract_paths(self):
        paths = {route.path for route in saas_billing_router.routes}
        self.assertIn("/api/v1/saas-billing/catalog", paths)
        self.assertIn("/api/v1/saas-billing/quotes", paths)
        self.assertIn("/api/v1/saas-billing/payment-intents", paths)
        self.assertIn("/api/v1/saas-billing/webhooks/xendit", paths)


if __name__ == "__main__":
    unittest.main()
