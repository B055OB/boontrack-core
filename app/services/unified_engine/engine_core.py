"""app/services/unified_engine/engine_core.py
Unified Conversation Engine Orchestrator: Binds Tenant Context, 
Signal Extraction, State Management, and Lead Projection.
"""

from typing import Dict, Any, Optional
import logging

from app.services.unified_engine.state_manager import unified_state_manager
from app.services.unified_engine.signal_extractor import signal_extractor
from app.services.tenant_context_resolver import tenant_context_resolver

logger = logging.getLogger("UNIFIED_ENGINE_CORE")

class UnifiedEngineCore:
    """Orchestrates the complete message processing flow through the unified architecture."""

    @staticmethod
    async def process_incoming_message(
        tenant_slug: str,
        phone: str,
        message_text: str,
        button_id: Optional[str] = None,
        existing_session_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes the prioritized pipeline:
        1. Resolve Tenant Context
        2. Extract Signals & Intent
        3. Evaluate Conversation & Business States
        4. Project into Lead State for BoonTrack Inbox
        """
        clean_tenant = str(tenant_slug or "onlineboost").strip().lower()
        session = existing_session_data or {}
        
        # 1. Extract Signals deterministically
        signals = signal_extractor.extract_signals(message_text, button_id)

        # 2. Derive Conversation & Business States from session & signals
        conv_state = session.get("conversation_state", "AWARENESS")
        business_state = session.get("business_state", {})
        conversion_state = session.get("conversion_state", "CHECKOUT_NOT_STARTED")

        if signals["has_checkout_intent"]:
            conversion_state = "INITIATE_CHECKOUT_SENT"
            if signals["extracted_payment_method"]:
                business_state["payment_method"] = signals["extracted_payment_method"]
        elif signals["has_booking_intent"]:
            conv_state = "BOOKING"
            business_state["booking_ready"] = True
        elif signals["has_capacity_signal"]:
            conv_state = "CONSIDERATION"
            business_state["capacity"] = signals["extracted_capacity"]

        # 3. Project into Unified Lead State for Inbox
        projection = unified_state_manager.evaluate_lead_projection(
            conversation_state=conv_state,
            business_state=business_state,
            conversion_state=conversion_state
        )

        updated_session = {
            "tenant_slug": clean_tenant,
            "conversation_state": conv_state,
            "business_state": business_state,
            "conversion_state": conversion_state,
            "lead_state": projection["lead_state"],
            "lead_state_source": projection["source"],
            "lead_state_confidence": projection["confidence"]
        }

        logger.info(f"[UNIFIED ENGINE] Tenant: {clean_tenant} | Phone: {phone} | LeadState: {projection['lead_state']} ({projection['source']})")

        return {
            "signals": signals,
            "session_state": updated_session,
            "lead_state": projection["lead_state"]
        }

unified_engine_core = UnifiedEngineCore()