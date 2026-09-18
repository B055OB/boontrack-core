"""
app/services/whatsapp/session_router.py
------------------------------------------
Dynamic tenant resolver untuk demo portal WhatsApp,
termasuk session greeting maps dan routing logic.
"""
import os
import re
import logging
from typing import Optional, Dict, Any, Tuple

from app.services.whatsapp.credentials import (
    normalize_phone_number,
    reset_whatsapp_user_session,
    user_session_states,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Demo portal constants (DEACTIVATED)
# Seluruh chatbot percakapan demo telah dinonaktifkan total.
# Nomor resmi WABA (+6285179555449) hanya melayani Gateway Notifikasi & Aktivasi Sistem.
# ---------------------------------------------------------------------------

DEMO_MENU_TEXT = ""
DEMO_TENANT_GREETINGS: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Dynamic tenant resolver
# ---------------------------------------------------------------------------

def resolve_dynamic_tenant_for_whatsapp(
    phone_id: str,
    from_phone: str,
    message_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[str, bool]:
    clean_phone = normalize_phone_number(from_phone)
    text = (message_text or "").strip()
    text_lower = text.lower()
    clean_phone_id = str(phone_id).strip()
    career_phone_id = os.getenv("CAREER_PHONE_NUMBER_ID", "1340866379104241")
    is_career_phone = (clean_phone_id == "1340866379104241" or clean_phone_id == career_phone_id)

    # =========================================================================
    # JALUR KHUSUS NOMOR CAREER ASSISTANT (TOTAL ISOLATION)
    # =========================================================================
    if is_career_phone:
        # Jika user di nomor Career ketik #reset, bersihkan session tapi TETAP di boontrack-career
        if text_lower in ("#reset", "reset"):
            if clean_phone:
                reset_whatsapp_user_session(clean_phone)
            logger.info(f"[DYNAMIC TENANT WA] Career sender {clean_phone} reset session -> kept in boontrack-career")
            return "boontrack-career", False

        # Nomor Career TIDAK BOLEH bocor ke demo portal toko ritel/B2B sama sekali!
        return "boontrack-career", False

    # =========================================================================
    # JALUR NOMOR OM BUDI / DEMO NUMBER (SANDBOX)
    # =========================================================================
    option_map = {
        "1": "boontrack-shop",
        "boontrack-shop": "boontrack-shop",
        "shop": "boontrack-shop",
        "retail": "boontrack-shop",
        "2": "growthplus",
        "growth": "growthplus",
        "growthplus": "growthplus",
        "growth+": "growthplus",
        "tier growth+": "growthplus",
        "3": "proscale",
        "proscale": "proscale",
        "pro scale": "proscale",
        "tier proscale": "proscale",
        "waba": "proscale",
        "4": "onlineboost",
        "onlineboost": "onlineboost",
        "digital": "onlineboost",
        "course": "onlineboost",
        "suhu-ads-masterclass": "onlineboost",
        "suhu ads": "onlineboost",
        "bale": "bale_pananggeuhan",
        "bale pananggeuhan": "bale_pananggeuhan",
        "gym": "atmosfitnes",
        "prima fit": "atmosfitnes",
        "prima fit gym": "atmosfitnes",
        "atmosfitnes": "atmosfitnes",
    }

    if text_lower in ("#reset", "reset", "menu utama", "#menu", "menu", "demo"):
        if clean_phone:
            reset_whatsapp_user_session(clean_phone)
            user_session_states[clean_phone] = "AWAITING_PORTAL_CHOICE"
        logger.info(f"[DYNAMIC TENANT WA] Sender {clean_phone} triggered reset/demo menu")
        return "__MENU__", False

    if user_session_states.get(clean_phone) == "AWAITING_PORTAL_CHOICE" and text_lower in option_map:
        target_slug = option_map[text_lower]
        if clean_phone:
            from app.services.session_store import set_user_tenant_session
            set_user_tenant_session(clean_phone, target_slug)
        logger.info(f"[DYNAMIC TENANT WA] Sender {clean_phone} selected option '{text_lower}' -> locked to '{target_slug}'")
        return target_slug, True

    from app.services.session_store import get_user_tenant_session, set_user_tenant_session
    locked_tenant = get_user_tenant_session(clean_phone, text)
    if locked_tenant and locked_tenant in ("onlineboost", "growthplus", "proscale", "boontrack-shop"):
        return locked_tenant, False

    match = re.search(
        r"saya\s+baru\s+(?:saja\s+)?(?:mendaftar|daftar)\s+toko\s+([a-zA-Z0-9\-_]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"toko\s*:\s*([a-zA-Z0-9\-_]+)", text, re.IGNORECASE)

    if match:
        target_slug = match.group(1).lower().strip()
        if clean_phone:
            set_user_tenant_session(clean_phone, target_slug)
        logger.info(f"[DYNAMIC TENANT WA] Bound sender {clean_phone} to store '{target_slug}' via onboarding message")
        return target_slug, True

    # CATATAN: Fallback ke "boontrack-shop" untuk pesan greeting ("halo", "hi", dll)
    # telah DIHAPUS per arsitektur multi-tenant.
    # Pesan dari Evolution webhook sudah membawa tenant_slug eksplisit dari URL path.
    # Fungsi ini seharusnya hanya dipanggil untuk WABA demo portal jika ada session aktif.
    # Jika tidak ada session, kembalikan None agar handler upstream bisa memutuskan.
    if text_lower in ("halo", "hi", "p", "test", "tes", "hai", "start", "info"):
        # Jangan fallback ke demo tenant - kembalikan None agar tidak ada respons spurious
        return "__NO_TENANT__", False

    if clean_phone_id == "1268977686299719":
        # Phone ID ini sudah tidak digunakan sebagai routing signal
        return "__NO_TENANT__", False

    try:
        from app.services.onboarding_service import onboarding_service
        latest_slug = onboarding_service.get_latest_commerce_tenant()
        if latest_slug:
            if clean_phone:
                set_user_tenant_session(clean_phone, latest_slug)
            return latest_slug, False
    except Exception as e:
        logger.warning(f"[DYNAMIC TENANT WA] Failed to query latest commerce tenant: {e}")

    return "onlineboost", False
