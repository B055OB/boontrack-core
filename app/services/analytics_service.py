import os
from supabase import create_client, Client

class AnalyticsService:
    def __init__(self):
        url: str = os.getenv("SUPABASE_URL", "")
        key: str = os.getenv("SUPABASE_KEY", "")
        self.supabase: Client = create_client(url, key) if url and key else None

    async def get_realtime_metrics(self) -> dict:
        if not self.supabase:
            return {
                "total_users": 0,
                "cv_generated": 0,
                "cv_reviewed": 0,
                "career_page_created": 0,
                "paid_users": 0,
                "total_revenue": 0,
                "active_referrals": 0
            }

        try:
            # Query hitung jumlah record dari masing-masing tabel Supabase
            users_res = self.supabase.table("users").select("id", count="exact").execute()
            cv_res = self.supabase.table("cvs").select("id", count="exact").execute()
            
            return {
                "total_users": users_res.count or 0,
                "cv_generated": cv_res.count or 0,
                "cv_reviewed": 0,
                "career_page_created": 0,
                "paid_users": 0,
                "total_revenue": 0,
                "active_referrals": 0
            }
        except Exception as e:
            print(f"[ANALYTICS ERROR] {e}")
            return {
                "total_users": 0,
                "cv_generated": 0,
                "cv_reviewed": 0,
                "career_page_created": 0,
                "paid_users": 0,
                "total_revenue": 0,
                "active_referrals": 0
            }

    async def get_traffic_sources(self) -> dict:
        """
        Mengambil breakdown traffic source (UTM) dari tabel users di Supabase.
        """
        if not self.supabase:
            return {}

        try:
            # Mengambil kolom utm_source dari tabel users (atau sesuaikan dengan tabel utm_logs kamu)
            response = self.supabase.table("users").select("utm_source").execute()
            
            sources = {}
            if response.data:
                for row in response.data:
                    src = row.get("utm_source") or "Direct / Organic"
                    sources[src] = sources.get(src, 0) + 1
            return sources
        except Exception as e:
            print(f"[UTM FETCH ERROR] {e}")
            return {}

analytics_service = AnalyticsService()