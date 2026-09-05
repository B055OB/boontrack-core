"""tests/test_boonpilot.py
Unit tests for Agentic AI BoonPilot Backend Architecture:
1. Dynamic Context & System Prompt Injection.
2. Query-only Tools & Guardrail Masking.
3. Data Mutation Tools & Action Proposal creation (Human-in-the-loop).
4. Proposal TTL & Approval/Rejection Execution.
"""

import time
import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.services.boonpilot_service import (
    boonpilot_service,
    mask_sensitive_data,
    ACTION_PROPOSAL_TTL_SECONDS,
)


class TestBoonPilot(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.client = TestClient(app)
        # Reset memory cache untuk isolasi test
        boonpilot_service._action_proposals.clear()

    # =========================================================================
    # 1. CONTEXT BUILDER & GUARDRAIL
    # =========================================================================

    async def test_build_tenant_context(self):
        """Memverifikasi context dinamis toko mencakup katalog, snapshot analitik, dan guardrail."""
        context = await boonpilot_service.build_tenant_context("onlineboost")

        self.assertEqual(context["tenant_slug"], "onlineboost")
        self.assertIn("system_prompt", context)
        self.assertIn("products", context)
        self.assertIn("analytics_snapshot", context)
        self.assertIn("shipping_origin", context)
        self.assertIn("active_couriers", context)

        # Cek Persona BoonPilot dan Guardrails
        prompt = context["system_prompt"]
        self.assertIn("BoonPilot", prompt)
        self.assertIn("nomor rekening", prompt.lower())
        self.assertIn("kredensial", prompt.lower())

        # Cek Snapshot Analitik 7 & 30 Hari
        snapshot = context["analytics_snapshot"]
        self.assertIn("last_7_days", snapshot)
        self.assertIn("last_30_days", snapshot)
        self.assertGreater(snapshot["last_30_days"]["gross_revenue"], 0)

    def test_guardrail_masking_sensitive_data(self):
        """Memverifikasi sanitasi nomor rekening bank dan kredensial API."""
        raw_text = "Transfer ke BCA no rek 883012345678 dengan token sb_publishable_abc123"
        masked = mask_sensitive_data(raw_text)

        self.assertNotIn("883012345678", masked)
        self.assertIn("****5678", masked)
        self.assertNotIn("sb_publishable_abc123", masked)
        self.assertIn("[REDACTED_CREDENTIAL]", masked)

    # =========================================================================
    # 2. QUERY-ONLY TOOLS (SALES & INVENTORY)
    # =========================================================================

    async def test_sales_and_roas_report_tool(self):
        """Memverifikasi tool query laporan penjualan dan ROAS."""
        report = await boonpilot_service.get_sales_and_roas_report("onlineboost", days=7)
        self.assertEqual(report["period_days"], 7)
        self.assertGreater(report["total_revenue"], 0)
        self.assertGreater(report["total_orders"], 0)
        self.assertGreater(report["blended_roas"], 0)
        self.assertIn("recommendation", report)

    def test_check_inventory_levels_tool(self):
        """Memverifikasi tool monitoring stok mendeteksi barang di bawah threshold."""
        inv = boonpilot_service.check_inventory_levels("onlineboost", threshold=5)
        self.assertIn("low_stock_items", inv)
        self.assertGreater(inv["low_stock_count"], 0)
        # Pastikan setiap item low stock memenuhi kriteria
        for item in inv["low_stock_items"]:
            self.assertLessEqual(item["stock"], 5)

    # =========================================================================
    # 3. CHAT ENDPOINT & ACTION PROPOSALS
    # =========================================================================

    def test_chat_query_sales_report(self):
        """Memverifikasi chat intent laporan omset langsung mengembalikan data teks."""
        resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Berapa omset dan performa closing toko saya 7 hari terakhir?",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "text")
        self.assertIn("Laporan Penjualan", data["reply"])
        self.assertIn("data", data)
        self.assertGreater(data["data"]["total_revenue"], 0)

    def test_chat_query_inventory_check(self):
        """Memverifikasi chat intent cek stok produk menipis."""
        resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Cek stok barang yang mau habis",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "text")
        self.assertIn("Peringatan Stok Menipis", data["reply"])

    def test_chat_mutation_proposal_update_stock(self):
        """Memverifikasi mutasi stok menghasilkan action_proposal dengan status AWAITING_APPROVAL."""
        resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Tolong ubah stok Masterclass Ads jadi 60 unit",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "action_proposal")
        self.assertEqual(data["action_type"], "update_product_stock")
        self.assertEqual(data["status"], "AWAITING_APPROVAL")
        self.assertEqual(data["payload"]["new_stock"], 60)
        self.assertIn("action_id", data)

    def test_chat_mutation_proposal_update_shipping_origin(self):
        """Memverifikasi mutasi alamat gudang menghasilkan action_proposal."""
        resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Ganti alamat gudang pengiriman ke Jl Dago No 120 Bandung 40132",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "action_proposal")
        self.assertEqual(data["action_type"], "update_shipping_origin")
        self.assertEqual(data["status"], "AWAITING_APPROVAL")
        self.assertEqual(data["payload"]["postal_code"], "40132")

    def test_chat_mutation_proposal_toggle_courier(self):
        """Memverifikasi mutasi kurir menghasilkan action_proposal."""
        resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Nonaktifkan kurir Grab untuk pengiriman",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "action_proposal")
        self.assertEqual(data["action_type"], "toggle_courier_service")
        self.assertEqual(data["status"], "AWAITING_APPROVAL")
        self.assertEqual(data["payload"]["courier_name"], "Grab")
        self.assertFalse(data["payload"]["is_active"])

    # =========================================================================
    # 4. HUMAN-IN-THE-LOOP EXECUTE ACTION
    # =========================================================================

    def test_execute_action_approved_successfully(self):
        """Memverifikasi aksi disetujui (approved=True) mengeksekusi mutasi ke database toko."""
        # 1. Buat proposal ubah stok
        chat_resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Ubah stok Masterclass Ads jadi 85",
            },
        )
        proposal = chat_resp.json()
        action_id = proposal["action_id"]

        # 2. Eksekusi persetujuan
        exec_resp = self.client.post(
            "/api/v1/boonpilot/execute-action",
            json={
                "tenant_slug": "onlineboost",
                "action_id": action_id,
                "approved": True,
            },
        )
        self.assertEqual(exec_resp.status_code, 200)
        exec_data = exec_resp.json()
        self.assertTrue(exec_data["success"])
        self.assertEqual(exec_data["status"], "EXECUTED")

        # 3. Pastikan stok toko benar-benar terupdate
        inv = boonpilot_service.check_inventory_levels("onlineboost")
        masterclass = next(p for p in inv["all_inventory"] if p["product_id"] == "prod_masterclass_ads")
        self.assertEqual(masterclass["stock"], 85)

    def test_execute_action_rejected_successfully(self):
        """Memverifikasi aksi dibatalkan (approved=False) tidak mengubah database toko."""
        chat_resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Ubah stok Masterclass Ads jadi 999",
            },
        )
        action_id = chat_resp.json()["action_id"]

        exec_resp = self.client.post(
            "/api/v1/boonpilot/execute-action",
            json={
                "tenant_slug": "onlineboost",
                "action_id": action_id,
                "approved": False,
            },
        )
        self.assertEqual(exec_resp.status_code, 200)
        exec_data = exec_resp.json()
        self.assertTrue(exec_data["success"])
        self.assertEqual(exec_data["status"], "REJECTED")

        # Pastikan stok TIDAK berubah jadi 999
        inv = boonpilot_service.check_inventory_levels("onlineboost")
        masterclass = next(p for p in inv["all_inventory"] if p["product_id"] == "prod_masterclass_ads")
        self.assertNotEqual(masterclass["stock"], 999)

    def test_execute_action_expired_or_not_found(self):
        """Memverifikasi aksi kedaluwarsa (> 10 menit TTL) atau ID palsu ditolak."""
        # 1. ID palsu
        fake_resp = self.client.post(
            "/api/v1/boonpilot/execute-action",
            json={
                "tenant_slug": "onlineboost",
                "action_id": "non-existent-action-uuid",
                "approved": True,
            },
        )
        self.assertEqual(fake_resp.status_code, 404)

        # 2. Proposal kedaluwarsa
        expired_proposal = boonpilot_service.create_action_proposal(
            tenant_slug="onlineboost",
            action_type="update_product_stock",
            description="Test expired",
            payload={"product_id": "prod_masterclass_ads", "new_stock": 10},
        )
        # Paksa set waktu kedaluwarsa ke masa lalu
        expired_proposal["expires_at"] = time.time() - 10

        exp_resp = self.client.post(
            "/api/v1/boonpilot/execute-action",
            json={
                "tenant_slug": "onlineboost",
                "action_id": expired_proposal["action_id"],
                "approved": True,
            },
        )
        self.assertEqual(exp_resp.status_code, 404)
        self.assertIn("kedaluwarsa", exp_resp.json()["detail"].lower())

    # =========================================================================
    # 5. WHATSAPP AUTOMATION CAPABILITIES & ANTI-GREETING LOOP
    # =========================================================================

    def test_chat_whatsapp_automation_capability_response(self):
        """
        Memverifikasi respon taktis untuk pertanyaan WhatsApp Automation:
        - Tidak merespons dengan greeting loop perkenalan berulang.
        - Menyajikan 3 alur otomatisasi WhatsApp dan opsi aksi cepat.
        """
        queries = [
            "Bagaimana otomatisasi whatsapp untuk toko ini?",
            "Status bot wa toko",
            "Apakah whatsapp automation sudah aktif?",
            "Fitur otomatisasi wa",
        ]
        for q in queries:
            resp = self.client.post(
                "/api/v1/boonpilot/chat",
                json={
                    "tenant_slug": "onlineboost",
                    "message": q,
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["type"], "text")
            reply = data["reply"]

            # Pastikan TIDAK mengulang greeting loop generic
            self.assertNotIn("Halo! Saya BoonPilot, siap membantu pengelolaan toko", reply)

            # Pastikan teks alur terstruktur hadir sesuai spesifikasi
            self.assertIn("Otomatisasi WhatsApp untuk toko Onlineboost sudah aktif dengan alur:", reply)
            self.assertIn("1. Sambutan otomatis calon pembeli via WA.", reply)
            self.assertIn("2. Menu bernomor (1, 2, 3) untuk cek detail produk & ulasan.", reply)
            self.assertIn("3. Link checkout instan & pelacakan konversi iklan otomatis (Lead/CAPI).", reply)
            self.assertIn("Apakah Anda ingin melihat statistik chat, menguji nomor asisten, atau mengubah alur katalog?", reply)

            # Pastikan metadata quick actions ada di payload response
            self.assertIn("data", data)
            self.assertEqual(data["data"]["status"], "ACTIVE")
            self.assertGreaterEqual(len(data["data"]["quick_actions"]), 3)

    def test_chat_whatsapp_subactions_proposals(self):
        """Memverifikasi sub-aksi pengujian nomor dan modifikasi alur katalog menghasilkan proposal."""
        # 1. Sub-aksi Uji Nomor Asisten
        test_num_resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Tolong uji nomor asisten sekarang",
            },
        )
        self.assertEqual(test_num_resp.status_code, 200)
        num_proposal = test_num_resp.json()
        self.assertEqual(num_proposal["type"], "action_proposal")
        self.assertEqual(num_proposal["action_type"], "test_assistant_number")
        self.assertEqual(num_proposal["status"], "AWAITING_APPROVAL")

        # 2. Sub-aksi Ubah Alur Katalog
        edit_flow_resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Ubah alur katalog produk WhatsApp toko",
            },
        )
        self.assertEqual(edit_flow_resp.status_code, 200)
        flow_proposal = edit_flow_resp.json()
        self.assertEqual(flow_proposal["type"], "action_proposal")
        self.assertEqual(flow_proposal["action_type"], "edit_catalog_flow")
        self.assertEqual(flow_proposal["status"], "AWAITING_APPROVAL")

    # =========================================================================
    # 6. MULTI-TURN CONVERSATION HISTORY
    # =========================================================================

    def test_chat_multi_turn_conversation_history(self):
        """Memverifikasi endpoint /chat menerima dan membaca array conversation_history."""
        history = [
            {"role": "user", "content": "Halo BoonPilot"},
            {"role": "assistant", "content": "Halo! Saya BoonPilot siap membantu operasional toko Onlineboost."},
            {"role": "user", "content": "Berapa omset minggu ini?"},
            {"role": "assistant", "content": "Total omset 7 hari terakhir adalah Rp 11.085.600."},
        ]

        resp = self.client.post(
            "/api/v1/boonpilot/chat",
            json={
                "tenant_slug": "onlineboost",
                "message": "Bagaimana dengan otomatisasi WhatsApp tokonya?",
                "session_id": "sess-multi-turn-001",
                "conversation_history": history,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["type"], "text")
        self.assertIn("Otomatisasi WhatsApp untuk toko Onlineboost sudah aktif", data["reply"])
        self.assertEqual(data["session_id"], "sess-multi-turn-001")


if __name__ == "__main__":
    unittest.main()

