"""app/services/ai/__init__.py
Module package for AI services, prompt builders, and grounding directives.
"""

from app.services.ai.grounding import (
    READER_ALLOWED_MERCHANT_ACCOUNTS,
    READER_PROHIBITED_MERCHANT_ACCOUNTS,
    STRICT_READER_GROUNDING_PROMPT,
    BOONTRACK_OFFICIAL_SERVICES_PACKAGES,
    DIRECT_CHECKOUT_WA_SOP_PROMPT,
    COMBINED_STRICT_AI_DIRECTIVE,
    HANDOVER_HUMAN_KEYWORDS,
    HANDOVER_TRANSITION_REPLY,
    is_setup_toko_intent,
    is_reader_inquiry_intent,
    is_handover_intent,
    is_screening_inquiry_intent,
    generate_setup_toko_consultation_reply,
    generate_reader_account_explanation_reply,
    generate_screening_link_reply,
    CLINIC_SCREENING_GROUNDING_PROMPT,
    BOONTRACK_ADS_TRACKING_AND_SYNC_DIRECTIVE,
    CUSTOMER_SYNC_AND_CAPI_KEYWORDS,
    is_capi_or_sync_inquiry_intent,
    generate_capi_and_sync_explanation_reply,
)

__all__ = [
    "READER_ALLOWED_MERCHANT_ACCOUNTS",
    "READER_PROHIBITED_MERCHANT_ACCOUNTS",
    "STRICT_READER_GROUNDING_PROMPT",
    "BOONTRACK_OFFICIAL_SERVICES_PACKAGES",
    "DIRECT_CHECKOUT_WA_SOP_PROMPT",
    "COMBINED_STRICT_AI_DIRECTIVE",
    "HANDOVER_HUMAN_KEYWORDS",
    "HANDOVER_TRANSITION_REPLY",
    "is_setup_toko_intent",
    "is_reader_inquiry_intent",
    "is_handover_intent",
    "is_screening_inquiry_intent",
    "generate_setup_toko_consultation_reply",
    "generate_reader_account_explanation_reply",
    "generate_screening_link_reply",
    "CLINIC_SCREENING_GROUNDING_PROMPT",
    "BOONTRACK_ADS_TRACKING_AND_SYNC_DIRECTIVE",
    "CUSTOMER_SYNC_AND_CAPI_KEYWORDS",
    "is_capi_or_sync_inquiry_intent",
    "generate_capi_and_sync_explanation_reply",
]
