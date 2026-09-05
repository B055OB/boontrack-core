"""app/services/ai_gateway/gateway.py
BoonTrack Shared AI Gateway & Model Router.
Coordinates multi-agent profiles, provider fallback chains, and non-blocking usage metrics.
"""

import os
import json
import logging
import uuid
import time
import asyncio
from typing import Dict, Any, Optional, Tuple, List
import psycopg2
import aiohttp

from app.services.goal_detector import BaseGoalDetector
from app.services.ai_gateway.models import (
    ModelProfile,
    AgentProfile,
    AGENT_TO_MODEL_PROFILE,
    clean_ai_response,
)
from app.services.ai_gateway.providers import (
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    ClaudeProvider,
    OpenAIProvider,
    OpenRouterProvider,
)

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


class GeminiGoalDetector(BaseGoalDetector):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def detect(self, query: str, request_id: str = None) -> Dict[str, Any]:
        return {
            "intent": "general_query",
            "confidence": 0.95,
            "request_id": request_id or str(uuid.uuid4()),
        }


class AIGateway:
    """
    Shared Enterprise AI Gateway BoonTrack.
    Mengatur router model multi-agent profile, failover antar provider, dan audit logging.
    """

    def __init__(self):
        self.providers: Dict[str, BaseLLMProvider] = {
            "Gemini": GeminiProvider(),
            "Groq": GroqProvider(),
            "Claude": ClaudeProvider(),
            "OpenAI": OpenAIProvider(),
            "OpenRouter": OpenRouterProvider(),
        }

        # Legacy backward compatibility
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_detector = GeminiGoalDetector(self.gemini_api_key)

        available_providers = [name for name, p in self.providers.items() if p.is_available()]
        logger.info(
            f"AIGateway initialized | Available Providers: {available_providers} | MockMode={MOCK_MODE}"
        )

    def _get_db_conn(self):
        host = os.getenv("POSTGRES_HOST")
        if host:
            try:
                return psycopg2.connect(
                    host=host,
                    port=os.getenv("POSTGRES_PORT", "6543"),
                    dbname=os.getenv("POSTGRES_DB", "postgres"),
                    user=os.getenv("POSTGRES_USER"),
                    password=os.getenv("POSTGRES_PASSWORD"),
                    connect_timeout=3,
                )
            except Exception as e:
                logger.warning(f"[AI Gateway] Pooler connect failed ({e}), trying DATABASE_URL...")

        db_url = os.getenv("DATABASE_URL")
        if db_url:
            clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
            return psycopg2.connect(clean_url, connect_timeout=3)
        return None

    def _insert_db_sync(self, user_id, provider, feature, p_tokens, c_tokens, status_code, is_error, error_msg):
        try:
            conn = self._get_db_conn()
            if not conn:
                return
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ai_usage_logs (user_id, provider, feature, prompt_tokens, completion_tokens, status_code, is_error, error_message, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (str(user_id or "anonymous"), provider, feature, p_tokens, c_tokens, status_code, is_error, error_msg),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"[AI Gateway] Logging usage to PostgreSQL skipped: {e}")

    async def log_usage_db(
        self,
        user_id: str,
        provider: str,
        feature: str,
        p_tokens: int,
        c_tokens: int,
        status_code: int = 200,
        is_error: bool = False,
        error_msg: str = None,
    ):
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(
                None,
                self._insert_db_sync,
                user_id, provider, feature, p_tokens, c_tokens, status_code, is_error, error_msg,
            )
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
        logger.info(
            f"[AI Gateway] Routing agent '{agent_profile.value}' -> ModelProfile: '{model_profile.value}'"
        )
        return await self.generate_with_profile(
            profile=model_profile,
            user_message=user_message,
            context=context,
            system_prompt=system_prompt,
            agent_profile_tag=agent_profile.value,
        )

    async def generate_with_profile(
        self,
        profile: ModelProfile,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        agent_profile_tag: str = "GENERAL",
    ) -> Optional[str]:
        """
        Mengeksekusi inferensi AI berdasarkan profil model dengan chain of failover otomatis.
        """
        context = context or {}
        feature = context.get("feature", f"agent_{agent_profile_tag.lower()}")
        user_id = context.get("user_id") or context.get("tenant_slug") or context.get("phone") or "guest"
        sys_prompt = system_prompt or SYSTEM_PROMPT_DEFAULT

        provider_chain = self.resolve_provider_order(profile, only_available=True)

        if not provider_chain:
            logger.error(f"[AI Gateway] No available providers configured for profile {profile.value}")
            return None

        total_start = time.time()
        trace_logs = []
        timeout = aiohttp.ClientTimeout(total=18.0)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for idx, (provider, model_name) in enumerate(provider_chain):
                p_start = time.time()
                try:
                    res_text, p_tokens, c_tokens = await provider.call(
                        session=session,
                        user_message=user_message,
                        context=context,
                        system_prompt=sys_prompt,
                        model_name=model_name,
                    )
                    p_lat_ms = (time.time() - p_start) * 1000.0
                    tot_lat_s = time.time() - total_start

                    # Log successful inference
                    fallback_flag = f"YES (Used {provider.name})" if idx > 0 else "NO"
                    print(
                        f"\n[AI LOG]\n"
                        f"  Provider  : {provider.name}\n"
                        f"  Model     : {model_name}\n"
                        f"  Status    : SUCCESS\n"
                        f"  Latency   : {tot_lat_s:.2f}s\n"
                        f"  Fallback  : {fallback_flag}",
                        flush=True,
                    )

                    await self.log_usage_db(
                        user_id=user_id,
                        provider=f"{provider.name}:{model_name}",
                        feature=feature,
                        p_tokens=p_tokens,
                        c_tokens=c_tokens,
                        status_code=200,
                        is_error=False,
                    )
                    return res_text

                except Exception as e:
                    p_lat_ms = (time.time() - p_start) * 1000.0
                    err_str = str(e)
                    err_type = "TIMEOUT" if isinstance(e, asyncio.TimeoutError) else "ERROR"
                    trace_logs.append(f"• {provider.name} ({model_name}): {p_lat_ms:.1f}ms -> {err_type} ({err_str[:60]})")

                    fallback_target = provider_chain[idx + 1][0].name if idx + 1 < len(provider_chain) else "None"
                    print(
                        f"\n[AI LOG]\n"
                        f"  Provider  : {provider.name}\n"
                        f"  Model     : {model_name}\n"
                        f"  Status    : FAILED\n"
                        f"  Latency   : {p_lat_ms / 1000.0:.2f}s\n"
                        f"  Fallback  : YES ({fallback_target})\n"
                        f"  Reason    : {err_str[:120]}",
                        flush=True,
                    )

                    await self.log_usage_db(
                        user_id=user_id,
                        provider=f"{provider.name}:{model_name}",
                        feature=feature,
                        p_tokens=0,
                        c_tokens=0,
                        status_code=500,
                        is_error=True,
                        error_msg=err_str[:250],
                    )

                    if idx + 1 < len(provider_chain):
                        logger.warning(
                            f"[AI Gateway Failover] {provider.name} failed ({err_str[:60]}), "
                            f"trying fallback provider: {provider_chain[idx + 1][0].name}"
                        )
                    continue

        tot_lat_ms = (time.time() - total_start) * 1000.0
        trace_str = "\n".join(trace_logs)
        print(f"\n[AI TRACE ({profile.value})] Agent: {agent_profile_tag} | Total: {tot_lat_ms:.1f}ms\n{trace_str}\n", flush=True)
        logger.error(f"[AI Gateway] All providers exhausted for profile {profile.value}")
        return None

    async def generate(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
        feature: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Fungsi general generasi teks yang backwards-compatible.
        Memanfaatkan profile BALANCED secara default.
        """
        ctx = context or {}
        if feature:
            ctx["feature"] = feature
        if user_id:
            ctx["user_id"] = user_id

        return await self.generate_with_profile(
            profile=ModelProfile.BALANCED,
            user_message=user_message,
            context=ctx,
            system_prompt=system_prompt,
            agent_profile_tag="LEGACY_BALANCED",
        )


# Singleton
ai_gateway = AIGateway()
