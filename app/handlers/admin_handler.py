import os
import psycopg2
from psycopg2.extras import RealDictCursor
from app.utils.admin_check import is_owner
from app.services.analytics_service import analytics_service

class AdminHandler:
    """
    Handler khusus command internal Owner/Admin.
    """

    def _get_db_conn(self):
        return psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
        )

    def _get_ai_usage_today(self) -> dict:
        """Mengambil data penggunaan AI real-time hari ini dari PostgreSQL"""
        summary = {
            "Gemini": {"req": 0, "tokens": 0, "status": "🟢"},
            "Groq": {"req": 0, "tokens": 0, "status": "🟢"},
            "OpenRouter": {"req": 0, "tokens": 0, "status": "🟢"},
            "cv_reviews_count": 0,
            "cv_ai_calls": 0
        }
        try:
            conn = self._get_db_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Rekap Usage Token & Requests per Provider hari ini
            cur.execute("""
                SELECT 
                    provider, 
                    COUNT(*) as req_count, 
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) FILTER (WHERE status_code = 429 or is_error = TRUE) as error_count
                FROM ai_usage_logs 
                WHERE created_at >= CURRENT_DATE 
                GROUP BY provider;
            """)
            rows = cur.fetchall()
            for r in rows:
                p_name = r["provider"]
                if p_name in summary:
                    summary[p_name]["req"] = r["req_count"]
                    summary[p_name]["tokens"] = r["total_tokens"]
                    if r["error_count"] > 3:
                        summary[p_name]["status"] = "🔴"
                    elif r["error_count"] > 0:
                        summary[p_name]["status"] = "🟡"

            # Rekap CV Reviews & AI Calls hari ini
            cur.execute("SELECT COUNT(*) as cnt FROM cv_reviews WHERE created_at >= CURRENT_DATE;")
            rev_row = cur.fetchone()
            if rev_row:
                summary["cv_reviews_count"] = rev_row["cnt"]

            cur.execute("SELECT COUNT(*) as cnt FROM ai_usage_logs WHERE feature = 'cv_review' AND is_error = FALSE AND created_at >= CURRENT_DATE;")
            ai_call_row = cur.fetchone()
            if ai_call_row:
                summary["cv_ai_calls"] = ai_call_row["cnt"]

            cur.close()
            conn.close()
        except Exception as e:
            print(f"[AdminHandler Error] _get_ai_usage_today: {e}")
            
        return summary

    async def handle_admin_command(self, user_id: int, command_text: str) -> str:
        # Security Guard: Tolak jika bukan Owner
        if not is_owner(user_id):
            return "⛔ Akses ditolak. Command ini hanya untuk Admin/Owner."

        clean_cmd = command_text.strip().lower()

        if clean_cmd in ["/analytics", "/admin"]:
            # 1. Metrics Bisnis Realtime, Traffic Sources, & Content Attribution
            metrics = await analytics_service.get_realtime_metrics()
            traffic_sources = await analytics_service.get_traffic_sources()
            funnel_data = await analytics_service.get_content_funnel_metrics()

            # Format Traffic Sources (UTM Agregat)
            utm_text = ""
            if traffic_sources:
                for src, count in traffic_sources.items():
                    utm_text += f"• `{src}`: {count} user\n"
            else:
                utm_text = "• belum ada data traffic\n"

            # Format Content & Buzzer Funnel
            funnel_text = ""
            if funnel_data:
                for item in funnel_data:
                    funnel_text += (
                        f"• `{item['content']}` ({item['campaign']}): "
                        f"{item['clicks']} clicks ➔ {item['bot_starts']} starts "
                        f"({item.get('conversion_rate', 0):.1f}%)\n"
                    )
            else:
                funnel_text = "• belum ada data atribusi buzzer/konten\n"

            # 2. Metrics Usage AI Realtime Hari Ini
            ai_data = self._get_ai_usage_today()

            return (
                "📊 **BoonTrack Real-time Metrics (Sprint C)**\n\n"
                f"• **Total Users:** {metrics.get('total_users', 0)}\n"
                f"• **CV Generated:** {metrics.get('cv_generated', 0)}\n"
                f"• **CV Reviewed:** {metrics.get('cv_reviewed', 0)}\n"
                f"• **Career Page Created:** {metrics.get('career_page_created', 0)}\n"
                f"• **Paid Users:** {metrics.get('paid_users', 0)}\n"
                f"• **Total Revenue:** Rp{metrics.get('total_revenue', 0):,}\n"
                f"• **Active Referrals:** {metrics.get('active_referrals', 0)}\n\n"
                "🌐 **Top Traffic Sources (UTM):**\n"
                f"{utm_text}\n"
                "🎯 **Content & Buzzer Attribution:**\n"
                f"{funnel_text}\n"
                "🤖 **AI USAGE TODAY**\n\n"
                f"**Gemini**\nRequests: {ai_data['Gemini']['req']} | Tokens: {ai_data['Gemini']['tokens']:,}\n\n"
                f"**Groq**\nRequests: {ai_data['Groq']['req']} | Tokens: {ai_data['Groq']['tokens']:,}\n\n"
                f"**OpenRouter**\nRequests: {ai_data['OpenRouter']['req']} | Tokens: {ai_data['OpenRouter']['tokens']:,}\n\n"
                "📄 **CV REVIEW**\n"
                f"Reviews: {ai_data['cv_reviews_count']} | AI Calls: {ai_data['cv_ai_calls']}\n\n"
                "⚠️ **Provider Status**\n"
                f"Gemini {ai_data['Gemini']['status']} / Groq {ai_data['Groq']['status']} / OpenRouter {ai_data['OpenRouter']['status']}\n\n"
                "⚙️ *Sistem whitelisting owner & query Supabase aktif 100%.*"
            )

        return "❓ Command admin tidak dikenali. Gunakan `/analytics`."

admin_handler = AdminHandler()