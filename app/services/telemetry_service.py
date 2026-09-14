"""app/services/telemetry_service.py
Centralized Telemetry Hooks & Unit Economics Tracking Engine.
Provides asynchronous, zero-latency (fire-and-forget) recording of:
1. AI Token Usage (Gemini Flash prompt_tokens, candidate_tokens per tenant/session).
2. WhatsApp Message Counters (INBOUND/OUTBOUND volume and session classification per tenant).
3. Telemetry metrics logging to Supabase `tenant_telemetry_logs` with memory aggregation.
"""

import os
import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from collections import defaultdict

logger = logging.getLogger("TELEMETRY")

# In-memory aggregated telemetry metrics
_telemetry_stats = {
    "ai_tokens": defaultdict(lambda: {"prompt_tokens": 0, "candidate_tokens": 0, "total_tokens": 0, "calls": 0}),
    "whatsapp": defaultdict(lambda: {"inbound": 0, "outbound": 0, "classifications": defaultdict(int)}),
}


def _get_supabase_client():
    """Lazy resolver for Supabase client."""
    try:
        from app.services.tenant_context_resolver import get_supabase_client
        client = get_supabase_client()
        if client:
            return client
    except Exception:
        pass

    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "https://mpluzajlzpregmjwpjqr.supabase.co")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
        if url and key:
            return create_client(url, key)
    except Exception:
        pass
    return None


async def _async_record_to_supabase(payload: Dict[str, Any]) -> bool:
    """Non-blocking background insert into Supabase `tenant_telemetry_logs`."""
    try:
        client = _get_supabase_client()
        if not client:
            return False

        # Run in executor to avoid blocking the asyncio event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: client.table("tenant_telemetry_logs").insert(payload).execute()
        )
        return True
    except Exception as e:
        # Table might not exist yet in remote migration, or network hiccup.
        # Fall back to structured logger without raising.
        logger.debug(f"[TELEMETRY_DB_NOTICE] Could not insert to tenant_telemetry_logs: {e}")
        return False


def _fire_and_forget(coro):
    """Executes a coroutine in background without awaiting or blocking the current frame."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        # No running event loop in thread; create one or run
        try:
            asyncio.run(coro)
        except Exception as err:
            logger.debug(f"[TELEMETRY_BACKGROUND_ERROR] {err}")


def track_ai_tokens(
    tenant_id: str,
    session_id: str,
    prompt_tokens: int,
    candidate_tokens: int,
    model: str = "gemini-flash",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Fire-and-forget hook for AI token usage tracking.
    Zero latency impact on request handling.
    """
    clean_tenant = str(tenant_id or "unknown").strip().lower()
    clean_session = str(session_id or "anonymous").strip()
    p_tokens = int(prompt_tokens or 0)
    c_tokens = int(candidate_tokens or 0)
    total_tokens = p_tokens + c_tokens

    # 1. Update in-memory aggregate stats
    stats = _telemetry_stats["ai_tokens"][clean_tenant]
    stats["prompt_tokens"] += p_tokens
    stats["candidate_tokens"] += c_tokens
    stats["total_tokens"] += total_tokens
    stats["calls"] += 1

    # 2. Structured telemetry logging
    logger.info(
        f"[TELEMETRY:AI] tenant={clean_tenant} session={clean_session} "
        f"prompt_tokens={p_tokens} candidate_tokens={c_tokens} total={total_tokens} model={model}"
    )

    # 3. Fire-and-forget Supabase persistence
    payload = {
        "tenant_id": clean_tenant,
        "session_id": clean_session,
        "event_type": "ai_token_usage",
        "direction": None,
        "prompt_tokens": p_tokens,
        "candidate_tokens": c_tokens,
        "total_tokens": total_tokens,
        "model": model,
        "classification": "ai_inference",
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _fire_and_forget(_async_record_to_supabase(payload))


def track_whatsapp_message(
    direction: str,
    tenant_id: str,
    session_id: str,
    classification: str = "general",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Fire-and-forget hook for WhatsApp message volume & session classification counter.
    Direction: 'INBOUND' or 'OUTBOUND'.
    Zero latency impact on webhook response.
    """
    clean_dir = str(direction or "INBOUND").strip().upper()
    if clean_dir not in ("INBOUND", "OUTBOUND"):
        clean_dir = "INBOUND" if "in" in clean_dir.lower() else "OUTBOUND"

    clean_tenant = str(tenant_id or "unknown").strip().lower()
    clean_session = str(session_id or "anonymous").strip()
    clean_class = str(classification or "general").strip().lower()

    # 1. Update in-memory aggregate stats
    stats = _telemetry_stats["whatsapp"][clean_tenant]
    if clean_dir == "INBOUND":
        stats["inbound"] += 1
    else:
        stats["outbound"] += 1
    stats["classifications"][clean_class] += 1

    # 2. Structured telemetry logging
    logger.info(
        f"[TELEMETRY:WA] direction={clean_dir} tenant={clean_tenant} "
        f"session={clean_session} classification={clean_class}"
    )

    # 3. Fire-and-forget Supabase persistence
    payload = {
        "tenant_id": clean_tenant,
        "session_id": clean_session,
        "event_type": "whatsapp_message",
        "direction": clean_dir,
        "prompt_tokens": 0,
        "candidate_tokens": 0,
        "total_tokens": 0,
        "model": None,
        "classification": clean_class,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _fire_and_forget(_async_record_to_supabase(payload))


def get_telemetry_summary(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """Returns in-memory telemetry aggregates for a specific tenant or all tenants."""
    if tenant_id:
        clean_tenant = str(tenant_id).strip().lower()
        ai = dict(_telemetry_stats["ai_tokens"].get(clean_tenant, {}))
        wa = _telemetry_stats["whatsapp"].get(clean_tenant, {})
        wa_dict = {
            "inbound": wa.get("inbound", 0) if isinstance(wa, dict) else 0,
            "outbound": wa.get("outbound", 0) if isinstance(wa, dict) else 0,
            "classifications": dict(wa.get("classifications", {})) if isinstance(wa, dict) else {},
        }
        return {
            "tenant_id": clean_tenant,
            "ai_tokens": ai,
            "whatsapp": wa_dict,
        }

    return {
        "ai_tokens": {k: dict(v) for k, v in _telemetry_stats["ai_tokens"].items()},
        "whatsapp": {
            k: {
                "inbound": v.get("inbound", 0),
                "outbound": v.get("outbound", 0),
                "classifications": dict(v.get("classifications", {})),
            }
            for k, v in _telemetry_stats["whatsapp"].items()
        },
    }


def reset_telemetry_stats() -> None:
    """Reset counters for testing isolation."""
    _telemetry_stats["ai_tokens"].clear()
    _telemetry_stats["whatsapp"].clear()
