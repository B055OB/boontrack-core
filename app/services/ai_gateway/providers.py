"""app/services/ai_gateway/providers.py
Multi-provider LLM abstraction layer for BoonTrack AI Gateway.
CTO Production Model Hierarchy:
1. Primary: Gemini 3.8 Flash (gemini-3.8-flash)
2. Groq Fallback #1: Qwen 3.6 27B (qwen/qwen3.6-27b)
3. Groq Fallback #2: OpenAI GPT-OSS 120B (openai/gpt-oss-120b)
4. Emergency Cross-Provider: OpenRouter
"""

import os
import json
import logging
from typing import Dict, Any, Tuple, Optional
import aiohttp

from app.services.ai_gateway.models import (
    ModelProfile,
    AICapability,
    CAPABILITY_TO_GEMINI_THINKING,
    clean_ai_response,
)

logger = logging.getLogger("ai_gateway.providers")


class BaseLLMProvider:
    """Antarmuka dasar untuk semua provider LLM (AIProvider interface)."""

    def __init__(self, name: str):
        self.name = name

    @property
    def provider_name(self) -> str:
        return self.name.lower()

    def is_available(self) -> bool:
        raise NotImplementedError

    def get_model_for_capability(self, capability: AICapability) -> str:
        raise NotImplementedError

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
        capability: Optional[AICapability] = None,
    ) -> Tuple[str, int, int]:
        """Eksekusi panggilan HTTP ke provider. Returns: (response_text, prompt_tokens, completion_tokens)."""
        raise NotImplementedError


class GeminiProvider(BaseLLMProvider):
    """Primary Provider: Google Gemini 3.8 Flash (Production GA Stack)."""

    def __init__(self):
        super().__init__("Gemini")
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.default_model = os.getenv("AI_PRIMARY_MODEL", "gemini-3.8-flash").strip()
        self.api_version = os.getenv("GEMINI_API_VERSION", "v1beta").strip()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_model_for_capability(self, capability: AICapability) -> str:
        return self.default_model

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
        capability: Optional[AICapability] = None,
    ) -> Tuple[str, int, int]:
        model_id = model_name or self.default_model
        url = (
            f"https://generativelanguage.googleapis.com/{self.api_version}/models/"
            f"{model_id}:generateContent?key={self.api_key}"
        )

        thinking_level = "low"
        if capability and capability in CAPABILITY_TO_GEMINI_THINKING:
            thinking_level = CAPABILITY_TO_GEMINI_THINKING[capability]

        generation_config: Dict[str, Any] = {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        }

        if thinking_level in ("low", "medium", "high"):
            generation_config["thinkingConfig"] = {
                "thinkingBudget": 0 if thinking_level == "low" else (1024 if thinking_level == "medium" else 2048)
            }

        payload: Dict[str, Any] = {
            "contents": [{"parts": [{"text": user_message}]}],
            "generationConfig": generation_config,
        }

        if system_prompt and str(system_prompt).strip():
            payload["system_instruction"] = {
                "parts": [{"text": str(system_prompt).strip()}]
            }

        async with session.post(url, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                # Fallback tanpa thinkingConfig jika model v1 / payload ditolak
                fallback_payload = {
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\nUser: {user_message}"}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
                }
                async with session.post(url, json=fallback_payload) as fb_resp:
                    if fb_resp.status == 200:
                        data = await fb_resp.json()
                        res_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        res_text = clean_ai_response(res_text)
                        usage_meta = data.get("usageMetadata", {})
                        return res_text, usage_meta.get("promptTokenCount", 100), usage_meta.get("candidatesTokenCount", 100)
                raise RuntimeError(f"Gemini HTTP {resp.status}: {body[:300]}")

            data = json.loads(body)
            res_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            res_text = clean_ai_response(res_text)
            usage_meta = data.get("usageMetadata", {})
            prompt_len = len(str(system_prompt or "")) + len(str(user_message or ""))
            p_tokens = usage_meta.get("promptTokenCount", prompt_len // 4)
            c_tokens = usage_meta.get("candidatesTokenCount", len(res_text) // 4)
            return res_text, p_tokens, c_tokens


class GroqProvider(BaseLLMProvider):
    """Secondary / Failover Provider: Qwen 3.6 27B & OpenAI GPT-OSS 120B."""

    def __init__(self):
        super().__init__("Groq")
        self.api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.primary_model = os.getenv("AI_GROQ_MODEL", "qwen/qwen3.6-27b").strip()
        self.secondary_model = os.getenv("AI_GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b").strip()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def get_model_for_capability(self, capability: AICapability) -> str:
        if capability in (AICapability.BUSINESS_ADVISOR, AICapability.COMPLEX_REASONING):
            return self.secondary_model
        return self.primary_model

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
        capability: Optional[AICapability] = None,
    ) -> Tuple[str, int, int]:
        target_model = model_name or self.primary_model
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "max_tokens": 1024,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Groq HTTP {resp.status} on model {target_model}: {body[:300]}")
            data = json.loads(body)
            res_text = data["choices"][0]["message"]["content"].strip()
            res_text = clean_ai_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


class OpenRouterProvider(BaseLLMProvider):
    """Emergency / Cross-Provider Failover Provider (Last-Line Safety Net)."""

    def __init__(self):
        super().__init__("OpenRouter")
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.enabled = os.getenv("AI_OPENROUTER_ENABLED", "true").lower() == "true"
        self.models_chain = [
            os.getenv("AI_OPENROUTER_MODEL_1", "google/gemini-2.0-flash-001"),
            os.getenv("AI_OPENROUTER_MODEL_2", "qwen/qwen-2.5-72b-instruct"),
            os.getenv("AI_OPENROUTER_MODEL_3", "meta-llama/llama-3.3-70b-instruct"),
        ]

    def is_available(self) -> bool:
        return bool(self.api_key and self.enabled)

    def get_model_for_capability(self, capability: AICapability) -> str:
        return self.models_chain[0]

    async def call(
        self,
        session: aiohttp.ClientSession,
        user_message: str,
        context: Dict[str, Any],
        system_prompt: str,
        model_name: str,
        capability: Optional[AICapability] = None,
    ) -> Tuple[str, int, int]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://boontrack.com",
            "X-Title": "BoonTrack AI Emergency Gateway",
        }

        models_to_try = [model_name] if model_name else []
        for m in self.models_chain:
            if m not in models_to_try:
                models_to_try.append(m)

        payload = {
            "models": models_to_try,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "max_tokens": 1024,
        }

        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"OpenRouter HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            actual_model = data.get("model", "unknown")
            logger.info(f"[OpenRouter Emergency] Resolved model: {actual_model}")
            res_text = data["choices"][0]["message"]["content"].strip()
            res_text = clean_ai_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)