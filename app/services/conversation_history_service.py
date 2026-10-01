"""
app/services/conversation_history_service.py
Service terpadu untuk memuat riwayat obrolan pelanggan (Conversation History)
dari tabel Supabase 'messages' secara deterministik (Single Source of Truth).
"""

import logging
from typing import List, Dict, Any, Optional
from app.services.whatsapp.credentials import get_supabase
from app.services.whatsapp_service import normalize_phone_number

logger = logging.getLogger("CONVERSATION_HISTORY")


async def get_recent_chat_history(
    tenant_slug: str,
    sender_phone: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Mengambil riwayat percakapan 5-10 pesan terakhir dari Supabase table 'messages'.
    
    Returns:
        List of dicts: [
            {"role": "user"|"assistant", "sender": "user"|"bot", "content": "...", "text": "...", "created_at": "..."},
            ...
        ]
        Diurutkan secara kronologis (pesan terlama -> pesan terbaru).
    """
    clean_slug = str(tenant_slug or "").strip().lower()
    clean_phone = normalize_phone_number(sender_phone) if any(c.isdigit() for c in str(sender_phone or "")) else str(sender_phone or "").strip()
    if not clean_slug or not clean_phone:
        return []

    try:
        supabase = get_supabase()
        if not supabase:
            return []

        # Query messages untuk tenant dan sender phone
        res = (
            supabase.from_("messages")
            .select("sender, text, created_at, user_phone")
            .eq("tenant_id", clean_slug)
            .or_(f"user_phone.eq.{clean_phone},user_id.eq.{clean_phone}")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        if not res or not res.data:
            return []

        raw_msgs = res.data
        # Urutkan dari pesan lama ke pesan baru (chronological order)
        raw_msgs.reverse()

        history: List[Dict[str, Any]] = []
        for m in raw_msgs:
            sender_raw = str(m.get("sender") or "").strip().lower()
            text = str(m.get("text") or "").strip()
            if not text:
                continue

            # Petakan sender ke role standar LLM (user / assistant)
            if sender_raw in ("bot", "ai", "assistant", "system", "admin"):
                role = "assistant"
            else:
                role = "user"

            history.append({
                "role": role,
                "sender": role,
                "content": text,
                "text": text,
                "created_at": m.get("created_at"),
            })

        return history
    except Exception as e:
        logger.warning(f"[CONVERSATION_HISTORY] Failed to load history for '{clean_slug}':{clean_phone}: {e}")
        return []
