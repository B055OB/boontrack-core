"""
================================================================================
TEST SUITE: Offline Verification for Affiliate Identity Audit Tooling (Rev 4)
File: tests/test_audit_affiliate_identities_offline.py
Classification: P0 Security Tooling Verification
Version: 2.2.0-gate-b0-rev4 (CTO-P0-GATE-B0-007)
Posture: STRICT READ-ONLY — ZERO LIVE DB ACCESS
================================================================================
"""

import os
import sys
import re
import json
from unittest.mock import MagicMock
import pytest
from scripts.audit_affiliate_identities import (
    AffiliateIdentityAuditor,
    get_mock_audit_fixtures,
    execute_database_read_only,
    validate_scan_limit,
    build_fetch_affiliates_sql,
    build_fetch_auth_users_sql,
    get_keyed_pseudonym,
    mask_name,
    mask_email,
    mask_phone,
    normalize_phone,
    resolve_safe_output_path,
    assert_no_raw_uuid_in_text,
    HARD_SCAN_CEILING,
    DEFAULT_MANIFEST_DIR,
    SQL_FETCH_AFFILIATES,
    SQL_FETCH_AUTH_USERS,
)


class TestGateB0AuditAffiliateIdentities:
    """Comprehensive offline test suite verifying Gate B0 Rev 4 invariants."""

    def test_01_existing_invalid_auth_user_id_held_as_stale_not_class2(self):
        """
        Verify that an affiliate with an existing but invalid auth_user_id
        is held as Class 1b (Stale Auth Reference) and NEVER falls back
        to email matching (Class 2).
        """
        auditor = AffiliateIdentityAuditor()
        affiliates = [{
            "id": "aff-stale-001",
            "auth_user_id": "99999999-9999-9999-9999-999999999999",
            "email": "stale@boontrack.com",
            "phone": "0812345678"
        }]
        auth_users = [{
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "stale@boontrack.com",
            "phone": "62812345678"
        }]
        result = auditor.classify_records(affiliates, auth_users)
        stats = result["summary_statistics"]

        assert stats["class_1b_stale_auth_reference"] == 1
        assert stats["class_2_unlinked_candidate"] == 0

        entry = result["manifest"][0]
        assert entry["classification"] == "CLASS_1B_STALE_AUTH_REFERENCE"
        assert entry["reconciliation_action"] == "HOLD_FOR_MANUAL_INVESTIGATION"
        assert "Fallback to email is strictly blocked" in entry["notes"]

    def test_02_email_match_but_phone_mismatch_classified_4a(self):
        """
        Verify that a 1:1 email match with conflicting phone numbers is
        classified as Class 4a (Phone Mismatch) and held for investigation.
        """
        auditor = AffiliateIdentityAuditor()
        affiliates = [{
            "id": "aff-conflict-001",
            "auth_user_id": None,
            "email": "conflict@boontrack.com",
            "phone": "0811111111"
        }]
        auth_users = [{
            "id": "22222222-2222-2222-2222-222222222222",
            "email": "conflict@boontrack.com",
            "phone": "6289999999"
        }]
        result = auditor.classify_records(affiliates, auth_users)
        stats = result["summary_statistics"]

        assert stats["class_4a_phone_mismatch"] == 1
        assert stats["class_2_unlinked_candidate"] == 0

        entry = result["manifest"][0]
        assert entry["classification"] == "CLASS_4A_PHONE_MISMATCH"
        assert entry["reconciliation_action"] == "HOLD_FOR_MANUAL_INVESTIGATION"

    def test_03_email_match_but_phone_missing_classified_4b_never_class2(self):
        """
        Verify that a 1:1 email match where phone evidence is missing
        (in affiliate or auth user) is classified as Class 4b and never Class 2.
        """
        # Case A: Affiliate phone missing
        auditor_a = AffiliateIdentityAuditor()
        affiliates_a = [{
            "id": "aff-missing-phone-a",
            "auth_user_id": None,
            "email": "missing@boontrack.com",
            "phone": None
        }]
        auth_users_a = [{
            "id": "33333333-3333-3333-3333-333333333333",
            "email": "missing@boontrack.com",
            "phone": "6281111111"
        }]
        res_a = auditor_a.classify_records(affiliates_a, auth_users_a)
        assert res_a["summary_statistics"]["class_4b_missing_phone_evidence"] == 1
        assert res_a["summary_statistics"]["class_2_unlinked_candidate"] == 0
        assert res_a["manifest"][0]["classification"] == "CLASS_4B_MISSING_PHONE_EVIDENCE"
        assert res_a["manifest"][0]["reconciliation_action"] == "HOLD_FOR_MANUAL_INVESTIGATION"

        # Case B: Auth user phone missing
        auditor_b = AffiliateIdentityAuditor()
        affiliates_b = [{
            "id": "aff-missing-phone-b",
            "auth_user_id": None,
            "email": "missing_b@boontrack.com",
            "phone": "0812345678"
        }]
        auth_users_b = [{
            "id": "44444444-4444-4444-4444-444444444444",
            "email": "missing_b@boontrack.com",
            "phone": None
        }]
        res_b = auditor_b.classify_records(affiliates_b, auth_users_b)
        assert res_b["summary_statistics"]["class_4b_missing_phone_evidence"] == 1
        assert res_b["summary_statistics"]["class_2_unlinked_candidate"] == 0

    def test_04_existing_linked_identity_with_email_discrepancy(self):
        """
        Verify that an affiliate linked by auth_user_id whose email differs
        from auth.users is classified as Class 1a and flagged for manual review.
        """
        auditor = AffiliateIdentityAuditor()
        auth_id = "55555555-5555-5555-5555-555555555555"
        affiliates = [{
            "id": "aff-linked-email-diff",
            "auth_user_id": auth_id,
            "email": "aff_email@boontrack.com",
            "phone": "0812345678"
        }]
        auth_users = [{
            "id": auth_id,
            "email": "auth_email@boontrack.com",
            "phone": "62812345678"
        }]
        result = auditor.classify_records(affiliates, auth_users)
        stats = result["summary_statistics"]

        assert stats["class_1a_linked_attribute_discrepancy"] == 1
        assert stats["class_1_exact_linked_healthy"] == 0

        entry = result["manifest"][0]
        assert entry["classification"] == "CLASS_1A_LINKED_ATTRIBUTE_DISCREPANCY"
        assert entry["reconciliation_action"] == "FLAG_FOR_MANUAL_OPERATOR_REVIEW"
        assert "email mismatch" in entry["notes"]

    def test_05_existing_linked_identity_with_phone_discrepancy(self):
        """
        Verify that an affiliate linked by auth_user_id whose phone differs
        from auth.users is classified as Class 1a and flagged for manual review.
        """
        auditor = AffiliateIdentityAuditor()
        auth_id = "66666666-6666-6666-6666-666666666666"
        affiliates = [{
            "id": "aff-linked-phone-diff",
            "auth_user_id": auth_id,
            "email": "same@boontrack.com",
            "phone": "0811111111"
        }]
        auth_users = [{
            "id": auth_id,
            "email": "same@boontrack.com",
            "phone": "6289999999"
        }]
        result = auditor.classify_records(affiliates, auth_users)
        stats = result["summary_statistics"]

        assert stats["class_1a_linked_attribute_discrepancy"] == 1
        assert stats["class_1_exact_linked_healthy"] == 0

        entry = result["manifest"][0]
        assert entry["classification"] == "CLASS_1A_LINKED_ATTRIBUTE_DISCREPANCY"
        assert entry["reconciliation_action"] == "FLAG_FOR_MANUAL_OPERATOR_REVIEW"
        assert "phone mismatch" in entry["notes"]

    def test_06_zero_raw_uuid_in_manifest_output(self):
        """
        Verify that assert_no_raw_uuid_in_text succeeds on manifest JSON
        and that zero raw UUIDs leak into the exported manifest.
        """
        affiliates, auth_users = get_mock_audit_fixtures()
        auditor = AffiliateIdentityAuditor()
        result = auditor.classify_records(affiliates, auth_users)

        manifest_json_str = json.dumps(result)
        assert_no_raw_uuid_in_text(manifest_json_str)

        uuid_regex = re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        )
        matches = uuid_regex.findall(manifest_json_str)
        assert len(matches) == 0, f"Raw UUID(s) leaked in manifest: {matches}"

        for entry in result["manifest"]:
            assert entry["affiliate_pseudonym"].startswith("psn_aff_")
            if entry["candidate_auth_pseudonym"] != "NONE":
                assert entry["candidate_auth_pseudonym"].startswith("psn_auth_")

    def test_07_no_connection_without_live_cli_flag(self, monkeypatch):
        """
        Verify that execute_database_read_only fails closed (Lock 1/2)
        if invoked without live_cli_flag=True, even if env var is true.
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        with pytest.raises(PermissionError) as exc_info:
            execute_database_read_only(live_cli_flag=False)
        assert "GATE_B0_SECURITY_VIOLATION" in str(exc_info.value)
        assert "--live" in str(exc_info.value)

    def test_08_no_connection_without_env_authorization(self, monkeypatch):
        """
        Verify that execute_database_read_only fails closed (Lock 2/2)
        if AUTHORIZE_GATE_B1_EXECUTION != 'true', even if live_cli_flag=True.
        """
        monkeypatch.delenv("AUTHORIZE_GATE_B1_EXECUTION", raising=False)
        with pytest.raises(PermissionError) as exc_info:
            execute_database_read_only(live_cli_flag=True)
        assert "GATE_B0_SECURITY_VIOLATION" in str(exc_info.value)
        assert "AUTHORIZE_GATE_B1_EXECUTION=true" in str(exc_info.value)

    def test_09_offline_test_never_imports_or_calls_db_connector(self, monkeypatch):
        """
        Verify that offline test mode uses fixtures exclusively and never
        attempts database connections or imports database drivers.
        """
        def prohibited_db_call(*args, **kwargs):
            raise AssertionError("Prohibited DB call executed during offline test!")

        monkeypatch.setattr(
            "scripts.audit_affiliate_identities.execute_database_read_only",
            prohibited_db_call
        )

        affiliates, auth_users = get_mock_audit_fixtures()
        assert len(affiliates) == 9
        assert len(auth_users) == 9

        auditor = AffiliateIdentityAuditor()
        result = auditor.classify_records(affiliates, auth_users)
        assert result["summary_statistics"]["total_affiliates"] == 9
        assert result["summary_statistics"]["total_auth_users"] == 9

    def test_10_sql_ascii_purity_and_pii_sanitization(self):
        """
        Verify pure ASCII SQL queries with LIMIT 50000, domain-masked emails,
        and keyed pseudonym format.
        """
        for sql_text, name in [(SQL_FETCH_AFFILIATES, "AFFILIATES"), (SQL_FETCH_AUTH_USERS, "AUTH_USERS")]:
            assert all(ord(c) < 128 for c in sql_text), f"Non-ASCII character in SQL_{name}"
            assert f"LIMIT {HARD_SCAN_CEILING}" in sql_text, f"LIMIT {HARD_SCAN_CEILING} missing in SQL_{name}"
            assert "ORDER BY id ASC" in sql_text, f"ORDER BY id ASC missing in SQL_{name}"

        assert mask_email("alice@boontrack.com") == "al***@bo***.com"
        assert mask_email("bob@example.com") == "bo***@ex***.com"

        aff_psn = get_keyed_pseudonym("aff", "aff-test-123")
        assert aff_psn.startswith("psn_aff_")
        assert len(aff_psn) == 24

        auth_psn = get_keyed_pseudonym("auth", "auth-test-456")
        assert auth_psn.startswith("psn_auth_")
        assert len(auth_psn) == 25

    def test_11_stale_auth_and_unlinked_duplicate_email_collision(self):
        """
        Regression Test (CTO-P0-GATE-B0-005):
        When one affiliate has a stale auth_user_id and another affiliate is unlinked
        but shares the same email (e.g. bob@example.com), verify the collision policy:
        1. Stale record is held under Class 1b (Stale Auth Reference).
        2. Unlinked record is held under Class 3 (Multi-Affiliate Collision).
        3. Neither affiliate is classified as Class 2 (Zero auto-link).
        """
        auditor = AffiliateIdentityAuditor()
        affiliates = [
            {
                "id": "aff-stale-dup",
                "auth_user_id": "99999999-9999-9999-9999-999999999999",  # Not in auth.users
                "email": "bob@example.com",
                "phone": "0822222222"
            },
            {
                "id": "aff-unlinked-dup",
                "auth_user_id": None,
                "email": "bob@example.com",
                "phone": "0822222222"
            }
        ]
        auth_users = [
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "email": "bob@example.com",
                "phone": "62822222222"
            }
        ]

        result = auditor.classify_records(affiliates, auth_users)
        stats = result["summary_statistics"]

        assert stats["class_1b_stale_auth_reference"] == 1
        assert stats["class_3_email_collision"] == 1
        assert stats["class_2_unlinked_candidate"] == 0

        manifest_map = {m["affiliate_pseudonym"]: m for m in result["manifest"]}
        stale_psn = get_keyed_pseudonym("aff", "aff-stale-dup")
        unlinked_psn = get_keyed_pseudonym("aff", "aff-unlinked-dup")

        stale_entry = manifest_map[stale_psn]
        assert stale_entry["classification"] == "CLASS_1B_STALE_AUTH_REFERENCE"
        assert stale_entry["reconciliation_action"] == "HOLD_FOR_MANUAL_INVESTIGATION"
        assert "collision" in stale_entry["notes"].lower()

        unlinked_entry = manifest_map[unlinked_psn]
        assert unlinked_entry["classification"] == "CLASS_3_MULTI_AFFILIATE_COLLISION"
        assert unlinked_entry["reconciliation_action"] == "HOLD_FOR_MANUAL_INVESTIGATION"
        assert "blocked from auto-linking" in unlinked_entry["notes"]

    def test_12_mocked_connector_snapshot_consistency_and_rollback(self, monkeypatch):
        """
        Verify transaction isolation setup order, snapshot consistency,
        and guaranteed rollback/close behavior using mocked connector.
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        monkeypatch.setenv("SUPABASE_READ_REPLICA_URL", "postgresql://mock_user:mock_pass@mock_replica:5432/db")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn

        monkeypatch.setitem(sys.modules, "psycopg2", mock_psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", MagicMock())

        execute_database_read_only(live_cli_flag=True, scan_limit=50000)

        # 1. Verify read-only session configuration
        mock_conn.set_session.assert_called_once_with(readonly=True, autocommit=False)

        # 2. Verify exact transaction setup statements in order
        executed_sqls = [call[0][0].strip() for call in mock_cur.execute.call_args_list]
        assert executed_sqls[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;"
        assert executed_sqls[1] == "SET statement_timeout = '15000ms';"
        assert executed_sqls[2] == "SET lock_timeout = '2000ms';"
        assert "FROM public.affiliates" in executed_sqls[3]
        assert "FROM auth.users" in executed_sqls[4]

        # 3. Verify guaranteed rollback and connection close
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_13_scan_ceiling_50000_boundary_succeeds(self):
        """Verify that exactly 50,000 rows succeeds at boundary."""
        assert validate_scan_limit(50000) == 50000
        sql_aff = build_fetch_affiliates_sql(50000)
        sql_auth = build_fetch_auth_users_sql(50000)
        assert "LIMIT 50000;" in sql_aff
        assert "LIMIT 50000;" in sql_auth

    def test_14_scan_ceiling_50001_boundary_fails_closed(self, monkeypatch):
        """Verify that 50,001 rows fails closed before database connection/import."""
        with pytest.raises(ValueError) as exc_info:
            validate_scan_limit(50001)
        assert "SCAN_CEILING_VIOLATION" in str(exc_info.value)
        assert "50000" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info_sql:
            build_fetch_affiliates_sql(50001)
        assert "SCAN_CEILING_VIOLATION" in str(exc_info_sql.value)

        # Fails in connector before URL check or DB connection
        monkeypatch.delenv("SUPABASE_READ_REPLICA_URL", raising=False)
        with pytest.raises(ValueError) as exc_info_conn:
            execute_database_read_only(live_cli_flag=True, scan_limit=50001)
        assert "SCAN_CEILING_VIOLATION" in str(exc_info_conn.value)

    def test_15_exception_sanitization_masks_db_details(self, monkeypatch):
        """
        Verify that database connection exceptions are sanitized and do not
        leak credentials, connection strings, or internal database hostnames.
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        monkeypatch.setenv("SUPABASE_READ_REPLICA_URL", "postgresql://mock_admin:supersecretpassword@prod-db.internal:5432/live")

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.side_effect = Exception(
            "FATAL: password authentication failed for user 'mock_admin' at postgresql://mock_admin:supersecretpassword@prod-db.internal:5432/live"
        )

        monkeypatch.setitem(sys.modules, "psycopg2", mock_psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", MagicMock())

        with pytest.raises(RuntimeError) as exc_info:
            execute_database_read_only(live_cli_flag=True, scan_limit=50000)

        err_msg = str(exc_info.value)
        assert "ERR_DATABASE_EXECUTION_FAILURE" in err_msg
        assert "supersecretpassword" not in err_msg
        assert "prod-db.internal" not in err_msg
        assert "mock_admin" not in err_msg
        assert "postgresql://" not in err_msg

    def test_16_class_6_semantics_phone_mismatch_auth_user_is_orphan(self):
        """
        Class 6 Semantics:
        An auth user involved in phone mismatch (Class 4a) lacks a validated identity
        association and is accounted for under Class 6 (Orphan Auth User).
        """
        auditor = AffiliateIdentityAuditor()
        affiliates = [{
            "id": "aff-4a",
            "auth_user_id": None,
            "email": "user@boontrack.com",
            "phone": "0811111111"
        }]
        auth_users = [{
            "id": "auth-4a",
            "email": "user@boontrack.com",
            "phone": "6289999999"
        }]
        res = auditor.classify_records(affiliates, auth_users)
        assert res["summary_statistics"]["class_4a_phone_mismatch"] == 1
        assert res["summary_statistics"]["class_6_orphan_auth_user"] == 1

    def test_17_class_6_semantics_missing_phone_auth_user_is_orphan(self):
        """
        Class 6 Semantics:
        An auth user involved in missing phone evidence (Class 4b) lacks a validated identity
        association and is accounted for under Class 6 (Orphan Auth User).
        """
        auditor = AffiliateIdentityAuditor()
        affiliates = [{
            "id": "aff-4b",
            "auth_user_id": None,
            "email": "user@boontrack.com",
            "phone": None
        }]
        auth_users = [{
            "id": "auth-4b",
            "email": "user@boontrack.com",
            "phone": "6281111111"
        }]
        res = auditor.classify_records(affiliates, auth_users)
        assert res["summary_statistics"]["class_4b_missing_phone_evidence"] == 1
        assert res["summary_statistics"]["class_6_orphan_auth_user"] == 1

    def test_18_class_6_semantics_email_collision_auth_users_are_orphans(self):
        """
        Class 6 Semantics:
        Auth users involved in an unresolved email collision (Class 3) lack a validated
        identity association and are both accounted for under Class 6 (Orphan Auth User).
        """
        auditor = AffiliateIdentityAuditor()
        affiliates = [{
            "id": "aff-col",
            "auth_user_id": None,
            "email": "col@boontrack.com",
            "phone": "0811111111"
        }]
        auth_users = [
            {"id": "auth-col-1", "email": "col@boontrack.com", "phone": "6281111111"},
            {"id": "auth-col-2", "email": "col@boontrack.com", "phone": "6281111111"},
        ]
        res = auditor.classify_records(affiliates, auth_users)
        assert res["summary_statistics"]["class_3_email_collision"] == 1
        assert res["summary_statistics"]["class_6_orphan_auth_user"] == 2

    def test_19_class_6_semantics_valid_linked_and_candidate_not_in_class_6(self):
        """
        Class 6 Semantics:
        Auth users possessing a validated identity association (Class 1, Class 1a,
        or Class 2 candidate) are matched and NEVER counted under Class 6.
        """
        auditor = AffiliateIdentityAuditor()
        affiliates = [
            {"id": "aff-1", "auth_user_id": "auth-1", "email": "a1@test.com", "phone": "081111"},
            {"id": "aff-1a", "auth_user_id": "auth-1a", "email": "a1a@test.com", "phone": "082222"},
            {"id": "aff-2", "auth_user_id": None, "email": "cand@test.com", "phone": "083333"},
        ]
        auth_users = [
            {"id": "auth-1", "email": "a1@test.com", "phone": "6281111"},
            {"id": "auth-1a", "email": "different@test.com", "phone": "6282222"},
            {"id": "auth-2", "email": "cand@test.com", "phone": "6283333"},
        ]
        res = auditor.classify_records(affiliates, auth_users)
        stats = res["summary_statistics"]
        assert stats["class_1_exact_linked_healthy"] == 1
        assert stats["class_1a_linked_attribute_discrepancy"] == 1
        assert stats["class_2_unlinked_candidate"] == 1
        assert stats["class_6_orphan_auth_user"] == 0

    # ==========================================================================
    # NEW REGRESSION & VERIFICATION TESTS (CTO-P0-GATE-B0-007)
    # ==========================================================================
    def test_20_linked_identity_missing_affiliate_email_classified_1a(self):
        """
        CTO-P0-GATE-B0-007 (Correction 1):
        Linked identity with missing email on affiliate side must NOT qualify as Class 1.
        Must be classified as Class 1a and preserve the existing relationship.
        """
        auditor = AffiliateIdentityAuditor()
        auth_id = "aaaa1111-1111-1111-1111-111111111111"
        affiliates = [{
            "id": "aff-no-email",
            "auth_user_id": auth_id,
            "email": None,
            "phone": "0812345678"
        }]
        auth_users = [{
            "id": auth_id,
            "email": "user@boontrack.com",
            "phone": "62812345678"
        }]
        res = auditor.classify_records(affiliates, auth_users)
        assert res["summary_statistics"]["class_1_exact_linked_healthy"] == 0
        assert res["summary_statistics"]["class_1a_linked_attribute_discrepancy"] == 1

        entry = res["manifest"][0]
        assert entry["classification"] == "CLASS_1A_LINKED_ATTRIBUTE_DISCREPANCY"
        assert "missing affiliate email" in entry["notes"]
        assert entry["candidate_auth_pseudonym"] == get_keyed_pseudonym("auth", auth_id)

    def test_21_linked_identity_missing_auth_email_classified_1a(self):
        """
        CTO-P0-GATE-B0-007 (Correction 1):
        Linked identity with missing email on auth user side must NOT qualify as Class 1.
        Must be classified as Class 1a and preserve the existing relationship.
        """
        auditor = AffiliateIdentityAuditor()
        auth_id = "aaaa2222-2222-2222-2222-222222222222"
        affiliates = [{
            "id": "aff-has-email",
            "auth_user_id": auth_id,
            "email": "user@boontrack.com",
            "phone": "0812345678"
        }]
        auth_users = [{
            "id": auth_id,
            "email": None,
            "phone": "62812345678"
        }]
        res = auditor.classify_records(affiliates, auth_users)
        assert res["summary_statistics"]["class_1_exact_linked_healthy"] == 0
        assert res["summary_statistics"]["class_1a_linked_attribute_discrepancy"] == 1

        entry = res["manifest"][0]
        assert entry["classification"] == "CLASS_1A_LINKED_ATTRIBUTE_DISCREPANCY"
        assert "missing auth user email" in entry["notes"]
        assert entry["candidate_auth_pseudonym"] == get_keyed_pseudonym("auth", auth_id)

    def test_22_linked_identity_missing_affiliate_phone_classified_1a(self):
        """
        CTO-P0-GATE-B0-007 (Correction 1):
        Linked identity with missing phone on affiliate side must NOT qualify as Class 1.
        Must be classified as Class 1a and preserve the existing relationship.
        """
        auditor = AffiliateIdentityAuditor()
        auth_id = "aaaa3333-3333-3333-3333-333333333333"
        affiliates = [{
            "id": "aff-no-phone",
            "auth_user_id": auth_id,
            "email": "user@boontrack.com",
            "phone": None
        }]
        auth_users = [{
            "id": auth_id,
            "email": "user@boontrack.com",
            "phone": "62812345678"
        }]
        res = auditor.classify_records(affiliates, auth_users)
        assert res["summary_statistics"]["class_1_exact_linked_healthy"] == 0
        assert res["summary_statistics"]["class_1a_linked_attribute_discrepancy"] == 1

        entry = res["manifest"][0]
        assert entry["classification"] == "CLASS_1A_LINKED_ATTRIBUTE_DISCREPANCY"
        assert "missing affiliate phone" in entry["notes"]
        assert entry["candidate_auth_pseudonym"] == get_keyed_pseudonym("auth", auth_id)

    def test_23_linked_identity_missing_auth_phone_classified_1a(self):
        """
        CTO-P0-GATE-B0-007 (Correction 1):
        Linked identity with missing phone on auth user side must NOT qualify as Class 1.
        Must be classified as Class 1a and preserve the existing relationship.
        """
        auditor = AffiliateIdentityAuditor()
        auth_id = "aaaa4444-4444-4444-4444-444444444444"
        affiliates = [{
            "id": "aff-has-phone",
            "auth_user_id": auth_id,
            "email": "user@boontrack.com",
            "phone": "0812345678"
        }]
        auth_users = [{
            "id": auth_id,
            "email": "user@boontrack.com",
            "phone": None
        }]
        res = auditor.classify_records(affiliates, auth_users)
        assert res["summary_statistics"]["class_1_exact_linked_healthy"] == 0
        assert res["summary_statistics"]["class_1a_linked_attribute_discrepancy"] == 1

        entry = res["manifest"][0]
        assert entry["classification"] == "CLASS_1A_LINKED_ATTRIBUTE_DISCREPANCY"
        assert "missing auth user phone" in entry["notes"]
        assert entry["candidate_auth_pseudonym"] == get_keyed_pseudonym("auth", auth_id)

    def test_24_manifest_and_sql_data_minimization(self):
        """
        CTO-P0-GATE-B0-007 (Correction 2):
        Verify manifest records do NOT contain unnecessary name, role, status, or timestamps.
        Verify SQL statements exclude unnecessary columns.
        """
        affiliates, auth_users = get_mock_audit_fixtures()
        auditor = AffiliateIdentityAuditor()
        res = auditor.classify_records(affiliates, auth_users)

        expected_manifest_keys = {
            "affiliate_pseudonym",
            "classification",
            "reconciliation_action",
            "masked_email",
            "masked_phone",
            "pseudonym_email_hash",
            "candidate_auth_pseudonym",
            "candidate_masked_email",
            "notes",
        }

        prohibited_keys = {
            "masked_name",
            "affiliate_role",
            "affiliate_status",
            "affiliate_created_at",
            "candidate_created_at",
            "name",
            "role",
            "status",
            "created_at",
        }

        for entry in res["manifest"]:
            assert set(entry.keys()) == expected_manifest_keys
            for pk in prohibited_keys:
                assert pk not in entry, f"Prohibited key '{pk}' found in manifest entry"

        # Verify SQL statements
        sql_aff = build_fetch_affiliates_sql(50000)
        assert "name," not in sql_aff
        assert "role," not in sql_aff
        assert "status," not in sql_aff
        assert "created_at" not in sql_aff
        assert "updated_at" not in sql_aff
        assert "ORDER BY id ASC" in sql_aff

        sql_auth = build_fetch_auth_users_sql(50000)
        assert "created_at" not in sql_auth
        assert "last_sign_in_at" not in sql_auth
        assert "ORDER BY id ASC" in sql_auth

    def test_25_phone_normalization_handles_leading_8_and_indonesian_formats(self):
        """
        CTO-P0-GATE-B0-007 (Correction 5):
        Verify Indonesian phone numbers beginning with 8 are normalized consistently to 628...
        """
        assert normalize_phone("8123456789") == "628123456789"
        assert normalize_phone("08123456789") == "628123456789"
        assert normalize_phone("+62 812-3456-789") == "628123456789"
        assert normalize_phone("628123456789") == "628123456789"
        assert normalize_phone("0215551234") == "62215551234"
        assert normalize_phone(None) == ""
        assert normalize_phone("") == ""

    def test_26_assert_no_raw_uuid_error_message_has_zero_uuid_fragments(self):
        """
        CTO-P0-GATE-B0-007 (Correction 5):
        Verify that assert_no_raw_uuid_in_text raises ValueError on UUIDs and does NOT
        leak UUID fragments or prefixes in the exception message.
        """
        leaked_uuid = "12345678-1234-1234-1234-123456789abc"
        text_with_uuid = f"Audit result: user id is {leaked_uuid}"

        with pytest.raises(ValueError) as exc_info:
            assert_no_raw_uuid_in_text(text_with_uuid)

        err_msg = str(exc_info.value)
        assert "SECURITY_VIOLATION: Raw UUID leakage detected" in err_msg
        assert "12345678" not in err_msg
        assert "123456789abc" not in err_msg
        assert leaked_uuid not in err_msg

    def test_27_transaction_cleanup_select_1_failure_rolls_back_and_closes(self, monkeypatch):
        """
        CTO-P0-GATE-B0-007 (Correction 3):
        Failure during SELECT 1 triggers conn.rollback() and conn.close().
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        monkeypatch.setenv("SUPABASE_READ_REPLICA_URL", "postgresql://user:pass@host:5432/db")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # Fail on the 4th execute call (which is SQL_FETCH_AFFILIATES)
        mock_cur.execute.side_effect = [None, None, None, Exception("SELECT 1 simulated failure")]

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        monkeypatch.setitem(sys.modules, "psycopg2", mock_psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", MagicMock())

        with pytest.raises(RuntimeError) as exc_info:
            execute_database_read_only(live_cli_flag=True, scan_limit=50000)

        assert "ERR_DATABASE_EXECUTION_FAILURE" in str(exc_info.value)
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_28_transaction_cleanup_select_2_failure_rolls_back_and_closes(self, monkeypatch):
        """
        CTO-P0-GATE-B0-007 (Correction 3):
        Failure during SELECT 2 triggers conn.rollback() and conn.close().
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        monkeypatch.setenv("SUPABASE_READ_REPLICA_URL", "postgresql://user:pass@host:5432/db")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        # Fail on the 5th execute call (which is SQL_FETCH_AUTH_USERS)
        mock_cur.execute.side_effect = [None, None, None, None, Exception("SELECT 2 simulated failure")]

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        monkeypatch.setitem(sys.modules, "psycopg2", mock_psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", MagicMock())

        with pytest.raises(RuntimeError) as exc_info:
            execute_database_read_only(live_cli_flag=True, scan_limit=50000)

        assert "ERR_DATABASE_EXECUTION_FAILURE" in str(exc_info.value)
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_29_transaction_cleanup_fetchall_failure_rolls_back_and_closes(self, monkeypatch):
        """
        CTO-P0-GATE-B0-007 (Correction 3):
        Failure during fetchall triggers conn.rollback() and conn.close().
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        monkeypatch.setenv("SUPABASE_READ_REPLICA_URL", "postgresql://user:pass@host:5432/db")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.side_effect = Exception("Fetchall simulated network failure")

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        monkeypatch.setitem(sys.modules, "psycopg2", mock_psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", MagicMock())

        with pytest.raises(RuntimeError) as exc_info:
            execute_database_read_only(live_cli_flag=True, scan_limit=50000)

        assert "ERR_DATABASE_EXECUTION_FAILURE" in str(exc_info.value)
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_30_transaction_cleanup_rollback_failure_still_closes_connection(self, monkeypatch):
        """
        CTO-P0-GATE-B0-007 (Correction 3):
        Failure during rollback() must still guarantee conn.close() in finally block.
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        monkeypatch.setenv("SUPABASE_READ_REPLICA_URL", "postgresql://user:pass@host:5432/db")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []
        mock_conn.rollback.side_effect = Exception("Rollback failure")

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        monkeypatch.setitem(sys.modules, "psycopg2", mock_psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", MagicMock())

        with pytest.raises(RuntimeError):
            execute_database_read_only(live_cli_flag=True, scan_limit=50000)

        mock_conn.close.assert_called_once()

    def test_31_transaction_cleanup_close_failure_handled_gracefully(self, monkeypatch):
        """
        CTO-P0-GATE-B0-007 (Correction 3):
        Failure during close() in finally block must be handled gracefully.
        """
        monkeypatch.setenv("AUTHORIZE_GATE_B1_EXECUTION", "true")
        monkeypatch.setenv("SUPABASE_READ_REPLICA_URL", "postgresql://user:pass@host:5432/db")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []
        mock_conn.close.side_effect = Exception("Close error ignored")

        mock_psycopg2 = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        monkeypatch.setitem(sys.modules, "psycopg2", mock_psycopg2)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", MagicMock())

        # Should complete successfully despite close exception
        aff, auth = execute_database_read_only(live_cli_flag=True, scan_limit=50000)
        assert aff == []
        assert auth == []
        mock_conn.close.assert_called_once()

    def test_32_filesystem_containment_path_traversal_rejected(self):
        """
        CTO-P0-GATE-B0-007 (Correction 4):
        Verify path traversal attempts ('..') are rejected.
        """
        with pytest.raises(ValueError) as exc1:
            resolve_safe_output_path("../evil.json")
        assert "traversal detected" in str(exc1.value)

        with pytest.raises(ValueError) as exc2:
            resolve_safe_output_path("../../etc/shadow")
        assert "traversal detected" in str(exc2.value)

    def test_33_filesystem_containment_symlink_escape_rejected(self, monkeypatch):
        """
        CTO-P0-GATE-B0-007 (Correction 4):
        Verify symlink targets and symlink escapes are rejected.
        """
        # Mock os.path.islink returning True for candidate
        monkeypatch.setattr(os.path, "islink", lambda path: True)
        with pytest.raises(ValueError) as exc_sym:
            resolve_safe_output_path("symlink_test.json")
        assert "Symlink escape rejected" in str(exc_sym.value)

    def test_34_scan_ceiling_truncation_detection_and_reporting(self):
        """
        CTO-P0-GATE-B0-007 (Correction 5):
        Verify scan truncation detection when affiliates or auth users reach ceiling limit.
        """
        auditor = AffiliateIdentityAuditor()
        # Create a mock list at ceiling boundary
        mock_aff = [{"id": f"aff-{i}", "email": f"u{i}@test.com", "phone": "081111"} for i in range(10)]
        mock_auth = [{"id": f"auth-{i}", "email": f"u{i}@test.com", "phone": "6281111"} for i in range(10)]

        # When limit is 10 (reached), truncation is detected
        res_truncated = auditor.classify_records(mock_aff, mock_auth, scan_limit=10)
        assert res_truncated["audit_metadata"]["scan_ceiling_truncated"] is True
        assert "Scan ceiling limit reached" in res_truncated["audit_metadata"]["scan_ceiling_warning"]

        # When limit is 50000 (not reached), truncation is False
        auditor2 = AffiliateIdentityAuditor()
        res_normal = auditor2.classify_records(mock_aff, mock_auth, scan_limit=50000)
        assert res_normal["audit_metadata"]["scan_ceiling_truncated"] is False
        assert "scan_ceiling_warning" not in res_normal["audit_metadata"]
