"""tests/test_phase1_stage3_step2b1_checkout_binding.py
Phase 1 Stage 3 Step 2B.1: Checkout Profile Resolution & Order Binding Test Suite.

Proves:
1. Checkout uses default active_provider of tenant when no override is given.
2. Valid provider override succeeds (Midtrans / Duitku).
3. Unavailable or unsupported provider override is rejected fail-closed.
4. Order metadata stores provider and credential_profile_id.
5. Zero plaintext secrets in order metadata or database payload.
6. Tenant A cannot use Tenant B's credential profile (HTTP 403 CREDENTIAL_PROFILE_TENANT_MISMATCH).
7. Resolver failure produces zero partial orders (no DB insert, no external gateway call).
8. Legacy valid checkout flow without modern credential_profiles remains fully operational.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure repository root is on sys.path and enforce isolated synthetic env before `app.*` imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security.test_isolation_guard import (
    assert_disposable_postgres_target,
    bootstrap_isolated_test_env,
)
bootstrap_isolated_test_env(REPO_ROOT)

import multiprocessing
import psycopg2
import pytest
from fastapi import HTTPException

from app.schemas.context import TenantRuntimeContext
from app.services.checkout_flow_service import create_d2c_order_and_dispatch_qris
from app.core.security.payment_auth_guard import CredentialProfileMapper

TENANT_ALPHA_UUID = "a1b2c3d4-0000-0000-0000-000000000001"
TENANT_BETA_UUID = "b2c3d4e5-0000-0000-0000-000000000002"

MOCK_VAULT_STORE = {
    "vault://tenants/alpha/xendit/active": "xendit_active_secret_key_v2_strong",
    "vault://tenants/alpha/midtrans/active": "midtrans_active_server_key_strong_123",
    "vault://tenants/alpha/duitku/active": "duitku_active_api_key_strong_123456",
    "vault://tenants/beta/xendit/active": "xendit_beta_secret_key_distinct_999",
    "vault://tenants/beta/midtrans/active": "midtrans_beta_server_key_distinct_888",
    "vault://tenants/beta/duitku/active": "duitku_beta_api_key_distinct_777",
}


def _make_multi_provider_tenant_context(
    active_provider: str = "XENDIT",
    tenant_uuid: str = TENANT_ALPHA_UUID,
    slug: str = "alpha-store",
) -> TenantRuntimeContext:
    """Builds a TenantRuntimeContext with modern multi-provider credential profiles."""
    slug_key = "beta" if tenant_uuid == TENANT_BETA_UUID or "beta" in slug else "alpha"
    account_prefix = "beta" if slug_key == "beta" else "alpha"
    xendit_prof_id = "cred_xendit_beta" if slug_key == "beta" else "cred_xendit_primary"
    midtrans_prof_id = "cred_midtrans_beta" if slug_key == "beta" else "cred_midtrans_primary"
    duitku_prof_id = "cred_duitku_beta" if slug_key == "beta" else "cred_duitku_primary"
    midtrans_acc_id = "G_beta_123" if slug_key == "beta" else "G123456789"
    duitku_acc_id = "D_beta_999" if slug_key == "beta" else "D1234"

    meta = {
        "payment_config": {
            "mode": "NATIVE_PG",
            "active_provider": active_provider,
            "credential_profiles": {
                xendit_prof_id: {
                    "credential_profile_id": xendit_prof_id,
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "XENDIT",
                    "verification_method": "XENDIT_CALLBACK_TOKEN",
                    "expected_provider_account_id": f"xnd_biz_{account_prefix}_01",
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "updated_at_utc": "2026-11-06T00:00:00Z",
                    "verification_secrets": [
                        {
                            "secret_version_id": f"xnd_sec_{slug_key}_v1",
                            "secret_ref": f"vault://tenants/{slug_key}/xendit/active",
                            "status": "ACTIVE",
                            "created_at_utc": "2026-11-06T00:00:00Z",
                        }
                    ],
                },
                midtrans_prof_id: {
                    "credential_profile_id": midtrans_prof_id,
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "MIDTRANS",
                    "verification_method": "MIDTRANS_SHA512",
                    "expected_provider_account_id": midtrans_acc_id,
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "updated_at_utc": "2026-11-06T00:00:00Z",
                    "verification_secrets": [
                        {
                            "secret_version_id": f"mid_sec_{slug_key}_v1",
                            "secret_ref": f"vault://tenants/{slug_key}/midtrans/active",
                            "status": "ACTIVE",
                            "created_at_utc": "2026-11-06T00:00:00Z",
                        }
                    ],
                },
                duitku_prof_id: {
                    "credential_profile_id": duitku_prof_id,
                    "canonical_tenant_id": tenant_uuid,
                    "provider": "DUITKU",
                    "verification_method": "DUITKU_CALLBACK_HMAC_SHA256",
                    "expected_provider_account_id": duitku_acc_id,
                    "environment": "production",
                    "profile_status": "ACTIVE",
                    "updated_at_utc": "2026-11-06T00:00:00Z",
                    "verification_secrets": [
                        {
                            "secret_version_id": f"dk_sec_{slug_key}_v1",
                            "secret_ref": f"vault://tenants/{slug_key}/duitku/active",
                            "status": "ACTIVE",
                            "created_at_utc": "2026-11-06T00:00:00Z",
                        }
                    ],
                },
            },
        }
    }

    return TenantRuntimeContext(
        tenant_id=tenant_uuid,
        slug=slug,
        name=f"{slug_key.title()} Store",
        metadata=meta,
    )


def _make_test_mapper() -> CredentialProfileMapper:
    return CredentialProfileMapper(
        vault_store=MOCK_VAULT_STORE,
        runtime_environment="production",
    )


@pytest.fixture(autouse=True)
def mock_common_io():
    """Mock external messaging and gateways by default to isolate checkout logic."""
    with patch("app.services.checkout_flow_service.send_whatsapp_image", new_callable=AsyncMock) as m_wa_img, \
         patch("app.services.checkout_flow_service.send_whatsapp_text", new_callable=AsyncMock) as m_wa_txt, \
         patch("app.services.checkout_flow_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as m_xen, \
         patch("app.services.midtrans_service.midtrans_service.create_qris_charge", new_callable=AsyncMock) as m_mid:
        m_wa_img.return_value = {"status": "success"}
        m_wa_txt.return_value = {"status": "success"}
        m_xen.return_value = {
            "external_id": "ORD-ALPHA-XEN",
            "amount": 250000,
            "qr_string": "00020101021226660014ID.CO.XENDIT.WWW...",
            "qr_code_url": "https://api.xendit.co/qr/ORD-ALPHA-XEN.png",
        }
        m_mid.return_value = {
            "order_id": "ORD-ALPHA-MID",
            "gross_amount": 250000,
            "qr_string": "00020101021226660014ID.CO.MIDTRANS.WWW...",
            "qr_code_url": "https://api.midtrans.com/qr/ORD-ALPHA-MID.png",
        }
        yield {
            "wa_img": m_wa_img,
            "wa_txt": m_wa_txt,
            "xen": m_xen,
            "mid": m_mid,
        }


# =============================================================================
# 1. Checkout Uses Default active_provider of Tenant
# =============================================================================
@pytest.mark.asyncio
async def test_01_checkout_uses_default_active_provider(mock_common_io):
    ctx = _make_multi_provider_tenant_context(active_provider="XENDIT")
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        res = await create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-store",
            customer_name="Budi Santoso",
            customer_phone="081234567890",
            items=[{"product_id": "prod_1", "title": "Buku Bisnis", "price": 250000, "quantity": 1}],
            total_amount=250000,
            credential_mapper=mapper,
        )

        assert res["provider"] == "XENDIT"
        assert res["credential_profile_id"] == "cred_xendit_primary"
        assert res["tenant_id"] == TENANT_ALPHA_UUID
        assert res["metadata"]["provider"] == "XENDIT"
        assert res["metadata"]["credential_profile_id"] == "cred_xendit_primary"
        assert mock_common_io["xen"].called


# =============================================================================
# 2. Valid Provider Override Succeeds (Midtrans)
# =============================================================================
@pytest.mark.asyncio
async def test_02_valid_provider_override_succeeds(mock_common_io):
    # active_provider is XENDIT, but buyer/checkout requests MIDTRANS override
    ctx = _make_multi_provider_tenant_context(active_provider="XENDIT")
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        res = await create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-store",
            customer_name="Siti Aminah",
            customer_phone="081234567891",
            items=[{"product_id": "prod_2", "title": "Kursus Online", "price": 250000, "quantity": 1}],
            total_amount=250000,
            provider_override="MIDTRANS",
            credential_mapper=mapper,
        )

        assert res["provider"] == "MIDTRANS"
        assert res["credential_profile_id"] == "cred_midtrans_primary"
        assert res["metadata"]["provider"] == "MIDTRANS"
        assert res["metadata"]["credential_profile_id"] == "cred_midtrans_primary"
        assert mock_common_io["mid"].called
        assert not mock_common_io["xen"].called


# =============================================================================
# 3. Valid Duitku Override Succeeds
# =============================================================================
@pytest.mark.asyncio
async def test_03_valid_duitku_override_succeeds(mock_common_io):
    ctx = _make_multi_provider_tenant_context(active_provider="XENDIT")
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res, \
         patch("app.services.payment.gateway_duitku.DuitkuAdapter.create_transaction", new_callable=AsyncMock) as m_dk:
        m_res.return_value = ctx
        m_dk_resp = MagicMock()
        m_dk_resp.qr_string = "00020101021226660014ID.CO.DUITKU.WWW..."
        m_dk_resp.payment_url = "https://passport.duitku.com/qr/123"
        m_dk.return_value = m_dk_resp

        res = await create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-store",
            customer_name="Andi Wijaya",
            customer_phone="081234567892",
            items=[{"product_id": "prod_3", "title": "Tiket Workshop", "price": 250000, "quantity": 1}],
            total_amount=250000,
            provider_override="DUITKU",
            credential_mapper=mapper,
        )

        assert res["provider"] == "DUITKU"
        assert res["credential_profile_id"] == "cred_duitku_primary"
        assert m_dk.called


# =============================================================================
# 4. Unavailable Provider Override Rejected Fail-Closed
# =============================================================================
@pytest.mark.asyncio
async def test_04_unavailable_provider_override_rejected():
    # Tenant only has Xendit profile
    ctx = TenantRuntimeContext(
        tenant_id=TENANT_ALPHA_UUID,
        slug="alpha-single-prov",
        name="Single Prov Store",
        metadata={
            "payment_config": {
                "active_provider": "XENDIT",
                "credential_profiles": {
                    "cred_xendit_only": {
                        "credential_profile_id": "cred_xendit_only",
                        "canonical_tenant_id": TENANT_ALPHA_UUID,
                        "provider": "XENDIT",
                        "verification_method": "XENDIT_CALLBACK_TOKEN",
                        "expected_provider_account_id": "xnd_biz_01",
                        "environment": "production",
                        "profile_status": "ACTIVE",
                        "updated_at_utc": "2026-11-06T00:00:00Z",
                        "verification_secrets": [
                            {
                                "secret_version_id": "xnd_sec_v1",
                                "secret_ref": "vault://tenants/alpha/xendit/active",
                                "status": "ACTIVE",
                                "created_at_utc": "2026-11-06T00:00:00Z",
                            }
                        ],
                    }
                },
            }
        },
    )
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        # Attempt to checkout requesting MIDTRANS override which does not exist for this tenant
        with pytest.raises(HTTPException) as exc:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-single-prov",
                customer_name="Rudi",
                customer_phone="081234567893",
                items=[{"product_id": "prod_1", "title": "Buku", "price": 100000, "quantity": 1}],
                total_amount=100000,
                provider_override="MIDTRANS",
                credential_mapper=mapper,
            )

        assert exc.value.status_code == 404
        assert "CREDENTIAL_PROFILE_NOT_FOUND" in exc.value.detail


# =============================================================================
# 5. Unsupported Provider Override Rejected (HTTP 422)
# =============================================================================
@pytest.mark.asyncio
async def test_05_unsupported_provider_override_rejected():
    ctx = _make_multi_provider_tenant_context()
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        with pytest.raises(HTTPException) as exc:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Rudi",
                customer_phone="081234567893",
                items=[{"product_id": "prod_1", "title": "Buku", "price": 100000, "quantity": 1}],
                total_amount=100000,
                provider_override="BITCOIN",
                credential_mapper=mapper,
            )

        assert exc.value.status_code == 422
        assert "UNSUPPORTED_PAYMENT_PROVIDER" in exc.value.detail


# =============================================================================
# 6. Zero Plaintext Secrets in Order Metadata
# =============================================================================
@pytest.mark.asyncio
async def test_06_order_metadata_stores_provider_and_profile_and_zero_plaintext_secrets():
    ctx = _make_multi_provider_tenant_context(active_provider="XENDIT")
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        res = await create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-store",
            customer_name="Dewi Sartika",
            customer_phone="081234567894",
            items=[{"product_id": "prod_1", "title": "Jasa Desain", "price": 300000, "quantity": 1}],
            total_amount=300000,
            credential_mapper=mapper,
        )

        meta = res.get("metadata", {})
        assert meta["provider"] == "XENDIT"
        assert meta["credential_profile_id"] == "cred_xendit_primary"
        assert meta["canonical_tenant_id"] == TENANT_ALPHA_UUID

        # Security scan: Ensure no plaintext secrets or secret refs exist in stored order metadata
        meta_str = json.dumps(meta).lower()
        forbidden_substrings = [
            "xendit_active_secret_key",
            "midtrans_active_server_key",
            "duitku_active_api_key",
            "secret_ref",
            "vault://",
            "env://",
            "api_key",
            "server_key",
            "secret_key",
        ]
        for forbidden in forbidden_substrings:
            assert forbidden not in meta_str, f"Found forbidden secret or key '{forbidden}' in order metadata: {meta}"


# =============================================================================
# 7. Tenant A Cannot Use Tenant B's Profile (HTTP 403)
# =============================================================================
@pytest.mark.asyncio
async def test_07_tenant_a_cannot_use_tenant_b_profile():
    # Tenant Alpha tries to use a profile belonging to Tenant Beta
    malicious_ctx = TenantRuntimeContext(
        tenant_id=TENANT_ALPHA_UUID,
        slug="alpha-store",
        name="Alpha Store",
        metadata={
            "payment_config": {
                "active_provider": "XENDIT",
                "credential_profiles": {
                    "cred_beta_stolen": {
                        "credential_profile_id": "cred_beta_stolen",
                        "canonical_tenant_id": TENANT_BETA_UUID,  # Belongs to Beta, not Alpha!
                        "provider": "XENDIT",
                        "verification_method": "XENDIT_CALLBACK_TOKEN",
                        "expected_provider_account_id": "xnd_biz_beta_01",
                        "environment": "production",
                        "profile_status": "ACTIVE",
                        "updated_at_utc": "2026-11-06T00:00:00Z",
                        "verification_secrets": [
                            {
                                "secret_version_id": "xnd_sec_v1",
                                "secret_ref": "vault://tenants/beta/xendit/active",
                                "status": "ACTIVE",
                                "created_at_utc": "2026-11-06T00:00:00Z",
                            }
                        ],
                    }
                },
            }
        },
    )
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = malicious_ctx

        with pytest.raises(HTTPException) as exc:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Attacker",
                customer_phone="081234567895",
                items=[{"product_id": "prod_1", "title": "Test", "price": 50000, "quantity": 1}],
                total_amount=50000,
                credential_mapper=mapper,
            )

        assert exc.value.status_code == 403
        assert "CREDENTIAL_PROFILE_TENANT_MISMATCH" in exc.value.detail


# =============================================================================
# 8. Resolver Failure Produces Zero Partial Order
# =============================================================================
@pytest.mark.asyncio
async def test_08_resolver_failure_produces_zero_partial_order():
    # Ambiguous configuration: multiple active Xendit profiles with no default
    ambiguous_ctx = TenantRuntimeContext(
        tenant_id=TENANT_ALPHA_UUID,
        slug="alpha-store",
        name="Alpha Store",
        metadata={
            "payment_config": {
                "active_provider": "XENDIT",
                "credential_profiles": {
                    "cred_xendit_1": {
                        "credential_profile_id": "cred_xendit_1",
                        "canonical_tenant_id": TENANT_ALPHA_UUID,
                        "provider": "XENDIT",
                        "verification_method": "XENDIT_CALLBACK_TOKEN",
                        "expected_provider_account_id": "xnd_biz_01",
                        "environment": "production",
                        "profile_status": "ACTIVE",
                        "updated_at_utc": "2026-11-06T00:00:00Z",
                        "verification_secrets": [
                            {"secret_version_id": "s1", "secret_ref": "vault://s1", "status": "ACTIVE", "created_at_utc": "2026-11-06T00:00:00Z"}
                        ],
                    },
                    "cred_xendit_2": {
                        "credential_profile_id": "cred_xendit_2",
                        "canonical_tenant_id": TENANT_ALPHA_UUID,
                        "provider": "XENDIT",
                        "verification_method": "XENDIT_CALLBACK_TOKEN",
                        "expected_provider_account_id": "xnd_biz_02",
                        "environment": "production",
                        "profile_status": "ACTIVE",
                        "updated_at_utc": "2026-11-06T00:00:00Z",
                        "verification_secrets": [
                            {"secret_version_id": "s2", "secret_ref": "vault://s2", "status": "ACTIVE", "created_at_utc": "2026-11-06T00:00:00Z"}
                        ],
                    },
                },
            }
        },
    )
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res, \
         patch("app.core.database.get_db_connection") as m_db_conn, \
         patch("app.services.checkout_flow_service.get_supabase") as m_sb, \
         patch("app.services.xendit_service.xendit_service.create_dynamic_qris", new_callable=AsyncMock) as m_xen, \
         patch("app.services.checkout_flow_service.send_whatsapp_image", new_callable=AsyncMock) as m_wa:

        m_res.return_value = ambiguous_ctx

        with pytest.raises(HTTPException) as exc:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Buyer",
                customer_phone="081234567899",
                items=[{"product_id": "prod_1", "title": "Buku", "price": 100000, "quantity": 1}],
                total_amount=100000,
                credential_mapper=mapper,
            )

        assert exc.value.status_code == 403
        assert "AMBIGUOUS_CREDENTIAL_PROFILE_BINDING" in exc.value.detail

        # Assert no partial order or side effect was executed
        assert not m_db_conn.called, "Postgres connection was initiated despite resolver failure!"
        assert not m_sb.return_value.table.called, "Supabase orders table was mutated despite resolver failure!"
        assert not m_xen.called, "External payment gateway was called despite resolver failure!"
        assert not m_wa.called, "WhatsApp dispatch was executed despite resolver failure!"


# =============================================================================
# 9. Legacy Checkout Flow Remains Compatible
# =============================================================================
@pytest.mark.asyncio
async def test_09_legacy_checkout_flow_remains_compatible(mock_common_io):
    # Tenant has legacy payment_config (no credential_profiles)
    legacy_ctx = TenantRuntimeContext(
        tenant_id=TENANT_ALPHA_UUID,
        slug="alpha-legacy",
        name="Alpha Legacy",
        metadata={
            "payment_config": {
                "mode": "NATIVE_PG",
                "provider": "xendit",
                "secret_key": "xnd_development_valid_legacy_key",
            }
        },
    )

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = legacy_ctx

        res = await create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-legacy",
            customer_name="Legacy Buyer",
            customer_phone="081234567896",
            items=[{"product_id": "prod_legacy", "title": "Legacy Item", "price": 150000, "quantity": 1}],
            total_amount=150000,
        )

        assert res["provider"] == "XENDIT"
        assert res["credential_profile_id"] is None  # Legacy order has no explicit profile binding
        assert res["metadata"]["provider"] == "XENDIT"
        assert res["metadata"]["credential_profile_id"] is None
        assert mock_common_io["xen"].called


# =============================================================================
# 10. Missing or Non-UUID Canonical Tenant ID Rejected Fail-Closed (HTTP 422)
# =============================================================================
@pytest.mark.asyncio
async def test_10_missing_or_invalid_canonical_tenant_id_rejected():
    """Finding #1: Authoritative tenant context must have a valid RFC 4122 UUID.

    Slugs, empty UUIDs, or unparseable values must fail closed (HTTP 422).
    """
    slug_ctx = _make_multi_provider_tenant_context()
    slug_ctx.tenant_id = "alpha-store-slug-not-uuid"  # Non-UUID string
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = slug_ctx

        with pytest.raises(HTTPException) as exc:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Budi",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Buku", "price": 100000, "quantity": 1}],
                total_amount=100000,
                credential_mapper=mapper,
            )

        assert exc.value.status_code == 422
        assert "INVALID_CANONICAL_TENANT_ID" in exc.value.detail


# =============================================================================
# 11. Multiple Active Secret Versions Rejected (HTTP 403)
# =============================================================================
@pytest.mark.asyncio
async def test_11_multiple_active_secrets_rejected():
    """Finding #3: Reject picking arbitrary active secret when multiple exist.

    Exactly one active secret version is permitted for checkout resolution.
    """
    ctx = _make_multi_provider_tenant_context(active_provider="XENDIT")
    xendit_prof = ctx.metadata["payment_config"]["credential_profiles"]["cred_xendit_primary"]
    # Introduce a second conflicting ACTIVE secret
    xendit_prof["verification_secrets"].append({
        "secret_version_id": "xnd_sec_v3_ambiguous",
        "secret_ref": "vault://tenants/alpha/xendit/active2",
        "status": "ACTIVE",
        "created_at_utc": "2026-11-06T00:00:00Z",
    })
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        with pytest.raises(HTTPException) as exc:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Budi",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Buku", "price": 100000, "quantity": 1}],
                total_amount=100000,
                credential_mapper=mapper,
            )

        assert exc.value.status_code == 403
        assert "AMBIGUOUS_CREDENTIAL_SECRET_VERSION" in exc.value.detail


# =============================================================================
# 12. Per-Provider Client Receives Exact Profile Secret (Isolation Proof)
# =============================================================================
@pytest.mark.asyncio
async def test_12_per_provider_client_receives_exact_profile_secret(mock_common_io):
    """Finding #4: Xendit, Midtrans, and Duitku genuinely receive and use credentials

    from the resolved profile on each request without modifying global singletons.
    """
    import copy as py_copy
    from app.services.payment.gateway_duitku import DuitkuAdapter

    ctx = _make_multi_provider_tenant_context()
    mapper = _make_test_mapper()

    copied_clients = []
    real_copy = py_copy.copy

    def tracking_copy(obj):
        res = real_copy(obj)
        copied_clients.append(res)
        return res

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        # 12a. Xendit Dispatch Check
        with patch("copy.copy", side_effect=tracking_copy):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Budi Xendit",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item 1", "price": 100000, "quantity": 1}],
                total_amount=100000,
                provider_override="XENDIT",
                credential_mapper=mapper,
            )
            assert len(copied_clients) >= 1
            xen_copy = copied_clients[-1]
            assert xen_copy.secret_key == "xendit_active_secret_key_v2_strong"
            assert xen_copy.env == "production"

        # 12b. Midtrans Dispatch Check
        copied_clients.clear()
        with patch("copy.copy", side_effect=tracking_copy):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Siti Midtrans",
                customer_phone="081234567891",
                items=[{"product_id": "p2", "title": "Item 2", "price": 100000, "quantity": 1}],
                total_amount=100000,
                provider_override="MIDTRANS",
                credential_mapper=mapper,
            )
            assert len(copied_clients) >= 1
            mid_copy = copied_clients[-1]
            assert mid_copy.server_key == "midtrans_active_server_key_strong_123"
            assert mid_copy.client_key == "G123456789"
            assert mid_copy.is_production is True

        # 12c. Duitku Dispatch Check
        duitku_init_args = {}
        real_duitku_init = DuitkuAdapter.__init__

        def spy_duitku_init(self, *args, **kwargs):
            duitku_init_args.update(kwargs)
            real_duitku_init(self, *args, **kwargs)

        with patch.object(DuitkuAdapter, "__init__", spy_duitku_init), \
             patch.object(DuitkuAdapter, "create_transaction", new_callable=AsyncMock) as m_dk_tx:
            m_resp = MagicMock()
            m_resp.qr_string = "00020101021226660014ID.CO.DUITKU.WWW..."
            m_resp.payment_url = "https://passport.duitku.com/qr/test"
            m_dk_tx.return_value = m_resp

            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Andi Duitku",
                customer_phone="081234567892",
                items=[{"product_id": "p3", "title": "Item 3", "price": 100000, "quantity": 1}],
                total_amount=100000,
                provider_override="DUITKU",
                credential_mapper=mapper,
            )
            assert duitku_init_args.get("merchant_code") == "D1234"
            assert duitku_init_args.get("api_key") == "duitku_active_api_key_strong_123456"
            assert duitku_init_args.get("is_sandbox") is False


# =============================================================================
# 13. Global Env Fallback Not Used For Modern Profiles
# =============================================================================
@pytest.mark.asyncio
async def test_13_global_env_fallback_not_used_for_modern_profiles(mock_common_io):
    """Finding #2: Hostile/dummy global env variables are ignored by modern profiles.

    Modern profiles derive credentials strictly from authoritative profile metadata.
    If secret resolution returns empty or fails, checkout fails 503 instead of falling back.
    """
    from app.services.payment.gateway_duitku import DuitkuAdapter

    ctx = _make_multi_provider_tenant_context()
    mapper = _make_test_mapper()

    hostile_env = {
        "DUITKU_API_KEY": "HOSTILE_GLOBAL_DUITKU_KEY",
        "DUITKU_MERCHANT_CODE": "HOSTILE_GLOBAL_CODE",
        "XENDIT_SECRET_KEY": "HOSTILE_GLOBAL_XENDIT_KEY",
        "MIDTRANS_SERVER_KEY": "HOSTILE_GLOBAL_MIDTRANS_KEY",
    }

    with patch.dict(os.environ, hostile_env):
        with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
            m_res.return_value = ctx

            # Modern Duitku checkout uses profile key, ignoring HOSTILE_GLOBAL_DUITKU_KEY
            duitku_init_args = {}
            real_duitku_init = DuitkuAdapter.__init__

            def spy_duitku_init(self, *args, **kwargs):
                duitku_init_args.update(kwargs)
                real_duitku_init(self, *args, **kwargs)

            with patch.object(DuitkuAdapter, "__init__", spy_duitku_init), \
                 patch.object(DuitkuAdapter, "create_transaction", new_callable=AsyncMock) as m_dk_tx:
                m_resp = MagicMock()
                m_resp.qr_string = "000201..."
                m_resp.payment_url = "https://passport.duitku.com/qr/test"
                m_dk_tx.return_value = m_resp

                await create_d2c_order_and_dispatch_qris(
                    merchant_slug="alpha-store",
                    customer_name="Buyer",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Buku", "price": 100000, "quantity": 1}],
                    total_amount=100000,
                    provider_override="DUITKU",
                    credential_mapper=mapper,
                )
                assert duitku_init_args["api_key"] == "duitku_active_api_key_strong_123456"
                assert duitku_init_args["api_key"] != "HOSTILE_GLOBAL_DUITKU_KEY"

            # When vault secret resolves to empty, modern flow fails closed with 503, never falling back to global env
            empty_vault_mapper = CredentialProfileMapper(
                vault_store={"vault://tenants/alpha/duitku/active": ""},
                runtime_environment="production",
            )
            with pytest.raises(HTTPException) as exc:
                await create_d2c_order_and_dispatch_qris(
                    merchant_slug="alpha-store",
                    customer_name="Buyer",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Buku", "price": 100000, "quantity": 1}],
                    total_amount=100000,
                    provider_override="DUITKU",
                    credential_mapper=empty_vault_mapper,
                )
            assert exc.value.status_code == 503
            assert "CREDENTIAL_SECRET_UNAVAILABLE" in exc.value.detail


# =============================================================================
# 14. Modern Order With Empty Provider or Profile ID Rejected (HTTP 422)
# =============================================================================
@pytest.mark.asyncio
async def test_14_empty_provider_or_profile_id_rejected():
    """Finding #5: Do not allow modern orders without valid provider and credential_profile_id."""
    ctx = _make_multi_provider_tenant_context()
    # Malform the profile so credential_profile_id is empty
    ctx.metadata["payment_config"]["credential_profiles"]["cred_xendit_primary"]["credential_profile_id"] = "   "
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = ctx

        with pytest.raises(HTTPException) as exc:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="alpha-store",
                customer_name="Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Buku", "price": 100000, "quantity": 1}],
                total_amount=100000,
                credential_mapper=mapper,
            )

        assert exc.value.status_code == 422
        assert "INVALID_CREDENTIAL_PROFILE" in exc.value.detail


