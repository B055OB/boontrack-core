"""app/services/ai_gateway/models.py
Agent Profiles, Model Profiles, and response cleaning utilities for BoonTrack AI Gateway.
"""

import enum
import re
import json
from typing import Dict, Any, Tuple, List


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


DEFAULT_QUICK_ACTIONS = ["Tambah Produk", "Setup WhatsApp", "Bikin Landing Page"]


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


def parse_ai_quick_actions_response(raw_response: Any) -> Tuple[str, List[str]]:
    """
    Ekstrak array 'quick_actions' dan text reply dari response JSON.
    Sanitasi dan potong secara ketat:
      quick_actions = [str(a).strip() for a in raw_actions if a][:3]
    Jika kosong atau gagal, berikan fallback default:
      ["Tambah Produk", "Setup WhatsApp", "Bikin Landing Page"]
    """
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
        # Lepaskan markdown code blocks jika LLM membungkus dalam ```json ... ```
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


_clean_response = clean_ai_response

