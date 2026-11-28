import os
import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from app.schemas.saas_billing import SaaSProduct, SaaSQuoteLineRequest
from app.services.saas_billing_catalog import TaxPolicy, quote_catalog_items
from app.services.saas_billing_repository import SaaSBillingRepository
from app.services.saas_billing_settlement import SaaSBillingSettlementRepository, SaaSSettlementError
from app.workers.saas_billing_outbox_consumer import SaaSOutboxConsumer
from app.services.saas_billing_reconciliation import SaaSBillingReconciliationService


@unittest.skipUnless(os.environ.get("CI") == "true", "requires disposable CI PostgreSQL")
class TestSaaSBillingP0PostgresE2E(unittest.IsolatedAsyncioTestCase):
    TENANT_ID = "00000000-0000-0000-0000-00000000000a"
    PROFILE_ID = "ci-xendit-saas-sandbox"
    BUSINESS_ID = "ci-saas-xendit-business"

    def setUp(self):
        self.suffix = uuid4().hex
        self.reference = "saas-e2e-" + self.suffix
        self.idempotency_key = "saas-e2e-idem-" + self.suffix
        self.repository = SaaSBillingRepository()
        self.quote = quote_catalog_items(
            product=SaaSProduct.SHOP,
            items=[
                SaaSQuoteLineRequest(sku="SHOP_ADDON_DYNAMIC_QRIS"),
                SaaSQuoteLineRequest(sku="SHOP_ADDON_SMARTCHATBOX_MULTI_CS"),
            ],
            tax_policy=TaxPolicy(
                status="APPROVED",
                mode="EXCLUSIVE",
                rate_bps=0,
                policy_id="CI-APPROVED-TAX-POLICY",
            ),
        )

    def _create_purchase(self):
        purchase = self.repository.create_purchase(
            canonical_tenant_id=self.TENANT_ID,
            product=SaaSProduct.SHOP,
            request_reference=self.reference,
            idempotency_key=self.idempotency_key,
            quote=self.quote,
            tax_policy_id="CI-APPROVED-TAX-POLICY",
            credential_profile_id=self.PROFILE_ID,
        )
        return purchase

    async def test_multi_sku_outbox_invoice_reconciliation_settlement_and_activation(self):
        from app.core.database import get_db_connection

        purchase = self._create_purchase()
        self.assertFalse(purchase["reused"])
        purchase_id = purchase["id"]
        self.assertEqual(self.quote.subtotal_idr, 188000)

        class FakeProvider:
            profile = SimpleNamespace(
                profile_id=TestSaaSBillingP0PostgresE2E.PROFILE_ID,
                business_id=TestSaaSBillingP0PostgresE2E.BUSINESS_ID,
            )

            def __init__(self):
                self.adapter = self

            async def create_invoice(self, *, purchase_reference, amount_idr, description):
                return {
                    "provider": "XENDIT",
                    "environment": "sandbox",
                    "profile_id": self.profile.profile_id,
                    "provider_invoice_id": "invoice-" + purchase_reference,
                    "checkout_url": "https://checkout.example.test/" + purchase_reference,
                    "amount_idr": amount_idr,
                    "status": "PENDING",
                }

            async def check_status(self, invoice_id):
                return SimpleNamespace(
                    status="SUCCESS",
                    amount=188000,
                    raw_response={
                        "id": invoice_id,
                        "external_id": purchase_id,
                        "business_id": self.profile.business_id,
                        "status": "PAID",
                        "amount": 188000,
                        "paid_amount": 188000,
                        "currency": "IDR",
                        "payment_method": "QRIS",
                    },
                )

        consumer = SaaSOutboxConsumer(
            connection_factory=get_db_connection,
            provider_factory=FakeProvider,
            worker_id="ci-saas-e2e-worker",
        )
        initiated = await consumer.process_one()
        self.assertTrue(initiated["processed"])
        self.assertEqual(initiated["payment_status"], "ACTIVE")

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider_invoice_id, checkout_url, payment_status
                    FROM public.saas_billing_purchases WHERE id = %s;
                    """,
                    (purchase_id,),
                )
                invoice_id, checkout_url, payment_status = cur.fetchone()
                self.assertEqual(invoice_id, "invoice-" + purchase_id)
                self.assertTrue(checkout_url.startswith("https://checkout.example.test/"))
                self.assertEqual(payment_status, "ACTIVE")
                cur.execute(
                    """
                    SELECT COUNT(*) FROM public.payment_outbox_events
                    WHERE event_id = %s AND delivery_status = 'DELIVERED';
                    """,
                    ("saas-payment-intent:" + purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], 1)
        finally:
            conn.close()

        settlement_repo = SaaSBillingSettlementRepository(connection_factory=get_db_connection)
        reconciliation = SaaSBillingReconciliationService(
            connection_factory=get_db_connection,
            provider_factory=FakeProvider,
            settlement_repository=settlement_repo,
        )
        reconciled = await reconciliation.reconcile_purchase(purchase_id)
        self.assertTrue(reconciled["reconciled"])
        self.assertEqual(reconciled["status"], "PAID")

        # Exact callback replay is acknowledged but never writes a second ledger row.
        duplicate_payload = {
            "id": "invoice-" + purchase_id,
            "external_id": purchase_id,
            "business_id": self.BUSINESS_ID,
            "status": "PAID",
            "amount": 188000,
            "paid_amount": 188000,
            "currency": "IDR",
            "payment_method": "QRIS",
        }
        duplicate = settlement_repo.settle_xendit_paid_event(
            duplicate_payload,
            credential_profile_id=self.PROFILE_ID,
            business_id=self.BUSINESS_ID,
        )
        self.assertTrue(duplicate["duplicate"])
        tampered_replay = dict(duplicate_payload, amount=188001)
        with self.assertRaisesRegex(SaaSSettlementError, "BILLING_PROVIDER_AMOUNT_MISMATCH"):
            settlement_repo.settle_xendit_paid_event(
                tampered_replay,
                credential_profile_id=self.PROFILE_ID,
                business_id=self.BUSINESS_ID,
            )

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sku, amount_idr FROM public.saas_billing_ledger_entries
                    WHERE purchase_id = %s ORDER BY sku;
                    """,
                    (purchase_id,),
                )
                ledger = cur.fetchall()
                self.assertEqual(len(ledger), 2)
                self.assertEqual({row[0] for row in ledger}, {
                    "SHOP_ADDON_DYNAMIC_QRIS", "SHOP_ADDON_SMARTCHATBOX_MULTI_CS"
                })
                self.assertEqual(sum(row[1] for row in ledger), 188000)
                cur.execute(
                    """
                    SELECT COUNT(*) FROM public.saas_billing_webhook_events
                    WHERE purchase_id = %s AND processing_status = 'PROCESSED';
                    """,
                    (purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], 1)
        finally:
            conn.close()

        activated = await consumer.process_one()
        self.assertTrue(activated["processed"])
        self.assertEqual(activated["activated_entitlements"], 2)

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM public.saas_billing_entitlement_events
                    WHERE purchase_id = %s AND event_status = 'ACTIVATED';
                    """,
                    (purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], 2)
                cur.execute(
                    """
                    SELECT COUNT(*) FROM public.payment_outbox_events
                    WHERE event_id = %s AND delivery_status = 'DELIVERED';
                    """,
                    ("saas-entitlement-activate:" + purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], 1)
        finally:
            conn.close()

        no_more = await consumer.process_one()
        self.assertFalse(no_more["processed"])

    def test_wrong_provider_business_cannot_settle(self):
        from app.core.database import get_db_connection

        purchase = self._create_purchase()
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.saas_billing_purchases
                    SET provider_invoice_id = %s
                    WHERE id = %s;
                    """,
                    ("invoice-" + purchase["id"], purchase["id"]),
                )
            conn.commit()
        finally:
            conn.close()

        callback = {
            "id": "invoice-" + purchase["id"],
            "external_id": purchase["id"],
            "business_id": "some-other-business",
            "status": "PAID",
            "amount": 188000,
            "currency": "IDR",
        }
        settlement = SaaSBillingSettlementRepository()
        with self.assertRaisesRegex(SaaSSettlementError, "BILLING_PROVIDER_BUSINESS_MISMATCH"):
            settlement.settle_xendit_paid_event(
                callback,
                credential_profile_id=self.PROFILE_ID,
                business_id=self.BUSINESS_ID,
            )


    def test_settlement_transaction_rolls_back_all_records_when_activation_outbox_insert_fails(self):
        from app.core.database import get_db_connection

        purchase = self._create_purchase()
        purchase_id = purchase["id"]
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE public.saas_billing_purchases SET provider_invoice_id = %s WHERE id = %s;",
                    ("invoice-" + purchase_id, purchase_id),
                )
                cur.execute(
                    """
                    CREATE OR REPLACE FUNCTION public.ci_force_saas_activation_outbox_failure()
                    RETURNS trigger LANGUAGE plpgsql AS 'BEGIN
                        IF NEW.event_type = ''SAAS_ENTITLEMENTS_ACTIVATE_REQUESTED'' THEN
                            RAISE EXCEPTION ''CI_FORCED_SAAS_ACTIVATION_OUTBOX_FAILURE'';
                        END IF;
                        RETURN NEW;
                    END;'
                    """
                )
                cur.execute(
                    "DROP TRIGGER IF EXISTS ci_force_saas_activation_outbox_failure ON public.payment_outbox_events;"
                )
                cur.execute(
                    """
                    CREATE TRIGGER ci_force_saas_activation_outbox_failure
                    BEFORE INSERT ON public.payment_outbox_events
                    FOR EACH ROW EXECUTE FUNCTION public.ci_force_saas_activation_outbox_failure();
                    """
                )
            conn.commit()
        finally:
            conn.close()

        payload = {
            "id": "invoice-" + purchase_id,
            "external_id": purchase_id,
            "business_id": self.BUSINESS_ID,
            "status": "PAID",
            "amount": 188000,
            "currency": "IDR",
        }
        try:
            with self.assertRaisesRegex(SaaSSettlementError, "BILLING_SETTLEMENT_TRANSACTION_FAILED"):
                SaaSBillingSettlementRepository().settle_xendit_paid_event(
                    payload,
                    credential_profile_id=self.PROFILE_ID,
                    business_id=self.BUSINESS_ID,
                )
        finally:
            cleanup = get_db_connection()
            try:
                with cleanup.cursor() as cur:
                    cur.execute(
                        "DROP TRIGGER IF EXISTS ci_force_saas_activation_outbox_failure ON public.payment_outbox_events;"
                    )
                    cur.execute(
                        "DROP FUNCTION IF EXISTS public.ci_force_saas_activation_outbox_failure();"
                    )
                cleanup.commit()
            finally:
                cleanup.close()

        verify = get_db_connection()
        try:
            with verify.cursor() as cur:
                cur.execute(
                    "SELECT payment_status FROM public.saas_billing_purchases WHERE id = %s;",
                    (purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], "INITIATING")
                cur.execute(
                    "SELECT COUNT(*) FROM public.saas_billing_webhook_events WHERE purchase_id = %s;",
                    (purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], 0)
                cur.execute(
                    "SELECT COUNT(*) FROM public.saas_billing_ledger_entries WHERE purchase_id = %s;",
                    (purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], 0)
                cur.execute(
                    "SELECT COUNT(*) FROM public.saas_billing_entitlement_events WHERE purchase_id = %s;",
                    (purchase_id,),
                )
                self.assertEqual(cur.fetchone()[0], 0)
        finally:
            verify.close()

