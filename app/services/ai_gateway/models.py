"""app/services/ai_gateway/models.py
Agent Profiles, Model Profiles, and response cleaning utilities for BoonTrack AI Gateway.
"""

import enum
import re
from typing import Dict


class ModelProfile(str, enum.Enum):
    """Karakteristik performa model LLM."""
    FAST = "FAST"              # Latensi ultra-rendah untuk chat realtime e-commerce
    BALANCED = "BALANCED"      # Keseimbangan kecepatan, empati, dan pemecahan masalah
    REASONING = "REASONING"    # Penalaran analitis mendalam, kalkulasi, & orkestrasi tools


class AgentProfile(str, enum.Enum):
    """3 Profil Agen Khusus BoonTrack Platform."""
    BUYER_ASSISTANT = "BUYER_ASSISTANT"    # Store Sales Agent (WhatsApp Inbound Customer)
    MERCHANT_COPILOT = "MERCHANT_COPILOT"  # BoonPilot (Copilot Operasional Toko Merchant)
    PLATFORM_SUPPORT = "PLATFORM_SUPPORT"  # BoonTrack Platform CS & Merchant Support


# Mapping default agent profile ke model profile
AGENT_TO_MODEL_PROFILE: Dict[AgentProfile, ModelProfile] = {
    AgentProfile.BUYER_ASSISTANT: ModelProfile.FAST,
    AgentProfile.MERCHANT_COPILOT: ModelProfile.REASONING,
    AgentProfile.PLATFORM_SUPPORT: ModelProfile.BALANCED,
}


def clean_ai_response(text: str) -> str:
    """Sanitasi output AI agar aman dari crash parsing Telegram & format rapi di WhatsApp."""
    if not text:
        return ""

    cleaned_lines = []
    for line in text.split("\n"):
        if line.strip().startswith(("*Lang", "*Leng", "*Format:")):
            continue

        line_str = line.strip()

        # Konversi heading ### atau ## menjadi baris kapital bersih
        header_match = re.match(r"^#{1,6}\s+(.*)", line_str)
        if header_match:
            line_str = header_match.group(1).strip()

        # Konversi bullet list (* item / - item) menjadi • item
        bullet_match = re.match(r"^([*\-])\s+(.*)", line_str)
        if bullet_match:
            line_str = f"• {bullet_match.group(2)}"

        cleaned_lines.append(line_str)

    result = "\n".join(cleaned_lines).strip()
    result = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", result)
    return result


_clean_response = clean_ai_response
