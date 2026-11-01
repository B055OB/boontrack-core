"""Regression tests for P0 JWT Trust Policy, Payout & Bank Account Identity Boundary, and Disbursement Lock."""
import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.jwt_secret import (
    encode_jwt_token_strict,
    get_core_jwt_audience,
    get_core_jwt_issuer,
    get_supabase_jwt_audience,
    get_supabase_jwt_issuer,
    verify_jwt_token_strict,
)
from app.main import app
from app.routes.affiliate_auth import generate_jwt_token
from app.services.partner_service import partner_service


class TestJwtTrustPolicy(unittest.TestCase):
    """P0 Regression Suite: Complete JWT Trust Policy & Strict Realm Separation."""

    def setUp(self):
        self.client = TestClient(app)

    def test_jwt_missing_exp_rejected(self):
        """Tokens missing mandatory `exp` claim must be rejected (HTTP 401 & ValueError)."""
        token_no_exp = generate_jwt_token({"sub": "aff_test_001", "role": "AFFILIATE"})
        with self.assertRaises(ValueError) as ctx:
            verify_jwt_token_strict(token_no_exp, realm="core")
        self.assertIn("exp", str(ctx.exception).lower())

        resp = self.client.get("/api/v1/affiliate/me", headers={"Authorization": f"Bearer {token_no_exp}"})
        self.assertEqual(resp.status_code, 401)

    def test_jwt_expired_token_rejected(self):
        """Expired tokens must be rejected (HTTP 401 & ValueError)."""
        expired_token = generate_jwt_token(
            {
                "sub": "aff_test_001",
                "role": "AFFILIATE",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
            }
        )
        with self.assertRaises(ValueError) as ctx:
            verify_jwt_token_strict(expired_token, realm="core")
        self.assertIn("expired", str(ctx.exception).lower())

        resp = self.client.get("/api/v1/affiliate/me", headers={"Authorization": f"Bearer {expired_token}"})
        self.assertEqual(resp.status_code, 401)

    def test_jwt_wrong_issuer_rejected(self):
        """Tokens with wrong or missing `iss` claim must be rejected (HTTP 401)."""
        wrong_iss_token = generate_jwt_token(
            {
                "sub": "aff_test_001",
                "role": "AFFILIATE",
                "iss": "https://evil-issuer.example.com",
                "aud": get_core_jwt_audience(),
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        )
        with self.assertRaises(ValueError) as ctx:
            verify_jwt_token_strict(wrong_iss_token, realm="core")
        self.assertIn("issuer", str(ctx.exception).lower())

        missing_iss_token = generate_jwt_token(
            {
                "sub": "aff_test_001",
                "role": "AFFILIATE",
                "iss": None,
                "aud": get_core_jwt_audience(),
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        )
        for tok in (wrong_iss_token, missing_iss_token):
            resp = self.client.get("/api/v1/affiliate/me", headers={"Authorization": f"Bearer {tok}"})
            self.assertEqual(resp.status_code, 401)

    def test_jwt_wrong_audience_rejected(self):
        """Tokens with wrong or missing `aud` claim must be rejected (HTTP 401)."""
        wrong_aud_token = generate_jwt_token(
            {
                "sub": "aff_test_001",
                "role": "AFFILIATE",
                "iss": get_core_jwt_issuer(),
                "aud": "wrong-audience-target",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        )
        with self.assertRaises(ValueError) as ctx:
            verify_jwt_token_strict(wrong_aud_token, realm="core")
        self.assertIn("audience", str(ctx.exception).lower())

        missing_aud_token = generate_jwt_token(
            {
                "sub": "aff_test_001",
                "role": "AFFILIATE",
                "iss": get_core_jwt_issuer(),
                "aud": None,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        )
        for tok in (wrong_aud_token, missing_aud_token):
            resp = self.client.get("/api/v1/affiliate/me", headers={"Authorization": f"Bearer {tok}"})
            self.assertEqual(resp.status_code, 401)



    def test_jwt_invalid_signature_and_alg_none_rejected(self):
        """Tokens with invalid signature, tampered payload, or alg='none' must be rejected (HTTP 401)."""
        forged_token = encode_jwt_token_strict(
            {
                "sub": "aff_test_001",
                "role": "AFFILIATE",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            realm="core",
            secret_override="attacker_forged_secret_key_99999",
        )
        with self.assertRaises(ValueError) as ctx:
            verify_jwt_token_strict(forged_token, realm="core")
        self.assertIn("signature", str(ctx.exception).lower())

        valid_token = generate_jwt_token(
            {
                "sub": "aff_low_priv",
                "role": "AFFILIATE",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        )
        parts = valid_token.split(".")
        tampered_body = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sub": "aff_victim_admin",
                    "role": "AFFILIATE",
                    "iss": get_core_jwt_issuer(),
                    "aud": get_core_jwt_audience(),
                    "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
                }
            ).encode()
        ).rstrip(b"=").decode()
        tampered_token = f"{parts[0]}.{tampered_body}.{parts[2]}"

        none_hdr = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        alg_none_token = f"{none_hdr}.{tampered_body}.sig"

        for bad_tok in (forged_token, tampered_token, alg_none_token):
            resp = self.client.get("/api/v1/affiliate/me", headers={"Authorization": f"Bearer {bad_tok}"})
            self.assertEqual(resp.status_code, 401)

    def test_jwt_cross_realm_rejections(self):
        """Supabase tokens must be rejected by Core realm and Core tokens must be rejected by Supabase realm."""
        exp_ts = datetime.now(timezone.utc) + timedelta(hours=1)
        supabase_token = encode_jwt_token_strict(
            {
                "sub": "supa_uid_001",
                "role": "authenticated",
                "iss": get_supabase_jwt_issuer(),
                "aud": get_supabase_jwt_audience(),
                "exp": exp_ts,
            },
            realm="supabase",
        )
        supa_decoded = verify_jwt_token_strict(supabase_token, realm="supabase")
        self.assertEqual(supa_decoded["sub"], "supa_uid_001")

        with self.assertRaises(ValueError):
            verify_jwt_token_strict(supabase_token, realm="core")

        self.assertEqual(
            self.client.get("/api/v1/affiliate/me", headers={"Authorization": f"Bearer {supabase_token}"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.get("/api/v1/partners/bank-account", headers={"Authorization": f"Bearer {supabase_token}"}).status_code,
            401,
        )

        core_token = encode_jwt_token_strict(
            {
                "sub": "core_aff_001",
                "role": "AFFILIATE",
                "iss": get_core_jwt_issuer(),
                "aud": get_core_jwt_audience(),
                "exp": exp_ts,
            },
            realm="core",
        )
        core_decoded = verify_jwt_token_strict(core_token, realm="core")
        self.assertEqual(core_decoded["sub"], "core_aff_001")

        with self.assertRaises(ValueError):
            verify_jwt_token_strict(core_token, realm="supabase")

        hybrid_token = encode_jwt_token_strict(
            {
                "sub": "hybrid_001",
                "iss": get_supabase_jwt_issuer(),
                "aud": get_supabase_jwt_audience(),
                "exp": exp_ts,
            },
            realm="core",
        )
        with self.assertRaises(ValueError):
            verify_jwt_token_strict(hybrid_token, realm="core")
        with self.assertRaises(ValueError):
            verify_jwt_token_strict(hybrid_token, realm="supabase")

    @patch("app.routes.affiliate_auth.supabase")
    def test_jwt_request_state_user_cannot_be_forged_without_cryptographic_verification(self, mock_supabase):
        """Blocker 1: Untrusted/forged `request.state.user` must be rejected (401) unless cryptographically verified."""
        import asyncio
        from types import SimpleNamespace
        from fastapi import HTTPException
        from app.routes.affiliate_auth import get_current_affiliate

        # 1. Forged request.state.user without a valid cryptographic token or sentinel -> 401
        fake_request = SimpleNamespace(
            state=SimpleNamespace(user={"sub": "forged_victim_id", "role": "AFFILIATE"}),
            cookies={},
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_affiliate(fake_request, authorization=None))
        self.assertEqual(ctx.exception.status_code, 401)

        # 2. External client attempting to spoof state via headers without Bearer token -> 401
        spoof_resp = self.client.get(
            "/api/v1/affiliate/me",
            headers={
                "X-User": json.dumps({"sub": "forged_victim_id", "role": "AFFILIATE"}),
                "X-Request-State-User": "forged_victim_id",
                "X-Authenticated-User": "forged_victim_id",
            },
        )
        self.assertEqual(spoof_resp.status_code, 401)

        # 3. Pre-existing unverified request.state.user is ignored and overwritten when a valid Bearer JWT is supplied
        mock_t = MagicMock()
        mock_t.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "real_verified_aff",
                "name": "Real Affiliate",
                "role": "AFFILIATE",
                "status": "ACTIVE",
            }
        ]
        mock_supabase.table.return_value = mock_t

        real_token = generate_jwt_token(
            {
                "sub": "real_verified_aff",
                "role": "AFFILIATE",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        )
        tampered_state_req = SimpleNamespace(
            state=SimpleNamespace(user={"sub": "spoofed_other_aff", "role": "AFFILIATE"}),
            cookies={},
        )
        resolved_aff = asyncio.run(
            get_current_affiliate(tampered_state_req, authorization=f"Bearer {real_token}")
        )
        self.assertEqual(resolved_aff["id"], "real_verified_aff")
        self.assertEqual(tampered_state_req.state.user["sub"], "real_verified_aff")



class TestPayoutDisbursementLock(unittest.TestCase):
    """P0 Regression Suite: Payout Disbursement Lock & Complete Payout/Bank Identity Boundary."""

    def setUp(self):
        self.client = TestClient(app)
        partner_service._memory_partners.clear()
        partner_service._memory_bank_accounts.clear()
        partner_service._memory_payouts.clear()

        self.partner_id = "partner-auth-001"
        partner_service._memory_partners[self.partner_id] = {
            "id": self.partner_id,
            "name": "Mitra Resmi",
            "phone": "6281234567800",
            "email": "mitra@boontrack.com",
            "role": "AFFILIATE",
            "ref_code": "MITRA001",
            "is_ref_customized": False,
            "status": "ACTIVE",
        }
        self.valid_token = generate_jwt_token(
            {
                "sub": self.partner_id,
                "role": "AFFILIATE",
                "exp": datetime.now(timezone.utc) + timedelta(hours=2),
            }
        )
        self.auth_headers = {"Authorization": f"Bearer {self.valid_token}"}

    def test_payout_settle_is_locked(self):
        with patch("app.main.PayoutService") as svc:
            resp = self.client.post("/payout/settle", json={"affiliate_code": "ANY", "notes": "x"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"], "PAYOUT_DISBURSEMENT_LOCKED")
        svc.assert_not_called()

    def test_manager_mark_paid_is_locked(self):
        with patch("app.routes.partner_routes.partner_service") as svc:
            resp_put = self.client.put(
                "/api/v1/manager/payouts/any-id/mark-paid",
                json={"proof_attachment_url": "https://example.com/p.jpg"},
            )
            resp_post = self.client.post(
                "/api/v1/manager/payouts/any-id/mark-paid",
                json={"proof_attachment_url": "https://example.com/p.jpg"},
            )
        self.assertEqual(resp_put.status_code, 403)
        self.assertEqual(resp_put.json()["error"], "PAYOUT_DISBURSEMENT_LOCKED")
        self.assertEqual(resp_post.status_code, 403)
        self.assertEqual(resp_post.json()["error"], "PAYOUT_DISBURSEMENT_LOCKED")
        svc.mark_payout_as_paid.assert_not_called()

    def test_payout_and_bank_routes_reject_unauthenticated_and_legacy_aliases(self):
        """All payout, bank account, slug, and legacy alias routes must reject unauthenticated calls (401)."""
        bank_payload = {
            "bank_name": "BCA",
            "bank_account_number": "1234567890",
            "bank_account_holder": "MITRA RESMI",
            "affiliate_id": self.partner_id,
        }
        for method, path in (
            ("PATCH", "/payout-account"),
            ("POST", "/payout-account"),
            ("POST", "/update-bank"),
            ("PATCH", "/api/v1/affiliate/payout-account"),
            ("POST", "/api/v1/affiliate/payout-account"),
            ("PATCH", "/api/v1/auth/affiliate/payout-account"),
            ("POST", "/api/v1/auth/affiliate/payout-account"),
            ("POST", "/api/v1/auth/affiliate/update-bank"),
        ):
            resp = self.client.request(method, path, json=bank_payload)
            self.assertEqual(resp.status_code, 401, f"Expected 401 on {method} {path}")

        slug_payload = {"new_slug": "mitra-baru", "affiliate_id": self.partner_id}
        for method, path in (
            ("PATCH", "/slug"),
            ("POST", "/slug"),
            ("PATCH", "/api/v1/affiliate/slug"),
            ("POST", "/api/v1/affiliate/slug"),
            ("PATCH", "/api/v1/auth/affiliate/slug"),
            ("POST", "/api/v1/auth/affiliate/slug"),
        ):
            resp = self.client.request(method, path, json=slug_payload)
            self.assertEqual(resp.status_code, 401, f"Expected 401 on {method} {path}")

        self.assertEqual(self.client.get(f"/api/v1/partners/bank-account?partner_id={self.partner_id}").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/v1/partners/bank-account",
                json={"bank_name": "BCA", "account_number": "1234567890", "account_holder_name": "Mitra", "partner_id": self.partner_id},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.put("/api/v1/partners/claim-ref-slug", json={"slug": "CUSTOM01", "partner_id": self.partner_id}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/api/v1/partners/payouts/request", json={"amount": 100000, "partner_id": self.partner_id}).status_code,
            401,
        )

    @patch("app.routes.affiliate_auth.supabase")
    def test_payout_rejects_client_supplied_affiliate_ids_and_enforces_allowlist(self, mock_supabase):
        """Authenticated callers supplying client-side affiliate_id/partner_id or non-allowlisted fields are rejected."""
        mock_t = MagicMock()
        mock_t.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": self.partner_id,
                "name": "Mitra Resmi",
                "phone": "6281234567800",
                "role": "AFFILIATE",
                "status": "ACTIVE",
                "referral_code": "mitra001",
                "is_ref_customized": False,
            }
        ]
        mock_t.select.return_value.ilike.return_value.execute.return_value.data = []
        mock_t.update.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": self.partner_id,
                "bank_name": "BCA",
                "bank_account_number": "8888999900",
                "bank_account_holder": "MITRA RESMI",
                "is_bank_verified": False,
            }
        ]
        mock_supabase.table.return_value = mock_t

        idor_bank_resp = self.client.patch(
            "/api/v1/affiliate/payout-account",
            json={
                "affiliate_id": "victim-affiliate-999",
                "bank_name": "BCA",
                "bank_account_number": "8888999900",
                "bank_account_holder": "ATTACKER",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(idor_bank_resp.status_code, 403)

        unauth_field_resp = self.client.patch(
            "/api/v1/affiliate/payout-account",
            json={
                "bank_name": "BCA",
                "bank_account_number": "8888999900",
                "bank_account_holder": "MITRA RESMI",
                "is_bank_verified": True,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(unauth_field_resp.status_code, 400)

        valid_bank_resp = self.client.patch(
            "/api/v1/affiliate/payout-account",
            json={
                "bank_name": "BCA",
                "bank_account_number": "8888999900",
                "bank_account_holder": "MITRA RESMI",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(valid_bank_resp.status_code, 200)
        self.assertFalse(valid_bank_resp.json()["affiliate"].get("is_bank_verified", True))

        idor_slug_resp = self.client.patch(
            "/api/v1/affiliate/slug",
            json={"new_slug": "hijack-slug", "affiliate_id": "victim-affiliate-999"},
            headers=self.auth_headers,
        )
        self.assertEqual(idor_slug_resp.status_code, 403)

        extra_slug_resp = self.client.patch(
            "/api/v1/affiliate/slug",
            json={"new_slug": "valid-slug", "commission_rate": 50.0},
            headers=self.auth_headers,
        )
        self.assertEqual(extra_slug_resp.status_code, 400)

        self.assertEqual(
            self.client.post(
                "/api/v1/partners/bank-account",
                json={
                    "bank_name": "BCA",
                    "account_number": "111222333",
                    "account_holder_name": "Mitra",
                    "partner_id": "other-partner",
                },
                headers=self.auth_headers,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/partners/bank-account",
                headers={**self.auth_headers, "X-Partner-Id": "other-partner"},
            ).status_code,
            403,
        )

        self.client.post(
            "/api/v1/partners/bank-account",
            json={"bank_name": "BCA", "account_number": "111222333", "account_holder_name": "Mitra Resmi"},
            headers=self.auth_headers,
        )
        payout_resp = self.client.post(
            "/api/v1/partners/payouts/request",
            json={"amount": 100000},
            headers=self.auth_headers,
        )
        self.assertEqual(payout_resp.status_code, 200)
        payout_id = payout_resp.json()["payout"]["id"]
        self.assertEqual(payout_resp.json()["payout"]["snapshot_account_number"], "111222333")

        self.client.post(
            "/api/v1/partners/bank-account",
            json={"bank_name": "MANDIRI", "account_number": "999888777", "account_holder_name": "Mitra Baru"},
            headers=self.auth_headers,
        )
        stored_payout = partner_service._memory_payouts[payout_id]
        self.assertEqual(stored_payout["snapshot_bank_name"], "BCA")
        self.assertEqual(stored_payout["snapshot_account_number"], "111222333")
        self.assertEqual(stored_payout["bank_name"], "BCA")
        self.assertEqual(stored_payout["account_number"], "111222333")




if __name__ == "__main__":
    unittest.main()
