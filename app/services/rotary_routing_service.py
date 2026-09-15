import logging
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)

class RotaryRoutingService:
    """
    Rotary / Round-Robin Routing Engine untuk BoonTrack Inbox.
    Mengelola penugasan percakapan inbound ke Customer Service (CS) Agen
    menggunakan algoritma beban terendah (least-busy agent) dengan batas kapasitas (max_active_chats).
    """

    def __init__(self):
        pass

    def _get_connection(self):
        return get_db_connection()

    def create_agent(
        self,
        tenant_id: str,
        name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        role: str = "agent",
        presence: str = "offline",
        max_active_chats: int = 10,
    ) -> Dict[str, Any]:
        """Membuat agen CS baru untuk tenant tertentu."""
        role_val = role.lower().strip()
        if role_val not in ("admin", "agent"):
            raise ValueError("Role harus 'admin' atau 'agent'")

        presence_val = presence.lower().strip()
        if presence_val not in ("active", "break", "offline"):
            raise ValueError("Presence harus 'active', 'break', atau 'offline'")

        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO cs_agents (tenant_id, name, phone, email, role, presence, max_active_chats)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, tenant_id, name, phone, email, role, presence, max_active_chats, created_at, updated_at;
                    """,
                    (tenant_id, name, phone, email, role_val, presence_val, max_active_chats)
                )
                agent = dict(cur.fetchone())
                conn.commit()
                agent["id"] = str(agent["id"])
                return agent
        finally:
            conn.close()

    def update_agent_presence(self, agent_id: str, presence: str) -> Dict[str, Any]:
        """Mengubah presence agen ('active', 'break', 'offline')."""
        presence_val = presence.lower().strip()
        if presence_val not in ("active", "break", "offline"):
            raise ValueError("Presence harus 'active', 'break', atau 'offline'")

        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE cs_agents
                    SET presence = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, tenant_id, name, phone, email, role, presence, max_active_chats, updated_at;
                    """,
                    (presence_val, agent_id)
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Agent with ID {agent_id} not found.")
                conn.commit()
                res = dict(row)
                res["id"] = str(res["id"])
                return res
        finally:
            conn.close()

    def get_tenant_agents(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Mengambil seluruh agen pada tenant berserta jumlah chat aktif masing-masing."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT 
                        a.id, a.tenant_id, a.name, a.phone, a.email, a.role, a.presence, a.max_active_chats,
                        a.created_at, a.updated_at,
                        COALESCE(COUNT(c.id) FILTER (WHERE c.status = 'assigned'), 0)::int AS active_chats
                    FROM cs_agents a
                    LEFT JOIN conversations c ON c.assigned_agent_id = a.id
                    WHERE a.tenant_id = %s
                    GROUP BY a.id
                    ORDER BY a.name ASC;
                    """,
                    (tenant_id,)
                )
                rows = cur.fetchall()
                result = []
                for r in rows:
                    item = dict(r)
                    item["id"] = str(item["id"])
                    result.append(item)
                return result
        finally:
            conn.close()

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Mengambil data percakapan berdasarkan ID."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, phone_number, contact_name, assigned_agent_id, status, bot_mode, bot_paused, updated_at
                    FROM conversations
                    WHERE id = %s;
                    """,
                    (conversation_id,)
                )
                row = cur.fetchone()
                if not row:
                    return None
                conv = dict(row)
                conv["id"] = str(conv["id"])
                if conv.get("assigned_agent_id"):
                    conv["assigned_agent_id"] = str(conv["assigned_agent_id"])
                return conv
        finally:
            conn.close()

    def assign_inbound_chat(self, tenant_id: str, conversation_id: str) -> Dict[str, Any]:
        """
        Rotary Routing Engine:
        1. Filter agen berstatus 'active' pada tenant_id.
        2. Hitung jumlah chat aktif masing-masing agen ('assigned').
        3. Filter agen yang belum melebihi max_active_chats (active_chats < max_active_chats).
        4. Urutkan berdasarkan beban terendah (least busy) dan rotasi giliran (updated_at ASC, id ASC).
        5. Jika ada agen memenuhi syarat: assign ke percakapan.
        6. Jika tidak ada agen online/tersedia: set status 'unassigned', bot_mode 'AI_ACTIVE', biarkan bot AI menangani.
        """
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Pastikan percakapan ada
                cur.execute(
                    "SELECT id, tenant_id, phone_number, status, bot_mode, bot_paused FROM conversations WHERE id = %s;",
                    (conversation_id,)
                )
                conv = cur.fetchone()
                if not conv:
                    logger.warning(f"[Rotary Routing] Conversation {conversation_id} not found.")
                    return {
                        "success": False,
                        "status": "error",
                        "error": f"Conversation {conversation_id} not found."
                    }

                # 2. Cari agen aktif dengan kapasitas tersisa
                cur.execute(
                    """
                    SELECT 
                        a.id, a.name, a.email, a.phone, a.max_active_chats, a.updated_at,
                        COALESCE(COUNT(c.id) FILTER (WHERE c.status = 'assigned'), 0)::int AS active_chats
                    FROM cs_agents a
                    LEFT JOIN conversations c ON c.assigned_agent_id = a.id
                    WHERE a.tenant_id = %s AND a.presence = 'active'
                    GROUP BY a.id
                    HAVING COALESCE(COUNT(c.id) FILTER (WHERE c.status = 'assigned'), 0) < a.max_active_chats
                    ORDER BY active_chats ASC, a.updated_at ASC, a.id ASC
                    LIMIT 1;
                    """,
                    (tenant_id,)
                )
                selected_agent = cur.fetchone()

                if selected_agent:
                    agent_id_str = str(selected_agent["id"])
                    # Tetapkan agen ke percakapan
                    cur.execute(
                        """
                        UPDATE conversations
                        SET assigned_agent_id = %s,
                            status = 'assigned',
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, tenant_id, phone_number, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                        """,
                        (selected_agent["id"], conversation_id)
                    )
                    conn.commit()

                    logger.info(
                        f"[Rotary Routing] Assigned chat {conversation_id} to agent {selected_agent['name']} "
                        f"(Load: {selected_agent['active_chats'] + 1}/{selected_agent['max_active_chats']})"
                    )

                    return {
                        "success": True,
                        "status": "assigned",
                        "conversation_id": str(conversation_id),
                        "assigned_agent_id": agent_id_str,
                        "agent_name": selected_agent["name"],
                        "agent_email": selected_agent["email"],
                        "agent_phone": selected_agent["phone"],
                        "active_chats": selected_agent["active_chats"] + 1,
                        "max_active_chats": selected_agent["max_active_chats"],
                        "bot_mode": conv.get("bot_mode") or "AI_ACTIVE",
                    }
                else:
                    # Tidak ada agen online atau semua penuh -> Biarkan unassigned, bot menangani
                    cur.execute(
                        """
                        UPDATE conversations
                        SET status = 'unassigned',
                            assigned_agent_id = NULL,
                            bot_mode = 'AI_ACTIVE',
                            bot_paused = FALSE,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, tenant_id, phone_number, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                        """,
                        (conversation_id,)
                    )
                    conn.commit()

                    logger.info(
                        f"[Rotary Routing] No active agents available for tenant {tenant_id}. "
                        f"Chat {conversation_id} unassigned. Fallback to AI_ACTIVE."
                    )

                    return {
                        "success": True,
                        "status": "unassigned",
                        "conversation_id": str(conversation_id),
                        "assigned_agent_id": None,
                        "bot_mode": "AI_ACTIVE",
                        "bot_paused": False,
                        "reason": "NO_AVAILABLE_AGENTS"
                    }
        finally:
            conn.close()

    def set_human_takeover(
        self,
        conversation_id: str,
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Memicu Human Takeover:
        - Mutasi status percakapan menjadi 'HUMAN_ACTIVE'.
        - Set flag bot_paused = TRUE agar AI tidak membalas otomatis.
        - Jika agent_id disediakan, assign ke agen tersebut dan set status = 'assigned'.
        """
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if agent_id:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET bot_mode = 'HUMAN_ACTIVE',
                            bot_paused = TRUE,
                            status = 'assigned',
                            assigned_agent_id = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, tenant_id, phone_number, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                        """,
                        (agent_id, conversation_id)
                    )
                else:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET bot_mode = 'HUMAN_ACTIVE',
                            bot_paused = TRUE,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, tenant_id, phone_number, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                        """,
                        (conversation_id,)
                    )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Conversation {conversation_id} not found.")
                conn.commit()
                res = dict(row)
                res["id"] = str(res["id"])
                if res.get("assigned_agent_id"):
                    res["assigned_agent_id"] = str(res["assigned_agent_id"])
                return res
        finally:
            conn.close()

    def set_bot_mode(
        self,
        conversation_id: str,
        bot_mode: str,
        bot_paused: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Mengubah mode bot secara eksplisit ('AI_ACTIVE' | 'HUMAN_ACTIVE')."""
        mode_val = bot_mode.upper().strip()
        if mode_val not in ("AI_ACTIVE", "HUMAN_ACTIVE"):
            raise ValueError("bot_mode harus 'AI_ACTIVE' atau 'HUMAN_ACTIVE'")

        if bot_paused is None:
            # Otomatis: jika HUMAN_ACTIVE -> paused=True, jika AI_ACTIVE -> paused=False
            bot_paused = (mode_val == "HUMAN_ACTIVE")

        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET bot_mode = %s,
                        bot_paused = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, tenant_id, phone_number, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                    """,
                    (mode_val, bot_paused, conversation_id)
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Conversation {conversation_id} not found.")
                conn.commit()
                res = dict(row)
                res["id"] = str(res["id"])
                if res.get("assigned_agent_id"):
                    res["assigned_agent_id"] = str(res["assigned_agent_id"])
                return res
        finally:
            conn.close()

    def resolve_conversation(self, conversation_id: str) -> Dict[str, Any]:
        """Menyelesaikan percakapan (status = 'resolved') dan mengembalikan mode ke AI_ACTIVE."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET status = 'resolved',
                        bot_mode = 'AI_ACTIVE',
                        bot_paused = FALSE,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, tenant_id, phone_number, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                    """,
                    (conversation_id,)
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Conversation {conversation_id} not found.")
                conn.commit()
                res = dict(row)
                res["id"] = str(res["id"])
                if res.get("assigned_agent_id"):
                    res["assigned_agent_id"] = str(res["assigned_agent_id"])
                return res
        finally:
            conn.close()

    def is_bot_paused_for_phone(self, tenant_id: str, phone: str) -> bool:
        """
        Mengecek apakah auto-reply bot di-pause untuk nomor pelanggan tertentu pada tenant_id.
        Digunakan oleh agent_service untuk mencegah AI membalas otomatis saat CS sedang takeover.
        """
        from app.services.whatsapp_service import normalize_phone_number
        clean_digits = normalize_phone_number(phone or "")
        if not clean_digits:
            return False

        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT bot_mode, bot_paused
                    FROM conversations
                    WHERE tenant_id = %s AND (phone_number = %s OR phone_number LIKE %s)
                    ORDER BY updated_at DESC
                    LIMIT 1;
                    """,
                    (tenant_id, clean_digits, f"%{clean_digits[-8:]}")
                )
                row = cur.fetchone()
                if not row:
                    return False
                return bool(row.get("bot_paused")) or (row.get("bot_mode") == "HUMAN_ACTIVE")
        finally:
            conn.close()

    def ensure_conversation_and_mark_unassigned(
        self,
        tenant_id: str,
        phone_or_session: str,
        contact_name: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Memastikan record percakapan tersedia dan memutasi statusnya menjadi 'unassigned'.
        Digunakan oleh Zero-Hallucination Safe Guard saat katalog kosong atau pertanyaan
        pelanggan di luar database sehingga tiket dialihkan ke antrean CS di Inbox.
        """
        from app.services.whatsapp_service import normalize_phone_number
        identifier = str(phone_or_session or "").strip()
        cleaned_phone = normalize_phone_number(identifier) if any(c.isdigit() for c in identifier) else identifier
        final_id = cleaned_phone or identifier or f"sess_{uuid.uuid4().hex[:8]}"

        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, tenant_id, phone_number, status, bot_mode, assigned_agent_id
                    FROM conversations
                    WHERE tenant_id = %s AND phone_number = %s
                    ORDER BY updated_at DESC
                    LIMIT 1;
                    """,
                    (tenant_id, final_id)
                )
                existing = cur.fetchone()

                if existing:
                    conv_id = str(existing["id"])
                    cur.execute(
                        """
                        UPDATE conversations
                        SET status = 'unassigned',
                            assigned_agent_id = NULL,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, tenant_id, phone_number, contact_name, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                        """,
                        (existing["id"],)
                    )
                    updated = cur.fetchone()
                    conn.commit()
                    res = dict(updated)
                    res["id"] = str(res["id"])
                    logger.info(f"[Rotary Routing Guardrail] Marked conversation {conv_id} as UNASSIGNED. Reason: {reason}")
                    return res
                else:
                    new_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO conversations (id, tenant_id, phone_number, contact_name, status, bot_mode, bot_paused, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, 'unassigned', 'AI_ACTIVE', FALSE, NOW(), NOW())
                        RETURNING id, tenant_id, phone_number, contact_name, assigned_agent_id, status, bot_mode, bot_paused, updated_at;
                        """,
                        (new_id, tenant_id, final_id, contact_name or "Pelanggan")
                    )
                    created = cur.fetchone()
                    conn.commit()
                    res = dict(created)
                    res["id"] = str(res["id"])
                    logger.info(f"[Rotary Routing Guardrail] Created and marked conversation {new_id} as UNASSIGNED. Reason: {reason}")
                    return res
        except Exception as err:
            logger.warning(f"[Rotary Routing Warning] ensure_conversation_and_mark_unassigned error: {err}")
            return {
                "success": False,
                "status": "unassigned",
                "phone_number": final_id,
                "error": str(err)
            }
        finally:
            conn.close()

rotary_routing_service = RotaryRoutingService()

