"""app/services/unified_engine/state_manager.py
Unified Conversation Engine: State Management & Lead State Projection.
Implements the 3-tier state separation (Conversation, Business, Conversion) 
and projects them cleanly into lead_state for BoonTrack Inbox.
"""

from typing import Dict, Any, Optional, Literal
import logging

logger = logging.getLogger("UNIFIED_STATE_MANAGER")

LeadState = Literal["TANYA_TANYA", "TERTARIK", "AKAN_CLOSING", "CLOSING", "SELESAI"]

class UnifiedStateManager:
    """Manages multi-tier conversation states and projects them into seller-facing lead states."""

    @staticmethod
    def evaluate_lead_projection(
        conversation_state: str,
        business_state: Dict[str, Any],
        conversion_state: str
    ) -> Dict[str, Any]:
        """
        Projects Conversation, Business, and Conversion states into a unified lead_state
        for BoonTrack Inbox without creating an independent state machine.
        """
        # 1. Check Conversion State first for terminal or advanced checkout milestones
        if conversion_state in ("PAYMENT_CONFIRMED", "PURCHASE_SENT", "JOB_COMPLETED"):
            return {
                "lead_state": "SELESAI",
                "source": "CONVERSION_STATE",
                "confidence": 1.0
            }
        
        if conversion_state in ("INITIATE_CHECKOUT_SENT", "PAYMENT_PENDING"):
            return {
                "lead_state": "CLOSING",
                "source": "CONVERSION_STATE",
                "confidence": 0.98
            }

        # 2. Check Business State & Conversation milestones for intent progression
        has_service_or_product = bool(business_state.get("service_id") or business_state.get("product_id"))
        has_pricing_resolved = bool(business_state.get("price") is not None)
        has_schedule_or_details = bool(business_state.get("scheduled_date") or business_state.get("shipping_address"))
        is_booking_ready = bool(business_state.get("booking_ready") or business_state.get("is_checkout_ready"))

        if is_booking_ready or (has_pricing_resolved and has_schedule_or_details):
            return {
                "lead_state": "AKAN_CLOSING",
                "source": "BUSINESS_RULE_ENGINE",
                "confidence": 0.95
            }

        if conversation_state in ("CONSIDERATION", "DECISION", "HESITATION") or has_service_or_product or has_pricing_resolved:
            return {
                "lead_state": "TERTARIK",
                "source": "CONVERSATION_STATE",
                "confidence": 0.90
            }

        # 3. Default fallback initial state
        return {
            "lead_state": "TANYA_TANYA",
            "source": "DEFAULT_RULE",
            "confidence": 1.0
        }

    @staticmethod
    def classify_intent_lightweight(message_text: str) -> Dict[str, Any]:
        """
        Prioritized Lightweight Classifier (Deterministic signals & rule engine before LLM).
        """
        text_lower = (message_text or "").lower()

        # Deterministic Signals: Checkout / Payment selection
        if any(w in text_lower for w in ["qris", "tunai", "bayar", "transfer", "checkout", "scan"]):
            return {"conversion_state": "INITIATE_CHECKOUT_SENT", "confidence": 0.99, "source": "DETERMINISTIC_SIGNAL"}

        # Deterministic Signals: Booking / Agreement
        if any(w in text_lower for w in ["jadi", "pesan", "booking", "ambil", "lanjutkan", "deal", "siap"]):
            return {"conversation_state": "BOOKING", "confidence": 0.95, "source": "RULE_ENGINE"}

        # Deterministic Signals: Specific capacity / pricing inquiry
        if any(char.isdigit() for char in text_lower) or any(w in text_lower for w in ["liter", "harga", "biaya", "berapa", "rp"]):
            return {"conversation_state": "CONSIDERATION", "confidence": 0.90, "source": "RULE_ENGINE"}

        return {"conversation_state": "AWARENESS", "confidence": 0.70, "source": "DEFAULT"}

unified_state_manager = UnifiedStateManager()