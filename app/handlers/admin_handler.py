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
            # Ambil data real-time dari Supabase
            metrics = await analytics_service.get_realtime_metrics()

            return (
                "📊 **BoonTrack Real-time Metrics (Sprint C)**\n\n"
                f"• **Total Users:** {metrics['total_users']}\n"
                f"• **CV Generated:** {metrics['cv_generated']}\n"
                f"• **CV Reviewed:** {metrics['cv_reviewed']}\n"
                f"• **Career Page Created:** {metrics['career_page_created']}\n"
                f"• **Paid Users:** {metrics['paid_users']}\n"
                f"• **Total Revenue:** Rp{metrics['total_revenue']:,}\n"
                f"• **Active Referrals:** {metrics['active_referrals']}\n\n"
                "⚙️ *Sistem whitelisting owner & query Supabase aktif 100%.*"
            )

        return "❓ Command admin tidak dikenali. Gunakan `/analytics`."

admin_handler = AdminHandler()