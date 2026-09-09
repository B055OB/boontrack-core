"""app/services/unified_engine/signal_extractor.py
Unified Conversation Engine: Prioritized Signal Extractor & Intent Classifier.
Executes deterministic checks and rule engines before falling back to LLM.
"""

import re
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger("UNIFIED_SIGNAL_EXTRACTOR")

class SignalExtractor:
    """Extracts business signals and conversation intent using prioritized deterministic rules."""

    @staticmethod
    def extract_signals(message_text: str, button_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Prioritized extraction pipeline:
        1. Button / Action payload inspection
        2. Deterministic Regex / Keyword matching
        3. Business entity extraction (capacity, numbers, pricing)
        """
        text = (message_text or "").strip()
        text_lower = text.lower()
        clean_btn = (button_id or "").strip().lower()

        signals = {
            "has_checkout_intent": False,
            "has_booking_intent": False,
            "has_capacity_signal": False,
            "extracted_capacity": None,
            "extracted_payment_method": None,
            "is_ambiguous": True,
            "confidence": 0.50,
            "source": "DEFAULT"
        }

        # 1. Inspect Button ID Payload
        if clean_btn in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris", "btn_checkout_cart"} or clean_btn.startswith("prod_"):
            signals["has_checkout_intent"] = True
            signals["confidence"] = 0.99
            signals["source"] = "BUTTON_PAYLOAD"
            signals["is_ambiguous"] = False
            return signals

        # 2. Checkout / Payment Intent
        if any(w in text_lower for w in ["qris", "tunai", "bayar", "transfer", "checkout", "scan", "pesan sekarang"]):
            signals["has_checkout_intent"] = True
            if "qris" in text_lower or "scan" in text_lower:
                signals["extracted_payment_method"] = "QRIS"
            elif "tunai" in text_lower or "tempat" in text_lower:
                signals["extracted_payment_method"] = "COD"
            signals["confidence"] = 0.98
            signals["source"] = "DETERMINISTIC_SIGNAL"
            signals["is_ambiguous"] = False
            return signals

        # 3. Booking / Agreement Intent
        if any(w in text_lower for w in ["jadi", "pesan", "booking", "ambil", "lanjut", "deal", "siap", "mau"]):
            signals["has_booking_intent"] = True
            signals["confidence"] = 0.92
            signals["source"] = "RULE_ENGINE"
            signals["is_ambiguous"] = False
            return signals

        # 4. Capacity / Product Numeric Signal (e.g., 500 liter, 1000L)
        numbers = re.findall(r"\d+", text_lower)
        if numbers and any(w in text_lower for w in ["liter", "lt", "kapasitas", "toren", "tangki", "ukuran"]):
            signals["has_capacity_signal"] = True
            signals["extracted_capacity"] = numbers[0]
            signals["confidence"] = 0.90
            signals["source"] = "ENTITY_EXTRACTION"
            signals["is_ambiguous"] = False
            return signals
        elif numbers and len(text_lower.split()) <= 3:
            # Short numeric reply like "500" or "1000"
            signals["has_capacity_signal"] = True
            signals["extracted_capacity"] = numbers[0]
            signals["confidence"] = 0.85
            signals["source"] = "SHORT_NUMERIC_ENTITY"
            signals["is_ambiguous"] = False
            return signals

        return signals

signal_extractor = SignalExtractor()