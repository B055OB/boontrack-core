"""app/services/ai_gateway.py
BoonTrack Unified Shared AI Gateway & Model Router (ADR Architecture).

Menaungi 3 profil agen spesifik (Single AI Infrastructure, 3 Specialized Agents):
1. BUYER_ASSISTANT (Store Sales Agent)   -> Model Profile: FAST (Low Latency)
2. MERCHANT_COPILOT (BoonPilot)          -> Model Profile: REASONING (Deep Thinking & Tool Calling)
3. PLATFORM_SUPPORT (BoonTrack CS)       -> Model Profile: FAST / BALANCED (Empathetic & Solutive)

Fitur Utama:
- Abstraksi provider multi-model: Gemini, Claude (Anthropic), OpenAI, Groq, OpenRouter.
- Dynamic Model Router dengan automatic failover jika salah satu provider rate-limit (429) atau timeout.
- Non-blocking audit logging metrik latensi, token, dan health check ke PostgreSQL.
- 100% backward-compatible untuk modul yang sudah ada.
"""

import os
import json
import logging
import uuid
import time
import re
import asyncio
import enum
from typing import Dict, Any, Optional, Tuple, List, Callable
import psycopg2
import aiohttp
from app.services.goal_detector import BaseGoalDetector

logger = logging.getLogger("ai_gateway")

PROMPT_VERSION = "goal_detector_v1"
MOCK_MODE = False

SYSTEM_PROMPT_DEFAULT = (
    "Kamu adalah BoonTrack, asisten karir & rekrutmen profesional yang hangat, empatik, dan to-the-point.\n\n"
    "Pedoman Menjawab:\n"
    "1. Jawab pertanyaan user seputar pembuatan CV, persiapan interview, estimasi gaji/UMR, dan strategi karir secara langsung dan praktis.\n"
    "2. Gunakan Bahasa Indonesia yang natural, profesional, dan mudah dipahami.\n"
    "3. JANGAN PERNAH menyertakan penawaran jasa pembuatan website agensi berharga jutaan rupiah.\n\n"
    "Instruksi Khusus untuk Career Page / Portofolio Web:\n"
    "Jika user bertanya tentang pengaruh, fungsi, atau manfaat memiliki Career Page / Portofolio Online:\n"
    "- Jelaskan secara ringkas 2-3 alasan kenapa rekruter menyukainya.\n"
    "- Tutup jawaban secara natural dengan mengarahkan user untuk aktivasi Career Page BoonTrack:\n"
    "1. Order Career Page (Rp10.000)\n"
    "2. Ajak 5 Teman (Gratis via Referral)\n"
    "_Ketik angka 1 atau 2 untuk memilih._"
)


# ============================================================================
# 1. ENUMS & AGENT PROFILE DEFINITIONS (ADR SPECIFICATION)
# ============================================================================

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


def _clean_response(text: str) -> str:
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


# ============================================================================
# 2. PROVIDER ABSTRACTION INTERFACE & CONCRETE IMPLEMENTATIONS
# ============================================================================

class BaseLLMProvider:
    """Antarmuka dasar untuk semua provider LLM yang terintegrasi."""

    def __init__(self, name: str):
        self.name = name

    @property
    def provider_name(self) -> str:
        return self.name.lower()

    def is_available(self) -> bool:
        raise NotImplementedError

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        raise NotImplementedError

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
    ) -> Tuple[str, int, int]:
        """Eksekusi panggilan HTTP ke provider. Returns: (response_text, prompt_tokens, completion_tokens)."""
        raise NotImplementedError


class GeminiProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__("Gemini")
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.default_model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.REASONING:
            return os.getenv("GEMINI_REASONING_MODEL", "gemini-1.5-pro")
        elif profile == ModelProfile.FAST:
            return os.getenv("GEMINI_FAST_MODEL", self.default_model or "gemini-1.5-flash")
        return self.default_model or "gemini-1.5-flash"

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
    ) -> Tuple[str, int, int]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={self.api_key}"
        )
        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": user_message}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        }
        if system_prompt and str(system_prompt).strip():
            payload["system_instruction"] = {
                "parts": [{"text": str(system_prompt).strip()}]
            }

        async with session.post(url, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                # Fallback jika model tidak support system_instruction terpisah
                if "system_instruction" in payload:
                    full_text = f"{system_prompt}\n\nUser Question: {user_message}"
                    fallback_payload = {
                        "contents": [{"parts": [{"text": full_text}]}],
                        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
                    }
                    async with session.post(url, json=fallback_payload) as fb_resp:
                        if fb_resp.status == 200:
                            data = await fb_resp.json()
                            res_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                            res_text = _clean_response(res_text)
                            usage_meta = data.get("usageMetadata", {})
                            p_tokens = usage_meta.get("promptTokenCount", len(full_text) // 4)
                            c_tokens = usage_meta.get("candidatesTokenCount", len(res_text) // 4)
                            return res_text, p_tokens, c_tokens
                raise RuntimeError(f"Gemini HTTP {resp.status}: {body[:300]}")

            data = json.loads(body)
            res_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            res_text = _clean_response(res_text)
            usage_meta = data.get("usageMetadata", {})
            prompt_len = len(str(system_prompt or "")) + len(str(user_message or ""))
            p_tokens = usage_meta.get("promptTokenCount", prompt_len // 4)
            c_tokens = usage_meta.get("candidatesTokenCount", len(res_text) // 4)
            return res_text, p_tokens, c_tokens


class GroqProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__("Groq")
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.default_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.FAST:
            return os.getenv("GROQ_FAST_MODEL", "llama-3.3-70b-versatile")
        elif profile == ModelProfile.REASONING:
            return os.getenv("GROQ_REASONING_MODEL", "llama-3.3-70b-versatile")
        return self.default_model

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
    ) -> Tuple[str, int, int]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_name,
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
                raise RuntimeError(f"Groq HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            res_text = data["choices"][0]["message"]["content"].strip()
            res_text = _clean_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude Provider (Claude 3.5 Sonnet / Haiku)."""

    def __init__(self):
        super().__init__("Claude")
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.REASONING:
            return os.getenv("CLAUDE_REASONING_MODEL", "claude-3-5-sonnet-20241022")
        return os.getenv("CLAUDE_FAST_MODEL", "claude-3-5-haiku-20241022")

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
    ) -> Tuple[str, int, int]:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model_name,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "max_tokens": 4096,
            "temperature": 0.7,
        }
        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Claude HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            text_blocks = [block["text"] for block in data.get("content", []) if block.get("type") == "text"]
            res_text = "\n".join(text_blocks).strip()
            res_text = _clean_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Direct Provider (GPT-4o / GPT-4o-mini)."""

    def __init__(self):
        super().__init__("OpenAI")
        self.api_key = os.getenv("OPENAI_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.REASONING:
            return os.getenv("OPENAI_REASONING_MODEL", "gpt-4o")
        return os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
    ) -> Tuple[str, int, int]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_name,
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
                raise RuntimeError(f"OpenAI HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            res_text = data["choices"][0]["message"]["content"].strip()
            res_text = _clean_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter Multi-Model Proxy Provider."""

    def __init__(self):
        super().__init__("OpenRouter")
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.default_model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.REASONING:
            return os.getenv("OPENROUTER_REASONING_MODEL", "anthropic/claude-3.5-sonnet")
        return self.default_model

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
    ) -> Tuple[str, int, int]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_name,
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
                raise RuntimeError(f"OpenRouter HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            res_text = data["choices"][0]["message"]["content"].strip()
            res_text = _clean_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


# ============================================================================
# 3. GOAL DETECTOR
# ============================================================================

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


# ============================================================================
# 4. UNIFIED AI GATEWAY & MODEL ROUTER
# ============================================================================

class AIGateway:
    """
    Central AI Gateway & Model Router BoonTrack.
    Mengelola failover, penentuan model profile, audit log, dan perutean agen.
    """

    def __init__(self, primary_provider: str = "gemini"):
        self.gemini_detector = GeminiGoalDetector()

        # Inisialisasi daftar provider terdaftar
        self.providers: Dict[str, BaseLLMProvider] = {
            "Gemini": GeminiProvider(),
            "Groq": GroqProvider(),
            "Claude": ClaudeProvider(),
            "OpenAI": OpenAIProvider(),
            "OpenRouter": OpenRouterProvider(),
        }

        # Model default per provider
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

        active_providers = [name for name, p in self.providers.items() if p.is_available()]
        logger.info(
            "AIGateway initialized | Available Providers: %s | MockMode=%s",
            active_providers, MOCK_MODE
        )

    def _get_db_conn(self):
        """Mendukung koneksi PostgreSQL via Supabase Connection Pooler maupun fallback default."""
        host = os.getenv("POSTGRES_HOST")
        if host:
            try:
                return psycopg2.connect(
                    host=host,
                    port=os.getenv("POSTGRES_PORT", "6543"),
                    dbname=os.getenv("POSTGRES_DB", "postgres"),
                    user=os.getenv("POSTGRES_USER"),
                    password=os.getenv("POSTGRES_PASSWORD"),
                    connect_timeout=5,
                )
            except Exception:
                pass

        db_url = os.getenv("DATABASE_URL")
        if db_url:
            return psycopg2.connect(db_url, connect_timeout=5)

        raise ValueError("Database connection configuration not found")

    def _log_health(
        self, provider: str, model: str, status: str, latency: float, fallback: str = "NO", error_msg: str = ""
    ):
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
        print(log_str, flush=True)

    def _insert_db_sync(
        self,
        user_id: Optional[int],
        provider: str,
        feature: str,
        p_tokens: int,
        c_tokens: int,
        status_code: int,
        is_error: bool,
        error_msg: str,
    ):
        try:
            clean_user_id = None
            if user_id is not None:
                try:
                    clean_user_id = int(user_id)
                except (ValueError, TypeError):
                    clean_user_id = None

            conn = self._get_db_conn()
            cur = conn.cursor()
            query = """
                INSERT INTO ai_usage_logs
                (user_id, provider, feature, prompt_tokens, completion_tokens, total_tokens, status_code, is_error, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """
            cur.execute(
                query,
                (
                    clean_user_id, provider, feature, p_tokens, c_tokens,
                    p_tokens + c_tokens, status_code, is_error, error_msg[:500],
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug("Catatan AI Usage Log DB: %s", str(e))

    def _log_usage(self, user_id, provider, feature, p_tokens, c_tokens, status_code=200, is_error=False, error_msg=""):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(
                self._insert_db_sync,
                user_id, provider, feature, p_tokens, c_tokens, status_code, is_error, error_msg
            ))
        except RuntimeError:
            self._insert_db_sync(user_id, provider, feature, p_tokens, c_tokens, status_code, is_error, error_msg)

    async def detect_goal_and_intent(self, query: str, request_id: str = None) -> Dict[str, Any]:
        return await self.gemini_detector.detect(query, request_id)

    def resolve_provider_order(
        self,
        profile: ModelProfile,
        only_available: bool = True,
    ) -> List[Tuple[BaseLLMProvider, str]]:
        """
        Menyusun urutan provider dan nama model berdasarkan ModelProfile yang diminta:
        - FAST: Memprioritaskan Groq (Llama 70B fast inference) -> Gemini Flash -> Claude Haiku -> OpenAI mini -> OpenRouter
        - BALANCED: Memprioritaskan Gemini Flash -> Claude Haiku -> Groq -> OpenAI mini -> OpenRouter
        - REASONING: Memprioritaskan Gemini Pro / Claude Sonnet -> OpenAI GPT-4o -> Groq / OpenRouter
        """
        resolved: List[Tuple[BaseLLMProvider, str]] = []

        if profile == ModelProfile.FAST:
            preference = ["Groq", "Gemini", "Claude", "OpenAI", "OpenRouter"]
        elif profile == ModelProfile.REASONING:
            preference = ["Gemini", "Claude", "OpenAI", "Groq", "OpenRouter"]
        else:  # BALANCED
            preference = ["Gemini", "Groq", "Claude", "OpenAI", "OpenRouter"]

        for name in preference:
            p = self.providers.get(name)
            if p and (not only_available or p.is_available()):
                model = p.get_model_for_profile(profile)
                resolved.append((p, model))

        return resolved

    async def generate_for_agent(
        self,
        agent_profile: AgentProfile,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """
        Entrypoint terpadu untuk mengeksekusi inferensi AI berdasarkan profil agen khusus.
        Memetakan AgentProfile -> ModelProfile (FAST, REASONING, BALANCED).
        """
        context = context or {}
        model_profile = AGENT_TO_MODEL_PROFILE.get(agent_profile, ModelProfile.FAST)
        context["agent_profile"] = agent_profile.value
        context["model_profile"] = model_profile.value

        return await self.generate_with_profile(
            profile=model_profile,
            user_message=user_message,
            context=context,
            system_prompt=system_prompt or SYSTEM_PROMPT_DEFAULT,
        )

    async def generate_with_profile(
        self,
        profile: ModelProfile,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: str = SYSTEM_PROMPT_DEFAULT,
    ) -> Optional[str]:
        """Menjalankan perutean model dan failover berdasarkan profil performa."""
        if MOCK_MODE:
            logger.info("AIGateway running in MOCK_MODE")
            return f"🤖 [MOCK RESPON]: Pesan '{user_message[:50]}' diproses oleh AIGateway ({profile.value})."

        context = context or {}
        user_id = context.get("user_id")
        feature = context.get("feature", context.get("agent_profile", "general"))
        timeout_sec = float(context.get("timeout", 25.0))

        provider_chain = self.resolve_provider_order(profile)
        if not provider_chain:
            logger.warning("[AI Gateway Router] Tidak ada provider aktif dengan API key!")
            return None

        provider_timeout = aiohttp.ClientTimeout(total=timeout_sec)
        gateway_start_time = time.time()
        trace_logs = []

        async with aiohttp.ClientSession(timeout=provider_timeout) as session:
            for idx, (provider, model_name) in enumerate(provider_chain):
                p_start = time.time()
                try:
                    res_text, p_tokens, c_tokens = await provider.call(
                        session=session,
                        user_message=user_message,
                        context=context,
                        system_prompt=system_prompt,
                        model_name=model_name,
                    )
                    p_lat_ms = (time.time() - p_start) * 1000
                    total_ai_ms = (time.time() - gateway_start_time) * 1000

                    trace_logs.append(f"• {provider.name} ({model_name}): {p_lat_ms:.1f}ms -> SUCCESS")
                    print(
                        f"\n[AI TRACE ({profile.value})] Agent: {feature} | Total: {total_ai_ms:.1f}ms\n"
                        + "\n".join(trace_logs),
                        flush=True,
                    )

                    fallback_info = "NO" if idx == 0 else f"YES (Used {provider.name})"
                    self._log_health(provider.name, model_name, "SUCCESS", p_lat_ms / 1000, fallback=fallback_info)
                    self._log_usage(user_id, provider.name, feature, p_tokens, c_tokens, 200, False)
                    return res_text

                except Exception as e:
                    p_lat_ms = (time.time() - p_start) * 1000
                    err_str = str(e)
                    err_type = "TIMEOUT" if "Timeout" in err_str or "timed out" in err_str else "ERROR"
                    trace_logs.append(f"• {provider.name} ({model_name}): {p_lat_ms:.1f}ms -> {err_type} ({err_str[:60]})")

                    status_code = (
                        429 if ("429" in err_str or "quota" in err_str.lower() or "limit" in err_str.lower())
                        else 500
                    )
                    next_provider = provider_chain[idx + 1][0].name if idx + 1 < len(provider_chain) else "NONE"
                    self._log_health(
                        provider.name, model_name, "FAILED", p_lat_ms / 1000,
                        fallback=f"YES ({next_provider})", error_msg=err_str
                    )
                    self._log_usage(user_id, provider.name, feature, 0, 0, status_code, True, err_str)
                    continue

        total_ai_ms = (time.time() - gateway_start_time) * 1000
        print(f"\n[AI TRACE EXHAUSTED] Total AI: {total_ai_ms:.1f}ms\n" + "\n".join(trace_logs), flush=True)
        return None

    async def generate(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: str = SYSTEM_PROMPT_DEFAULT,
    ) -> Optional[str]:
        """
        Metode generik backward-compatible.
        Secara default menggunakan profil FAST atau model profile yang tertera di context.
        """
        context = context or {}
        raw_prof = str(context.get("model_profile", "FAST")).upper().strip()
        profile = ModelProfile.FAST
        if raw_prof in ModelProfile.__members__:
            profile = ModelProfile[raw_prof]

        return await self.generate_with_profile(
            profile=profile,
            user_message=user_message,
            context=context,
            system_prompt=system_prompt,
        )


ai_gateway = AIGateway()
