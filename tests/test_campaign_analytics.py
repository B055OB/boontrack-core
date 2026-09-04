"""tests/test_campaign_analytics.py
Unit tests for Ad Campaign Attribution Analytics Table & Seeding Mechanics.
"""

import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.services.campaign_analytics_service import (
    campaign_analytics_service,
    ONLINEBOOST_DEMO_CAMPAIGNS,
    normalize_platform_from_source,
)
from app.models.campaign import CampaignAttribution


class TestCampaignAnalytics(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        # Pastikan data demo onlineboost ter-reset
        campaign_analytics_service.seed_onlineboost_demo_data()

    def test_campaign_attribution_onlineboost_demo_data(self):
        """
        Memverifikasi tenant demo 'onlineboost' mengembalikan 4 data atribusi campaign
        lengkap dengan parameter clicks, leads_wa, closings, cr_pct, omset_closing, dan status.
        """
        resp = self.client.get("/api/v1/analytics/campaigns?tenant_slug=onlineboost")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 4)

        expected_keys = {
            "campaign_name",
            "platform",
            "clicks",
            "leads_wa",
            "closings",
            "cr_pct",
            "omset_closing",
            "status",
        }

        platforms_found = set()
        statuses_found = set()

        for item in data:
            # 1. Pastikan semua key ada
            self.assertTrue(expected_keys.issubset(item.keys()))

            # 2. Pastikan tipe data sesuai
            self.assertIsInstance(item["campaign_name"], str)
            self.assertIsInstance(item["platform"], str)
            self.assertIsInstance(item["clicks"], int)
            self.assertIsInstance(item["leads_wa"], int)
            self.assertIsInstance(item["closings"], int)
            self.assertIsInstance(item["cr_pct"], (float, int))
            self.assertIsInstance(item["omset_closing"], (float, int))
            self.assertIsInstance(item["status"], str)

            # 3. Status harus 'Scale Up' atau 'Stable'
            self.assertIn(item["status"], ["Scale Up", "Stable"])

            platforms_found.add(item["platform"])
            statuses_found.add(item["status"])

        # Verifikasi platform mencakup Meta Ads, TikTok Ads, Google Ads
        self.assertIn("Meta Ads", platforms_found)
        self.assertIn("TikTok Ads", platforms_found)
        self.assertIn("Google Ads", platforms_found)

        # Verifikasi status mencakup Scale Up dan Stable
        self.assertIn("Scale Up", statuses_found)
        self.assertIn("Stable", statuses_found)

    def test_campaign_attribution_alias_tenant_id(self):
        """Memverifikasi parameter query tenant_id berfungsi sebagai alias tenant_slug."""
        resp = self.client.get("/api/v1/analytics/campaigns?tenant_id=onlineboost")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 4)

    def test_campaign_attribution_other_tenants_empty_data(self):
        """
        Memverifikasi tenant lain yang baru mendaftar (tanpa traffic/orders)
        mengembalikan array kosong [] agar dasbor mereka bersih 0 data.
        """
        new_tenants = ["tokobaru", "boutique_fashion", "kopi_senja_99", "brand_baru"]
        for slug in new_tenants:
            resp = self.client.get(f"/api/v1/analytics/campaigns?tenant_slug={slug}")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIsInstance(data, list)
            self.assertEqual(
                data,
                [],
                f"Tenant baru '{slug}' seharusnya memiliki 0 data (array kosong [])",
            )

    def test_campaign_attribution_missing_tenant_slug(self):
        """Memverifikasi request tanpa tenant_slug mengembalikan array kosong []."""
        resp = self.client.get("/api/v1/analytics/campaigns")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_normalize_platform_from_source(self):
        """Memverifikasi helper normalisasi platform dari UTM source."""
        self.assertEqual(normalize_platform_from_source("fb"), "Meta Ads")
        self.assertEqual(normalize_platform_from_source("facebook"), "Meta Ads")
        self.assertEqual(normalize_platform_from_source("ig"), "Meta Ads")
        self.assertEqual(normalize_platform_from_source("tiktok"), "TikTok Ads")
        self.assertEqual(normalize_platform_from_source("spark_ads"), "TikTok Ads")
        self.assertEqual(normalize_platform_from_source("google"), "Google Ads")
        self.assertEqual(normalize_platform_from_source("youtube"), "Google Ads")

    def test_campaign_attribution_orm_model(self):
        """Memverifikasi keberadaan dan atribut CampaignAttribution ORM SQLAlchemy model."""
        self.assertEqual(CampaignAttribution.__tablename__, "campaign_attributions")
        self.assertTrue(hasattr(CampaignAttribution, "tenant_slug"))
        self.assertTrue(hasattr(CampaignAttribution, "campaign_name"))
        self.assertTrue(hasattr(CampaignAttribution, "platform"))
        self.assertTrue(hasattr(CampaignAttribution, "clicks"))
        self.assertTrue(hasattr(CampaignAttribution, "leads_wa"))
        self.assertTrue(hasattr(CampaignAttribution, "closings"))
        self.assertTrue(hasattr(CampaignAttribution, "cr_pct"))
        self.assertTrue(hasattr(CampaignAttribution, "omset_closing"))
        self.assertTrue(hasattr(CampaignAttribution, "status"))


if __name__ == "__main__":
    unittest.main()
