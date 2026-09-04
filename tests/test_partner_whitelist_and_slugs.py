"""tests/test_partner_whitelist_and_slugs.py
Unit tests for Whitelist Partner Management (AM & Affiliate),
Bank Account Payout Routing, and Custom Referral Slug Mechanics.
"""

import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.services.partner_service import (
    partner_service,
    validate_referral_slug,
    RESERVED_SLUGS,
    ALLOWED_BANKS,
    MINIMUM_PAYOUT_AMOUNT,
)
from app.models.affiliate import (
    Partner,
    PartnerRole,
    PartnerStatus,
    PartnerBankAccount,
    PayoutRequest,
    PayoutStatus,
    AllowedBank,
)


class TestPartnerWhitelistAndSlugs(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        # Reset memory cache untuk isolasi test
        partner_service._memory_partners.clear()
        partner_service._memory_bank_accounts.clear()
        partner_service._memory_payouts.clear()

        # Seed 1 partner awal untuk testing
        self.test_partner_id = "test-partner-uuid-001"
        self.test_partner = {
            "id": self.test_partner_id,
            "name": "Budi Marketer",
            "phone": "6281234567890",
            "email": "budi@affiliate.com",
            "role": "AFFILIATE",
            "ref_code": "AFF7890",
            "is_ref_customized": False,
            "registered_by_am_id": None,
            "status": "ACTIVE",
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        }
        partner_service._memory_partners[self.test_partner_id] = self.test_partner

    # =========================================================================
    # 1. SLUG REGEX & SYSTEM BLACKLIST VALIDATION
    # =========================================================================

    def test_slug_regex_valid_patterns(self):
        """Memverifikasi slug 3-20 karakter alfanumerik kapital dianggap valid."""
        valid_slugs = ["VIP", "PROMO2026", "ALDY99", "CUANMAX88", "A1B2C3D4E5F6G7H8I9J0"]
        for slug in valid_slugs:
            self.assertTrue(validate_referral_slug(slug), f"Slug '{slug}' seharusnya valid")

    def test_slug_regex_invalid_length(self):
        """Memverifikasi slug < 3 karakter atau > 20 karakter ditolak."""
        # Terlalu pendek (< 3)
        self.assertFalse(validate_referral_slug("AB"))
        self.assertFalse(validate_referral_slug("X"))
        self.assertFalse(validate_referral_slug(""))

        # Terlalu panjang (> 20)
        self.assertFalse(validate_referral_slug("A" * 21))

    def test_slug_regex_invalid_characters(self):
        """Memverifikasi slug mengandung spasi atau simbol ditolak."""
        invalid_slugs = [
            "PROMO-2026",
            "ALDY_99",
            "DISCOUNT 50",
            "CUAN.MAX",
            "VIP@STORE",
            "HELLO#WORLD",
        ]
        for slug in invalid_slugs:
            self.assertFalse(validate_referral_slug(slug), f"Slug '{slug}' seharusnya ditolak karena simbol")

    def test_slug_reserved_system_blacklist(self):
        """Memverifikasi semua kata kunci sistem dalam blacklist ditolak."""
        for reserved in RESERVED_SLUGS:
            self.assertFalse(
                validate_referral_slug(reserved),
                f"Reserved word '{reserved}' wajib ditolak oleh validator"
            )
            # Uji case-insensitive juga
            self.assertFalse(
                validate_referral_slug(reserved.lower()),
                f"Reserved word '{reserved.lower()}' wajib ditolak secara case-insensitive"
            )

    # =========================================================================
    # 2. ENDPOINT CHECK-REF-SLUG & CASE-INSENSITIVE UNIQUENESS
    # =========================================================================

    def test_check_ref_slug_endpoint(self):
        """Memverifikasi endpoint POST /api/v1/partners/check-ref-slug."""
        # 1. Cek slug valid dan tersedia
        resp = self.client.post("/api/v1/partners/check-ref-slug", json={"slug": "SUPERSELLER"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["available"])
        self.assertEqual(data["slug"], "SUPERSELLER")

        # 2. Cek slug reserved keyword
        resp_res = self.client.post("/api/v1/partners/check-ref-slug", json={"slug": "ADMIN"})
        self.assertEqual(resp_res.status_code, 200)
        data_res = resp_res.json()
        self.assertFalse(data_res["available"])
        self.assertIn("reserved", data_res["reason"].lower())

        # 3. Cek slug yang sudah dipakai oleh partner existing (case-insensitive)
        resp_dup = self.client.post("/api/v1/partners/check-ref-slug", json={"slug": "aff7890"})
        self.assertEqual(resp_dup.status_code, 200)
        data_dup = resp_dup.json()
        self.assertFalse(data_dup["available"])
        self.assertIn("sudah digunakan", data_dup["reason"].lower())

    # =========================================================================
    # 3. 1X CUSTOM SLUG CLAIM & PERMANENT LOCK MECHANISM
    # =========================================================================

    def test_claim_custom_slug_and_lock_mechanism(self):
        """
        Memverifikasi alur klaim custom slug:
        - Sukses pada klaim pertama dan mengunci is_ref_customized = True.
        - Gagal saat mencoba klaim kedua kalinya (400 Bad Request).
        - Gagal jika mengklaim slug yang sudah diambil orang lain (409 Conflict).
        """
        # 1. Klaim pertama: sukses
        claim_resp = self.client.put(
            "/api/v1/partners/claim-ref-slug",
            json={"slug": "BUDISULTAN", "partner_id": self.test_partner_id},
        )
        self.assertEqual(claim_resp.status_code, 200)
        data = claim_resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["ref_code"], "BUDISULTAN")
        self.assertTrue(data["is_ref_customized"])

        # Verifikasi status di database memory
        updated_partner = partner_service.get_partner_by_id(self.test_partner_id)
        self.assertTrue(updated_partner["is_ref_customized"])
        self.assertEqual(updated_partner["ref_code"], "BUDISULTAN")

        # 2. Percobaan klaim kedua oleh user yang sama: wajib DITOLAK
        second_resp = self.client.put(
            "/api/v1/partners/claim-ref-slug",
            json={"slug": "BUDIBARU", "partner_id": self.test_partner_id},
        )
        self.assertEqual(second_resp.status_code, 400)
        self.assertIn("sudah dikunci", second_resp.json()["detail"].lower())

        # 3. Percobaan klaim slug yang sama oleh user lain: wajib 409 CONFLICT
        other_partner_id = "test-partner-uuid-002"
        partner_service._memory_partners[other_partner_id] = {
            "id": other_partner_id,
            "name": "Rina Affiliate",
            "phone": "62899998888",
            "role": "AFFILIATE",
            "ref_code": "AFF9999",
            "is_ref_customized": False,
            "status": "ACTIVE",
        }

        dup_resp = self.client.put(
            "/api/v1/partners/claim-ref-slug",
            json={"slug": "budisultan", "partner_id": other_partner_id},  # case-insensitive
        )
        self.assertEqual(dup_resp.status_code, 409)
        self.assertIn("sudah digunakan", dup_resp.json()["detail"].lower())

    # =========================================================================
    # 4. BANK ACCOUNT REGISTRATION & VALIDATION
    # =========================================================================

    def test_bank_account_registration(self):
        """Memverifikasi penyimpanan data rekening bank mitra dengan bank yang valid."""
        # 1. Bank valid (BCA)
        resp = self.client.post(
            "/api/v1/partners/bank-account",
            json={
                "bank_name": "BCA",
                "account_number": "8830123456",
                "account_holder_name": "Budi Marketer",
                "partner_id": self.test_partner_id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["bank_name"], "BCA")
        self.assertEqual(data["data"]["account_number"], "8830123456")

        # 2. Get bank account endpoint
        get_resp = self.client.get(f"/api/v1/partners/bank-account?partner_id={self.test_partner_id}")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["data"]["bank_name"], "BCA")

        # 3. Bank tidak didukung
        invalid_bank_resp = self.client.post(
            "/api/v1/partners/bank-account",
            json={
                "bank_name": "BANK_UNKNOWN_XYZ",
                "account_number": "12345678",
                "account_holder_name": "Budi Marketer",
                "partner_id": self.test_partner_id,
            },
        )
        self.assertEqual(invalid_bank_resp.status_code, 400)
        self.assertIn("tidak didukung", invalid_bank_resp.json()["detail"].lower())

    # =========================================================================
    # 5. PAYOUT REQUEST (MINIMUM RP 50.000)
    # =========================================================================

    def test_payout_request_flow(self):
        """
        Memverifikasi alur permohonan penarikan dana:
        - Ditolak jika belum ada rekening bank.
        - Ditolak jika nominal < Rp 50.000.
        - Sukses jika nominal >= Rp 50.000 dengan status 'PENDING'.
        """
        # 1. Coba request tanpa rekening bank: ditolak
        no_bank_resp = self.client.post(
            "/api/v1/partners/payouts/request",
            json={"amount": 100000, "partner_id": self.test_partner_id},
        )
        self.assertEqual(no_bank_resp.status_code, 400)
        self.assertIn("rekening bank", no_bank_resp.json()["detail"].lower())

        # Daftarkan rekening bank terlebih dahulu
        self.client.post(
            "/api/v1/partners/bank-account",
            json={
                "bank_name": "MANDIRI",
                "account_number": "1300098765432",
                "account_holder_name": "Budi Marketer",
                "partner_id": self.test_partner_id,
            },
        )

        # 2. Coba request di bawah batas minimum (misal Rp 40.000): ditolak
        under_min_resp = self.client.post(
            "/api/v1/partners/payouts/request",
            json={"amount": 40000, "partner_id": self.test_partner_id},
        )
        self.assertEqual(under_min_resp.status_code, 422)  # Pydantic ge=50000 validation

        # 3. Request valid >= Rp 50.000 (misal Rp 150.000): sukses
        valid_resp = self.client.post(
            "/api/v1/partners/payouts/request",
            json={"amount": 150000, "partner_id": self.test_partner_id},
        )
        self.assertEqual(valid_resp.status_code, 200)
        payout_data = valid_resp.json()["payout"]
        self.assertEqual(payout_data["amount"], 150000)
        self.assertEqual(payout_data["status"], "PENDING")
        self.assertEqual(payout_data["bank_name"], "MANDIRI")

    # =========================================================================
    # 6. MANAGER CONTROL TOWER (WHITELIST, LIST & MARK-PAID)
    # =========================================================================

    def test_manager_whitelist_partner(self):
        """Memverifikasi pendaftaran mitra baru ke Whitelist oleh Admin/Manager."""
        # 1. Pendaftaran Account Manager (AM)
        am_resp = self.client.post(
            "/api/v1/manager/partners/whitelist",
            json={
                "name": "Dimas Account Manager",
                "phone": "081987654321",
                "role": "AM",
                "ref_code": "AMDIMAS",
                "email": "dimas@boontrack.com",
            },
        )
        self.assertEqual(am_resp.status_code, 200)
        am_data = am_resp.json()["partner"]
        self.assertEqual(am_data["role"], "AM")
        self.assertEqual(am_data["ref_code"], "AMDIMAS")
        self.assertTrue(am_data["is_ref_customized"])

        # 2. Pendaftaran Affiliate yang dibina oleh AM tersebut
        aff_resp = self.client.post(
            "/api/v1/manager/partners/whitelist",
            json={
                "name": "Eka Affiliate",
                "phone": "085678901234",
                "role": "AFFILIATE",
                "registered_by_am_id": am_data["id"],
            },
        )
        self.assertEqual(aff_resp.status_code, 200)
        aff_data = aff_resp.json()["partner"]
        self.assertEqual(aff_data["role"], "AFFILIATE")
        self.assertEqual(aff_data["registered_by_am_id"], am_data["id"])

        # 3. List partners di manager
        list_resp = self.client.get("/api/v1/manager/partners")
        self.assertEqual(list_resp.status_code, 200)
        partners = list_resp.json()["partners"]
        self.assertGreaterEqual(len(partners), 3)

    def test_manager_mark_payout_paid(self):
        """Memverifikasi konfirmasi pembayaran payout oleh Finance/Manager."""
        # Setup rekening & permohonan payout
        self.client.post(
            "/api/v1/partners/bank-account",
            json={
                "bank_name": "BCA",
                "account_number": "123456789",
                "account_holder_name": "Budi Marketer",
                "partner_id": self.test_partner_id,
            },
        )
        req_resp = self.client.post(
            "/api/v1/partners/payouts/request",
            json={"amount": 250000, "partner_id": self.test_partner_id},
        )
        payout_id = req_resp.json()["payout"]["id"]

        # Cek antrean di manager
        queue_resp = self.client.get("/api/v1/manager/payouts?status=PENDING")
        self.assertEqual(queue_resp.status_code, 200)
        payouts = queue_resp.json()["payouts"]
        self.assertTrue(any(p["id"] == payout_id for p in payouts))

        # Eksekusi Mark Paid
        proof_url = "https://storage.boontrack.com/proofs/transfer_bca_250k.jpg"
        paid_resp = self.client.put(
            f"/api/v1/manager/payouts/{payout_id}/mark-paid",
            json={
                "proof_attachment_url": proof_url,
                "notes": "Transfer manual via BCA KlikBisnis ref TRX9988",
            },
        )
        self.assertEqual(paid_resp.status_code, 200)
        updated_payout = paid_resp.json()["payout"]
        self.assertEqual(updated_payout["status"], "PAID")
        self.assertEqual(updated_payout["proof_attachment_url"], proof_url)
        self.assertIsNotNone(updated_payout["processed_at"])

    # =========================================================================
    # 7. ORM MODEL EXPORTS VERIFICATION
    # =========================================================================

    def test_orm_models_and_enums(self):
        """Memverifikasi ketersediaan dan struktur Model ORM SQLAlchemy."""
        self.assertEqual(PartnerRole.AM.value, "AM")
        self.assertEqual(PartnerRole.AFFILIATE.value, "AFFILIATE")
        self.assertEqual(PartnerStatus.ACTIVE.value, "ACTIVE")
        self.assertEqual(PayoutStatus.PAID.value, "PAID")
        self.assertEqual(AllowedBank.BCA.value, "BCA")

        # Verifikasi atribut model
        self.assertTrue(hasattr(Partner, "ref_code"))
        self.assertTrue(hasattr(Partner, "is_ref_customized"))
        self.assertTrue(hasattr(Partner, "registered_by_am_id"))
        self.assertTrue(hasattr(PartnerBankAccount, "bank_name"))
        self.assertTrue(hasattr(PayoutRequest, "proof_attachment_url"))


if __name__ == "__main__":
    unittest.main()
