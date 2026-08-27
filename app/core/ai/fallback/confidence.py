from enum import Enum
from typing import Tuple

class MatchConfidence(Enum):
    HIGH = "HIGH"       # >= 0.85 -> Auto Reply
    MEDIUM = "MEDIUM"   # 0.70 - 0.84 -> Reply + Guardrail
    LOW = "LOW"         # < 0.70 -> LLM / Tier 5 Fallback

def evaluate_confidence(score: float) -> Tuple[MatchConfidence, bool]:
    if score >= 0.85:
        return MatchConfidence.HIGH, True
    elif score >= 0.70:
        return MatchConfidence.MEDIUM, True
    return MatchConfidence.LOW, False