class TestSaaSBillingWebhookRoute(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_saas_callback_calls_only_saas_settlement_repository(self):
        import json
        from unittest.mock import patch
        from app.routes.saas_billing_routes import receive_saas_xendit_webhook

        payload = {
            "id": "invoice-ci-route",
            "external_id": "00000000-0000-0000-0000-000000000001",
            "business_id": "ci-business",
            "status": "PAID",
            "amount": 1000,
            "currency": "IDR",
        }

        class FakeRequest:
            headers = {"x-callback-token": "ci-dedicated-callback-token"}

            async def json(self):
                return payload

        class FakeProvider:
            class Profile:
                profile_id = "ci-dedicated-profile"
                business_id = "ci-business"

            profile = Profile()

            def verify_callback_token(self, token):
                return token == "ci-dedicated-callback-token"

        class FakeSettlement:
            def settle_xendit_paid_event(self, received, *, credential_profile_id, business_id):
                assert received == payload
                assert credential_profile_id == "ci-dedicated-profile"
                assert business_id == "ci-business"
                return {"purchase_id": received["external_id"], "duplicate": False, "payment_status": "PAID"}

        with patch("app.routes.saas_billing_routes.SaaSXenditProvider", return_value=FakeProvider()), patch(
            "app.routes.saas_billing_routes.SaaSBillingSettlementRepository", return_value=FakeSettlement()
        ):
            response = await receive_saas_xendit_webhook(FakeRequest())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.body)["payment_status"], "PAID")

    async def test_unauthenticated_saas_callback_never_calls_settlement(self):
        from unittest.mock import patch
        from app.routes.saas_billing_routes import receive_saas_xendit_webhook

        class FakeRequest:
            headers = {"x-callback-token": "wrong-token"}

            async def json(self):
                raise AssertionError("unauthenticated callback must not parse or settle")

        class FakeProvider:
            class Profile:
                profile_id = "ci-dedicated-profile"
                business_id = "ci-business"

            profile = Profile()

            def verify_callback_token(self, token):
                return False

        with patch("app.routes.saas_billing_routes.SaaSXenditProvider", return_value=FakeProvider()), patch(
            "app.routes.saas_billing_routes.SaaSBillingSettlementRepository"
        ) as settlement:
            response = await receive_saas_xendit_webhook(FakeRequest())
        self.assertEqual(response.status_code, 403)
        settlement.assert_not_called()


if __name__ == "__main__":
    unittest.main()