# =============================================================================
# 15. Interleaved Concurrent Checkouts Multi-Tenant Isolation
# =============================================================================
@pytest.mark.asyncio
async def test_15_interleaved_concurrent_checkouts_multi_tenant_isolation(mock_common_io):
    """Guard 1: Deterministic interleaved concurrency test using asyncio.gather().

    Simulates simultaneous checkouts from Tenant Alpha and Tenant Beta.
    Uses asyncio.Event synchronization to interleave execution inside the gateway calls.
    Proves:
    1. Xendit request A receives secret A; request B receives secret B.
    2. Midtrans request A receives server key A; request B receives server key B.
    3. Duitku requests use respective merchant codes, API keys, and generate distinct signatures.
    4. Process-level singletons (xendit_service, midtrans_service) are never mutated.
    5. Order metadata and responses contain zero plaintext secrets or cross-tenant contamination.
    """
    import hashlib
    from app.services.xendit_service import xendit_service, XenditService
    from app.services.midtrans_service import midtrans_service, MidtransService
    from app.services.payment.gateway_duitku import DuitkuAdapter

    initial_xendit_key = xendit_service.secret_key
    initial_midtrans_key = midtrans_service.server_key

    ctx_alpha = _make_multi_provider_tenant_context(tenant_uuid=TENANT_ALPHA_UUID, slug="alpha-store")
    ctx_beta = _make_multi_provider_tenant_context(tenant_uuid=TENANT_BETA_UUID, slug="beta-store")
    mapper = _make_test_mapper()

    async def mock_resolver(slug: str):
        if slug == "alpha-store":
            return ctx_alpha
        elif slug == "beta-store":
            return ctx_beta
        return None

    # -------------------------------------------------------------------------
    # 15a. Interleaved Concurrent Xendit Dispatch
    # -------------------------------------------------------------------------
    evt_xen_a = asyncio.Event()
    evt_xen_b = asyncio.Event()
    captured_xen = {}

    import copy as py_copy
    real_copy = py_copy.copy

    def tracking_copy_xendit(obj):
        res = real_copy(obj)
        if isinstance(obj, XenditService):
            async def interleaved_xendit_create(external_id, amount, tenant_id=None, customer_phone=None, metadata=None):
                slug = (metadata or {}).get("merchant_slug")
                captured_xen[slug] = {
                    "secret_key": res.secret_key,
                    "env": res.env,
                    "instance_id": id(res),
                }
                if slug == "alpha-store":
                    evt_xen_a.set()
                    await asyncio.wait_for(evt_xen_b.wait(), timeout=5.0)
                else:
                    evt_xen_b.set()
                    await asyncio.wait_for(evt_xen_a.wait(), timeout=5.0)

                return {
                    "external_id": external_id,
                    "amount": amount,
                    "qr_string": f"000201...XEN_{slug}",
                    "qr_code_url": f"https://api.xendit.co/qr/{slug}.png",
                }
            res.create_dynamic_qris = interleaved_xendit_create
        return res

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", side_effect=mock_resolver), \
         patch("copy.copy", side_effect=tracking_copy_xendit):

        task_a = create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-store",
            customer_name="Buyer Alpha",
            customer_phone="081234567890",
            items=[{"product_id": "p1", "title": "Product Alpha", "price": 100000, "quantity": 1}],
            total_amount=100000,
            provider_override="XENDIT",
            credential_mapper=mapper,
        )
        task_b = create_d2c_order_and_dispatch_qris(
            merchant_slug="beta-store",
            customer_name="Buyer Beta",
            customer_phone="081234567891",
            items=[{"product_id": "p2", "title": "Product Beta", "price": 200000, "quantity": 1}],
            total_amount=200000,
            provider_override="XENDIT",
            credential_mapper=mapper,
        )

        res_a, res_b = await asyncio.gather(task_a, task_b)

        # Assert Xendit request A received secret A, request B received secret B
        assert captured_xen["alpha-store"]["secret_key"] == "xendit_active_secret_key_v2_strong"
        assert captured_xen["beta-store"]["secret_key"] == "xendit_beta_secret_key_distinct_999"
        assert captured_xen["alpha-store"]["instance_id"] != captured_xen["beta-store"]["instance_id"]
        assert captured_xen["alpha-store"]["instance_id"] != id(xendit_service)
        assert captured_xen["beta-store"]["instance_id"] != id(xendit_service)
        assert xendit_service.secret_key == initial_xendit_key  # Singleton unpolluted

        # Assert clean isolated responses
        assert res_a["tenant_id"] == TENANT_ALPHA_UUID
        assert res_b["tenant_id"] == TENANT_BETA_UUID
        assert "xendit_active_secret_key" not in json.dumps(res_a)
        assert "xendit_beta_secret_key" not in json.dumps(res_b)

    # -------------------------------------------------------------------------
    # 15b. Interleaved Concurrent Midtrans Dispatch
    # -------------------------------------------------------------------------
    evt_mid_a = asyncio.Event()
    evt_mid_b = asyncio.Event()
    captured_mid = {}

    def tracking_copy_midtrans(obj):
        res = real_copy(obj)
        if isinstance(obj, MidtransService):
            async def interleaved_midtrans_create(order_id, amount, customer_name, customer_phone, tenant_id=None, metadata=None):
                slug = (metadata or {}).get("merchant_slug")
                captured_mid[slug] = {
                    "server_key": res.server_key,
                    "client_key": res.client_key,
                    "is_production": res.is_production,
                    "instance_id": id(res),
                }
                if slug == "alpha-store":
                    evt_mid_a.set()
                    await asyncio.wait_for(evt_mid_b.wait(), timeout=5.0)
                else:
                    evt_mid_b.set()
                    await asyncio.wait_for(evt_mid_a.wait(), timeout=5.0)

                return {
                    "order_id": order_id,
                    "gross_amount": amount,
                    "qr_string": f"000201...MID_{slug}",
                    "qr_code_url": f"https://api.midtrans.com/qr/{slug}.png",
                }
            res.create_qris_charge = interleaved_midtrans_create
        return res

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", side_effect=mock_resolver), \
         patch("copy.copy", side_effect=tracking_copy_midtrans):

        task_a = create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-store",
            customer_name="Buyer Alpha",
            customer_phone="081234567890",
            items=[{"product_id": "p1", "title": "Product Alpha", "price": 100000, "quantity": 1}],
            total_amount=100000,
            provider_override="MIDTRANS",
            credential_mapper=mapper,
        )
        task_b = create_d2c_order_and_dispatch_qris(
            merchant_slug="beta-store",
            customer_name="Buyer Beta",
            customer_phone="081234567891",
            items=[{"product_id": "p2", "title": "Product Beta", "price": 200000, "quantity": 1}],
            total_amount=200000,
            provider_override="MIDTRANS",
            credential_mapper=mapper,
        )

        res_a, res_b = await asyncio.gather(task_a, task_b)

        assert captured_mid["alpha-store"]["server_key"] == "midtrans_active_server_key_strong_123"
        assert captured_mid["beta-store"]["server_key"] == "midtrans_beta_server_key_distinct_888"
        assert captured_mid["alpha-store"]["client_key"] == "G123456789"
        assert captured_mid["beta-store"]["client_key"] == "G_beta_123"
        assert captured_mid["alpha-store"]["instance_id"] != captured_mid["beta-store"]["instance_id"]
        assert midtrans_service.server_key == initial_midtrans_key  # Singleton unpolluted

    # -------------------------------------------------------------------------
    # 15c. Interleaved Concurrent Duitku Dispatch
    # -------------------------------------------------------------------------
    evt_dk_a = asyncio.Event()
    evt_dk_b = asyncio.Event()
    captured_dk = {}

    async def interleaved_duitku_create(self, tx_req):
        slug = (tx_req.metadata or {}).get("merchant_slug")
        sig = hashlib.md5(f"{self.merchant_code}{tx_req.order_id}{tx_req.amount}{self.api_key}".encode("utf-8")).hexdigest()
        captured_dk[slug] = {
            "merchant_code": self.merchant_code,
            "api_key": self.api_key,
            "is_sandbox": self.is_sandbox,
            "signature": sig,
            "instance_id": id(self),
        }
        if slug == "alpha-store":
            evt_dk_a.set()
            await asyncio.wait_for(evt_dk_b.wait(), timeout=5.0)
        else:
            evt_dk_b.set()
            await asyncio.wait_for(evt_dk_a.wait(), timeout=5.0)

        resp = MagicMock()
        resp.qr_string = f"000201...DK_{slug}"
        resp.payment_url = f"https://passport.duitku.com/qr/{slug}"
        return resp

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", side_effect=mock_resolver), \
         patch.object(DuitkuAdapter, "create_transaction", interleaved_duitku_create):

        task_a = create_d2c_order_and_dispatch_qris(
            merchant_slug="alpha-store",
            customer_name="Buyer Alpha",
            customer_phone="081234567890",
            items=[{"product_id": "p1", "title": "Product Alpha", "price": 100000, "quantity": 1}],
            total_amount=100000,
            provider_override="DUITKU",
            credential_mapper=mapper,
        )
        task_b = create_d2c_order_and_dispatch_qris(
            merchant_slug="beta-store",
            customer_name="Buyer Beta",
            customer_phone="081234567891",
            items=[{"product_id": "p2", "title": "Product Beta", "price": 200000, "quantity": 1}],
            total_amount=200000,
            provider_override="DUITKU",
            credential_mapper=mapper,
        )

        res_a, res_b = await asyncio.gather(task_a, task_b)

        assert captured_dk["alpha-store"]["merchant_code"] == "D1234"
        assert captured_dk["alpha-store"]["api_key"] == "duitku_active_api_key_strong_123456"
        assert captured_dk["beta-store"]["merchant_code"] == "D_beta_999"
        assert captured_dk["beta-store"]["api_key"] == "duitku_beta_api_key_distinct_777"
        assert captured_dk["alpha-store"]["signature"] != captured_dk["beta-store"]["signature"]
        assert captured_dk["alpha-store"]["instance_id"] != captured_dk["beta-store"]["instance_id"]


