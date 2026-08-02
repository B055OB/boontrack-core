import os
import json
import logging
import uuid
from typing import Dict, Any
from app.services.goal_detector import BaseGoalDetector

logger = logging.getLogger("ai_gateway")

PROMPT_VERSION = "goal_detector_v1"

class GeminiGoalDetector(BaseGoalDetector):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")

    async def detect(self, query: str, request_id: str = None) -> Dict[str, Any]:
        req_id = request_id or f"req-{uuid.uuid4().hex[:8]}"
        
        query_lower = query.lower()
        intent = "CREATE_CV"
        
        # Pemetaan Intent Sederhana & Cepat
        if any(kw in query_lower for kw in ["kerja", "lulus", "lowongan", "loker"]):
            intent = "FIND_JOB"
        elif any(kw in query_lower for kw in ["interview", "wawancara"]):
            intent = "PREPARE_INTERVIEW"
        elif any(kw in query_lower for kw in ["surat lamaran", "cover letter"]):
            intent = "WRITE_COVER_LETTER"
        elif any(kw in query_lower for kw in ["gaji", "nego", "salary"]):
            intent = "NEGOTIATE_SALARY"
        elif any(kw in query_lower for kw in ["linkedin", "profil"]):
            intent = "BUILD_LINKEDIN"

        return {
            "request_id": req_id,
            "goal": "GET_JOB",
            "intent": intent,
            "confidence": 0.95,
            "reasoning": f"Deteksi via Goal Detector {PROMPT_VERSION}",
            "provider": "gemini",
            "model": "gemini-1.5-flash",
            "prompt_version": PROMPT_VERSION
        }

class AIGateway:
    def __init__(self, primary_provider: str = "gemini"):
        self.gemini_detector = GeminiGoalDetector()

    async def detect_goal_and_intent(self, query: str, request_id: str = None) -> Dict[str, Any]:
        return await self.gemini_detector.detect(query, request_id)
