"""app/services/outbound_registry.py
Outbound Message Registry & Telemetry Helper.

Architectural Authority (§4.2, §8.4, §9.8):
- Records all bot outbound messages to avoid self-echo and loop storms.
- Dual-layer storage:
  1. Fast in-memory Set/LRU for sub-millisecond Layer 2 Self-Echo lookups.
  2. Persistent write to Supabase `outbound_messages` table:
     (id, tenant_id, conversation_id, runtime_instance_id, wa_message_id, recipient_jid, message_type, content_hash, source, created_at).
"""

import os
import uuid
import hashlib
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set, List

logger = logging.getLogger("OUTBOUND_MESSAGE_REGISTRY")


class OutboundMessageRegistry:
    """Registry for all outbound messages dispatched by BoonTrack platform bots."""

    def __init__(self):
        self._outbound_ids: Set[str] = set()
        self._outbound_records: Dict[str, Dict[str, Any]] = {}
        self._recipient_records: Dict[str, List[Dict[str, Any]]] = {}

    def register_outbound(
        self,
        wa_message_id: str,
        tenant_id: str,
        recipient_jid: str,
        content: str = "",
        message_type: str = "text",
        source: str = "bot",
        conversation_id: Optional[str] = None,
        runtime_instance_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Registers an outbound message ID to the registry before or upon dispatch.
        """
        if not wa_message_id:
            return {}

        wa_id_clean = str(wa_message_id).strip()
        content_str = str(content or "")
        content_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
        now_iso = datetime.now(timezone.utc).isoformat()

        record: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id or "default"),
            "conversation_id": conversation_id,
            "runtime_instance_id": runtime_instance_id,
            "wa_message_id": wa_id_clean,
            "recipient_jid": str(recipient_jid or ""),
            "message_type": message_type,
            "content_hash": content_hash,
            "source": source,
            "created_at": now_iso,
        }

        # 1. In-memory fast cache
        self._outbound_ids.add(wa_id_clean)
        self._outbound_records[wa_id_clean] = record
        
        clean_recipient = str(recipient_jid or "").split("@")[0]
        rec_list = self._recipient_records.setdefault(clean_recipient, [])
        rec_list.append(record)
        # Limit in-memory recipient records to last 100
        if len(rec_list) > 100:
            self._recipient_records[clean_recipient] = rec_list[-100:]

        # 2. Async persistent write to Supabase outbound_messages table
        try:
            from app.services.whatsapp_service import get_supabase
            sb = get_supabase()
            if sb:
                async def _persist():
                    try:
                        sb.table("outbound_messages").insert(record).execute()
                    except Exception as err:
                        logger.debug(f"[OUTBOUND_REGISTRY_DB_WARN] Could not persist message {wa_id_clean}: {err}")

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_persist())
                except RuntimeError:
                    # Running in sync context or test
                    pass
        except Exception as e:
            logger.debug(f"[OUTBOUND_REGISTRY_INIT_WARN] {e}")

        logger.info(
            f"[OUTBOUND_REGISTRY] Registered wa_message_id='{wa_id_clean}' | "
            f"tenant='{tenant_id}' | recipient='{recipient_jid}' | source='{source}'"
        )
        return record

    def is_outbound_message(self, wa_message_id: str) -> bool:
        """
        Layer 2 Self-Echo Detection:
        Checks whether wa_message_id was dispatched by our bot runtime.
        """
        if not wa_message_id:
            return False

        clean_id = str(wa_message_id).strip()
        if clean_id in self._outbound_ids:
            return True

        # Fallback to Supabase database lookup
        try:
            from app.services.whatsapp_service import get_supabase
            sb = get_supabase()
            if sb:
                res = sb.table("outbound_messages").select("id").eq("wa_message_id", clean_id).limit(1).execute()
                if res and res.data:
                    self._outbound_ids.add(clean_id)
                    return True
        except Exception:
            pass

        return False

    def get_record(self, wa_message_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached outbound message record."""
        return self._outbound_records.get(str(wa_message_id).strip())

    def clear(self) -> None:
        """Clears in-memory registry (used for test isolation)."""
        self._outbound_ids.clear()
        self._outbound_records.clear()
        self._recipient_records.clear()


# Singleton Instance
outbound_registry = OutboundMessageRegistry()
