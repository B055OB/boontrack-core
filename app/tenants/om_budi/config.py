import os
from typing import Dict, List, Any

TENANT_ID = "om_budi"
TENANT_NAME = "Om Budi Community & Mentorship"
DEFAULT_VERIFY_TOKEN = os.getenv("OM_BUDI_VERIFY_TOKEN", "om_budi_secure_token_2026")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("OM_BUDI_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("OM_BUDI_ACCESS_TOKEN", "")

# Keyword pemicu eskalasi ke CS / Admin Manual
ESCALATION_KEYWORDS: List[str] = [
    "admin",
    "cs",
    "komplain",
    "refund",
    "human",
    "petugas",
    "bicara dengan admin",
    "bantuan manusia",
    "hubungi om budi"
]

# Daftar Segmen Member
MEMBER_SEGMENTS: Dict[str, Dict[str, Any]] = {
    "FREE_TIER": {
        "label": "Member Gratis / Leads",
        "description": "Pengikut webinar publik, pembaca newsletter, calon pembeli kursus/mentoring.",
        "support_sla": "Best Effort"
    },
    "VIP_MEMBER": {
        "label": "VIP / Mastermind Member",
        "description": "Member berbayar aktif program akselerasi bisnis & mentorship eksklusif Om Budi.",
        "support_sla": "Prioritas Tinggi (Dedicated AI & Fast Escalation)"
    },
    "ALUMNI": {
        "label": "Alumni Program",
        "description": "Pernah menyelesaikan batch program sebelumnya.",
        "support_sla": "Standard"
    }
}