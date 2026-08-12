from app.utils.admin_check import is_owner
from app.services.analytics_service import analytics_service

class AdminHandler:
    """
    Handler khusus command internal Owner/Admin.
    """

    async def handle_admin_command(self, user_id: int, command_text: str) -> str:
        # Security Guard: Tolak jika bukan Owner
        if not is_owner(user_id):
            return "⛔ Akses ditolak. Command ini hanya untuk Admin/Owner."

        clean_cmd = command_text.strip().lower()

        if clean_cmd in ["/analytics", "/admin"]:
            # Ambil data real-time & breakdown UTM dari analytics_service
            metrics = await analytics_service.get_realtime_metrics()
            traffic_sources = await analytics_service.get_traffic_sources()

            # Format teks breakdown UTM
            utm_text = ""
            if traffic_sources:
                for src, count in traffic_sources.items():
                    utm_text += f"• `{src}`: {count} user\n"
            else:
                utm_text = "• belum ada data traffic\n"

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
                "⚙️ *Sistem whitelisting owner & query Supabase aktif 100%.*"
            )

        return "❓ Command admin tidak dikenali. Gunakan `/analytics`."

admin_handler = AdminHandler()