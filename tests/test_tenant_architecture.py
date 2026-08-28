"""tests/test_tenant_architecture.py
Unit tests for standardized multi-tenant architecture, BaseTenantService contract,
om_budi refactoring, and B2G pilot scaffold isolation.
"""

import os
import unittest
from pathlib import Path
from app.tenants.base import BaseTenantService
from app.tenants.om_budi import (
    OmBudiService,
    om_budi_service,
    TENANT_ID as OM_BUDI_TENANT_ID,
    TENANT_NAME as OM_BUDI_TENANT_NAME,
)
from app.tenants.digilife_indra import (
    DigiLifeIndraService,
    digilife_indra_service,
    TENANT_ID as DIGILIFE_TENANT_ID,
    TENANT_NAME as DIGILIFE_TENANT_NAME,
)
from app.tenants.bale_pananggeuhan import (
    BalePananggeuhanService,
    bale_pananggeuhan_service,
    TENANT_ID as BALE_TENANT_ID,
    TENANT_NAME as BALE_TENANT_NAME,
)


class TestTenantArchitecture(unittest.IsolatedAsyncioTestCase):

    def test_tenants_directory_cleanliness(self):
        """Memverifikasi tidak ada file script liar di root app/tenants/ kecuali base.py dan __init__.py."""
        tenants_dir = Path(__file__).resolve().parent.parent / "app" / "tenants"
        self.assertTrue(tenants_dir.exists() and tenants_dir.is_dir())

        py_files = [f.name for f in tenants_dir.iterdir() if f.is_file() and f.suffix == ".py"]
        self.assertCountEqual(py_files, ["__init__.py", "base.py"])

        # Pastikan seluruh folder tenant wajib ada
        subdirs = [d.name for d in tenants_dir.iterdir() if d.is_dir() and not d.name.startswith("__")]
        self.assertIn("career", subdirs)
        self.assertIn("gym", subdirs)
        self.assertIn("om_budi", subdirs)
        self.assertIn("digilife_indra", subdirs)
        self.assertIn("bale_pananggeuhan", subdirs)

    def test_base_tenant_service_abc_contract(self):
        """Memverifikasi BaseTenantService tidak dapat diinisialisasi tanpa implementasi handle_incoming_message."""
        class IncompleteTenant(BaseTenantService):
            pass

        with self.assertRaises(TypeError):
            IncompleteTenant()

    def test_om_budi_service_inherits_base_tenant(self):
        """Memverifikasi OmBudiService mengimplementasikan BaseTenantService."""
        self.assertIsInstance(om_budi_service, BaseTenantService)
        self.assertEqual(om_budi_service.tenant_id, OM_BUDI_TENANT_ID)
        self.assertEqual(om_budi_service.tenant_name, OM_BUDI_TENANT_NAME)
        info = om_budi_service.get_info()
        self.assertEqual(info["tenant_id"], "om_budi")
        self.assertTrue(info["is_active"])

    async def test_digilife_indra_service_inquiries(self):
        """Memverifikasi modul B2G pilot DigiLife Indra (Kelurahan Kebon Melati)."""
        self.assertIsInstance(digilife_indra_service, BaseTenantService)
        self.assertEqual(digilife_indra_service.tenant_id, DIGILIFE_TENANT_ID)
        self.assertEqual(digilife_indra_service.tenant_name, DIGILIFE_TENANT_NAME)

        # 1. Welcome / Default query
        res_welcome = await digilife_indra_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="halo selamat pagi"
        )
        self.assertEqual(res_welcome.get("type"), "welcome")
        self.assertIn("DIGILIFE INDRA", res_welcome.get("reply", ""))

        # 2. Inquiry SKU
        res_sku = await digilife_indra_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="syarat pengurusan sku untuk modal usaha"
        )
        self.assertEqual(res_sku.get("type"), "service_detail")
        self.assertEqual(res_sku.get("service_id"), "sku")
        self.assertIn("Surat Keterangan Usaha", res_sku.get("reply", ""))
        self.assertIn("Pengantar RT/RW", res_sku.get("reply", ""))

        # 3. Inquiry Pengantar Nikah
        res_nikah = await digilife_indra_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="bagaimana alur pengantar nikah n1 n4 ke kua?"
        )
        self.assertEqual(res_nikah.get("type"), "service_detail")
        self.assertEqual(res_nikah.get("service_id"), "nikah")
        self.assertIn("Surat Pengantar Nikah", res_nikah.get("reply", ""))

        # 4. Inquiry Jam Operasional
        res_jam = await digilife_indra_service.handle_incoming_message(
            phone_number="081234567890",
            message_text="jam buka kantor kelurahan kapan?"
        )
        self.assertEqual(res_jam.get("type"), "information")
        self.assertIn("Jam Operasional", res_jam.get("reply", ""))

    async def test_bale_pananggeuhan_service_dispatch(self):
        """Memverifikasi modul B2G pilot Balé Pananggeuhan (Setda Pemprov Jawa Barat)."""
        self.assertIsInstance(bale_pananggeuhan_service, BaseTenantService)
        self.assertEqual(bale_pananggeuhan_service.tenant_id, BALE_TENANT_ID)
        self.assertEqual(bale_pananggeuhan_service.tenant_name, BALE_TENANT_NAME)

        # 1. Aduan Publik (Pipa air PDAM bocor) -> Tiket & Dispatch
        res_aduan_pdam = await bale_pananggeuhan_service.handle_incoming_message(
            phone_number="081299887766",
            message_text="Lapor pipa air pdam bocor di jalan riau bandung"
        )
        self.assertEqual(res_aduan_pdam.get("type"), "ticket")
        self.assertTrue(res_aduan_pdam.get("is_escalated"))
        ticket = res_aduan_pdam.get("ticket", {})
        self.assertTrue(ticket.get("id", "").startswith("PS-"))
        self.assertIn("PDAM", ticket.get("kategori", ""))
        self.assertEqual(ticket.get("status"), "OPEN")

        # 2. Aduan Listrik PLN
        res_aduan_pln = await bale_pananggeuhan_service.handle_incoming_message(
            phone_number="081299887766",
            message_text="aduan tiang listrik korsleting padam satu blok"
        )
        self.assertEqual(res_aduan_pln.get("type"), "ticket")
        ticket_pln = res_aduan_pln.get("ticket", {})
        self.assertIn("PLN", ticket_pln.get("kategori", ""))

        # 3. Konsultasi Syarat KTP
        res_ktp = await bale_pananggeuhan_service.handle_incoming_message(
            phone_number="081299887766",
            message_text="syarat ktp rusak apa saja ya?"
        )
        self.assertEqual(res_ktp.get("type"), "information")
        self.assertIn("PERSYARATAN PENGURUSAN KTP-EL", res_ktp.get("reply", ""))

        # 4. Konsultasi Bansos
        res_bansos = await bale_pananggeuhan_service.handle_incoming_message(
            phone_number="081299887766",
            message_text="bagaimana cara cek bansos dtks jabar?"
        )
        self.assertEqual(res_bansos.get("type"), "information")
        self.assertIn("BANTUAN SOSIAL PEMPROV JABAR", res_bansos.get("reply", ""))


if __name__ == "__main__":
    unittest.main()
