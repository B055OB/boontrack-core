import os
import json
import logging
import uuid
import time
import re
import psycopg2
from typing import Dict, Any, Optional, Tuple

import aiohttp
from app.services.goal_detector import BaseGoalDetector

logger = logging.getLogger("ai_gateway")

PROMPT_VERSION = "goal_detector_v1"

SYSTEM_PROMPT_DEFAULT = (
    "Kamu adalah BoonTrack, asisten karir yang hangat, empatik, dan sangat informatif. "
    "Jawab pertanyaan user tentang CV, interview, gaji/UMR, dan strategi karir secara langsung (to the point), "
    "berikan estimasi angka jika ditanya nominal gaji/UMR, dan gunakan Bahasa Indonesia yang natural tanpa "
    "menyertakan tag format internal atau debug."
)

MOCK_MODE = False


def _clean_response(text: str) -> str:
    """
    Membersihkan tag debug internal dan mengonversi Markdown gaya GFM
    (**bold**, ### heading, dst -- yang lazim dihasilkan LLM) menjadi
    format yang KOMPATIBEL dengan Telegram legacy Markdown parse_mode,
    yang HANYA mengenali *bold* (satu bintang), bukan **bold** (dua bintang).

    Kalau tidak dikonversi, Telegram gagal parse entity-nya dan
    mengembalikan error "can't parse entities" -- yang biasanya berujung
    pesan terkirim mentah dengan tanda bintang kelihatan semua (persis
    bug yang muncul di screenshot).
    """
    if not text:
        return ""

    cleaned_lines = []
    for line in text.split("\n"):
        if line.strip().startswith(("*Lang", "*Leng", "*Format:")):
            continue

        line_stripped = line.strip()

        if line_stripped.startswith("### "):
            header_content = line_stripped[4:].strip()
            line = f"*{header_content}*"
        elif line_stripped.startswith("## "):
            header_content = line_stripped[3:].strip()
            line = f"*{header_content}*"
        elif line_stripped.startswith("# "):
            header_content = line_stripped[2:].strip()
            line = f"*{header_content}*"

        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()

    # INI FIX UTAMANYA: ubah **bold** (GFM/dua bintang) -> *bold* (Telegram/satu bintang)
    result = re.sub(r"\*\*(.+?)\*\*", r"*\1*", result)

    # Safety net: kalau jumlah asterisk masih ganjil (unmatched), buang
    # semua asterisk daripada bikin Telegram gagal parse & pesan gak terkirim.
    if result.count("*") % 2 != 0:
        logger.warning("Odd number of '*' detected after cleaning, stripping all asterisks as safety fallback")
        result = result.replace("*", "")

    return result


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
    def __init__(self, primary_provider: str = "gemini"):
        self.gemini_detector = GeminiGoalDetector()

        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

        logger.info(
            "AIGateway init | GeminiModel=%s GroqModel=%s OpenRouterModel=%s | MockMode=%s",
            self.gemini_model, self.groq_model, self.openrouter_model, MOCK_MODE,
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

    def _log_usage(self, user_id, provider, feature, p_tokens, c_tokens, status_code=200, is_error=False, error_msg=""):
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

    async def detect_goal_and_intent(self, query: str, request_id: str = None) -> Dict[str, Any]:
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

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as session:
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

    async def _call_gemini(self, session, user_message, context, system_prompt) -> Tuple[str, int, int]:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY kosong / tidak ter-set")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        full_text = f"{system_prompt}\n\nUser Question: {user_message}"
        payload = {
            "contents": [{"parts": [{"text": full_text}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        }

        async with session.post(url, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            try:
                res_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                res_text = _clean_response(res_text)
                usage_meta = data.get("usageMetadata", {})
                p_tokens = usage_meta.get("promptTokenCount", len(full_text) // 4)
                c_tokens = usage_meta.get("candidatesTokenCount", len(res_text) // 4)
                return res_text, p_tokens, c_tokens
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected Gemini response shape: {data}") from e

    async def _call_groq(self, session, user_message, context, system_prompt) -> Tuple[str, int, int]:
        if not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY kosong / tidak ter-set")

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            try:
                res_text = data["choices"][0]["message"]["content"].strip()
                res_text = _clean_response(res_text)
                usage = data.get("usage", {})
                return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected Groq response shape: {data}") from e

    async def _call_openrouter(self, session, user_message, context, system_prompt) -> Tuple[str, int, int]:
        if not self.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY kosong / tidak ter-set")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.openrouter_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            try:
                res_text = data["choices"][0]["message"]["content"].strip()
                res_text = _clean_response(res_text)
                usage = data.get("usage", {})
                return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            except (KeyError, IndexError) as e:
                raise RuntimeError(f"Unexpected OpenRouter response shape: {data}") from e