#!/usr/bin/env python3
"""
================================================================================
B2-ASSERT-04 FAIL-CLOSED REGRESSION TEST SUITE (REV 2.8 CONTRACTUAL HARNESS)
================================================================================
Test suite verifying the fail-closed evaluation rules of B2-ASSERT-04
against the REV 2.8 relational contract in GATE_B2_VERIFICATION_PROTOCOL.md.

Mandated Failure & Discrepancy Scenarios:
- Test 1: 0 dangling references but 0/8 active FKs -> MUST FAIL
- Test 2: 0 dangling references but 7/8 active FKs -> MUST FAIL
- Test 3: 8/8 FKs registered but one has convalidated = False -> MUST FAIL
- Test 4: Positive Control (8/8 Validated FKs, exact names & actions, 0 Dangling) -> MUST PASS
- Test 5: Dangling Reference Rejection (8/8 Validated FKs, 3 Orphans) -> MUST FAIL
- Test 6: Missing Schema Column Rejection (8/8 Validated FKs, Missing attributions.order_id) -> MUST FAIL
- Test 7: Constraint Wrong Name (8/8 FKs exist, but 1 has wrong name) -> MUST FAIL (DISCREPANCY)
- Test 8: Constraint Wrong Action (8/8 FKs exist, but manager self-ref has CASCADE instead of RESTRICT) -> MUST FAIL (DISCREPANCY)
================================================================================
"""

import sys
import copy
import unittest

from audit_b2_comprehensive_inspector import (
    REV28_CONTRACTUAL_FK_MANIFEST,
    evaluate_b2_assert_04
)

FULL_COLUMNS_CATALOG = {
    "affiliate_commissions": {"tenant_id", "affiliate_id", "order_id", "amount"},
    "affiliates": {"tenant_id", "id", "manager_id", "referral_code"},
    "attribution_sessions": {"tenant_id", "order_id", "id"},
    "attributions": {"tenant_id", "order_id", "id"},
    "delivery_orders": {"tenant_id", "order_id", "id"},
    "product_orders": {"tenant_id", "order_id", "id"},
    "shop_commission_ledger": {"tenant_id", "subscription_id", "id"},
    "shop_subscriptions": {"tenant_id", "id", "xendit_invoice_id"}
}

ALL_8_VALID_FKS = [
    {
        "constraint_name": "fk_affiliate_commissions_affiliate_composite",
        "child_table": "affiliate_commissions",
        "parent_table": "affiliates",
        "child_cols": ["tenant_id", "affiliate_id"],
        "parent_cols": ["tenant_id", "id"],
        "confdeltype": "c",  # CASCADE
        "convalidated": True
    },
    {
        "constraint_name": "fk_affiliates_manager_composite",
        "child_table": "affiliates",
        "parent_table": "affiliates",
        "child_cols": ["tenant_id", "manager_id"],
        "parent_cols": ["tenant_id", "id"],
        "confdeltype": "r",  # RESTRICT (per CTO directive)
        "convalidated": True
    },
    {
        "constraint_name": "fk_attribution_sessions_order_composite",
        "child_table": "attribution_sessions",
        "parent_table": "orders",
        "child_cols": ["tenant_id", "order_id"],
        "parent_cols": ["tenant_id", "id"],
        "confdeltype": "c",  # CASCADE
        "convalidated": True
    },
    {
        "constraint_name": "fk_attributions_order_composite",
        "child_table": "attributions",
        "parent_table": "orders",
        "child_cols": ["tenant_id", "order_id"],
        "parent_cols": ["tenant_id", "id"],
        "confdeltype": "c",  # CASCADE
        "convalidated": True
    },
    {
        "constraint_name": "fk_delivery_orders_order_composite",
        "child_table": "delivery_orders",
        "parent_table": "orders",
        "child_cols": ["tenant_id", "order_id"],
        "parent_cols": ["tenant_id", "id"],
        "confdeltype": "c",  # CASCADE
        "convalidated": True
    },
    {
        "constraint_name": "fk_product_orders_order_composite",
        "child_table": "product_orders",
        "parent_table": "orders",
        "child_cols": ["tenant_id", "order_id"],
        "parent_cols": ["tenant_id", "id"],
        "confdeltype": "c",  # CASCADE
        "convalidated": True
    },
    {
        "constraint_name": "fk_shop_commission_ledger_subscription_composite",
        "child_table": "shop_commission_ledger",
        "parent_table": "shop_subscriptions",
        "child_cols": ["tenant_id", "subscription_id"],
        "parent_cols": ["tenant_id", "id"],
        "confdeltype": "c",  # CASCADE
        "convalidated": True
    },
    {
        "constraint_name": "fk_shop_subscriptions_tenant_anchor",
        "child_table": "shop_subscriptions",
        "parent_table": "tenants",
        "child_cols": ["tenant_id"],
        "parent_cols": ["id"],
        "confdeltype": "r",  # RESTRICT
        "convalidated": True
    }
]


