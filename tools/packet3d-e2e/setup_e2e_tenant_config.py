#!/usr/bin/env python3
"""tools/packet3d-e2e/setup_e2e_tenant_config.py
Packet 3D Step 3 (Terminal 5 / Account 5):
Configures ONLY disposable PG 17 tenant metadata (`onlineboost` payment_config + credential_profiles
using env:// secret pointers — ZERO plaintext secrets, ZERO raw-SQL seeded commerce orders!)
and prints ephemeral disposable test credentials (PostgREST HS256 JWTs, Ed25519 Provenance Keyring,
Internal Payment HMAC Keyring) into a scratch env JSON file for the E2E runner.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import psycopg2
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PGRST_JWT_SECRET = "p3d-e2e-disposable-jwt-secret-32chars-minimum-0001"
ONLINEBOOST_TENANT_UUID = "00000000-0000-0000-0000-000000000001"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_hs256_jwt(role: str, secret: str) -> str:
    now = int(time.time())
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = b64url(
        json.dumps(
            {"role": role, "iss": "supabase", "iat": now, "exp": now + 86400},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    sig = b64url(hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("utf-8"), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def main() -> int:
    dsn = sys.argv[1] if len(sys.argv) > 1 else "postgresql://postgres:p3d_disposable_pw@127.0.0.1:15432/boontrack_p3d_e2e"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(r"C:\Users\Alldy\.gemini\antigravity\brain\1c58429a-22f8-49ec-b556-3793835631e2\scratch\p3d_e2e_env.json")

    # 1. Configure onlineboost tenant payment_config + credential_profiles (ZERO plaintext secrets, ZERO orders seeded!)
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT metadata FROM public.tenants WHERE id = %s;", (ONLINEBOOST_TENANT_UUID,))
            row = cur.fetchone()
            assert row is not None, "onlineboost tenant not found after clean migration replay!"
            meta = dict(row[0] or {})
            meta["payment_config"] = {
                "rail": "NATIVE_PG",
                "mode": "NATIVE_PG",
                "provider": "XENDIT",
                "active_provider": "XENDIT",
                "channel": "DYNAMIC_QRIS",
                "api_credentials": {
                    "secret_ref": "env://XENDIT_SECRET_KEY",
                    "callback_token_ref": "env://XENDIT_CALLBACK_TOKEN",
                },
                "credential_profiles": {
                    "cred_ob_xendit_sandbox": {
                        "credential_profile_id": "cred_ob_xendit_sandbox",
                        "canonical_tenant_id": ONLINEBOOST_TENANT_UUID,
                        "provider": "XENDIT",
                        "verification_method": "XENDIT_CALLBACK_TOKEN",
                        "expected_provider_account_id": "xnd_biz_onlineboost_sandbox",
                        "environment": "sandbox",
                        "profile_status": "ACTIVE",
                        "updated_at_utc": "2026-11-23T00:00:00Z",
                        "verification_secrets": [
                            {
                                "secret_version_id": "xnd_cb_v1",
                                "secret_ref": "env://XENDIT_CALLBACK_TOKEN",
                                "status": "ACTIVE",
                                "created_at_utc": "2026-11-23T00:00:00Z",
                            }
                        ],
                    }
                },
            }
            cur.execute(
                "UPDATE public.tenants SET metadata = %s::jsonb WHERE id = %s;",
                (json.dumps(meta), ONLINEBOOST_TENANT_UUID),
            )
            # Confirm ZERO commerce orders exist in public.orders before E2E starts
            cur.execute("SELECT COUNT(*) FROM public.orders;")
            order_count = cur.fetchone()[0]
            assert order_count == 0, f"Expected 0 pre-existing orders, found {order_count}"
        conn.commit()
    finally:
        conn.close()

    # 2. Mint ephemeral Ed25519 Provenance Keypair (private ONLY in Core, public ONLY in Inbox!)
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    ).hex()
    pub_hex = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()

    prov_private_keyring = {
        "p3d-e2e-ed25519-v1": {
            "private_key_hex": priv_hex,
            "status": "ACTIVE",
        }
    }
    prov_public_keyring = {
        "p3d-e2e-ed25519-v1": {
            "public_key_hex": pub_hex,
            "status": "ACTIVE",
        }
    }

    hmac_secret = "p3d_e2e_ephemeral_internal_hmac_secret_key_64chars_0123456789abcdef"
    hmac_keyring = {
        "p3d-e2e-hmac-v1": {
            "key_id": "p3d-e2e-hmac-v1",
            "secret": hmac_secret,
            "status": "ACTIVE",
            "bound_principal": "service:core:payment_outbox_dispatcher",
            "bound_tenant_id": ONLINEBOOST_TENANT_UUID,
        }
    }

    env_bundle = {
        "ONLINEBOOST_TENANT_UUID": ONLINEBOOST_TENANT_UUID,
        "DATABASE_URL": dsn,
        "REDIS_URL": "redis://127.0.0.1:16379/0",
        "SUPABASE_URL": "http://127.0.0.1:18080",
        "SUPABASE_ANON_KEY": mint_hs256_jwt("anon", PGRST_JWT_SECRET),
        "SUPABASE_SERVICE_ROLE_KEY": mint_hs256_jwt("service_role", PGRST_JWT_SECRET),
        "XENDIT_API_URL": "http://127.0.0.1:18095",
        "XENDIT_ENV": "sandbox",
        "XENDIT_SECRET_KEY": "xnd_development_p3d_e2e_local_contract_key",
        "XENDIT_CALLBACK_TOKEN": "xnd_cb_token_p3d_e2e_0001",
        "XENDIT_BUSINESS_ID": "xnd_biz_onlineboost_sandbox",
        "PAYMENT_INTERNAL_HMAC_KEYRING_JSON": json.dumps(hmac_keyring),
        "PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON": json.dumps(prov_private_keyring),
        "PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON": json.dumps(prov_public_keyring),
        "APP_MASTER_KEY": "p3d_e2e_prohibited_master_key_do_not_accept",
        "EVOLUTION_API_KEY": "p3d_e2e_mock_evolution_key",
    }
    out_path.write_text(json.dumps(env_bundle, indent=2), encoding="utf-8")
    print(f"[E2E_SETUP_OK] Tenant onlineboost configured (env:// refs only); orders_count=0; env written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
