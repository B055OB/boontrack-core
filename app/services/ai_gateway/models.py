"""app/services/ai_gateway/models.py
Agent Profiles, Capability Tasks, and Sanitization Utilities.
CTO Directive Compliant: Task/Capability-based abstraction, zero provider coupling.
"""

import enum
import re
import json
from typing import Dict, Any, Tuple, List, Optional


class ModelProfile(str, enum.Enum):
    """Level performa model untuk router."""
    FAST = "FAST"
    BALANCED = "BALANCED"
    REASONING = "REASONING"


class AICapability(str, enum.Enum):
    """Abstraksi task/capability kerja AI (CTO Directive)."""
    FAST_CONVERSATION = "FAST_CONVERSATION"          # Buyer Chat, WhatsApp Inbound
    AI_INTERCEPTOR = "AI_INTERCEPTOR"                # Interceptor, Guardrails
    STRUCTURED_EXTRACTION = "STRUCTURED_EXTRACTION"  # Entity, intent extraction, JSON
    RESPONSE_FORMATTER = "RESPONSE_FORMATTER"        # Output cleaner, action payload
    BUSINESS_ADVISOR = "BUSINESS_ADVISOR"            # Merchant copilot, reporting, advisory
    COMPLEX_REASONING = "COMPLEX_REASONING"          # Platform architecture, deep tools reasoning


class AgentProfile(str, enum.Enum):
    """3 Profil Agen Khusus BoonTrack Platform."""
    BUYER_ASSISTANT = "BUYER_ASSISTANT"
    MERCHANT_COPILOT = "MERCHANT_COPILOT"
    PLATFORM_SUPPORT = "PLATFORM_SUPPORT"


# Mapping Agent Profile ke Capability Primer
AGENT_TO_CAPABILITY: Dict[AgentProfile, AICapability] = {
    AgentProfile.BUYER_ASSISTANT: AICapability.FAST_CONVERSATION,
    AgentProfile.MERCHANT_COPILOT: AICapability.BUSINESS_ADVISOR,
    AgentProfile.PLATFORM_SUPPORT: AICapability.FAST_CONVERSATION,
}

# Mapping Gemini Thinking Levels (CTO Spec: Low, Medium, High)
CAPABILITY_TO_GEMINI_THINKING: Dict[AICapability, str] = {
    AICapability.FAST_CONVERSATION: "low",
    AICapability.AI_INTERCEPTOR: "low",
    AICapability.STRUCTURED_EXTRACTION: "low",
    AICapability.RESPONSE_FORMATTER: "low",
    AICapability.BUSINESS_ADVISOR: "medium",
    AICapability.COMPLEX_REASONING: "high",
}

# Backward compatibility mapping untuk legacy router
AGENT_TO_MODEL_PROFILE: Dict[AgentProfile, ModelProfile] = {
    AgentProfile.BUYER_ASSISTANT: ModelProfile.FAST,
    AgentProfile.MERCHANT_COPILOT: ModelProfile.REASONING,
    AgentProfile.PLATFORM_SUPPORT: ModelProfile.BALANCED,
}

DEFAULT_QUICK_ACTIONS = ["Daftar Biaya Layanan", "Cek Area Jangkauan", "Jadwal & Cara Pesan"]


def clean_ai_response(text: str) -> str:
    """Sanitasi output AI agar aman dari formatting markdown berantakan."""
    if not text:
        return ""

    cleaned_lines = []
    for line in text.split("\n"):
        if line.strip().startswith(("*Lang", "*Leng", "*Format:")):
            continue

        line_str = line.strip()
        header_match = re.match(r"^#{1,6}\s+(.*)", line_str)
        if header_match:
            line_str = header_match.group(1).strip()

        bullet_match = re.match(r"^([*\-])\s+(.*)", line_str)
        if bullet_match:
            line_str = f"• {bullet_match.group(2)}"

        cleaned_lines.append(line_str)

    result = "\n".join(cleaned_lines).strip()
    result = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", result)
    return result


def parse_ai_quick_actions_response(raw_response: Any) -> Tuple[str, List[str]]:
    """Parsing response JSON dan quick_actions secara deterministik."""
    default_actions = list(DEFAULT_QUICK_ACTIONS)
    if not raw_response:
        return "", default_actions

    reply_text = ""
    raw_actions = None

    if isinstance(raw_response, dict):
        reply_text = str(raw_response.get("reply") or raw_response.get("reply_text") or raw_response.get("message") or "").strip()
        raw_actions = raw_response.get("quick_actions")
    elif isinstance(raw_response, str):
        text = raw_response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if len(lines) >= 2 and lines[-1].strip().startswith("```"):
                text = "\n".join(lines[1:-1]).strip()
            elif text.startswith("```json"):
                text = text[7:].rstrip("`").strip()
            elif text.startswith("```"):
                text = text[3:].rstrip("`").strip()

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                reply_text = str(parsed.get("reply") or parsed.get("reply_text") or parsed.get("message") or "").strip()
                raw_actions = parsed.get("quick_actions")
            else:
                reply_text = text
        except Exception:
            reply_text = text

    if not reply_text and isinstance(raw_response, str):
        reply_text = raw_response.strip()

    reply_text = clean_ai_response(reply_text)

    quick_actions = []
    if isinstance(raw_actions, (list, tuple)):
        sanitized = [str(a).strip() for a in raw_actions if a and str(a).strip()]
        quick_actions = [a for a in sanitized if a][:3]

    if not quick_actions:
        quick_actions = default_actions

    return reply_text, quick_actions

clean_response = clean_ai_response