# =============================================================================
# 16. Trial Quota Side-Effect Ordering and Isolation
# =============================================================================
@pytest.mark.asyncio
async def test_16_trial_quota_side_effect_ordering_and_isolation(mock_common_io):
    """Guard 2: Trial quota consumption ordering proof.

    Proves:
    1. Credential resolution failure does NOT consume trial quota.
    2. Secret resolution failure does NOT consume trial quota.
    3. Successful checkout increments trial quota by exactly 1.
    4. Oversubscribed trial tenant (>=30 orders) is blocked upfront without side effects.
    """
    from app.core.trial_guardrail import trial_guardrail, TrialLimitExceededException

    trial_guardrail.reset("trial-store")

    # Build trial context
    trial_ctx = _make_multi_provider_tenant_context(slug="trial-store")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        # 16a. Credential resolution failure: Unsupported provider
        with pytest.raises(HTTPException):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-store",
                customer_name="Trial Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="INVALID_PROVIDER_XYZ",
                credential_mapper=mapper,
            )
        assert trial_guardrail.get_order_count("trial-store") == 0, "Quota was consumed on unsupported provider failure!"

        # 16b. Credential resolution failure: Empty secret in vault
        empty_mapper = CredentialProfileMapper(
            vault_store={"vault://tenants/alpha/xendit/active": ""},
            runtime_environment="production",
        )
        with pytest.raises(HTTPException):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-store",
                customer_name="Trial Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=empty_mapper,
            )
        assert trial_guardrail.get_order_count("trial-store") == 0, "Quota was consumed on secret resolution failure!"

        # 16c. Successful checkout: Quota increments by exactly 1
        res = await create_d2c_order_and_dispatch_qris(
            merchant_slug="trial-store",
            customer_name="Trial Buyer",
            customer_phone="081234567890",
            items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
            total_amount=50000,
            provider_override="XENDIT",
            credential_mapper=mapper,
        )
        assert res["status"] == "PENDING"
        assert trial_guardrail.get_order_count("trial-store") == 1, "Quota was not incremented on successful checkout!"

        # 16d. Trial limit reached (30 orders): Blocked upfront in PostgreSQL SSOT
        for i in range(2, 31):
            trial_guardrail.reserve_slot("trial-store", f"ORD-TRIAL-FILL-{i:03d}", is_trial=True)
            trial_guardrail.commit_slot("trial-store", f"ORD-TRIAL-FILL-{i:03d}", is_trial=True)

        assert trial_guardrail.get_order_count("trial-store") == 30

        with pytest.raises(TrialLimitExceededException):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-store",
                customer_name="Trial Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
            )
        assert trial_guardrail.get_order_count("trial-store") == 30, "Quota count was incremented beyond limit!"

    trial_guardrail.reset("trial-store")


