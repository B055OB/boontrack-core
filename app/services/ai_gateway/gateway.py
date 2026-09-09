"""app/services/ai_gateway/gateway.py
BoonTrack Shared AI Gateway & Model Router.
Coordinates multi-agent profiles, task capabilities, and resilient failover chains.
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

from app.services.ai_gateway.models import (
    ModelProfile,
    AgentProfile,
    AICapability,
    AGENT_TO_CAPABILITY,
    clean_ai_response,
)
from app.services.ai_gateway.providers import (
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    OpenRouterProvider,
)

logger = logging.getLogger("ai_gateway")


class CircuitBreaker:
    """Circuit Breaker untuk mencegah request flood saat provider mengalami total outage."""
    def __init__(self, failure_threshold: int = 3, recovery_time: float = 45.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.failure_count = 0
        self.last_failure_time = 0.0

    def is_open(self) -> bool:
        if self.failure_count >= self.failure_threshold:
            if time.time() - self.last_failure_time > self.recovery_time:
                self.failure_count = 0
                return False
            return True
        return False

    def record_success(self):
        self.failure_count = 0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()


class AIGateway:
    """
    Shared Enterprise AI Gateway BoonTrack.
    Mengatur Single Doorway LLM, Capability Mapping, Circuit Breaker, dan Audit Usage Logging.
    """

    def __init__(self):
        self.gemini = GeminiProvider()
        self.groq = GroqProvider()
        self.openrouter = OpenRouterProvider()

        self.circuit_breakers: Dict[str, CircuitBreaker] = {
            "gemini": CircuitBreaker(failure_threshold=3, recovery_time=45.0),
            "groq": CircuitBreaker(failure_threshold=3, recovery_time=45.0),
            "openrouter": CircuitBreaker(failure_threshold=2, recovery_time=60.0),
        }

        logger.info(
            f"AIGateway initialized per CTO Spec | Gemini Available={self.gemini.is_available()}, "
            f"Groq Available={self.groq.is_available()}, OpenRouter Available={self.openrouter.is_available()}"
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
            except Exception:
                pass

        db_url = os.getenv("DATABASE_URL")
        if db_url:
            clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
            try:
                return psycopg2.connect(clean_url, connect_timeout=3)
            except Exception:
                return None
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
        except Exception:
            pass

    async def log_usage_db(self, user_id: str, provider: str, feature: str, p_tokens: int, c_tokens: int, status_code: int = 200, is_error: bool = False, error_msg: str = None):
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._insert_db_sync, user_id, provider, feature, p_tokens, c_tokens, status_code, is_error, error_msg)
        except RuntimeError:
            self._insert_db_sync(user_id, provider, feature, p_tokens, c_tokens, status_code, is_error, error_msg)

    def build_execution_chain(self, capability: AICapability) -> List[Tuple[BaseLLMProvider, str, str]]:
        """
        Menyusun rantai eksekusi terverifikasi CTO:
        1. Primary: Gemini 3.8 Flash
        2. Groq #1: Qwen 3.6 27B
        3. Groq #2: OpenAI GPT-OSS 120B
        4. Emergency: OpenRouter
        """
        chain: List[Tuple[BaseLLMProvider, str, str]] = []

        # 1. Primary Path (Gemini 3.8 Flash)
        if self.gemini.is_available() and not self.circuit_breakers["gemini"].is_open():
            gemini_model = self.gemini.get_model_for_capability(capability)
            chain.append((self.gemini, gemini_model, "Primary (Gemini 3.8)"))

        # 2. Secondary Path (Groq Qwen 3.6 27B & GPT-OSS 120B)
        if self.groq.is_available() and not self.circuit_breakers["groq"].is_open():
            groq_qwen = os.getenv("AI_GROQ_MODEL", "qwen/qwen3.6-27b").strip()
            groq_gpt_oss = os.getenv("AI_GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b").strip()
            chain.append((self.groq, groq_qwen, "Groq #1 (Qwen 3.6)"))
            chain.append((self.groq, groq_gpt_oss, "Groq #2 (GPT-OSS 120B)"))

        # 3. Emergency Path (OpenRouter)
        if self.openrouter.is_available() and not self.circuit_breakers["openrouter"].is_open():
            chain.append((self.openrouter, self.openrouter.get_model_for_capability(capability), "Emergency (OpenRouter)"))

        return chain

    async def generate_for_capability(
        self,
        capability: AICapability,
        user_message: str,
        system_prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Eksekusi inferensi AI berdasarkan Capability Task secara deterministik."""
        context = context or {}
        feature = context.get("feature", f"capability_{capability.value.lower()}")
        user_id = context.get("user_id") or context.get("tenant_slug") or "store_guest"

        chain = self.build_execution_chain(capability)
        if not chain:
            logger.error(f"[AI Gateway] Circuit breaker open or all providers unconfigured for {capability.value}")
            return None

        total_start = time.time()
        timeout = aiohttp.ClientTimeout(total=15.0)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for provider, model_name, path_role in chain:
                p_start = time.time()
                try:
                    res_text, p_tokens, c_tokens = await provider.call(
                        session=session,
                        user_message=user_message,
                        context=context,
                        system_prompt=system_prompt,
                        model_name=model_name,
                        capability=capability,
                    )
                    tot_lat_s = time.time() - total_start

                    cb_key = provider.name.lower()
                    if cb_key in self.circuit_breakers:
                        self.circuit_breakers[cb_key].record_success()

                    print(
                        f"\n[AI LOG - CTO PIPELINE]\n"
                        f"  Role      : {path_role}\n"
                        f"  Provider  : {provider.name}\n"
                        f"  Model     : {model_name}\n"
                        f"  Status    : SUCCESS\n"
                        f"  Latency   : {tot_lat_s:.2f}s\n",
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

                    cb_key = provider.name.lower()
                    if cb_key in self.circuit_breakers:
                        self.circuit_breakers[cb_key].record_failure()

                    print(
                        f"\n[AI LOG - CTO PIPELINE]\n"
                        f"  Role      : {path_role}\n"
                        f"  Provider  : {provider.name}\n"
                        f"  Model     : {model_name}\n"
                        f"  Status    : FAILED ({p_lat_ms:.1f}ms)\n"
                        f"  Reason    : {err_str[:120]}\n",
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
                    continue

        logger.error(f"[AI Gateway] All execution paths exhausted for capability {capability.value}")
        return None

    async def generate_for_agent(
        self,
        agent_profile: AgentProfile,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """Adapter router AgentProfile -> AICapability."""
        capability = AGENT_TO_CAPABILITY.get(agent_profile, AICapability.FAST_CONVERSATION)
        return await self.generate_for_capability(
            capability=capability,
            user_message=user_message,
            system_prompt=system_prompt or "",
            context=context,
        )

    async def generate(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """General fallback."""
        return await self.generate_for_capability(
            capability=AICapability.FAST_CONVERSATION,
            user_message=user_message,
            system_prompt=system_prompt or "",
            context=context,
        )


ai_gateway = AIGateway()