class TestAssert04FailClosedRegression(unittest.TestCase):

    def test_scenario_1_zero_dangling_zero_fks_must_fail(self):
        """
        Test 1: 0 dangling reference tetapi 0/8 FK aktif -> WAJIB FAIL
        """
        print("\n[RUNNING TEST 1] Scenario: 0 dangling references, 0/8 active FKs...")
        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=[],  # 0 active FKs
            columns_catalog=FULL_COLUMNS_CATALOG,
            orphaned_count=0,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertFalse(res["is_pass"], "Test 1 Failed: evaluate_b2_assert_04 MUST NOT pass when 0 FKs active")
        self.assertEqual(res["matched_fk_count"], 0)
        self.assertEqual(res["convalidated_fk_count"], 0)
        self.assertEqual(res["verdict"], "FAIL/PENDING")
        self.assertEqual(res["tag"], "UNPROVEN / PENDING DDL")
        print("  -> Result: PASS (Rejected as expected: FAIL/PENDING, UNPROVEN / PENDING DDL)")

    def test_scenario_2_zero_dangling_seven_fks_must_fail(self):
        """
        Test 2: 0 dangling reference tetapi 7/8 FK aktif -> WAJIB FAIL
        """
        print("\n[RUNNING TEST 2] Scenario: 0 dangling references, 7/8 active FKs...")
        seven_fks = ALL_8_VALID_FKS[:7]
        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=seven_fks,  # 7 of 8 active
            columns_catalog=FULL_COLUMNS_CATALOG,
            orphaned_count=0,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertFalse(res["is_pass"], "Test 2 Failed: evaluate_b2_assert_04 MUST NOT pass when only 7/8 FKs active")
        self.assertEqual(res["matched_fk_count"], 7)
        self.assertEqual(res["convalidated_fk_count"], 7)
        self.assertEqual(res["verdict"], "FAIL/PENDING")
        self.assertEqual(res["tag"], "UNPROVEN / PENDING DDL")
        print("  -> Result: PASS (Rejected as expected: FAIL/PENDING, UNPROVEN / PENDING DDL)")

    def test_scenario_3_eight_fks_one_unvalidated_must_fail(self):
        """
        Test 3: 8/8 FK terdaftar tetapi salah satu berstatus convalidated = False -> WAJIB FAIL
        """
        print("\n[RUNNING TEST 3] Scenario: 8/8 FKs registered, but 1 has convalidated = False...")
        mock_fks = copy.deepcopy(ALL_8_VALID_FKS)
        # Invalidate 4th constraint (attributions -> orders)
        mock_fks[3]["convalidated"] = False

        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=mock_fks,
            columns_catalog=FULL_COLUMNS_CATALOG,
            orphaned_count=0,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertFalse(res["is_pass"], "Test 3 Failed: evaluate_b2_assert_04 MUST NOT pass when an FK is NOT VALID")
        self.assertEqual(res["convalidated_fk_count"], 7, "Convalidated count must be 7 when 1 FK is invalid")
        self.assertGreater(res["discrepancy_count"], 0)
        self.assertEqual(res["verdict"], "FAIL/PENDING")
        print("  -> Result: PASS (Rejected as expected: convalidated_fk_count=7, discrepancy=1, FAIL/PENDING)")

    def test_scenario_4_positive_control_all_valid_must_pass(self):
        """
        Test 4 (Positive Control): 8/8 Validated FKs, 0 Dangling, All Columns -> MUST PASS
        """
        print("\n[RUNNING TEST 4] Positive Control: 8/8 Validated FKs, 0 Dangling, All Columns...")
        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=ALL_8_VALID_FKS,
            columns_catalog=FULL_COLUMNS_CATALOG,
            orphaned_count=0,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertTrue(res["is_pass"], "Test 4 Failed: evaluate_b2_assert_04 MUST pass when all 8 FKs are active & validated")
        self.assertEqual(res["matched_fk_count"], 8)
        self.assertEqual(res["convalidated_fk_count"], 8)
        self.assertEqual(res["discrepancy_count"], 0)
        self.assertEqual(res["verdict"], "PASS")
        self.assertEqual(res["tag"], "PASS (8/8 COMPOSITE FKS VALIDATED & 0 DANGLING)")
        print("  -> Result: PASS (Accepted as expected: PASS, 8/8 COMPOSITE FKS VALIDATED)")

    def test_scenario_5_dangling_reference_detected_must_fail(self):
        """
        Test 5: 8/8 Validated FKs but dangling references exist -> WAJIB FAIL
        """
        print("\n[RUNNING TEST 5] Scenario: 8/8 Validated FKs, but 3 orphaned rows exist...")
        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=ALL_8_VALID_FKS,
            columns_catalog=FULL_COLUMNS_CATALOG,
            orphaned_count=3,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertFalse(res["is_pass"], "Test 5 Failed: evaluate_b2_assert_04 MUST NOT pass when orphaned rows exist")
        self.assertEqual(res["verdict"], "FAIL")
        self.assertEqual(res["tag"], "FAIL (DANGLING REFERENCES OR INTEGRITY VIOLATION)")
        print("  -> Result: PASS (Rejected as expected: FAIL, INTEGRITY VIOLATION)")

    def test_scenario_6_missing_schema_column_must_fail(self):
        """
        Test 6: 8/8 Validated FKs but attributions.order_id column is missing -> WAJIB FAIL
        """
        print("\n[RUNNING TEST 6] Scenario: 8/8 Validated FKs, but attributions.order_id is absent...")
        incomplete_catalog = copy.deepcopy(FULL_COLUMNS_CATALOG)
        incomplete_catalog["attributions"].remove("order_id")

        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=ALL_8_VALID_FKS,
            columns_catalog=incomplete_catalog,
            orphaned_count=0,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertFalse(res["is_pass"], "Test 6 Failed: evaluate_b2_assert_04 MUST NOT pass when relational column is missing")
        self.assertGreater(res["pending_ddl_columns_count"], 0)
        self.assertIn("attributions", res["missing_columns_detail"])
        self.assertEqual(res["verdict"], "FAIL/PENDING")
        self.assertEqual(res["tag"], "UNPROVEN / PENDING DDL")
        print("  -> Result: PASS (Rejected as expected: pending_ddl_columns_count=1, UNPROVEN / PENDING DDL)")

    def test_scenario_7_constraint_wrong_name_must_fail(self):
        """
        Test 7: 8/8 FK ada dan tervalidasi, tetapi salah satu FK menggunakan nama yang salah -> WAJIB ditolak (FAIL/PENDING)
        """
        print("\n[RUNNING TEST 7] Scenario: 8/8 FKs exist, but 1 FK has wrong constraint name...")
        mock_fks = copy.deepcopy(ALL_8_VALID_FKS)
        # Change name of fk_affiliates_manager_composite to an arbitrary name
        mock_fks[1]["constraint_name"] = "fk_affiliates_manager_custom_name_wrong"

        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=mock_fks,
            columns_catalog=FULL_COLUMNS_CATALOG,
            orphaned_count=0,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertFalse(res["is_pass"], "Test 7 Failed: evaluate_b2_assert_04 MUST NOT pass when constraint name mismatches manifest")
        self.assertEqual(res["matched_fk_count"], 7)
        self.assertEqual(res["discrepancy_count"], 1)
        self.assertEqual(res["verdict"], "FAIL/PENDING")
        self.assertIn("DISCREPANCY", res["tag"])
        print("  -> Result: PASS (Rejected as expected: matched=7/8, discrepancy=1, NAME_MISMATCH caught)")

    def test_scenario_8_constraint_wrong_action_must_fail(self):
        """
        Test 8: 8/8 FK ada dan tervalidasi, tetapi manager self-ref menggunakan ON DELETE CASCADE alih-alih RESTRICT -> WAJIB ditolak (FAIL/PENDING)
        """
        print("\n[RUNNING TEST 8] Scenario: 8/8 FKs exist, but fk_affiliates_manager_composite uses CASCADE instead of RESTRICT...")
        mock_fks = copy.deepcopy(ALL_8_VALID_FKS)
        # Change action from 'r' (RESTRICT) to 'c' (CASCADE) on affiliates manager self-ref
        mock_fks[1]["confdeltype"] = "c"

        res = evaluate_b2_assert_04(
            manifest=REV28_CONTRACTUAL_FK_MANIFEST,
            live_fks=mock_fks,
            columns_catalog=FULL_COLUMNS_CATALOG,
            orphaned_count=0,
            mismatch_count=0,
            anti_join_orphaned=0,
            anti_join_losers=0
        )
        self.assertFalse(res["is_pass"], "Test 8 Failed: evaluate_b2_assert_04 MUST NOT pass when referential action mismatches manifest")
        self.assertEqual(res["matched_fk_count"], 7)
        self.assertEqual(res["discrepancy_count"], 1)
        self.assertEqual(res["verdict"], "FAIL/PENDING")
        self.assertIn("DISCREPANCY", res["tag"])
        print("  -> Result: PASS (Rejected as expected: matched=7/8, discrepancy=1, ACTION_MISMATCH caught)")


def main():
    print("=" * 80)
    print(" EXECUTING B2-ASSERT-04 FAIL-CLOSED REGRESSION TEST SUITE (8 SCENARIOS)")
    print("=" * 80)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAssert04FailClosedRegression)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 80)
    print(" REGRESSION SUITE VERIFICATION SUMMARY")
    print("=" * 80)
    print(f"Total Tests Run   : {result.testsRun}")
    print(f"Failures          : {len(result.failures)}")
    print(f"Errors            : {len(result.errors)}")
    
    if result.wasSuccessful() and result.testsRun == 8:
        print("[+] ALL 8 REGRESSION SCENARIOS VERIFIED SUCCESSFULLY (8/8 PASS).")
        print("[+] POSTURE: STRICT FAIL-CLOSED, NAME & ACTION MATCHING VERIFIED.")
        return 0
    else:
        print("[!] REGRESSION TEST FAILED: Verification criteria not met!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
