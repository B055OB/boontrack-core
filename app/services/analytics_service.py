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
            response = self.supabase.table("users").select("utm_source").execute()
            
            sources = {}
            if response.data:
                for row in response.data:
                    src = row.get("utm_source") or "direct"
                    sources[src] = sources.get(src, 0) + 1
            return sources
        except Exception as e:
            print(f"[UTM FETCH ERROR] {e}")
            return {}

    async def save_user_utm(self, user_id: int, payload_str: str):
        """
        Memecah string payload dari Telegram start (misal: 'facebook-cpc-promo1-none')
        dan menyimpannya ke 4 kolom UTM di Supabase.
        """
        if not self.supabase or not payload_str:
            return

        try:
            parts = payload_str.split('-')
            utm_source = parts[0] if len(parts) > 0 and parts[0] else "direct"
            utm_medium = parts[1] if len(parts) > 1 and parts[1] else "none"
            utm_campaign = parts[2] if len(parts) > 2 and parts[2] else "none"
            utm_content = parts[3] if len(parts) > 3 and parts[3] else "none"

            # Upsert/Update data UTM user di tabel users
            self.supabase.table("users").upsert({
                "telegram_id": user_id,
                "utm_source": utm_source,
                "utm_medium": utm_medium,
                "utm_campaign": utm_campaign,
                "utm_content": utm_content
            }, on_conflict="telegram_id").execute()

        except Exception as e:
            print(f"[UTM SAVE ERROR] {e}")

analytics_service = AnalyticsService()