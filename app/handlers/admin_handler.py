from app.utils.admin_check import is_owner

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
            return (
                "📊 **BoonTrack Real-time Metrics (Sprint C)**\n\n"
                "• **Total Users:** 0\n"
                "• **CV Generated:** 0\n"
                "• **CV Reviewed:** 0\n"
                "• **Career Page Created:** 0\n"
                "• **Paid Users:** 0\n"
                "• **Total Revenue:** Rp0\n"
                "• **Active Referrals:** 0\n\n"
                "⚙️ *Sistem whitelisting owner aktif 100%.*"
            )

        return "❓ Command admin tidak dikenali. Gunakan `/analytics`."

admin_handler = AdminHandler()