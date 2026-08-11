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

        Schema yang digunakan:
        - users
        - cv_documents
        - cv_reviews
        - user_progress
        - donation_sessions

        Setiap metric memiliki try/except sendiri supaya
        satu query gagal tidak membuat seluruh analytics menjadi 0.
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

        # --------------------------------------------------------
        # 1. TOTAL USERS
        # --------------------------------------------------------
        try:
            # users tidak memiliki kolom "id".
            # Gunakan telegram_id yang memang ada di schema.
            response = (
                self.supabase
                .table("users")
                .select("telegram_id", count="exact", head=True)
                .execute()
            )

            metrics["total_users"] = response.count or 0

            print(
                f"[ANALYTICS] Total Users: "
                f"{metrics['total_users']}"
            )

        except Exception as e:
            print(f"[ANALYTICS USERS ERROR] {e}")

        # --------------------------------------------------------
        # 2. CV GENERATED
        # --------------------------------------------------------
        try:
            # cv_documents memang memiliki kolom id.
            response = (
                self.supabase
                .table("cv_documents")
                .select("id", count="exact", head=True)
                .execute()
            )

            metrics["cv_generated"] = response.count or 0

            print(
                f"[ANALYTICS] CV Generated: "
                f"{metrics['cv_generated']}"
            )

        except Exception as e:
            print(f"[ANALYTICS CV ERROR] {e}")

        # --------------------------------------------------------
        # 3. CV REVIEWED
        # --------------------------------------------------------
        try:
            # cv_reviews memang memiliki kolom id.
            response = (
                self.supabase
                .table("cv_reviews")
                .select("id", count="exact", head=True)
                .execute()
            )

            metrics["cv_reviewed"] = response.count or 0

            print(
                f"[ANALYTICS] CV Reviewed: "
                f"{metrics['cv_reviewed']}"
            )

        except Exception as e:
            print(f"[ANALYTICS REVIEW ERROR] {e}")

        # --------------------------------------------------------
        # 4. CAREER / USER PROGRESS
        # --------------------------------------------------------
        try:
            # user_progress tidak terlihat memiliki kolom id.
            # Schema yang terlihat:
            # user_id, last_step, data, updated_at
            response = (
                self.supabase
                .table("user_progress")
                .select("user_id", count="exact", head=True)
                .execute()
            )

            metrics["career_page_created"] = response.count or 0

            print(
                f"[ANALYTICS] User Progress: "
                f"{metrics['career_page_created']}"
            )

        except Exception as e:
            print(f"[ANALYTICS PROGRESS ERROR] {e}")

        # --------------------------------------------------------
        # 5. PAID USERS + TOTAL REVENUE
        # --------------------------------------------------------
        try:
            response = (
                self.supabase
                .table("donation_sessions")
                .select("total_amount")
                .eq("status", "VERIFIED")
                .execute()
            )

            rows = response.data or []

            metrics["paid_users"] = len(rows)

            total_revenue = 0

            for row in rows:
                amount = row.get("total_amount", 0)

                if amount is None:
                    amount = 0

                try:
                    total_revenue += float(amount)
                except (TypeError, ValueError):
                    print(
                        f"[ANALYTICS] Invalid total_amount: "
                        f"{amount}"
                    )

            metrics["total_revenue"] = total_revenue

            print(
                f"[ANALYTICS] Paid Users: "
                f"{metrics['paid_users']} | "
                f"Revenue: Rp{metrics['total_revenue']:,.0f}"
            )

        except Exception as e:
            print(f"[ANALYTICS DONATION ERROR] {e}")

        # --------------------------------------------------------
        # 6. ACTIVE REFERRALS
        # --------------------------------------------------------
        # Belum ada sumber referral yang tervalidasi dari schema
        # yang kita lihat.
        metrics["active_referrals"] = 0

        print(
            "[ANALYTICS SUMMARY] "
            f"users={metrics['total_users']} | "
            f"cv={metrics['cv_generated']} | "
            f"reviews={metrics['cv_reviewed']} | "
            f"progress={metrics['career_page_created']} | "
            f"paid={metrics['paid_users']} | "
            f"revenue={metrics['total_revenue']}"
        )

        return metrics

    # ============================================================
    # TRAFFIC SOURCES / UTM
    # ============================================================

    async def get_traffic_sources(self) -> dict:
        """
        Mengambil breakdown UTM dari click_logs.

        Schema click_logs yang terlihat:
        - utm_source
        - utm_medium
        - utm_campaign
        - utm_content
        - utm_term
        - event_name
        - telegram_user_id
        """

        if not self.supabase:
            print("[UTM] Supabase client unavailable")
            return {}

        try:
            response = (
                self.supabase
                .table("click_logs")
                .select(
                    "utm_source, "
                    "utm_medium, "
                    "utm_campaign, "
                    "utm_content, "
                    "utm_term, "
                    "event_name"
                )
                .execute()
            )

            rows = response.data or []

            sources = {}

            for row in rows:
                source = row.get("utm_source")

                if not source:
                    source = "direct"

                source = str(source).strip().lower()

                sources[source] = sources.get(source, 0) + 1

            print(f"[UTM] Traffic sources: {sources}")

            return sources

        except Exception as e:
            print(f"[UTM FETCH ERROR] {e}")
            return {}

    # ============================================================
    # SAVE UTM
    # ============================================================

    async def save_user_utm(
        self,
        user_id: int,
        payload_str: str
    ):
        """
        Menyimpan UTM dari Telegram start payload.

        CATATAN:
        UTM sekarang diarahkan ke click_logs,
        bukan users, karena schema yang kita lihat
        menunjukkan field UTM berada di click_logs.
        """

        if not self.supabase:
            print("[UTM SAVE] Supabase unavailable")
            return

        if not payload_str:
            return

        try:
            parts = payload_str.split("-")

            utm_source = (
                parts[0]
                if len(parts) > 0 and parts[0]
                else "direct"
            )

            utm_medium = (
                parts[1]
                if len(parts) > 1 and parts[1]
                else "none"
            )

            utm_campaign = (
                parts[2]
                if len(parts) > 2 and parts[2]
                else "none"
            )

            utm_content = (
                parts[3]
                if len(parts) > 3 and parts[3]
                else "none"
            )

            self.supabase.table("click_logs").insert({
                "telegram_user_id": user_id,
                "utm_source": utm_source,
                "utm_medium": utm_medium,
                "utm_campaign": utm_campaign,
                "utm_content": utm_content,
                "event_name": "telegram_start"
            }).execute()

            print(
                "[UTM SAVE] Saved: "
                f"source={utm_source}, "
                f"medium={utm_medium}, "
                f"campaign={utm_campaign}, "
                f"content={utm_content}"
            )

        except Exception as e:
            print(f"[UTM SAVE ERROR] {e}")


# ================================================================
# SINGLETON
# ================================================================

analytics_service = AnalyticsService()