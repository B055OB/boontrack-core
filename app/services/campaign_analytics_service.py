import os
import logging
from typing import List, Dict, Any, Optional
from supabase import create_client, Client

logger = logging.getLogger("CAMPAIGN_ANALYTICS_SERVICE")

from dotenv import load_dotenv
load_dotenv()

# Supabase Client
supabase_url = os.getenv("SUPABASE_URL", "https://mpluzajlzpregmjwpjqr.supabase.co")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY", "")
supabase: Optional[Client] = None
if supabase_url and supabase_key:
    try:
        supabase = create_client(supabase_url, supabase_key)
    except Exception as e:
        logger.warning(f"Failed to create Supabase client: {e}")

# Demo Dataset khusus tenant 'onlineboost'
ONLINEBOOST_DEMO_CAMPAIGNS: List[Dict[str, Any]] = [
    {
        "campaign_name": "Scale-Up Masterclass Meta Ads 2026",
        "platform": "Meta Ads",
        "clicks": 2450,
        "leads_wa": 620,
        "closings": 186,
        "cr_pct": 30.0,
        "omset_closing": 27714000.0,
        "status": "Scale Up",
    },
    {
        "campaign_name": "TikTok Spark Ads - Hook Viral Formula",
        "platform": "TikTok Ads",
        "clicks": 1890,
        "leads_wa": 410,
        "closings": 98,
        "cr_pct": 23.9,
        "omset_closing": 14602000.0,
        "status": "Scale Up",
    },
    {
        "campaign_name": "Retargeting Abandoned Cart IG Stories",
        "platform": "Meta Ads",
        "clicks": 850,
        "leads_wa": 215,
        "closings": 75,
        "cr_pct": 34.88,
        "omset_closing": 11175000.0,
        "status": "Stable",
    },
    {
        "campaign_name": "Google Search Ads - Jasa Tracking CAPI",
        "platform": "Google Ads",
        "clicks": 620,
        "leads_wa": 130,
        "closings": 39,
        "cr_pct": 30.0,
        "omset_closing": 5811000.0,
        "status": "Stable",
    },
]


def normalize_platform_from_source(source: Optional[str]) -> str:
    """Konversi utm_source menjadi nama platform iklan standar."""
    if not source:
        return "Unknown Platform"
    src = source.strip().lower()
    if any(k in src for k in ["meta", "facebook", "fb", "ig", "instagram"]):
        return "Meta Ads"
    if any(k in src for k in ["tiktok", "tt", "spark"]):
        return "TikTok Ads"
    if any(k in src for k in ["google", "gads", "youtube", "yt"]):
        return "Google Ads"
    if any(k in src for k in ["snack", "snackvideo"]):
        return "SnackVideo Ads"
    if "twitter" in src or "x.com" in src:
        return "X Ads"
    return f"{src.title()} Ads"


