import os
import json
import logging
import uuid
from typing import Dict, Any, Optional

import aiohttp

from app.services.goal_detector import BaseGoalDetector

logger = logging.getLogger("ai_gateway")

PROMPT_VERSION = "goal_detector_v1"

SYSTEM_PROMPT_DEFAULT = (
    "Kamu adalah BoonTrack, asisten karir yang hangat, empatik, dan suportif. "
    "Bantu user dengan pertanyaan seputar CV, interview, dan strategi karir. "
    "Jawab singkat, jelas, dan dalam Bahasa Indonesia yang natural."
)


class GeminiGoalDetector(BaseGoalDetector):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")

    async def detect(self, query: str, request_id: str = None) -> Dict[str, Any]:
        req_id = request_id or f"req-{uuid.uuid4().hex[:8]}"

        query_lower = query.lower()
        intent = "CREATE_CV"

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
            "model": "gemini-2.5-flash",
            "prompt_version": PROMPT_VERSION,
        }


class AIGateway:
    """
    Gateway untuk konsultasi karir bebas (general query).
    Coba provider berurutan: Gemini -> Groq -> OpenRouter.
    Semua kegagalan di-log dengan jelas (bukan silent fail) supaya
    gampang di-debug lewat Render Logs.
    """

    def __init__(self, primary_provider: str = "gemini"):
        self.gemini_detector = GeminiGoalDetector()

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

        # Log status key saat startup -- supaya ketauan dari awal
        # kalau ada key yang kosong/hilang, bukan nunggu request gagal dulu.
        logger.info(
            "AIGateway init | gemini_key=%s groq_key=%s openrouter_key=%s",
            bool(self.gemini_api_key),
            bool(self.groq_api_key),
            bool(self.openrouter_api_key),
        )

    async def detect_goal_and_intent(
        self, query: str, request_id: str = None
    ) -> Dict[str, Any]:
        return await self.gemini_detector.detect(query, request_id)

    async def generate(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: str = SYSTEM_PROMPT_DEFAULT,
    ) -> Optional[str]:
        """
        Entry point utama yang dipanggil BrainEngine untuk general query.
        Return string jawaban AI, atau None kalau SEMUA provider gagal
        (BrainEngine yang handle fallback statis-nya).
        """
        context = context or {}

        providers = [
            ("gemini", self._call_gemini),
            ("groq", self._call_groq),
            ("openrouter", self._call_openrouter),
        ]

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            for name, fn in providers:
                try:
                    result = await fn(session, user_message, context, system_prompt)
                    if result:
                        logger.info("AI response OK via provider=%s", name)
                        return result
                    logger.warning(
                        "Provider=%s returned empty result, trying next", name
                    )
                except Exception as e:
                    # WAJIB di-log detail -- ini yang tadi hilang di versi lama,
                    # bikin kamu gak pernah tau kenapa selalu jatuh ke fallback.
                    logger.error(
                        "Provider=%s FAILED | %s: %s",
                        name,
                        type(e).__name__,
                        str(e),
                    )
                    continue

        logger.error("ALL AI providers failed for message: %r", user_message[:80])
        return None

    async def _call_gemini(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
    ) -> Optional[str]:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY kosong / tidak ter-set")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={self.gemini_api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": user_message}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512},
        }

        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = await resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected Gemini response shape: {data}") from e

    async def _call_groq(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
    ) -> Optional[str]:
        if not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY kosong / tidak ter-set")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = await resp.json()
            try:
                return data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected Groq response shape: {data}") from e

    async def _call_openrouter(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
    ) -> Optional[str]:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY kosong / tidak ter-set")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "deepseek/deepseek-chat:free",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = await resp.json()
            try:
                return data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError) as e:
                raise RuntimeError(
                    f"Unexpected OpenRouter response shape: {data}"
                ) from e