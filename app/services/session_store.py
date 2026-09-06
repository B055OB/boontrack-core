import os
import json
import logging
import re
from typing import Optional, Dict, Any

logger = logging.getLogger("SESSION_STORE")

DISK_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".demo_sessions.json")

# In-memory session references imported from whatsapp_service
from app.services.whatsapp_service import (
    user_tenant_sessions,
    user_session_states,
    normalize_phone_number
)

DEMO_KEYWORDS_ONLINEBOOST = [
    "paid traffic", "traffic", "ads", "iklan", "youtube", "cpm", "digital marketing",
    "ecourse", "kursus", "suhu ads", "marketing", "onlineboost", "modul", "silabus",
    "meta ads", "tiktok ads", "google ads", "affiliate", "landing page"
]

DEMO_KEYWORDS_GROWTHPLUS = [
    "growthplus", "growth+", "tier growth", "growth plus"
]

DEMO_KEYWORDS_PROSCALE = [
    "proscale", "tier proscale", "enterprise", "waba"
]


def detect_demo_intent_keyword(text: str) -> Optional[str]:
    """Mendeteksi apakah pesan mengarah kuat ke produk salah satu toko demo."""
    if not text:
        return None
    lower = text.lower()

    if any(kw in lower for kw in DEMO_KEYWORDS_ONLINEBOOST):
        return "onlineboost"
    if any(kw in lower for kw in DEMO_KEYWORDS_GROWTHPLUS):
        return "growthplus"
    if any(kw in lower for kw in DEMO_KEYWORDS_PROSCALE):
        return "proscale"

    return None


def _load_disk_cache() -> Dict[str, Any]:
    try:
        if os.path.exists(DISK_CACHE_PATH):
            with open(DISK_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.debug(f"[DISK CACHE LOAD ERROR] {e}")
    return {}


def _save_disk_cache(data: Dict[str, Any]) -> None:
    try:
        with open(DISK_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug(f"[DISK CACHE SAVE ERROR] {e}")


def _save_to_db(phone: str, tenant_slug: str, state: str = "ACTIVE", context: Optional[dict] = None) -> None:
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO demo_user_sessions (phone, tenant_slug, state, context_json, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (phone) DO UPDATE 
            SET tenant_slug = EXCLUDED.tenant_slug,
                state = EXCLUDED.state,
                context_json = COALESCE(EXCLUDED.context_json, demo_user_sessions.context_json),
                updated_at = CURRENT_TIMESTAMP;
        """, (phone, tenant_slug, state, json.dumps(context or {})))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"[SESSION STORE DB SAVE ERROR] {e}")


def _load_from_db(phone: str) -> Optional[Dict[str, Any]]:
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT tenant_slug, state, context_json FROM demo_user_sessions WHERE phone = %s", (phone,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            ctx = row[2]
            if isinstance(ctx, str):
                try:
                    ctx = json.loads(ctx)
                except Exception:
                    ctx = {}
            return {"tenant_slug": str(row[0]).strip(), "state": str(row[1]).strip() if row[1] else "ACTIVE", "context_json": ctx or {}}
    except Exception as e:
        logger.debug(f"[SESSION STORE DB LOAD] {e}")
    return None


def _delete_from_db(phone: str) -> None:
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM demo_user_sessions WHERE phone = %s", (phone,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.debug(f"[SESSION STORE DB DELETE] {e}")


def _recover_from_recent_messages(phone: str) -> Optional[str]:
    """Pemulihan darurat jika sesi kosong: cek riwayat pesan terakhir di Supabase."""
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT tenant_id FROM messages 
            WHERE user_phone = %s 
              AND tenant_id IN ('onlineboost', 'growthplus', 'proscale')
            ORDER BY created_at DESC 
            LIMIT 1;
        """, (phone,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return str(row[0]).strip()
    except Exception as e:
        logger.debug(f"[SESSION RECOVERY ERROR] {e}")
    return None


def get_user_tenant_session(phone: str, message_text: str = "") -> Optional[str]:
    """Membaca tenant sesi aktif user dengan hirarki: In-Memory -> Disk Cache -> PostgreSQL -> History Recovery -> Keyword Detection."""
    clean_p = normalize_phone_number(phone)
    if not clean_p:
        return None

    # 1. In-Memory
    if clean_p in user_tenant_sessions and user_tenant_sessions[clean_p]:
        return user_tenant_sessions[clean_p]

    # 2. Disk Cache
    disk_data = _load_disk_cache()
    if clean_p in disk_data:
        cached = disk_data[clean_p]
        tenant = cached.get("tenant_slug")
        if tenant:
            user_tenant_sessions[clean_p] = tenant
            user_session_states[clean_p] = cached.get("state", "ACTIVE")
            logger.info(f"[SESSION STORE] Restored session for {clean_p} -> '{tenant}' from disk cache.")
            return tenant

    # 3. PostgreSQL Database
    db_res = _load_from_db(clean_p)
    if db_res and db_res.get("tenant_slug"):
        tenant = db_res["tenant_slug"]
        user_tenant_sessions[clean_p] = tenant
        user_session_states[clean_p] = db_res.get("state", "ACTIVE")
        disk_data[clean_p] = db_res
        _save_disk_cache(disk_data)
        logger.info(f"[SESSION STORE] Restored session for {clean_p} -> '{tenant}' from database.")
        return tenant

    # 4. History Recovery dari pesan terakhir
    recovered = _recover_from_recent_messages(clean_p)
    if recovered:
        set_user_tenant_session(clean_p, recovered)
        logger.info(f"[SESSION STORE] Recovered session for {clean_p} -> '{recovered}' from message history.")
        return recovered

    # 5. Keyword Inference jika pesan jelas-jelas mengenai produk demo
    keyword_tenant = detect_demo_intent_keyword(message_text)
    if keyword_tenant:
        set_user_tenant_session(clean_p, keyword_tenant)
        logger.info(f"[SESSION STORE] Inferred session for {clean_p} -> '{keyword_tenant}' from message keyword.")
        return keyword_tenant

    return None


def set_user_tenant_session(phone: str, tenant_slug: str, state: str = "ACTIVE", context: Optional[dict] = None) -> None:
    """Menyimpan session lock secara persisten (In-Memory, Disk Cache, dan Database)."""
    clean_p = normalize_phone_number(phone)
    if not clean_p or not tenant_slug:
        return

    user_tenant_sessions[clean_p] = tenant_slug
    user_session_states[clean_p] = state

    # Disk Cache
    disk_data = _load_disk_cache()
    disk_data[clean_p] = {
        "tenant_slug": tenant_slug,
        "state": state,
        "context_json": context or {}
    }
    _save_disk_cache(disk_data)

    # Database
    _save_to_db(clean_p, tenant_slug, state, context)
    logger.info(f"[SESSION STORE] Persistent lock saved: {clean_p} -> '{tenant_slug}'")


def clear_user_tenant_session(phone: str) -> None:
    """Menghapus session lock user secara menyeluruh saat perintah #reset dijalankan."""
    clean_p = normalize_phone_number(phone)
    if not clean_p:
        return

    user_tenant_sessions.pop(clean_p, None)
    user_session_states.pop(clean_p, None)

    disk_data = _load_disk_cache()
    disk_data.pop(clean_p, None)
    _save_disk_cache(disk_data)

    _delete_from_db(clean_p)
    logger.info(f"[SESSION STORE] Cleared session lock for {clean_p}")