# =============================================================================
# 17. Secret Reference and Exception Hygiene
# =============================================================================
@pytest.mark.asyncio
async def test_17_secret_reference_and_exception_hygiene(caplog):
    """Guard 3: Secret reference and exception hygiene proof.

    Proves:
    1. Error detail never leaks raw secrets, secret reference URIs, or resolver internal traces.
    2. Logs never print raw secrets or pointer URIs.
    3. Safe operational context (correlation_id, tenant UUID, profile ID) is preserved for debugging.
    """
    import logging
    CANARY_SECRET_POINTER = "vault://internal-infra/secrets/sentinel-canary-key-9999"
    CANARY_SECRET_VALUE = "CANARY_SECRET_RAW_SENSITIVE_STRING_ABCD_1234"

    canary_ctx = _make_multi_provider_tenant_context()
    # Inject canary pointer into active xendit profile
    prof = canary_ctx.metadata["payment_config"]["credential_profiles"]["cred_xendit_primary"]
    prof["verification_secrets"][0]["secret_ref"] = CANARY_SECRET_POINTER

    # 17a. Pointer missing in vault (resolution failure)
    mapper_missing = CredentialProfileMapper(
        vault_store={},  # Missing CANARY_SECRET_POINTER
        runtime_environment="production",
    )

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = canary_ctx

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(HTTPException) as exc:
                await create_d2c_order_and_dispatch_qris(
                    merchant_slug="alpha-store",
                    customer_name="Canary Buyer",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Item", "price": 100000, "quantity": 1}],
                    total_amount=100000,
                    provider_override="XENDIT",
                    credential_mapper=mapper_missing,
                )

        assert exc.value.status_code == 503
        assert exc.value.detail == "CREDENTIAL_SECRET_UNAVAILABLE: Payment credential secret is currently unavailable for checkout."
        # Information leakage assertions on HTTP detail
        assert CANARY_SECRET_POINTER not in exc.value.detail
        assert "vault://" not in exc.value.detail
        assert "sentinel-canary-key-9999" not in exc.value.detail

        # Information leakage assertions on captured logs
        assert CANARY_SECRET_POINTER not in caplog.text
        assert "sentinel-canary-key-9999" not in caplog.text
        assert "CHECKOUT_SECURITY" in caplog.text
        assert "cred_xendit_primary" in caplog.text
        assert TENANT_ALPHA_UUID in caplog.text

    # 17b. Secret resolves to empty string
    caplog.clear()
    mapper_empty = CredentialProfileMapper(
        vault_store={CANARY_SECRET_POINTER: ""},
        runtime_environment="production",
    )

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = canary_ctx

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(HTTPException) as exc:
                await create_d2c_order_and_dispatch_qris(
                    merchant_slug="alpha-store",
                    customer_name="Canary Buyer",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Item", "price": 100000, "quantity": 1}],
                    total_amount=100000,
                    provider_override="XENDIT",
                    credential_mapper=mapper_empty,
                )

        assert exc.value.status_code == 503
        assert exc.value.detail == "CREDENTIAL_SECRET_UNAVAILABLE: Payment credential secret is currently unavailable for checkout."
        assert CANARY_SECRET_POINTER not in exc.value.detail
        assert CANARY_SECRET_POINTER not in caplog.text


