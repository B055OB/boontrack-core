"""tests/test_seed_test_tier_tenants.py
Unit tests untuk memvalidasi script fixture seeding 3 test tier tenants (growth, growthplus, proscale).
"""

import unittest
from decimal import Decimal
from scripts.seed_test_tier_tenants import seed_test_tier_tenants, get_db_connection


class TestSeedTierTenants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Jalankan seed fixture untuk memastikan data terisi
        cls.seed_results = seed_test_tier_tenants()

    def test_seed_returned_three_tenants(self):
        """Memverifikasi bahwa proses seed mengembalikan tepat 3 record tenant."""
        self.assertEqual(len(self.seed_results), 3)
        slugs = [t["slug"] for t in self.seed_results]
        self.assertIn("growth", slugs)
        self.assertIn("growthplus", slugs)
        self.assertIn("proscale", slugs)

    def test_tenants_configuration_and_gateways(self):
        """Memverifikasi kesesuaian plan_tier dan wa_gateway_type di PostgreSQL."""
        conn = get_db_connection()
        cur = conn.cursor()

        expected = {
            "growth": {
                "name": "Boon Growth Store",
                "plan_tier": "growth",
                "wa_gateway_type": "unofficial_baileys",
            },
            "growthplus": {
                "name": "Boon Growth Plus Store",
                "plan_tier": "growth_tracking",
                "wa_gateway_type": "unofficial_baileys",
            },
            "proscale": {
                "name": "Boon ProScale Store",
                "plan_tier": "proscale",
                "wa_gateway_type": "official_waba",
            },
        }

        for slug, exp in expected.items():
            cur.execute("SELECT name, region_config FROM tenants WHERE slug = %s", (slug,))
            row = cur.fetchone()
            self.assertIsNotNone(row, f"Tenant {slug} tidak ditemukan di tabel tenants")
            name, reg_cfg = row[0], row[1]
            self.assertEqual(name, exp["name"])
            self.assertEqual(reg_cfg.get("plan_tier"), exp["plan_tier"])
            self.assertEqual(reg_cfg.get("wa_gateway_type"), exp["wa_gateway_type"])

            # Periksa juga tabel merchants
            cur.execute("SELECT store_name, status FROM merchants WHERE slug = %s", (slug,))
            m_row = cur.fetchone()
            self.assertIsNotNone(m_row, f"Merchant {slug} tidak ditemukan di tabel merchants")
            self.assertEqual(m_row[0], exp["name"])
            self.assertEqual(m_row[1], "ACTIVE")

        cur.close()
        conn.close()

    def test_sample_products_created(self):
        """Memverifikasi masing-masing tenant memiliki 1 produk uji coba seharga Rp 100.000."""
        conn = get_db_connection()
        cur = conn.cursor()

        for slug in ["growth", "growthplus", "proscale"]:
            cur.execute("SELECT id FROM tenants WHERE slug = %s", (slug,))
            t_id = cur.fetchone()[0]

            cur.execute("SELECT title, price, is_available FROM products WHERE tenant_id = %s", (t_id,))
            prods = cur.fetchall()
            self.assertEqual(len(prods), 1, f"Tenant {slug} harus memiliki tepat 1 produk")
            title, price, available = prods[0]
            self.assertEqual(title, "Produk Uji Coba")
            self.assertEqual(Decimal(str(price)), Decimal("100000.00"))
            self.assertTrue(available)

        cur.close()
        conn.close()

    def test_empty_state_orders_leads_campaigns(self):
        """Memverifikasi orders, leads, dan campaign_attributions bernilai 0 untuk fresh state."""
        conn = get_db_connection()
        cur = conn.cursor()

        for slug in ["growth", "growthplus", "proscale"]:
            cur.execute("SELECT COUNT(*) FROM orders WHERE tenant_slug = %s", (slug,))
            orders_count = cur.fetchone()[0]
            self.assertEqual(orders_count, 0, f"Orders untuk {slug} harus 0")

            cur.execute("SELECT COUNT(*) FROM campaign_attributions WHERE tenant_slug = %s", (slug,))
            campaigns_count = cur.fetchone()[0]
            self.assertEqual(campaigns_count, 0, f"Campaign attributions untuk {slug} harus 0")

            cur.execute("SELECT COUNT(*) FROM leads WHERE tenant_slug = %s OR tenant_id = %s", (slug, slug))
            leads_count = cur.fetchone()[0]
            self.assertEqual(leads_count, 0, f"Leads untuk {slug} harus 0")

        cur.close()
        conn.close()


if __name__ == "__main__":
    unittest.main()
