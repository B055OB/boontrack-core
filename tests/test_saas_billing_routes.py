import json
import unittest
from unittest.mock import patch

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

    def test_router_registers_core_saas_billing_contract_paths(self):
        paths = {route.path for route in saas_billing_router.routes}
        self.assertIn("/api/v1/saas-billing/catalog", paths)
        self.assertIn("/api/v1/saas-billing/quotes", paths)
        self.assertIn("/api/v1/saas-billing/payment-intents", paths)
        self.assertIn("/api/v1/saas-billing/webhooks/xendit", paths)


if __name__ == "__main__":
    unittest.main()
