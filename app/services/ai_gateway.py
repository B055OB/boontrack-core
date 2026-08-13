import os
import json
import logging
import uuid
import time
import psycopg2
from typing import Dict, Any, Optional, Tuple

import aiohttp
from app.services.goal_detector import BaseGoalDetector

logger = logging.getLogger("ai_gateway")

PROMPT_VERSION = "goal_detector_v1"

SYSTEM_PROMPT_DEFAULT = (
    "Kamu adalah BoonTrack, asisten karir yang hangat, empatik, dan suportif. "
    "Bantu user dengan pertanyaan seputar CV, interview, dan strategi karir. "
    "Jawab singkat, jelas, dan dalam Bahasa Indonesia yang natural."
)

MOCK_MODE = False


class GeminiGoalDetector(BaseGoalDetector):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

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
            "model": self.model_name,
            "prompt_version": PROMPT_VERSION,
        }


class AIGateway:
    """
    AI Gateway dengan metering usage, deteksi rate limit 429,
    logging ke ai_usage_logs, Model Health Check Logging, 
    dan dynamic failover terpusat via ENV (Gemini -> Groq -> OpenRouter).
    """

    def __init__(self, primary_provider: str = "gemini"):
        self.gemini_detector = GeminiGoalDetector()

        # CENTRALIZED CONFIG FROM ENV (ZERO HARDCODE)
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

        logger.info(
            "AIGateway init | GeminiModel=%s GroqModel=%s OpenRouterModel=%s | MockMode=%s",
            self.gemini_model,
            self.groq_model,
            self.openrouter_model,
            MOCK_MODE,
        )

    def _get_db_conn(self):
        return psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD")
        )

    def _log_health(self, provider: str, model: str, status: str, latency: float, fallback: str = "NO", error_msg: str = ""):
        """Observability Log untuk CTO & Internal Monitoring"""
        log_str = (
            f"\n[AI LOG]\n"
            f"  Provider  : {provider}\n"
            f"  Model     : {model}\n"
            f"  Status    : {status}\n"
            f"  Latency   : {latency:.2f}s\n"
            f"  Fallback  : {fallback}"
        )
        if error_msg:
            log_str += f"\n  Reason    : {error_msg[:300]}"
        print(log_str)

    def _log_usage(
        self,
        user_id: Optional[int],
        provider: str,
        feature: str,
        p_tokens: int,
        c_tokens: int,
        status_code: int = 200,
        is_error: bool = False,
        error_msg: str = ""
    ):
        """Mencatat penggunaan token & status HTTP secara real-time ke DB PostgreSQL."""
        try:
            conn = self._get_db_conn()
            cur = conn.cursor()
            query = """
                INSERT INTO ai_usage_logs 
                (user_id, provider, feature, prompt_tokens, completion_tokens, total_tokens, status_code, is_error, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """
            cur.execute(query, (
                user_id, provider, feature, p_tokens, c_tokens,
                p_tokens + c_tokens, status_code, is_error, error_msg[:500]
            ))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error("Gagal mencatat AI Usage Log: %s", str(e))

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
        if MOCK_MODE:
            logger.info("AIGateway running in MOCK_MODE")
            return f"🤖 [MOCK RESPON]: Halo! Pesan kamu '{user_message}' berhasil diproses oleh AIGateway Railway."

        context = context or {}
        user_id = context.get("user_id")
        feature = context.get("feature", "general")

        providers = [
            ("Gemini", self.gemini_model, self._call_gemini),
            ("Groq", self.groq_model, self._call_groq),
            ("OpenRouter", self.openrouter_model, self._call_openrouter),
        ]

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            for idx, (name, model, fn) in enumerate(providers):
                start_time = time.time()
                try:
                    result, p_tokens, c_tokens = await fn(session, user_message, context, system_prompt)
                    latency = time.time() - start_time
                    if result:
                        fallback_info = "NO" if idx == 0 else f"YES (Used {name})"
                        self._log_health(name, model, "SUCCESS", latency, fallback=fallback_info)
                        self._log_usage(user_id, name, feature, p_tokens, c_tokens, 200, False)
                        return result
                except Exception as e:
                    latency = time.time() - start_time
                    err_str = str(e)
                    status_code = 429 if ("429" in err_str or "quota" in err_str.lower() or "limit" in err_str.lower()) else 500
                    next_provider = providers[idx + 1][0] if idx + 1 < len(providers) else "NONE (EXHAUSTED)"
                    
                    self._log_health(name, model, "FAILED", latency, fallback=f"YES ({next_provider})", error_msg=err_str)
                    self._log_usage(user_id, name, feature, 0, 0, status_code, True, err_str)
                    continue

        logger.error("ALL AI providers failed for message: %r", user_message[:80])
        return None

    async def _call_gemini(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
    ) -> Tuple[str, int, int]:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY kosong / tidak ter-set")

        # Menggunakan Endpoint API Stable v1 & Dynamic Model dari ENV
        url = (
            "https://generativelanguage.googleapis.com/v1/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        
        full_text = f"{system_prompt}\n\nUser Question: {user_message}"
        payload = {
            "contents": [{"parts": [{"text": full_text}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 512},
        }

        async with session.post(url, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            try:
                res_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                usage_meta = data.get("usageMetadata", {})
                p_tokens = usage_meta.get("promptTokenCount", len(full_text) // 4)
                c_tokens = usage_meta.get("candidatesTokenCount", len(res_text) // 4)
                return res_text, p_tokens, c_tokens
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected Gemini response shape: {data}") from e

    async def _call_groq(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
    ) -> Tuple[str, int, int]:
        if not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY kosong / tidak ter-set")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            try:
                res_text = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                p_tokens = usage.get("prompt_tokens", 0)
                c_tokens = usage.get("completion_tokens", 0)
                return res_text, p_tokens, c_tokens
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected Groq response shape: {data}") from e

    async def _call_openrouter(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
    ) -> Tuple[str, int, int]:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY kosong / tidak ter-set")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            try:
                res_text = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                p_tokens = usage.get("prompt_tokens", 0)
                c_tokens = usage.get("completion_tokens", 0)
                return res_text, p_tokens, c_tokens
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected OpenRouter response shape: {data}") from e