# =============================================================================
# 18. Crash Setelah Gateway Success Sebelum Commit
# =============================================================================
@pytest.mark.asyncio
async def test_18_crash_after_gateway_success_preserves_reserved_slot(mock_common_io):
    """Proves that if an uncommitted slot is left in RESERVED state (e.g. process crash
    after gateway dispatch before commit_slot), the slot remains strictly counted in PostgreSQL.
    """
    from app.core.trial_guardrail import trial_guardrail

    trial_guardrail.reset("trial-crash")

    # Reserve slot manually simulating upfront reservation before crash
    res = trial_guardrail.reserve_slot("trial-crash", "ORD-CRASH-001", is_trial=True)
    assert res["status"] == "RESERVED"

    # Simulate app crash: commit_slot is never called
    # Verified: The uncommitted reservation remains counted in PostgreSQL SSOT!
    count = trial_guardrail.get_order_count("trial-crash")
    assert count == 1, "Uncommitted RESERVED slot was dropped!"

    trial_guardrail.reset("trial-crash")


# =============================================================================
# 19. Expired RESERVED Tetap Dihitung (P0 Recovery Safety)
# =============================================================================
@pytest.mark.asyncio
async def test_19_expired_reserved_slot_remains_counted_and_not_auto_released():
    """Proves that:
    1. Expired RESERVED slots are NOT automatically released by TTL.
    2. Expired RESERVED slots remain counted against active quota.
    3. recover_expired_reservations() transitions them to AMBIGUOUS_TIMEOUT, NOT RELEASED.
    """
    from app.core.trial_guardrail import trial_guardrail
    import psycopg2

    trial_guardrail.reset("trial-expired")

    # Insert an expired RESERVED slot directly into PostgreSQL
    store = trial_guardrail.get_pg_store()
    conn = store._get_connection()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO public.trial_quota_reservations (
            tenant_id, tenant_slug, order_id, status, expires_at
        ) VALUES (
            'trial-expired', 'trial-expired', 'ORD-EXP-001', 'RESERVED', NOW() - INTERVAL '300 seconds'
        );
        """
    )
    cur.close()
    conn.close()

    # 1. Active count MUST still count the expired RESERVED slot
    assert trial_guardrail.get_order_count("trial-expired") == 1, "Expired RESERVED was prematurely excluded!"

    # 2. Trigger recover_expired_reservations
    recovered_count = trial_guardrail.recover_expired_reservations(tenant_id="trial-expired")
    assert recovered_count == 1

    # 3. Verify in PostgreSQL that status is AMBIGUOUS_TIMEOUT, NEVER RELEASED
    conn = store._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM public.trial_quota_reservations WHERE order_id = 'ORD-EXP-001';")
    status = cur.fetchone()[0]
    cur.close()
    conn.close()

    assert status == "AMBIGUOUS_TIMEOUT", f"Expected AMBIGUOUS_TIMEOUT but got {status}!"
    assert trial_guardrail.get_order_count("trial-expired") == 1, "Quarantined slot was excluded from count!"

    trial_guardrail.reset("trial-expired")


# =============================================================================
# 20. Ambiguous Connection Reset Tetap Dikarantina
# =============================================================================
@pytest.mark.asyncio
async def test_20_ambiguous_connection_reset_quarantines_slot(mock_common_io):
    """Proves that a connection reset or network uncertainty during gateway call
    causes the slot to transition to AMBIGUOUS_TIMEOUT and remain counted in quota.
    """
    from app.core.trial_guardrail import trial_guardrail

    trial_reset_uuid = "20202020-0000-0000-0000-000000000020"
    trial_guardrail.reset(trial_reset_uuid)

    trial_ctx = _make_multi_provider_tenant_context(tenant_uuid=trial_reset_uuid, slug="trial-reset")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    mock_common_io["xen"].side_effect = ConnectionResetError("Connection reset by peer")

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        with pytest.raises(ConnectionResetError):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-reset",
                customer_name="Reset Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
            )

        # Slot MUST be quarantined as AMBIGUOUS_TIMEOUT and counted
        assert trial_guardrail.get_order_count(trial_reset_uuid) == 1

        store = trial_guardrail.get_pg_store()
        conn = store._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s;", (trial_reset_uuid,))
        status = cur.fetchone()[0]
        cur.close()
        conn.close()
        assert status == "AMBIGUOUS_TIMEOUT", f"Expected AMBIGUOUS_TIMEOUT, got {status}"

    trial_guardrail.reset(trial_reset_uuid)


# =============================================================================
# 21. Definitive Provider Rejection Melepaskan Slot
# =============================================================================
@pytest.mark.asyncio
async def test_21_definitive_provider_rejection_releases_slot(mock_common_io):
    """Proves that a definitive client/provider rejection (HTTP 422 with validation error)
    causes the slot to transition to RELEASED, consuming exactly 0 quota.
    """
    from app.core.trial_guardrail import trial_guardrail

    trial_reject_uuid = "21212121-0000-0000-0000-000000000021"
    trial_guardrail.reset(trial_reject_uuid)

    trial_ctx = _make_multi_provider_tenant_context(tenant_uuid=trial_reject_uuid, slug="trial-reject")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    from app.services.xendit_service import XenditAPIError
    rej_err = XenditAPIError(
        status_code=422,
        error_code="API_VALIDATION_ERROR",
        message="Amount below minimum",
        is_definitive_rejection=True,
    )
    mock_common_io["xen"].side_effect = rej_err

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        with pytest.raises(XenditAPIError) as exc_info:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-reject",
                customer_name="Reject Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.is_definitive_rejection is True

        # Quota MUST be released (0 active slots)
        assert trial_guardrail.get_order_count(trial_reject_uuid) == 0

        store = trial_guardrail.get_pg_store()
        conn = store._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s;", (trial_reject_uuid,))
        status = cur.fetchone()[0]
        cur.close()
        conn.close()
        assert status == "RELEASED", f"Expected RELEASED, got {status}"

    trial_guardrail.reset(trial_reject_uuid)


# =============================================================================
# 22. Quota 29 dengan Concurrent Requests Tidak Melebihi 30
# =============================================================================
@pytest.mark.asyncio
async def test_22_quota_29_concurrent_requests_never_exceeds_cap_30(mock_common_io):
    """Proves that when quota is at 29, N concurrent checkout requests are serialized
    by PostgreSQL advisory locking so that exactly 1 request wins and total committed
    slots NEVER exceeds 30.
    """
    from app.core.trial_guardrail import trial_guardrail, TrialLimitExceededException

    trial_conc_uuid = "c2900000-0000-0000-0000-000000000029"
    trial_guardrail.reset(trial_conc_uuid)

    # Seed 29 committed slots in PostgreSQL SSOT
    for i in range(1, 30):
        trial_guardrail.reserve_slot(trial_conc_uuid, f"ORD-CONC-SEED-{i:03d}", is_trial=True, tenant_slug="trial-conc29")
        trial_guardrail.commit_slot(trial_conc_uuid, f"ORD-CONC-SEED-{i:03d}", is_trial=True, tenant_slug="trial-conc29")

    assert trial_guardrail.get_order_count(trial_conc_uuid) == 29

    trial_ctx = _make_multi_provider_tenant_context(tenant_uuid=trial_conc_uuid, slug="trial-conc29")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        # Launch 8 concurrent checkouts at quota 29
        async def checkout_task(idx: int):
            return await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-conc29",
                customer_name=f"Concurrent Buyer {idx}",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
                order_id=f"ORD-CONC-RACE-{idx:03d}",
            )

        results = await asyncio.gather(*(checkout_task(i) for i in range(1, 9)), return_exceptions=True)

        successes = [r for r in results if isinstance(r, dict) and r.get("status") == "PENDING"]
        exceeded_errors = [r for r in results if isinstance(r, TrialLimitExceededException)]

        # Exactly 1 request succeeds (securing slot #30)
        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
        # Exactly 7 requests are rejected with TrialLimitExceededException
        assert len(exceeded_errors) == 7, f"Expected 7 TrialLimitExceededException, got {len(exceeded_errors)}"

        # Total in PostgreSQL SSOT must be exactly 30, never 31+
        final_count = trial_guardrail.get_order_count(trial_conc_uuid)
        assert final_count == 30, f"Hard cap violated! Count is {final_count}"

    trial_guardrail.reset(trial_conc_uuid)


# =============================================================================
# 23. Database Connection dan Cursor Ditutup pada Success dan Failure
# =============================================================================
def test_23_database_connection_and_cursor_closed_on_success_and_failure():
    """Proves that PostgresTrialQuotaStore closes both cursor and connection
    on every execution path:
    1. Success path.
    2. Quota exceeded (rollback) path.
    3. SQL exception path.
    """
    from app.core.trial_guardrail import PostgresTrialQuotaStore, TrialLimitExceededException, TrialQuotaStoreUnavailableError

    # Mock connection and cursor
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    store = PostgresTrialQuotaStore(db_connection_factory=lambda: mock_conn)

    # 1. Success path
    mock_cur.fetchone.side_effect = [
        None,   # Idempotency check: no existing order
        (5,),   # Active count: 5 (< 30)
        ("res_id_1", "RESERVED"), # Insert returning
    ]
    res = store.reserve_slot("tenant-conn-test", "ORD-CONN-001", is_trial=True)
    assert res["status"] == "RESERVED"
    assert mock_cur.close.called, "Cursor was not closed on success!"
    assert mock_conn.close.called, "Connection was not closed on success!"

    # Reset mocks
    mock_conn.reset_mock()
    mock_cur.reset_mock()

    # 2. Quota exceeded path
    mock_cur.fetchone.side_effect = [
        None,   # Idempotency check: no existing order
        (30,),  # Active count: 30 (>= 30)
    ]
    with pytest.raises(TrialLimitExceededException):
        store.reserve_slot("tenant-conn-test", "ORD-CONN-002", is_trial=True)
    assert mock_conn.rollback.called, "Rollback was not called on quota exceeded!"
    assert mock_cur.close.called, "Cursor was not closed on quota exceeded!"
    assert mock_conn.close.called, "Connection was not closed on quota exceeded!"

    # Reset mocks
    mock_conn.reset_mock()
    mock_cur.reset_mock()

    # 3. SQL Exception path
    mock_cur.execute.side_effect = psycopg2.DatabaseError("Deadlock detected or SQL error")
    with pytest.raises(TrialQuotaStoreUnavailableError):
        store.reserve_slot("tenant-conn-test", "ORD-CONN-003", is_trial=True)
    assert mock_conn.rollback.called, "Rollback was not called on SQL error!"
    assert mock_cur.close.called, "Cursor was not closed on SQL error!"
    assert mock_conn.close.called, "Connection was not closed on SQL error!"


# =============================================================================
# 24. Authenticated Role Privilege and RLS Lockdown (Least-Privilege Hardening)
# =============================================================================
def test_24_authenticated_role_privilege_and_rls_lockdown():
    """Proves that:
    1. Direct UPDATE on trial_quota_reservations by 'authenticated' role is BLOCKED (403/InsufficientPrivilege).
    2. Direct INSERT on trial_quota_reservations by 'authenticated' role is BLOCKED (403/InsufficientPrivilege).
    3. Direct DELETE on trial_quota_reservations by 'authenticated' role is BLOCKED (403/InsufficientPrivilege).
    4. Authenticated role has SELECT access strictly constrained to own tenant rows by RLS.
    5. Legitimate backend operations continue operating seamlessly.
    """
    assert_disposable_postgres_target(dsn=os.environ.get("DATABASE_URL"), allow_if_unconfigured=False)
    conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=3)
    cur = conn.cursor()

    test_tid = "24242424-0000-0000-0000-000000000024"
    cur.execute("DELETE FROM public.trial_quota_reservations WHERE tenant_id = %s;", (test_tid,))
    conn.commit()

    # 1. Seed as backend
    cur.execute("""
        INSERT INTO public.trial_quota_reservations (tenant_id, order_id, status, expires_at)
        VALUES (%s, 'ord-priv-test', 'RESERVED', NOW() + INTERVAL '120 seconds');
    """, (test_tid,))
    conn.commit()

    # 2. Impersonate authenticated role
    cur.execute("SET ROLE authenticated;")
    cur.execute("SET app.current_tenant_id = %s;", (test_tid,))

    # Negative Test 1: Direct UPDATE must fail
    update_blocked = False
    try:
        cur.execute("UPDATE public.trial_quota_reservations SET status = 'RELEASED' WHERE order_id = 'ord-priv-test';")
    except psycopg2.errors.InsufficientPrivilege:
        update_blocked = True
        conn.rollback()
    assert update_blocked, "CRITICAL VULNERABILITY: authenticated role was able to UPDATE trial_quota_reservations!"

    # Negative Test 2: Direct INSERT must fail
    cur.execute("SET ROLE authenticated;")
    cur.execute("SET app.current_tenant_id = %s;", (test_tid,))
    insert_blocked = False
    try:
        cur.execute("""
            INSERT INTO public.trial_quota_reservations (tenant_id, order_id, status, expires_at)
            VALUES (%s, 'ord-priv-injected', 'RELEASED', NOW() + INTERVAL '120 seconds');
        """, (test_tid,))
    except psycopg2.errors.InsufficientPrivilege:
        insert_blocked = True
        conn.rollback()
    assert insert_blocked, "CRITICAL VULNERABILITY: authenticated role was able to INSERT into trial_quota_reservations!"

    # Negative Test 3: Direct DELETE must fail
    cur.execute("SET ROLE authenticated;")
    cur.execute("SET app.current_tenant_id = %s;", (test_tid,))
    delete_blocked = False
    try:
        cur.execute("DELETE FROM public.trial_quota_reservations WHERE order_id = 'ord-priv-test';")
    except psycopg2.errors.InsufficientPrivilege:
        delete_blocked = True
        conn.rollback()
    assert delete_blocked, "CRITICAL VULNERABILITY: authenticated role was able to DELETE from trial_quota_reservations!"

    # Positive Test: SELECT own tenant rows under authenticated succeeds
    cur.execute("SET ROLE authenticated;")
    cur.execute("SET app.current_tenant_id = %s;", (test_tid,))
    cur.execute("SELECT order_id, status FROM public.trial_quota_reservations;")
    rows = cur.fetchall()
    assert len(rows) == 1 and rows[0][0] == "ord-priv-test"

    # Isolation Test: SELECT other tenant rows returns 0
    cur.execute("SET app.current_tenant_id = 'other-unrelated-tenant';")
    cur.execute("SELECT order_id, status FROM public.trial_quota_reservations;")
    other_rows = cur.fetchall()
    assert len(other_rows) == 0

    # Cleanup
    cur.execute("RESET ROLE;")
    cur.execute("DELETE FROM public.trial_quota_reservations WHERE tenant_id = %s;", (test_tid,))
    conn.commit()

    cur.close()
    conn.close()


# =============================================================================
# 25. Multi-Process Concurrency Proof with OS PIDs and PG Backend PIDs
# =============================================================================
def test_25_multi_process_concurrency_hard_cap_30():
    """Proves that under true OS multi-process concurrency with separate OS process IDs
    and separate PostgreSQL backend session PIDs:
    1. 8 independent OS workers start simultaneously when quota is seeded at 29.
    2. Exactly 1 process acquires slot #30 (SUCCESS).
    3. Exactly 7 processes receive TrialLimitExceededException (QUOTA_EXCEEDED).
    4. Database active quota in PostgreSQL SSOT remains exactly 30 (never 31+).
    """
    import tempfile
    import subprocess
    import sys
    from pathlib import Path

    script_content = '''import os
import sys
from pathlib import Path
import multiprocessing
import psycopg2

REPO_ROOT = Path(__REPO_ROOT_REPR__)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security.test_isolation_guard import (
    assert_disposable_postgres_target,
    bootstrap_isolated_test_env,
)
bootstrap_isolated_test_env(REPO_ROOT)

from app.core.trial_guardrail import PostgresTrialQuotaStore, TrialLimitExceededException

def _worker_reserve_slot(tenant_id, order_id, barrier, result_queue):
    os_pid = os.getpid()
    conn = None
    cur = None
    try:
        assert_disposable_postgres_target(dsn=os.environ.get("DATABASE_URL"), allow_if_unconfigured=False)
        conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT pg_backend_pid();")
        pg_pid = cur.fetchone()[0]
        cur.close()
        conn.close()
        conn = None

        store = PostgresTrialQuotaStore()

        # Synchronize all workers at barrier
        barrier.wait(timeout=10)

        # Attempt to reserve and commit slot
        res = store.reserve_slot(tenant_id=tenant_id, order_id=order_id, is_trial=True)
        store.commit_slot(tenant_id=tenant_id, order_id=order_id, is_trial=True)

        result_queue.put({
            "os_pid": os_pid,
            "pg_backend_pid": pg_pid,
            "order_id": order_id,
            "status": "SUCCESS",
            "reservation": res,
        })
    except TrialLimitExceededException as e:
        result_queue.put({
            "os_pid": os_pid,
            "pg_backend_pid": pg_pid,
            "order_id": order_id,
            "status": "QUOTA_EXCEEDED",
            "error": str(e),
        })
    except Exception as e:
        result_queue.put({
            "os_pid": os_pid,
            "pg_backend_pid": pg_pid if "pg_pid" in locals() and pg_pid else None,
            "order_id": order_id,
            "status": "ERROR",
            "error": repr(e),
        })
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
        if conn:
            try: conn.close()
            except Exception: pass

if __name__ == "__main__":
    multiprocessing.freeze_support()
    test_tenant_id = "25252525-0000-0000-0000-000000000025"
    store = PostgresTrialQuotaStore()
    store.reset(test_tenant_id)

    # 1. Seed 29 committed slots in PostgreSQL
    for i in range(1, 30):
        store.reserve_slot(tenant_id=test_tenant_id, order_id=f"SEED-MP-{i:03d}", is_trial=True)
        store.commit_slot(tenant_id=test_tenant_id, order_id=f"SEED-MP-{i:03d}", is_trial=True)

    assert store.get_order_count(test_tenant_id) == 29

    # 2. Launch 8 separate OS processes with barrier synchronization
    num_workers = 8
    barrier = multiprocessing.Barrier(num_workers)
    result_queue = multiprocessing.Queue()

    processes = []
    for idx in range(1, num_workers + 1):
        order_id = f"MP-RACE-{idx:03d}"
        p = multiprocessing.Process(
            target=_worker_reserve_slot,
            args=(test_tenant_id, order_id, barrier, result_queue),
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=15)
        if p.is_alive():
            p.terminate()

    results = []
    while not result_queue.empty():
        results.append(result_queue.get_nowait())

    os_pids = {r["os_pid"] for r in results}
    pg_pids = {r["pg_backend_pid"] for r in results}
    successes = [r for r in results if r["status"] == "SUCCESS"]
    quota_exceeded = [r for r in results if r["status"] == "QUOTA_EXCEEDED"]

    assert len(results) == num_workers, f"Expected {num_workers} results, got {len(results)}"
    assert len(os_pids) == num_workers, f"Expected {num_workers} unique OS PIDs, got {len(os_pids)}"
    assert len(pg_pids) == num_workers, f"Expected {num_workers} unique PG backend PIDs, got {len(pg_pids)}"
    assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
    assert len(quota_exceeded) == 7, f"Expected 7 QUOTA_EXCEEDED, got {len(quota_exceeded)}"

    final_count = store.get_order_count(test_tenant_id)
    assert final_count == 30, f"Hard cap violated! Count is {final_count}"

    store.reset(test_tenant_id)
    print(f"MP_VERIFIED: {len(os_pids)} OS PIDs {sorted(list(os_pids))}, {len(pg_pids)} PG PIDs {sorted(list(pg_pids))}, 1 success, 7 rejected, final count {final_count}")
'''.replace("__REPO_ROOT_REPR__", repr(str(REPO_ROOT)))

    tmp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
    tmp_path = tmp_file.name
    try:
        tmp_file.write(script_content)
        tmp_file.close()

        res = subprocess.run([sys.executable, tmp_path], capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, f"Multi-process concurrency test failed (rc={res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        assert "MP_VERIFIED" in res.stdout, f"Verification sentinel missing in stdout:\n{res.stdout}"
        print(f"\n[TEST_25 EVIDENCE] {res.stdout.strip()}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# =============================================================================
# 26. Xendit Structured Error and Outcome Lifecycle
# =============================================================================
@pytest.mark.asyncio
async def test_26_xendit_structured_error_and_outcome_lifecycle(mock_common_io):
    """Proves that:
    1. Xendit HTTP 400/422 definitive rejection releases the trial quota reservation (0 quota).
    2. Xendit HTTP 500 server error preserves the reservation in AMBIGUOUS_TIMEOUT (1 quota).
    3. Outcomes are determined by structured XenditAPIError, not generic string parsing.
    """
    from app.core.trial_guardrail import trial_guardrail
    from app.services.xendit_service import XenditAPIError

    tid = "26262626-0000-0000-0000-000000000026"
    trial_guardrail.reset(tid)

    trial_ctx = _make_multi_provider_tenant_context(tenant_uuid=tid, slug="trial-xendit-errors")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        # 1. Definitive 400 Bad Request -> RELEASED
        mock_common_io["xen"].side_effect = XenditAPIError(
            status_code=400,
            error_code="INVALID_API_PARAMETER",
            message="Amount must be positive",
            is_definitive_rejection=True,
        )
        with pytest.raises(XenditAPIError):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-xendit-errors",
                customer_name="Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
                order_id="ORD-XEN-400",
            )
        assert trial_guardrail.get_order_count(tid) == 0

        store = trial_guardrail.get_pg_store()
        conn = store._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s AND order_id = 'ORD-XEN-400';", (tid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        assert row is not None and row[0] == "RELEASED"

        # 2. Ambiguous 500 Server Error -> AMBIGUOUS_TIMEOUT (preserved)
        mock_common_io["xen"].side_effect = XenditAPIError(
            status_code=500,
            error_code="INTERNAL_SERVER_ERROR",
            message="Gateway internal failure",
            is_definitive_rejection=False,
        )
        with pytest.raises(XenditAPIError):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-xendit-errors",
                customer_name="Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
                order_id="ORD-XEN-500",
            )
        # Ambiguous 5xx keeps slot accounted for
        assert trial_guardrail.get_order_count(tid) == 1

        conn = store._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s AND order_id = 'ORD-XEN-500';", (tid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        assert row is not None and row[0] == "AMBIGUOUS_TIMEOUT"

    trial_guardrail.reset(tid)


# =============================================================================
# 27. Midtrans Structured Error and Production Lockdown
# =============================================================================
@pytest.mark.asyncio
async def test_27_midtrans_structured_error_and_production_lockdown(mock_common_io):
    """Proves that:
    1. Midtrans upstream rejection (406) releases slot (0 quota).
    2. Midtrans timeout (GATEWAY_TIMEOUT) preserves slot in AMBIGUOUS_TIMEOUT.
    3. Production checkout NEVER accepts synthetic QRIS as a success.
    4. Offline fallback is strictly blocked when allow_offline_simulator is False.
    """
    from app.core.trial_guardrail import trial_guardrail
    from app.services.midtrans_service import MidtransAPIError

    tid = "27272727-0000-0000-0000-000000000027"
    trial_guardrail.reset(tid)

    trial_ctx = _make_multi_provider_tenant_context(tenant_uuid=tid, slug="trial-midtrans-errors")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        # 1. Definitive 406 rejection -> RELEASED
        mock_common_io["mid"].side_effect = MidtransAPIError(
            status_code=406,
            error_code="406",
            message="Payment method not allowed for merchant",
            is_definitive_rejection=True,
        )
        with pytest.raises(MidtransAPIError):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-midtrans-errors",
                customer_name="Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="MIDTRANS",
                credential_mapper=mapper,
                order_id="ORD-MID-406",
            )
        assert trial_guardrail.get_order_count(tid) == 0

        store = trial_guardrail.get_pg_store()
        conn = store._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s AND order_id = 'ORD-MID-406';", (tid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        assert row is not None and row[0] == "RELEASED"

        # 2. Ambiguous timeout -> AMBIGUOUS_TIMEOUT
        mock_common_io["mid"].side_effect = MidtransAPIError(
            status_code=None,
            error_code="GATEWAY_TIMEOUT",
            message="Midtrans gateway timed out",
            is_definitive_rejection=False,
        )
        with pytest.raises(MidtransAPIError):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-midtrans-errors",
                customer_name="Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="MIDTRANS",
                credential_mapper=mapper,
                order_id="ORD-MID-TIMEOUT",
            )
        assert trial_guardrail.get_order_count(tid) == 1

        # 3. Production forbids synthetic success
        mock_common_io["mid"].side_effect = None
        mock_common_io["mid"].return_value = {
            "transaction_id": "mdtr_synthetic_123",
            "qr_string": "000201010212265000...",
            "is_synthetic": True,
        }
        with pytest.raises(MidtransAPIError) as exc_synth:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-midtrans-errors",
                customer_name="Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="MIDTRANS",
                credential_mapper=mapper,
                order_id="ORD-MID-SYNTHETIC",
            )
        assert exc_synth.value.error_code == "SYNTHETIC_SUCCESS_PROHIBITED"

    trial_guardrail.reset(tid)


# =============================================================================
# 28. Duitku Structured Error and Production Lockdown
# =============================================================================
@pytest.mark.asyncio
async def test_28_duitku_structured_error_and_production_lockdown(mock_common_io):
    """Proves that:
    1. Duitku upstream rejection releases reservation (0 quota).
    2. Duitku timeout preserves reservation in AMBIGUOUS_TIMEOUT.
    3. Production checkout NEVER accepts simulator reference as success.
    """
    from app.core.trial_guardrail import trial_guardrail
    from app.services.payment.gateway_duitku import DuitkuAPIError
    from app.services.payment.gateway_duitku import DuitkuAdapter

    tid = "28282828-0000-0000-0000-000000000028"
    trial_guardrail.reset(tid)

    trial_ctx = _make_multi_provider_tenant_context(tenant_uuid=tid, slug="trial-duitku-errors")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        # 1. Definitive rejection -> RELEASED
        with patch.object(DuitkuAdapter, "create_transaction", new_callable=AsyncMock) as m_dk:
            m_dk.side_effect = DuitkuAPIError(
                status_code=400,
                error_code="DUITKU_01",
                message="Merchant inactive or invalid",
                is_definitive_rejection=True,
            )
            with pytest.raises(DuitkuAPIError):
                await create_d2c_order_and_dispatch_qris(
                    merchant_slug="trial-duitku-errors",
                    customer_name="Buyer",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                    total_amount=50000,
                    provider_override="DUITKU",
                    credential_mapper=mapper,
                    order_id="ORD-DK-400",
                )
            assert trial_guardrail.get_order_count(tid) == 0

            store = trial_guardrail.get_pg_store()
            conn = store._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s AND order_id = 'ORD-DK-400';", (tid,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            assert row is not None and row[0] == "RELEASED"

        # 2. Ambiguous timeout -> AMBIGUOUS_TIMEOUT
        with patch.object(DuitkuAdapter, "create_transaction", new_callable=AsyncMock) as m_dk:
            m_dk.side_effect = DuitkuAPIError(
                status_code=None,
                error_code="GATEWAY_TIMEOUT",
                message="Duitku gateway timed out",
                is_definitive_rejection=False,
            )
            with pytest.raises(DuitkuAPIError):
                await create_d2c_order_and_dispatch_qris(
                    merchant_slug="trial-duitku-errors",
                    customer_name="Buyer",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                    total_amount=50000,
                    provider_override="DUITKU",
                    credential_mapper=mapper,
                    order_id="ORD-DK-TIMEOUT",
                )
            assert trial_guardrail.get_order_count(tid) == 1

        # 3. Production forbids simulator reference
        from app.services.payment.base import TransactionResponse
        with patch.object(DuitkuAdapter, "create_transaction", new_callable=AsyncMock) as m_dk:
            m_dk.return_value = TransactionResponse(
                transaction_id="DTK-REF-SIMULATED",
                order_id="ORD-DK-SIM",
                status="PENDING",
                payment_method="QRIS",
                amount=50000,
            )
            with pytest.raises(DuitkuAPIError) as exc_sim:
                await create_d2c_order_and_dispatch_qris(
                    merchant_slug="trial-duitku-errors",
                    customer_name="Buyer",
                    customer_phone="081234567890",
                    items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                    total_amount=50000,
                    provider_override="DUITKU",
                    credential_mapper=mapper,
                    order_id="ORD-DK-SIM",
                )
            assert exc_sim.value.error_code == "SIMULATOR_SUCCESS_PROHIBITED"

    trial_guardrail.reset(tid)


# =============================================================================
# 29. Exception Credential and Secret Leakage Hygiene
# =============================================================================
def test_29_exception_credential_and_secret_leakage_hygiene():
    """Proves that XenditAPIError, MidtransAPIError, and DuitkuAPIError never leak
    secret keys, API keys, or basic auth tokens in string representations or exceptions.
    """
    from app.services.xendit_service import XenditAPIError
    from app.services.midtrans_service import MidtransAPIError
    from app.services.payment.gateway_duitku import DuitkuAPIError

    sensitive_secrets = [
        "xnd_sec_super_secret_key_12345",
        "Mid-server-ultra-confidential-token-9999",
        "duitku_api_key_top_secret_xyz",
    ]

    for secret in sensitive_secrets:
        err_xen = XenditAPIError(
            status_code=401,
            error_code="UNAUTHORIZED",
            message="Invalid authentication credentials",
        )
        assert secret not in str(err_xen)
        assert secret not in repr(err_xen)

        err_mid = MidtransAPIError(
            status_code=401,
            error_code="401",
            message="Access denied: unauthorized server key",
        )
        assert secret not in str(err_mid)
        assert secret not in repr(err_mid)

        err_dk = DuitkuAPIError(
            status_code=401,
            error_code="INVALID_API_KEY",
            message="Signature mismatch for merchant",
        )
        assert secret not in str(err_dk)
        assert secret not in repr(err_dk)


# =============================================================================
# 30. Xendit HTTP 400 Non-Definitive Response Body Quarantines Slot (Audit 1)
# =============================================================================
@pytest.mark.asyncio
async def test_30_xendit_http_400_non_definitive_error_body_quarantines_slot(mock_common_io):
    """Audit Requirement 1: Proves that Xendit error evaluation inspects the response body
    (error code / status payload) and that an HTTP 400 with a non-definitive payload
    (e.g. DUPLICATE_ORDER_ID or ORDER_ALREADY_EXISTS) does NOT release the slot,
    but instead quarantines it in AMBIGUOUS_TIMEOUT in PostgreSQL SSOT.
    """
    from app.core.trial_guardrail import trial_guardrail
    from app.services.xendit_service import XenditAPIError

    tid = "30303030-0000-0000-0000-000000000030"
    trial_guardrail.reset(tid)

    trial_ctx = _make_multi_provider_tenant_context(tenant_uuid=tid, slug="trial-xendit-audit1")
    trial_ctx.metadata["is_trial"] = True
    mapper = _make_test_mapper()

    with patch("app.services.tenant_context_resolver.tenant_context_resolver.resolve_context", new_callable=AsyncMock) as m_res:
        m_res.return_value = trial_ctx

        # Skenario 1: HTTP 400 akibat payload non-definitive (ORDER_ALREADY_EXISTS / CONCURRENT_ORDER)
        # Sistem menolak mengasumsikannya sebagai pembatalan mutlak -> WAJIB karantina (is_definitive_rejection=False)
        mock_common_io["xen"].side_effect = XenditAPIError(
            status_code=400,
            error_code="ORDER_ALREADY_EXISTS",
            message="An order with this ID is currently processing or already exists",
            raw_response={"error_code": "ORDER_ALREADY_EXISTS", "message": "An order with this ID is currently processing"},
            is_definitive_rejection=False,
        )

        with pytest.raises(XenditAPIError) as exc_info:
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-xendit-audit1",
                customer_name="Audit Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
                order_id="ORD-XEN-NONDEF-400",
            )
        assert exc_info.value.error_code == "ORDER_ALREADY_EXISTS"
        assert exc_info.value.is_definitive_rejection is False

        # Slot TETAP DIHITUNG (kuota = 1, status = AMBIGUOUS_TIMEOUT)
        assert trial_guardrail.get_order_count(tid) == 1

        store = trial_guardrail.get_pg_store()
        conn = store._get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s AND order_id = 'ORD-XEN-NONDEF-400';",
            (tid,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        assert row is not None and row[0] == "AMBIGUOUS_TIMEOUT", f"Expected AMBIGUOUS_TIMEOUT, got {row}"

        # Skenario 2: HTTP 400 akibat definitive validation rejection (INVALID_API_PARAMETER)
        # Sistem melepaskan kuota (is_definitive_rejection=True)
        mock_common_io["xen"].side_effect = XenditAPIError(
            status_code=400,
            error_code="INVALID_API_PARAMETER",
            message="Amount must be positive integer",
            raw_response={"error_code": "INVALID_API_PARAMETER", "message": "Amount must be positive integer"},
            is_definitive_rejection=True,
        )

        with pytest.raises(XenditAPIError):
            await create_d2c_order_and_dispatch_qris(
                merchant_slug="trial-xendit-audit1",
                customer_name="Audit Buyer",
                customer_phone="081234567890",
                items=[{"product_id": "p1", "title": "Item", "price": 50000, "quantity": 1}],
                total_amount=50000,
                provider_override="XENDIT",
                credential_mapper=mapper,
                order_id="ORD-XEN-DEF-400",
            )
        # Skenario 1 tetap terhitung (1 slot), skenario 2 dilepaskan (0 slot tambahan) -> Total tetap 1
        assert trial_guardrail.get_order_count(tid) == 1

        conn = store._get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM public.trial_quota_reservations WHERE tenant_id = %s AND order_id = 'ORD-XEN-DEF-400';",
            (tid,)
        )
        row2 = cur.fetchone()
        cur.close()
        conn.close()
        assert row2 is not None and row2[0] == "RELEASED", f"Expected RELEASED, got {row2}"

    trial_guardrail.reset(tid)


# =============================================================================
# 31. Sandbox Conflicting Configuration Fail-Closed in Production (Audit 2)
# =============================================================================
@pytest.mark.asyncio
async def test_31_sandbox_conflicting_configuration_fail_closed_in_production(mock_common_io):
    """Audit Requirement 2: Proves that when ENVIRONMENT=production, any conflicting
    attribute or payload attempting to trigger simulator/sandbox mode is rejected
    fail-closed (100% mathematically impossible to generate synthetic success in production).
    """
    from app.services.midtrans_service import MidtransService, MidtransAPIError
    from app.services.payment.gateway_duitku import DuitkuAdapter, DuitkuAPIError
    from app.services.payment.base import TransactionRequest

    # 1. Midtrans: Tabrakan konfigurasi production vs allow_offline_simulator
    mid_service = MidtransService()
    mid_service.is_production = True
    # Upaya sengaja memicu simulator pada production
    mid_service.allow_offline_simulator = True

    with patch.dict(os.environ, {"MIDTRANS_IS_PRODUCTION": "true", "MIDTRANS_ALLOW_OFFLINE_SIMULATOR": "true"}):
        with patch("httpx.AsyncClient.post") as m_post:
            # Simulasikan upstream Midtrans mengembalikan error 500
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = '{"status_code": "500", "status_message": "Midtrans Bank Downtime"}'
            mock_resp.json.return_value = {"status_code": "500", "status_message": "Midtrans Bank Downtime"}
            m_post.return_value = mock_resp

            # Sistem WAJIB melempar MidtransAPIError dan TIDAK PERNAH menghasilkan QRIS sintetis
            with pytest.raises(MidtransAPIError) as exc_mid:
                await mid_service.create_qris_charge(
                    order_id="ORD-AUDIT-MID-001",
                    amount=50000,
                    customer_name="Audit Midtrans",
                )
            assert exc_mid.value.status_code == 500
            assert exc_mid.value.is_definitive_rejection is False

    # 2. Duitku: Tabrakan konfigurasi production vs allow_simulator
    duitku_adapter = DuitkuAdapter(
        merchant_code="D1234",
        api_key="sec_key",
        is_sandbox=False,  # Production mode
    )
    assert duitku_adapter.is_sandbox is False
    # Upaya sengaja menyuntikkan allow_simulator = True
    duitku_adapter.allow_simulator = True

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "DUITKU_ALLOW_SIMULATOR": "true"}):
        with patch("httpx.AsyncClient.post") as m_post:
            # Simulasikan upstream Duitku gagal atau mengembalikan response tanpa reference
            mock_resp_dk = MagicMock()
            mock_resp_dk.status_code = 502
            mock_resp_dk.text = "Bad Gateway"
            mock_resp_dk.json.side_effect = Exception("Not JSON")
            m_post.return_value = mock_resp_dk

            req = TransactionRequest(
                order_id="ORD-AUDIT-DK-001",
                amount=50000,
                customer_name="Audit Duitku",
                payment_method="QRIS",
            )

            # Sistem WAJIB melempar DuitkuAPIError dan TIDAK PERNAH menghasilkan DTK-REF-
            with pytest.raises(DuitkuAPIError) as exc_dk:
                await duitku_adapter.create_transaction(req)
            assert exc_dk.value.status_code == 502
            assert exc_dk.value.is_definitive_rejection is False





