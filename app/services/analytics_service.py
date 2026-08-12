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
                "cv_reviewed": 0,  # Bisa disesuaikan dengan tabel/event log
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

analytics_service = AnalyticsService()