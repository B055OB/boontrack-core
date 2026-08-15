import os
from supabase import create_client, Client


class AnalyticsService:
    def __init__(self):
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_KEY", "").strip()

        if url and key:
            self.supabase: Client = create_client(url, key)
            print("[ANALYTICS] Supabase client initialized")
        else:
            self.supabase = None
            print("[ANALYTICS] WARNING: SUPABASE_URL / SUPABASE_KEY missing")

    # ============================================================
    # REALTIME METRICS
    # ============================================================

    async def get_realtime_metrics(self) -> dict:
        """
        Mengambil metric utama BoonTrack dari Supabase.
        """
        metrics = {
            "total_users": 0,
            "cv_generated": 0,
            "cv_reviewed": 0,
            "career_page_created": 0,
            "paid_users": 0,
            "total_revenue": 0,
            "active_referrals": 0,
        }

        if not self.supabase:
            print("[ANALYTICS] Supabase client unavailable")
            return metrics

        # 1. Total Users
        try:
            response = (
                self.supabase
                .table("users")
                .select("telegram_id", count="exact", head=True)
                .execute()
            )
            metrics["total_users"] = response.count or 0
        except Exception as e:
            print(f"[ANALYTICS USERS ERROR] {e}")

        # 2. CV Generated
        try:
            response = (
                self.supabase
                .table("cv_documents")
                .select("id", count="exact", head=True)
                .execute()
            )
            metrics["cv_generated"] = response.count or 0
        except Exception as e:
            print(f"[ANALYTICS CV ERROR] {e}")

        # 3. CV Reviewed
        try:
            response = (
                self.supabase
                .table("cv_reviews")
                .select("id", count="exact", head=True)
                .execute()
            )
            metrics["cv_reviewed"] = response.count or 0
        except Exception as e:
            print(f"[ANALYTICS REVIEW ERROR] {e}")

        # 4. Career / User Progress
        try:
            response = (
                self.supabase
                .table("user_progress")
                .select("user_id", count="exact", head=True)
                .execute()
            )
            metrics["career_page_created"] = response.count or 0
        except Exception as e:
            print(f"[ANALYTICS PROGRESS ERROR] {e}")

        # 5. Paid Users + Total Revenue
        try:
            response = (
                self.supabase
                .table("donation_sessions")
                .select("user_id, total_amount")
                .eq("status", "VERIFIED")
                .execute()
            )
            rows = response.data or []
            
            # Count Distinct Paid Users
            unique_paid_users = {r.get("user_id") for r in rows if r.get("user_id")}
            metrics["paid_users"] = len(unique_paid_users) if unique_paid_users else len(rows)

            total_revenue = 0
            for row in rows:
                amount = row.get("total_amount", 0)
                try:
                    total_revenue += float(amount or 0)
                except (TypeError, ValueError):
                    pass

            metrics["total_revenue"] = total_revenue
        except Exception as e:
            print(f"[ANALYTICS DONATION ERROR] {e}")

        # 6. Active Referrals
        metrics["active_referrals"] = 0
        return metrics

    # ============================================================
    # TRAFFIC SOURCES / UTM LAMA
    # ============================================================

    async def get_traffic_sources(self) -> dict:
        """
        Mengambil breakdown UTM agregat dari click_logs.
        """
        if not self.supabase:
            return {}

        try:
            response = (
                self.supabase
                .table("click_logs")
                .select("utm_source")
                .execute()
            )
            rows = response.data or []
            sources = {}

            for row in rows:
                source = row.get("utm_source") or "direct"
                source = str(source).strip().lower()
                sources[source] = sources.get(source, 0) + 1

            return sources
        except Exception as e:
            print(f"[UTM FETCH ERROR] {e}")
            return {}

    # ============================================================
    # CONTENT & BUZZER ATTRIBUTION FUNNEL (NEW)
    # ============================================================

    async def get_content_funnel_metrics(self) -> list:
        """
        Mengambil performa funnel per campaign dan content ID (Buzzer/Kreator)
        dari tabel click_logs.
        """
        if not self.supabase:
            return []

        try:
            response = (
                self.supabase
                .table("click_logs")
                .select("utm_campaign, utm_content, event_name, telegram_user_id")
                .execute()
            )
            rows = response.data or []
            funnel_data = {}

            for row in rows:
                campaign = row.get("utm_campaign") or "direct"
                content = row.get("utm_content") or "general"
                key = (campaign, content)

                if key not in funnel_data:
                    funnel_data[key] = {
                        "campaign": campaign,
                        "content": content,
                        "clicks": 0,
                        "bot_starts": 0,
                        "unique_users": set()
                    }

                event = row.get("event_name")
                tg_user = row.get("telegram_user_id")

                if event == "page_view" or not event:
                    funnel_data[key]["clicks"] += 1

                if tg_user or event == "telegram_start":
                    funnel_data[key]["bot_starts"] += 1
                    if tg_user:
                        funnel_data[key]["unique_users"].add(tg_user)

            result_list = []
            for data in funnel_data.values():
                clicks = data["clicks"]
                starts = data["bot_starts"]
                conv_rate = (starts / clicks * 100) if clicks > 0 else 0

                result_list.append({
                    "campaign": data["campaign"],
                    "content": data["content"],
                    "clicks": clicks,
                    "bot_starts": starts,
                    "unique_users": len(data["unique_users"]),
                    "conversion_rate": conv_rate
                })

            return result_list

        except Exception as e:
            print(f"[CONTENT FUNNEL ERROR] {e}")
            return []

    # ============================================================
    # AI USAGE TODAY (NEW)
    # ============================================================

    async def get_ai_usage_today(self) -> dict:
        """
        Mengambil pemakaian token dan request AI dari ai_usage_logs.
        """
        usage_data = {
            "gemini": {"requests": 0, "tokens": 0},
            "groq": {"requests": 0, "tokens": 0},
            "openrouter": {"requests": 0, "tokens": 0},
        }

        if not self.supabase:
            return usage_data

        try:
            response = (
                self.supabase
                .table("ai_usage_logs")
                .select("provider, total_tokens")
                .execute()
            )
            rows = response.data or []

            for row in rows:
                provider = str(row.get("provider", "")).strip().lower()
                tokens = int(row.get("total_tokens", 0) or 0)

                if "gemini" in provider:
                    usage_data["gemini"]["requests"] += 1
                    usage_data["gemini"]["tokens"] += tokens
                elif "groq" in provider:
                    usage_data["groq"]["requests"] += 1
                    usage_data["groq"]["tokens"] += tokens
                elif "openrouter" in provider:
                    usage_data["openrouter"]["requests"] += 1
                    usage_data["openrouter"]["tokens"] += tokens

            return usage_data
        except Exception as e:
            print(f"[AI USAGE ERROR] {e}")
            return usage_data

    # ============================================================
    # SAVE UTM
    # ============================================================

    async def save_user_utm(
        self,
        user_id: int,
        payload_str: str
    ):
        """
        Menyimpan UTM dari Telegram start payload ke click_logs.
        """
        if not self.supabase or not payload_str:
            return

        try:
            parts = payload_str.split("-")
            utm_source = parts[0] if len(parts) > 0 and parts[0] else "direct"
            utm_medium = parts[1] if len(parts) > 1 and parts[1] else "none"
            utm_campaign = parts[2] if len(parts) > 2 and parts[2] else "none"
            utm_content = parts[3] if len(parts) > 3 and parts[3] else "none"
            utm_term = parts[4] if len(parts) > 4 and parts[4] else "none"

            self.supabase.table("click_logs").insert({
                "telegram_user_id": user_id,
                "utm_source": utm_source,
                "utm_medium": utm_medium,
                "utm_campaign": utm_campaign,
                "utm_content": utm_content,
                "utm_term": utm_term,
                "event_name": "telegram_start"
            }).execute()

            print(
                "[UTM SAVE] Saved: "
                f"source={utm_source}, "
                f"medium={utm_medium}, "
                f"campaign={utm_campaign}, "
                f"content={utm_content}, "
                f"term={utm_term}"
            )
        except Exception as e:
            print(f"[UTM SAVE ERROR] {e}")


# ================================================================
# SINGLETON
# ================================================================

analytics_service = AnalyticsService()