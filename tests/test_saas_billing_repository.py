import unittest

from app.schemas.saas_billing import SaaSProduct, SaaSQuoteLineRequest
from app.services.saas_billing_catalog import TaxPolicy, quote_catalog_items
from app.services.saas_billing_repository import (
    SaaSBillingRepository,
    SaaSBillingRepositoryError,
    SaaSBillingIdempotencyConflict,
)


class TestSaaSBillingRepositoryFailClosed(unittest.TestCase):
    def setUp(self):
        self.quote = quote_catalog_items(
            product=SaaSProduct.STUDIO,
            items=[SaaSQuoteLineRequest(sku="STUDIO-ANNUAL-99K")],
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
            items=[SaaSQuoteLineRequest(sku="STUDIO-ANNUAL-99K")],
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


@unittest.skipUnless(__import__("os").environ.get("CI") == "true", "requires disposable CI PostgreSQL")
class TestSaaSBillingRepositoryPostgresIntegration(unittest.TestCase):
    TENANT_ID = "00000000-0000-0000-0000-00000000000a"

    @classmethod
    def setUpClass(cls):
        from app.core.database import get_db_connection

        cls.get_db_connection = staticmethod(get_db_connection)
        conn = cls.get_db_connection()
        try:
            with conn.cursor() as cur:
                # The isolated CI schema intentionally keeps this legacy fixture minimal.
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.shop_subscriptions (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        tenant_slug VARCHAR(100) NOT NULL,
                        plan_tier VARCHAR(64) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        current_period_end TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            conn.commit()
        finally:
            conn.close()

    def setUp(self):
        from uuid import uuid4

        self.repository = SaaSBillingRepository()
        self.suffix = uuid4().hex
        self.reference = "saas-p1-" + self.suffix
        self.idempotency_key = "saas-p1-idem-" + self.suffix

    def _quote(self, sku="STUDIO-ANNUAL-99K"):
        return quote_catalog_items(
            product=SaaSProduct.STUDIO,
            items=[SaaSQuoteLineRequest(sku=sku)],
            tax_policy=TaxPolicy(
                status="APPROVED",
                mode="EXCLUSIVE",
                rate_bps=0,
                policy_id="CI-APPROVED-TAX-POLICY",
            ),
        )

    def _create(self, quote=None):
        return self.repository.create_purchase(
            canonical_tenant_id=self.TENANT_ID,
            product=SaaSProduct.STUDIO,
            request_reference=self.reference,
            idempotency_key=self.idempotency_key,
            quote=quote or self._quote(),
            tax_policy_id="CI-APPROVED-TAX-POLICY",
            credential_profile_id="ci-xendit-saas-sandbox",
        )

    def tearDown(self):
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM public.payment_intents WHERE idempotency_key = %s;",
                    (self.idempotency_key,),
                )
                row = cur.fetchone()
                if row:
                    payment_intent_id = row[0]
                    cur.execute(
                        "DELETE FROM public.saas_billing_purchases WHERE payment_intent_id = %s;",
                        (payment_intent_id,),
                    )
                    cur.execute(
                        "DELETE FROM public.payment_outbox_events WHERE payment_intent_id = %s;",
                        (payment_intent_id,),
                    )
                    cur.execute(
                        "DELETE FROM public.payment_intents WHERE id = %s;",
                        (payment_intent_id,),
                    )
            conn.commit()
        finally:
            conn.close()

    def test_same_idempotency_key_and_payload_reuses_existing_purchase(self):
        first = self._create()
        second = self._create()
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["payment_intent_id"], second["payment_intent_id"])

        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM public.saas_billing_purchases WHERE idempotency_key = %s;",
                    (self.idempotency_key,),
                )
                self.assertEqual(cur.fetchone()[0], 1)
                cur.execute(
                    "SELECT COUNT(*) FROM public.payment_intents WHERE idempotency_key = %s;",
                    (self.idempotency_key,),
                )
                self.assertEqual(cur.fetchone()[0], 1)
                cur.execute(
                    "SELECT COUNT(*) FROM public.payment_outbox_events WHERE idempotency_key = %s;",
                    ("saas-intent:" + self.idempotency_key,),
                )
                self.assertEqual(cur.fetchone()[0], 1)
        finally:
            conn.close()

    def test_same_idempotency_key_with_changed_payload_is_rejected(self):
        self._create()
        with self.assertRaisesRegex(SaaSBillingIdempotencyConflict, "BILLING_IDEMPOTENCY_CONFLICT"):
            self._create(self._quote("STUDIO-ANNUAL-299K"))

    def test_purchase_and_payment_intent_roll_back_when_outbox_insert_fails(self):
        trigger_name = "trg_saas_p1_force_outbox_failure"
        function_name = "public.saas_p1_force_outbox_failure"
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE OR REPLACE FUNCTION {function_name}() RETURNS trigger "
                    "LANGUAGE plpgsql AS $function$ BEGIN "
                    "IF NEW.event_type = 'SAAS_PAYMENT_INTENT_CREATE_REQUESTED' "
                    "THEN RAISE EXCEPTION 'CI_FORCED_OUTBOX_FAILURE'; END IF; "
                    "RETURN NEW; END; $function$;"
                )
                cur.execute(
                    f"DROP TRIGGER IF EXISTS {trigger_name} ON public.payment_outbox_events;"
                )
                cur.execute(
                    f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON public.payment_outbox_events "
                    f"FOR EACH ROW EXECUTE FUNCTION {function_name}();"
                )
            conn.commit()
        finally:
            conn.close()

        try:
            with self.assertRaises(SaaSBillingRepositoryError):
                self._create()
            check = self.get_db_connection()
            try:
                with check.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM public.payment_intents WHERE idempotency_key = %s;",
                        (self.idempotency_key,),
                    )
                    self.assertEqual(cur.fetchone()[0], 0)
                    cur.execute(
                        "SELECT COUNT(*) FROM public.saas_billing_purchases WHERE idempotency_key = %s;",
                        (self.idempotency_key,),
                    )
                    self.assertEqual(cur.fetchone()[0], 0)
                    cur.execute(
                        "SELECT COUNT(*) FROM public.payment_outbox_events WHERE idempotency_key = %s;",
                        ("saas-intent:" + self.idempotency_key,),
                    )
                    self.assertEqual(cur.fetchone()[0], 0)
            finally:
                check.close()
        finally:
            cleanup = self.get_db_connection()
            try:
                with cleanup.cursor() as cur:
                    cur.execute(
                        f"DROP TRIGGER IF EXISTS {trigger_name} ON public.payment_outbox_events;"
                    )
                    cur.execute(f"DROP FUNCTION IF EXISTS {function_name}();")
                cleanup.commit()
            finally:
                cleanup.close()

    def test_legacy_team_scale_maps_to_enterprise_without_rewriting_subscription(self):
        conn = self.get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.shop_subscriptions
                        (tenant_slug, plan_tier, status, current_period_end)
                    SELECT slug, 'TEAM_SCALE', 'ACTIVE', NULL
                    FROM public.tenants WHERE id = %s
                    RETURNING id;
                    """,
                    (self.TENANT_ID,),
                )
                subscription_id = cur.fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        try:
            state = self.repository.get_effective_tenant_entitlements(
                canonical_tenant_id=self.TENANT_ID,
                product=SaaSProduct.SHOP,
            )
            self.assertEqual(state["legacy_plan_id"], "ENTERPRISE")
            self.assertIn("ENTERPRISE", state["active_entitlement_keys"])
            self.assertIn("SHOP_DYNAMIC_QRIS", state["active_entitlement_keys"])
            self.assertIn("SHOP_SMARTCHATBOX_MULTI_CS", state["active_entitlement_keys"])
            verify = self.get_db_connection()
            try:
                with verify.cursor() as cur:
                    cur.execute(
                        "SELECT plan_tier, status FROM public.shop_subscriptions WHERE id = %s;",
                        (subscription_id,),
                    )
                    self.assertEqual(cur.fetchone(), ("TEAM_SCALE", "ACTIVE"))
            finally:
                verify.close()
        finally:
            cleanup = self.get_db_connection()
            try:
                with cleanup.cursor() as cur:
                    cur.execute("DELETE FROM public.shop_subscriptions WHERE id = %s;", (subscription_id,))
                cleanup.commit()
            finally:
                cleanup.close()


if __name__ == "__main__":
    unittest.main()