class CampaignAnalyticsService:
    """
    Service untuk menyajikan data ringkasan atribusi campaign iklan berbayar
    berdasarkan parameter UTM (utm_source, utm_campaign) dari orders dan leads.
    """

    def __init__(self):
        # Memory storage cache
        self._memory_campaigns: Dict[str, List[Dict[str, Any]]] = {
            "onlineboost": [dict(c) for c in ONLINEBOOST_DEMO_CAMPAIGNS]
        }

    async def get_campaign_attributions(self, tenant_slug: str) -> List[Dict[str, Any]]:
        """
        Mengambil ringkasan atribusi iklan per tenant.
        - Khusus tenant 'onlineboost': menyajikan 4 data atribusi campaign demo.
        - Untuk tenant baru lainnya: mengembalikan array kosong [] jika belum ada traffic/orders.
        """
        if not tenant_slug:
            return []

        clean_slug = tenant_slug.strip().lower()

        # 1. Cek tabel campaign_attributions di Supabase
        if supabase:
            try:
                res = (
                    supabase.table("campaign_attributions")
                    .select("campaign_name, platform, clicks, leads_wa, closings, cr_pct, omset_closing, status")
                    .eq("tenant_slug", clean_slug)
                    .order("omset_closing", desc=True)
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    formatted = []
                    for row in res.data:
                        formatted.append({
                            "campaign_name": str(row["campaign_name"]),
                            "platform": str(row["platform"]),
                            "clicks": int(row["clicks"]),
                            "leads_wa": int(row["leads_wa"]),
                            "closings": int(row["closings"]),
                            "cr_pct": float(row["cr_pct"]),
                            "omset_closing": float(row["omset_closing"]),
                            "status": str(row["status"]),
                        })
                    return formatted
            except Exception as e:
                logger.debug(f"Supabase query campaign_attributions fallback to memory: {e}")

        # 2. Cek apakah ada data di memory store
        if clean_slug in self._memory_campaigns:
            return self._memory_campaigns[clean_slug]

        # 3. Cek apakah ada agregasi live dari tabel orders / leads / seller_ad_conversions
        live_data = await self._aggregate_from_live_orders(clean_slug)
        if live_data:
            return live_data

        # 4. Jika tenant baru dan tidak ada data: kembalikan [] (clean 0 data)
        return []

    async def _aggregate_from_live_orders(self, tenant_slug: str) -> List[Dict[str, Any]]:
        """
        Agregasi dinamis dari tabel orders/leads jika ada transaksi nyata untuk tenant ini.
        """
        if not supabase:
            return []

        try:
            res = (
                supabase.table("orders")
                .select("utm_source, utm_campaign, total_amount, status")
                .eq("tenant_id", tenant_slug)
                .execute()
            )
            if not res.data:
                return []

            # Kelompokkan per utm_campaign
            campaign_map: Dict[str, Dict[str, Any]] = {}
            for order in res.data:
                campaign = order.get("utm_campaign") or "Default Organic Campaign"
                source = order.get("utm_source") or "meta"
                platform = normalize_platform_from_source(source)
                amount = float(order.get("total_amount") or 0)
                is_closed = str(order.get("status") or "").upper() in ["PAID", "COMPLETED", "SETTLED"]

                if campaign not in campaign_map:
                    campaign_map[campaign] = {
                        "campaign_name": campaign,
                        "platform": platform,
                        "clicks": 0,
                        "leads_wa": 0,
                        "closings": 0,
                        "omset_closing": 0.0,
                    }

                campaign_map[campaign]["leads_wa"] += 1
                campaign_map[campaign]["clicks"] += 4  # Estimasi rasio klik:leads
                if is_closed:
                    campaign_map[campaign]["closings"] += 1
                    campaign_map[campaign]["omset_closing"] += amount

            results = []
            for item in campaign_map.values():
                leads = item["leads_wa"]
                closings = item["closings"]
                cr_pct = round((closings / leads * 100), 2) if leads > 0 else 0.0
                status = "Scale Up" if cr_pct >= 20.0 or item["omset_closing"] >= 10000000 else "Stable"
                results.append({
                    "campaign_name": item["campaign_name"],
                    "platform": item["platform"],
                    "clicks": item["clicks"],
                    "leads_wa": leads,
                    "closings": closings,
                    "cr_pct": cr_pct,
                    "omset_closing": item["omset_closing"],
                    "status": status,
                })
            return results
        except Exception:
            return []

    def seed_onlineboost_demo_data(self) -> Dict[str, Any]:
        """
        Menyimpan dataset contoh ke Supabase (jika terhubung) dan memory store.
        """
        self._memory_campaigns["onlineboost"] = [dict(c) for c in ONLINEBOOST_DEMO_CAMPAIGNS]
        
        inserted_count = len(ONLINEBOOST_DEMO_CAMPAIGNS)
        if supabase:
            try:
                # Hapus data onlineboost lama di Supabase jika ada
                supabase.table("campaign_attributions").delete().eq("tenant_slug", "onlineboost").execute()

                rows_to_insert = []
                for item in ONLINEBOOST_DEMO_CAMPAIGNS:
                    rows_to_insert.append({
                        "tenant_slug": "onlineboost",
                        "campaign_name": item["campaign_name"],
                        "platform": item["platform"],
                        "clicks": item["clicks"],
                        "leads_wa": item["leads_wa"],
                        "closings": item["closings"],
                        "cr_pct": item["cr_pct"],
                        "omset_closing": item["omset_closing"],
                        "status": item["status"],
                    })
                res = supabase.table("campaign_attributions").insert(rows_to_insert).execute()
                if res.data:
                    inserted_count = len(res.data)
            except Exception as e:
                logger.warning(f"Supabase seeding fallback to memory: {e}")

        return {
            "status": "success",
            "tenant_slug": "onlineboost",
            "records_seeded": inserted_count,
            "campaigns": ONLINEBOOST_DEMO_CAMPAIGNS,
        }


# Global Instance
campaign_analytics_service = CampaignAnalyticsService()
