"""
tests/api/test_aiohttp_upload_security.py
=========================================
Dual-Server Parity Test Suite (aiohttp Runner on Railway)
Security Remediation for GitHub Issue #27 / PR #28:
"security(core): enforce signed merchant authorization on tenant upload route"

Enforces strict security parity between FastAPI and aiohttp for POST /api/v1/upload:
  1.  Positive: Authenticated merchant -> HTTP 201 Created with scoped namespace
  2.  Negative: Anonymous / missing Authorization -> HTTP 401
  3.  Negative: Malformed JWT token -> HTTP 401
  4.  Negative: Expired JWT token -> HTTP 401
  5.  Negative: Forged signature -> HTTP 401
  6.  Negative: Unauthorized merchant role (customer, user, guest) -> HTTP 403
  7.  Negative: Missing tenant claim -> HTTP 401
  8.  Negative: user_metadata-only tenant (untrusted) -> HTTP 401
  9.  Negative: Merchant principal without active tenant membership -> HTTP 403
  10. Negative: Revoked merchant membership -> HTTP 403
  11. Negative: Deactivated tenant -> HTTP 403
  12. Negative: X-Tenant-ID header spoofing -> HTTP 403
  13. Negative: X-Tenant-Slug header spoofing -> HTTP 403
  14. Negative: FormData tenant_id injection -> HTTP 403
  15. Negative: Query param tenant_id spoofing -> HTTP 403
  16. Negative: Path traversal in folder (..) -> HTTP 403
  17. Negative: Tenant-prefix lookalike (tenant-alpha-evil) -> HTTP 403
  18. Negative: URL-encoded path traversal (%2e%2e) -> HTTP 403
  19. Negative: Backslash separator in folder -> HTTP 403
  20. Negative: Magic-byte spoofing (Windows PE exe disguised as PNG) -> HTTP 422
  21. Negative: Corrupted image binary -> HTTP 422
  22. Negative: Oversized Content-Length pre-check -> HTTP 413
  23. Negative: Streamed / chunked oversized file abort -> HTTP 413
"""

import io
import re
import time
from typing import Optional
from unittest.mock import patch
from datetime import datetime, timezone
from PIL import Image
from fastapi import HTTPException
from app.core.subscription_guard import SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD

from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web, FormData
from app.core.server import create_web_app
from app.core.jwt_secret import encode_jwt_token_strict
from app.routes.media_routes import (
    register_merchant_membership,
    revoke_merchant_membership,
    clear_merchant_membership_registry,
)


def create_valid_test_image(format: str = "PNG", size: tuple = (200, 200), color: tuple = (0, 128, 255)) -> io.BytesIO:
    """Generates valid image bytes with authoritative magic bytes for JPEG / PNG."""
    buf = io.BytesIO()
    mode = "RGBA" if format.upper() == "PNG" else "RGB"
    img = Image.new(mode, size, color)
    img.save(buf, format=format)
    buf.seek(0)
    return buf


def make_signed_merchant_token(
    tenant_id: str = "tenant-alpha-001",
    merchant_id: str = "merch_owner@alpha.com",
    role: str = "merchant",
    expires_in_seconds: int = 3600,
    realm: str = "core",
    extra_claims: Optional[dict] = None,
    register_membership: bool = True,
) -> str:
    """Creates a cryptographically signed JWT token matching production trust policy."""
    now = int(time.time())
    payload = {
        "sub": merchant_id,
        "merchant_id": merchant_id,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_id,
        "role": role,
        "exp": now + expires_in_seconds,
    }
    if extra_claims:
        payload.update(extra_claims)
    if register_membership:
        register_merchant_membership(merchant_id=merchant_id, tenant_id=tenant_id, is_active=True, role=role)
    return encode_jwt_token_strict(payload, realm=realm)


