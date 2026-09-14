"""
app/services/auto_reply_service.py
Service for Custom Keyword Auto-Reply Rules per Tenant.

Architectural Guarantees:
1. Pure in-memory matching with zero latency overhead.
2. Supports 'contains' and 'exact' matching with whitespace trimming and case insensitivity.
3. Fallback resolution: tenant_metadata dict -> TenantRuntimeContext resolver -> Supabase query.
4. Fail-safe: if no rule matches or disabled, returns None to allow AI / default fallback.
"""

import logging
from typing import Dict, Any, List, Optional
from app.services.tenant_context_resolver import get_supabase, tenant_context_resolver

logger = logging.getLogger("AUTO_REPLY_SERVICE")


def match_auto_reply_rule(
    rules: List[Dict[str, Any]],
    user_message: str
) -> Optional[Dict[str, Any]]:
    """
    Evaluates list of auto_reply rules against user message:
    - Sanitizes user_message (lowercase, stripped whitespace).
    - Filters out inactive rules (is_active is False).
    - Checks match_type:
        * 'contains': trigger in user_message
        * 'exact': trigger == user_message
    Returns the first matching rule dict or None.
    """
    if not user_message or not rules or not isinstance(rules, list):
        return None

    clean_message = user_message.strip().lower()
    if not clean_message:
        return None

    for rule in rules:
        if not isinstance(rule, dict):
            continue

        # Rule must be active (defaults to True if omitted)
        if rule.get("is_active") is False:
            continue

        trigger = str(rule.get("trigger") or rule.get("keyword") or "").strip().lower()
        if not trigger:
            continue

        match_type = str(rule.get("match_type") or "contains").strip().lower()

        is_matched = False
        if match_type == "exact":
            is_matched = (clean_message == trigger)
        else:  # 'contains' is default
            is_matched = (trigger in clean_message)

        if is_matched:
            reply_text = rule.get("reply_text") or rule.get("reply") or rule.get("response") or ""
            if reply_text.strip():
                logger.info(
                    f"[AUTO_REPLY] Matched rule '{rule.get('id', 'unnamed')}' "
                    f"(trigger='{trigger}', type='{match_type}') for message: '{clean_message[:60]}'"
                )
                return rule

    return None


async def find_tenant_auto_reply(
    tenant_slug: str,
    user_message: str,
    tenant_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Finds and returns the custom auto-reply string for a tenant if any keyword matches.
    If no rule matches or rules array is empty, returns None.
    """
    if not tenant_slug or not user_message:
        return None

    rules: Optional[List[Dict[str, Any]]] = None

    # 1. Use provided tenant_metadata if available
    if tenant_metadata and isinstance(tenant_metadata, dict):
        rules = tenant_metadata.get("auto_replies")

    # 2. Resolve via cached TenantRuntimeContext if not provided
    if rules is None:
        try:
            context = await tenant_context_resolver.resolve_tenant(tenant_slug)
            if context and context.metadata:
                rules = context.metadata.get("auto_replies")
        except Exception as res_err:
            logger.debug(f"[AUTO_REPLY] Context resolver notice for '{tenant_slug}': {res_err}")

    # 3. Direct Supabase query fallback if still None
    if rules is None:
        try:
            supabase = get_supabase()
            if supabase:
                res = supabase.table("tenants").select("metadata").eq("slug", tenant_slug.lower()).execute()
                if res and res.data and len(res.data) > 0:
                    meta = res.data[0].get("metadata") or {}
                    if isinstance(meta, dict):
                        rules = meta.get("auto_replies")
        except Exception as db_err:
            logger.warning(f"[AUTO_REPLY] Supabase lookup error for '{tenant_slug}': {db_err}")

    if not rules or not isinstance(rules, list):
        return None

    matched_rule = match_auto_reply_rule(rules, user_message)
    if matched_rule:
        reply_text = matched_rule.get("reply_text") or matched_rule.get("reply") or matched_rule.get("response")
        if reply_text and isinstance(reply_text, str):
            return reply_text.strip()

    return None
