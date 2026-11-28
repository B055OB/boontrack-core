"""Unit tests for Supabase Staging identity validation in scripts/preflight_saas_billing_migration_038.py.

Verifies:
1. Strict acceptance of verified Supabase Staging pooler identity
   (host: aws-0-ap-southeast-1.pooler.supabase.com, db: postgres,
    user: saas_billing_staging_readonly.xkhqirhurnjqglmajghn).
2. Strict rejection of Production (mpluzajlzpregmjwpjqr) anywhere in DSN.
3. Fail-closed rejection of missing, partial, or mismatched identities.
"""
from __future__ import annotations

import unittest

from scripts.preflight_saas_billing_migration_038 import (
    SUPABASE_PRODUCTION_PROJECT_REF,
    SUPABASE_STAGING_DATABASE,
    SUPABASE_STAGING_POOLER_HOST,
    SUPABASE_STAGING_POOLER_USER,
    SUPABASE_STAGING_PROJECT_REF,
    validate_staging_target_identity,
)


class TestPreflightStagingTargetIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.valid_staging_dsn = (
            f"postgresql://{SUPABASE_STAGING_POOLER_USER}:mock_secret_pass_12345@"
            f"{SUPABASE_STAGING_POOLER_HOST}:5432/{SUPABASE_STAGING_DATABASE}?sslmode=require"
        )

    def test_valid_staging_pooler_identity_accepted(self) -> None:
        ident = validate_staging_target_identity(self.valid_staging_dsn)
        self.assertEqual(ident["host"], SUPABASE_STAGING_POOLER_HOST)
        self.assertEqual(ident["database"], SUPABASE_STAGING_DATABASE)
        self.assertEqual(ident["project_ref"], SUPABASE_STAGING_PROJECT_REF)
        self.assertEqual(ident["username"], SUPABASE_STAGING_POOLER_USER)

    def test_production_project_ref_strictly_rejected(self) -> None:
        # 1. In hostname
        prod_host_dsn = f"postgresql://{SUPABASE_STAGING_POOLER_USER}:pass@{SUPABASE_PRODUCTION_PROJECT_REF}.supabase.co:5432/postgres"
        with self.assertRaises(RuntimeError) as ctx:
            validate_staging_target_identity(prod_host_dsn)
        self.assertIn("PRODUCTION_TARGET_FORBIDDEN", str(ctx.exception))

        # 2. In username
        prod_user_dsn = f"postgresql://postgres.{SUPABASE_PRODUCTION_PROJECT_REF}:pass@{SUPABASE_STAGING_POOLER_HOST}:5432/postgres"
        with self.assertRaises(RuntimeError) as ctx:
            validate_staging_target_identity(prod_user_dsn)
        self.assertIn("PRODUCTION_TARGET_FORBIDDEN", str(ctx.exception))

        # 3. In password or query params
        prod_param_dsn = f"postgresql://{SUPABASE_STAGING_POOLER_USER}:secret@{SUPABASE_STAGING_POOLER_HOST}:5432/postgres?ref={SUPABASE_PRODUCTION_PROJECT_REF}"
        with self.assertRaises(RuntimeError) as ctx:
            validate_staging_target_identity(prod_param_dsn)
        self.assertIn("PRODUCTION_TARGET_FORBIDDEN", str(ctx.exception))

    def test_unconfigured_or_empty_dsn_rejected(self) -> None:
        for empty in ("", "   ", None):
            with self.assertRaises(RuntimeError) as ctx:
                validate_staging_target_identity(empty)  # type: ignore[arg-type]
            self.assertIn("SAAS_BILLING_STAGING_PREFLIGHT_DSN_NOT_CONFIGURED", str(ctx.exception))

    def test_host_mismatch_rejected(self) -> None:
        mismatched_hosts = [
            "localhost",
            "127.0.0.1",
            "aws-0-us-east-1.pooler.supabase.com",
            f"db.{SUPABASE_STAGING_PROJECT_REF}.supabase.co",
        ]
        for host in mismatched_hosts:
            dsn = f"postgresql://{SUPABASE_STAGING_POOLER_USER}:pass@{host}:5432/postgres"
            with self.assertRaises(RuntimeError) as ctx:
                validate_staging_target_identity(dsn)
            self.assertIn("STAGING_TARGET_HOST_MISMATCH", str(ctx.exception))

    def test_database_mismatch_rejected(self) -> None:
        dsn = f"postgresql://{SUPABASE_STAGING_POOLER_USER}:pass@{SUPABASE_STAGING_POOLER_HOST}:5432/test_boontrack"
        with self.assertRaises(RuntimeError) as ctx:
            validate_staging_target_identity(dsn)
        self.assertIn("STAGING_TARGET_DATABASE_MISMATCH", str(ctx.exception))

    def test_username_and_role_mismatch_rejected(self) -> None:
        mismatched_users = [
            f"postgres.{SUPABASE_STAGING_PROJECT_REF}",
            f"service_role.{SUPABASE_STAGING_PROJECT_REF}",
            "saas_billing_staging_readonly",
            "test_user",
        ]
        for user in mismatched_users:
            dsn = f"postgresql://{user}:pass@{SUPABASE_STAGING_POOLER_HOST}:5432/postgres"
            with self.assertRaises(RuntimeError) as ctx:
                validate_staging_target_identity(dsn)
            self.assertIn("STAGING_TARGET_USER_MISMATCH", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