class TestAioHttpUploadSecurityParity(AioHTTPTestCase):
    """Authoritative test suite verifying aiohttp runner security parity with FastAPI."""

    async def get_application(self):
        return create_web_app()

    @unittest_run_loop
    async def test_aiohttp_positive_verified_tenant(self):
        """1. Positive: Signed merchant auth succeeds on aiohttp with HTTP 201."""
        tenant_id = "tenant-alpha-001"
        merchant_id = "merch_owner@alpha.com"
        token = make_signed_merchant_token(tenant_id=tenant_id, merchant_id=merchant_id)

        img_data = create_valid_test_image(format="JPEG", size=(200, 200))
        form = FormData()
        form.add_field("file", img_data.read(), filename="product_banner.jpg", content_type="image/jpeg")

        now = datetime.now(timezone.utc)
        expected_year = now.strftime("%Y")
        expected_month = now.strftime("%m")

        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status, 201)
        data = await resp.json()

        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("tenant_id"), tenant_id)
        self.assertEqual(data.get("merchant_id"), merchant_id)

        storage_path = data.get("storage_path") or data.get("path", "").lstrip("/")
        expected_prefix = f"tenants/{tenant_id}/uploads/{expected_year}/{expected_month}/"
        self.assertTrue(
            storage_path.startswith(expected_prefix),
            f"Storage path '{storage_path}' must begin with '{expected_prefix}'",
        )

    @unittest_run_loop
    async def test_aiohttp_negative_anonymous_rejected(self):
        """2. Negative: Request without auth on aiohttp is rejected with HTTP 401."""
        img_data = create_valid_test_image(format="PNG")
        form = FormData()
        form.add_field("file", img_data.read(), filename="anon.png", content_type="image/png")

        resp = await self.client.request("POST", "/api/v1/upload", data=form)
        self.assertEqual(resp.status, 401)
        data = await resp.json()
        self.assertIn("Autentikasi merchant diperlukan", data.get("detail", ""))

    @unittest_run_loop
    async def test_aiohttp_negative_malformed_and_expired_tokens(self):
        """3. Negative: Malformed and expired tokens rejected with HTTP 401."""
        img_data = create_valid_test_image(format="PNG")

        # Malformed
        form1 = FormData()
        form1.add_field("file", img_data.read(), filename="malformed.png", content_type="image/png")
        resp1 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form1,
            headers={"Authorization": "Bearer not-a-valid-token"},
        )
        self.assertEqual(resp1.status, 401)

        # Expired
        expired_token = make_signed_merchant_token(expires_in_seconds=-3600)
        img_data.seek(0)
        form2 = FormData()
        form2.add_field("file", img_data.read(), filename="expired.png", content_type="image/png")
        resp2 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form2,
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        self.assertEqual(resp2.status, 401)

        # Forged signature
        valid_token = make_signed_merchant_token()
        parts = valid_token.split(".")
        tampered = f"{parts[0]}.{parts[1]}.fake_tampered_signature"
        img_data.seek(0)
        form3 = FormData()
        form3.add_field("file", img_data.read(), filename="forged.png", content_type="image/png")
        resp3 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form3,
            headers={"Authorization": f"Bearer {tampered}"},
        )
        self.assertEqual(resp3.status, 401)

    @unittest_run_loop
    async def test_aiohttp_negative_invalid_merchant_role(self):
        """4. Negative: Non-merchant roles (customer, user, guest) rejected with HTTP 403."""
        img_data = create_valid_test_image(format="PNG")

        for bad_role in ("customer", "user", "anonymous", "guest"):
            token = make_signed_merchant_token(role=bad_role)
            img_data.seek(0)
            form = FormData()
            form.add_field("file", img_data.read(), filename="bad_role.png", content_type="image/png")
            resp = await self.client.request(
                "POST",
                "/api/v1/upload",
                data=form,
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(resp.status, 403, f"Role '{bad_role}' should be 403, got {resp.status}")

    @unittest_run_loop
    async def test_aiohttp_negative_missing_tenant_claim(self):
        """5. Negative: Token without tenant claim rejected with HTTP 401."""
        now = int(time.time())
        payload = {
            "sub": "merchant@example.com",
            "merchant_id": "merchant@example.com",
            "role": "merchant",
            "exp": now + 3600,
        }
        token_no_tenant = encode_jwt_token_strict(payload, realm="core")

        img_data = create_valid_test_image(format="PNG")
        form = FormData()
        form.add_field("file", img_data.read(), filename="no_tenant.png", content_type="image/png")
        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form,
            headers={"Authorization": f"Bearer {token_no_tenant}"},
        )
        self.assertEqual(resp.status, 401)

    @unittest_run_loop
    async def test_aiohttp_negative_user_metadata_tenant_spoofing(self):
        """6. Negative: user_metadata-only tenant rejected with HTTP 401."""
        now = int(time.time())
        payload = {
            "sub": "attacker@evil.com",
            "role": "merchant",
            "exp": now + 3600,
            "user_metadata": {
                "tenant_id": "tenant-alpha-victim",
                "tenant_slug": "tenant-alpha-victim",
            },
        }
        token_user_meta = encode_jwt_token_strict(payload, realm="core")

        img_data = create_valid_test_image(format="PNG")
        form = FormData()
        form.add_field("file", img_data.read(), filename="meta_spoof.png", content_type="image/png")
        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form,
            headers={"Authorization": f"Bearer {token_user_meta}"},
        )
        self.assertEqual(resp.status, 401)

    @unittest_run_loop
    async def test_aiohttp_negative_merchant_not_authorized_for_tenant(self):
        """7. Negative: Principal without active membership in tenant rejected with HTTP 403 (CTO P1)."""
        tenant_id = "tenant-restricted-aio-001"
        register_merchant_membership("legit_owner@aio-restricted.com", tenant_id, is_active=True, role="owner")

        rogue_token = make_signed_merchant_token(
            tenant_id=tenant_id,
            merchant_id="unauthorized_rogue@outsider.com",
            role="merchant",
            register_membership=False,
        )

        img_data = create_valid_test_image(format="PNG")
        form = FormData()
        form.add_field("file", img_data.read(), filename="rogue.png", content_type="image/png")
        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form,
            headers={"Authorization": f"Bearer {rogue_token}"},
        )
        self.assertEqual(resp.status, 403)
        data = await resp.json()
        self.assertIn("keanggotaan aktif", data.get("detail", "").lower())

    @unittest_run_loop
    async def test_aiohttp_negative_revoked_merchant_membership(self):
        """8. Negative: Revoked merchant membership rejected with HTTP 403 (CTO P1)."""
        tenant_id = "tenant-aio-revoked-001"
        merchant_id = "revoked_staff@aio-tenant.com"

        register_merchant_membership(merchant_id, tenant_id, is_active=True, role="staff")
        revoke_merchant_membership(merchant_id, tenant_id)

        token = make_signed_merchant_token(
            tenant_id=tenant_id,
            merchant_id=merchant_id,
            role="staff",
            register_membership=False,
        )

        img_data = create_valid_test_image(format="PNG")
        form = FormData()
        form.add_field("file", img_data.read(), filename="revoked.png", content_type="image/png")
        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status, 403)
        data = await resp.json()
        self.assertIn("dicabut atau dinonaktifkan", data.get("detail", "").lower())

    @unittest_run_loop
    async def test_aiohttp_negative_deactivated_tenant(self):
        """9. Negative: Upload to deactivated tenant rejected with HTTP 403 (CTO P1)."""
        from app.api.deps import register_test_tenant
        tenant_id = "tenant-aio-deactivated-001"
        register_test_tenant(tenant_id=tenant_id, slug=tenant_id, is_active=False)

        token = make_signed_merchant_token(tenant_id=tenant_id, merchant_id="owner@aio-deactivated.com")

        img_data = create_valid_test_image(format="PNG")
        form = FormData()
        form.add_field("file", img_data.read(), filename="deact.png", content_type="image/png")
        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status, 403)

    @unittest_run_loop
    async def test_aiohttp_negative_cross_tenant_header_spoofing(self):
        """10. Negative: X-Tenant-ID and X-Tenant-Slug header spoofing rejected with HTTP 403."""
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
        img_data = create_valid_test_image(format="PNG")

        # X-Tenant-ID
        form1 = FormData()
        form1.add_field("file", img_data.read(), filename="h_id.png", content_type="image/png")
        resp1 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form1,
            headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": "tenant-bravo-victim"},
        )
        self.assertEqual(resp1.status, 403)

        # X-Tenant-Slug
        img_data.seek(0)
        form2 = FormData()
        form2.add_field("file", img_data.read(), filename="h_slug.png", content_type="image/png")
        resp2 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form2,
            headers={"Authorization": f"Bearer {token}", "X-Tenant-Slug": "tenant-bravo-victim"},
        )
        self.assertEqual(resp2.status, 403)

    @unittest_run_loop
    async def test_aiohttp_negative_form_and_query_tenant_spoofing(self):
        """11. Negative: FormData and query param tenant spoofing rejected with HTTP 403."""
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
        img_data = create_valid_test_image(format="PNG")

        # FormData tenant_id
        form1 = FormData()
        form1.add_field("file", img_data.read(), filename="f_tenant.png", content_type="image/png")
        form1.add_field("tenant_id", "tenant-bravo-victim")
        resp1 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form1,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp1.status, 403)

        # Query param tenant_id
        img_data.seek(0)
        form2 = FormData()
        form2.add_field("file", img_data.read(), filename="q_tenant.png", content_type="image/png")
        resp2 = await self.client.request(
            "POST",
            "/api/v1/upload?tenant_id=tenant-bravo-victim",
            data=form2,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp2.status, 403)

    @unittest_run_loop
    async def test_aiohttp_negative_path_traversal_and_lookalike(self):
        """12. Negative: Path traversal (..) and prefix lookalike rejected with HTTP 403."""
        token = make_signed_merchant_token(tenant_id="tenant-alpha")
        img_data = create_valid_test_image(format="PNG")

        # Path traversal
        form1 = FormData()
        form1.add_field("file", img_data.read(), filename="traversal.png", content_type="image/png")
        form1.add_field("folder", "../tenant-bravo-victim")
        resp1 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form1,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp1.status, 403)

        # Prefix lookalike (tenant-alpha-evil vs tenant-alpha)
        img_data.seek(0)
        form2 = FormData()
        form2.add_field("file", img_data.read(), filename="lookalike.png", content_type="image/png")
        form2.add_field("folder", "tenants/tenant-alpha-evil/uploads")
        resp2 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form2,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp2.status, 403)

        # URL-encoded traversal (%2e%2e)
        img_data.seek(0)
        form3 = FormData()
        form3.add_field("file", img_data.read(), filename="url_enc.png", content_type="image/png")
        form3.add_field("folder", "%2e%2e/etc")
        resp3 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form3,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp3.status, 403)

        # Backslash separator
        img_data.seek(0)
        form4 = FormData()
        form4.add_field("file", img_data.read(), filename="backslash.png", content_type="image/png")
        form4.add_field("folder", r"tenants\tenant-bravo\uploads")
        resp4 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form4,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp4.status, 403)

    @unittest_run_loop
    async def test_aiohttp_negative_file_validation(self):
        """13. Negative: Magic byte mismatch, corrupt image rejected with HTTP 422; oversize file rejected with HTTP 413."""
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001")

        # Windows PE disguised as PNG
        fake_exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00This is an executable."
        form1 = FormData()
        form1.add_field("file", fake_exe, filename="malware.png", content_type="image/png")
        resp1 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form1,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp1.status, 422)

        # Corrupted JPEG
        corrupt_jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 20 + b"BROKEN_IMAGE_BINARY"
        form2 = FormData()
        form2.add_field("file", corrupt_jpg, filename="corrupt.jpg", content_type="image/jpeg")
        resp2 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form2,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp2.status, 422)

        # Oversized file (> 5MB) - caught by bounded reader abort (HTTP 413)
        large_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1024)
        form3 = FormData()
        form3.add_field("file", large_data, filename="huge.png", content_type="image/png")
        resp3 = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=form3,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp3.status, 413)

    @unittest_run_loop
    async def test_aiohttp_negative_oversized_content_length_precheck(self):
        """14. Negative: Oversized Content-Length header strictly rejected with HTTP 413 (CTO P1)."""
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
        img_data = create_valid_test_image(format="PNG", size=(10, 10))

        oversized_cl = str(5 * 1024 * 1024 + 65537 + 1)
        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=img_data.read(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/png",
                "Content-Length": oversized_cl,
            },
        )
        # STRICT ASSERTION: must be exactly HTTP 413
        self.assertEqual(resp.status, 413)

    @unittest_run_loop
    async def test_aiohttp_chunked_streaming_without_content_length_oversized_aborts_early(self):
        """15. Real aiohttp network runner: Streamed chunked transfer without Content-Length aborts early with HTTP 413 (CTO P1)."""
        import asyncio
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
        boundary = "----AioHttpChunkedTestBoundary"

        yield_counter = 0

        async def chunked_body_generator():
            nonlocal yield_counter
            # Multipart header
            header = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="oversized.png"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode("utf-8")
            yield_counter += 1
            yield header

            # 100 chunks * 64 KB = ~6.4 MB total (exceeds 5 MB limit + 64 KB overhead)
            for _ in range(100):
                yield_counter += 1
                yield b"A" * 65536
                await asyncio.sleep(0.001)

            footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
            yield_counter += 1
            yield footer

        resp = await self.client.request(
            "POST",
            "/api/v1/upload",
            data=chunked_body_generator(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        self.assertEqual(resp.status, 413)
        self.assertLess(yield_counter, 100, f"Aiohttp server should abort early: expected < 100 chunks, got {yield_counter}")

    @unittest_run_loop
    async def test_aiohttp_tenant_aliases_anonymous_rejected(self):
        """16. All aiohttp tenant upload aliases reject anonymous requests with HTTP 401."""
        aliases = [
            "/api/v1/tenants/demo-shop/upload",
            "/api/v1/tenants/demo-shop/qris/upload",
            "/api/v1/tenants/demo-shop/upload-qris",
            "/api/v1/tenant/demo-shop/upload",
            "/api/v1/tenant/demo-shop/qris/upload",
        ]
        img_data = create_valid_test_image(format="PNG", size=(10, 10)).read()

        for path in aliases:
            form = FormData()
            form.add_field("file", img_data, filename="test.png", content_type="image/png")
            resp = await self.client.request("POST", path, data=form)
            self.assertEqual(resp.status, 401, f"Expected 401 on anonymous aiohttp {path}, got {resp.status}")

    @unittest_run_loop
    async def test_aiohttp_tenant_aliases_cross_tenant_rejected(self):
        """17. All aiohttp tenant upload aliases reject cross-tenant access with HTTP 403."""
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
        aliases = [
            "/api/v1/tenants/victim-shop/upload",
            "/api/v1/tenants/victim-shop/qris/upload",
            "/api/v1/tenants/victim-shop/upload-qris",
            "/api/v1/tenant/victim-shop/upload",
            "/api/v1/tenant/victim-shop/qris/upload",
        ]
        img_data = create_valid_test_image(format="PNG", size=(10, 10)).read()

        for path in aliases:
            form = FormData()
            form.add_field("file", img_data, filename="test.png", content_type="image/png")
            resp = await self.client.request(
                "POST",
                path,
                data=form,
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(resp.status, 403, f"Expected 403 on cross-tenant aiohttp {path}, got {resp.status}")

    @unittest_run_loop
    async def test_aiohttp_tenant_aliases_positive_authorized_upload(self):
        """18. All aiohttp tenant upload aliases succeed with scoped storage namespace when authorized."""
        token = make_signed_merchant_token(tenant_id="tenant-alpha-001")
        aliases = [
            "/api/v1/tenants/tenant-alpha-001/upload",
            "/api/v1/tenants/tenant-alpha-001/qris/upload",
            "/api/v1/tenants/tenant-alpha-001/upload-qris",
            "/api/v1/tenant/tenant-alpha-001/upload",
            "/api/v1/tenant/tenant-alpha-001/qris/upload",
        ]

        for path in aliases:
            img_data = create_valid_test_image(format="PNG", size=(10, 10)).read()
            form = FormData()
            form.add_field("file", img_data, filename="auth.png", content_type="image/png")
            resp = await self.client.request(
                "POST",
                path,
                data=form,
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertIn(resp.status, (200, 201), f"Expected 200/201 on authorized aiohttp {path}, got {resp.status}")
            data = await resp.json()
            self.assertEqual(data.get("tenant_id"), "tenant-alpha-001")
            self.assertTrue(
                data.get("storage_path", "").startswith("tenants/tenant-alpha-001/uploads/"),
                f"Storage path {data.get('storage_path')} not scoped to tenant namespace",
            )

    @unittest_run_loop
    async def test_aiohttp_subscription_guard_suspended_tenant_rejected_403(self):
        """19. aiohttp server strictly rejects upload for suspended tenant with HTTP 403."""
        token = make_signed_merchant_token(tenant_id="tenant-aio-suspended-001")
        img_data = create_valid_test_image(format="PNG", size=(10, 10)).read()
        form = FormData()
        form.add_field("file", img_data, filename="auth.png", content_type="image/png")

        with patch("app.core.subscription_guard.assert_tenant_mutation_allowed",
                   side_effect=HTTPException(status_code=403, detail=SUBSCRIPTION_MUTATION_RESTRICTED_PAYLOAD)):
            resp = await self.client.request(
                "POST",
                "/api/v1/upload",
                data=form,
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(resp.status, 403)
            data = await resp.json()
            detail = data.get("detail", {})
            self.assertEqual(detail.get("error"), "SUBSCRIPTION_REQUIRED")
            self.assertIn("Masa aktif paket/trial telah berakhir", detail.get("message", ""))

    @unittest_run_loop
    async def test_aiohttp_subscription_guard_exception_fails_closed_503(self):
        """20. aiohttp server strictly fails closed with HTTP 503 if subscription guard encounters internal or DB error."""
        token = make_signed_merchant_token(tenant_id="tenant-aio-err-002")
        img_data = create_valid_test_image(format="PNG", size=(10, 10)).read()
        form = FormData()
        form.add_field("file", img_data, filename="auth.png", content_type="image/png")

        with patch("app.core.subscription_guard.assert_tenant_mutation_allowed",
                   side_effect=RuntimeError("Cluster connection error in subscription")):
            resp = await self.client.request(
                "POST",
                "/api/v1/upload",
                data=form,
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(resp.status, 503)
            data = await resp.json()
            self.assertIn("fail-closed subscription guard", str(data.get("detail", "")))

