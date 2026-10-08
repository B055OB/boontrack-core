"""app/workers/whatsapp_inbound_worker.py
Inbound WhatsApp Stream Consumer Worker.

Consumes events from Redis Stream `stream:whatsapp:inbound`.
Extracts:
- tenant_id
- sender (phone)
- message content
When an inbound message matches the screening format:
- Extracts child_name and screening_id.
- Persists lead metadata to session store context.
- Generates personalized, empathetic welcoming response via Little Bite Feeding Knowledge Base.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

from app.services.knowledge_base import generate_greeting_response, get_tenant_knowledge_base
from app.services.screening_parser import extract_screening_lead
from app.services.session_store import set_user_tenant_session

logger = logging.getLogger("WHATSAPP_INBOUND_WORKER")

STREAM_NAME = "stream:whatsapp:inbound"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _extract_text_body(message_data: Any) -> str:
    """Helper to extract raw text body from various message data representations."""
    if not message_data:
        return ""

    if isinstance(message_data, str):
        try:
            parsed = json.loads(message_data)
            return _extract_text_body(parsed)
        except Exception:
            return message_data

    if isinstance(message_data, dict):
        # 1. Standard text object
        text_obj = message_data.get("text")
        if isinstance(text_obj, dict) and "body" in text_obj:
            return str(text_obj["body"])
        elif isinstance(text_obj, str):
            return text_obj

        # 2. Interactive reply button/list
        interactive = message_data.get("interactive")
        if isinstance(interactive, dict):
            btn = interactive.get("button_reply", {})
            if isinstance(btn, dict) and "title" in btn:
                return str(btn["title"])
            list_reply = interactive.get("list_reply", {})
            if isinstance(list_reply, dict) and "title" in list_reply:
                return str(list_reply["title"])

        # 3. Flat body field
        if "body" in message_data:
            return str(message_data["body"])

    return ""


def process_inbound_stream_event(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Processes an inbound message event dict from stream:whatsapp:inbound.

    Args:
        event_data: Mapping containing tenant_id, from, message_data, metadata, etc.

    Returns:
        Dict detailing processing outcome, parsed lead, and optional reply_text.
    """
    tenant_id = str(event_data.get("tenant_id") or "little-bite-feeding").strip()
    sender = str(event_data.get("from") or "").strip()
    raw_message = event_data.get("message_data") or event_data.get("message") or {}

    text_body = _extract_text_body(raw_message)

    # 1. Check for Little Bite Feeding screening lead pattern
    screening_lead = extract_screening_lead(text_body)

    if screening_lead:
        child_name = screening_lead["child_name"]
        screening_id = screening_lead["screening_id"]

        logger.info(
            f"[INBOUND WORKER] Screening lead detected for child '{child_name}' (ID: {screening_id}) from sender '{sender}'."
        )

        # 2. Persist lead metadata into session state
        lead_context = {
            "lead_type": "screening_submission",
            "child_name": child_name,
            "screening_id": screening_id,
            "raw_text": text_body,
            "received_at": time.time(),
        }
        try:
            set_user_tenant_session(
                phone=sender,
                tenant_slug=tenant_id,
                state="SCREENING_RECEIVED",
                context=lead_context,
            )
        except Exception as sess_err:
            logger.warning(f"[INBOUND WORKER] Could not persist session context: {sess_err}")

        # 3. Generate empathetic welcoming response
        reply_text = generate_greeting_response(
            child_name=child_name,
            screening_id=screening_id,
            tenant_id=tenant_id,
        )

        return {
            "status": "screening_lead_processed",
            "is_screening": True,
            "tenant_id": tenant_id,
            "sender": sender,
            "child_name": child_name,
            "screening_id": screening_id,
            "reply_text": reply_text,
        }

    # Standard non-screening inbound message
    return {
        "status": "standard_message_processed",
        "is_screening": False,
        "tenant_id": tenant_id,
        "sender": sender,
        "child_name": None,
        "screening_id": None,
        "reply_text": None,
    }


class WhatsAppInboundWorker:
    """Async Redis Stream Consumer Worker for Inbound WhatsApp Messages."""

    def __init__(
        self,
        stream_name: str = STREAM_NAME,
        redis_url: str = REDIS_URL,
    ):
        self.stream_name = stream_name
        self.redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None

    async def get_client(self) -> Optional[aioredis.Redis]:
        if self._redis is not None:
            return self._redis
        try:
            client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
            )
            await client.ping()
            self._redis = client
            return self._redis
        except Exception as err:
            logger.debug(f"[INBOUND WORKER] Redis client error: {err}")
            return None

    async def consume_batch(
        self,
        count: int = 10,
        block_ms: int = 1000,
        last_id: str = "$",
    ) -> List[Dict[str, Any]]:
        """Reads a batch of events from Redis stream and processes each.

        Returns list of processed result dictionaries.
        """
        client = await self.get_client()
        if not client:
            return []

        results = []
        try:
            # XREAD streams stream:whatsapp:inbound
            streams = await client.xread({self.stream_name: last_id}, count=count, block=block_ms)
            if not streams:
                return []

            for stream_key, entries in streams:
                for entry_id, fields in entries:
                    processed = process_inbound_stream_event(fields)
                    processed["entry_id"] = entry_id
                    results.append(processed)
        except Exception as exc:
            logger.error(f"[INBOUND WORKER] Error reading from stream '{self.stream_name}': {exc}")

        return results

    async def close(self) -> None:
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
