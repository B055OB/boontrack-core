"""app/services/ai_gateway/providers.py
Multi-provider LLM abstraction layer for BoonTrack AI Gateway.
Supported: Gemini, Groq, Claude (Anthropic), OpenAI, OpenRouter.
"""

import os
import json
import logging
from typing import Dict, Any, Tuple
import aiohttp

from app.services.ai_gateway.models import ModelProfile, clean_ai_response

logger = logging.getLogger("ai_gateway.providers")


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
                            res_text = clean_ai_response(res_text)
                            usage_meta = data.get("usageMetadata", {})
                            p_tokens = usage_meta.get("promptTokenCount", len(full_text) // 4)
                            c_tokens = usage_meta.get("candidatesTokenCount", len(res_text) // 4)
                            return res_text, p_tokens, c_tokens
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
            res_text = clean_ai_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


class ClaudeProvider(BaseLLMProvider):
    """Anthropic Claude Provider (Claude 3.5 Sonnet / Haiku)."""

    def __init__(self):
        super().__init__("Claude")
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("CLAUDE_API_KEY", "")
        self.default_model = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.FAST:
            return os.getenv("CLAUDE_FAST_MODEL", "claude-3-5-haiku-20241022")
        elif profile == ModelProfile.REASONING:
            return os.getenv("CLAUDE_REASONING_MODEL", "claude-3-5-sonnet-20241022")
        return self.default_model

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
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": user_message}],
        }
        if system_prompt and system_prompt.strip():
            payload["system"] = system_prompt.strip()

        async with session.post(url, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"Claude HTTP {resp.status}: {body[:300]}")
            data = json.loads(body)
            res_text = data["content"][0]["text"].strip()
            res_text = clean_ai_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Provider (GPT-4o / GPT-4o-mini)."""

    def __init__(self):
        super().__init__("OpenAI")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.default_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
            res_text = clean_ai_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter Multi-Model Provider (Fallback & Custom Routing)."""

    def __init__(self):
        super().__init__("OpenRouter")
        self.api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.default_model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def get_model_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.REASONING:
            return os.getenv("OPENROUTER_REASONING_MODEL", "anthropic/claude-3.5-sonnet")
        elif profile == ModelProfile.FAST:
            return os.getenv("OPENROUTER_FAST_MODEL", "meta-llama/llama-3.3-70b-instruct")
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
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://boontrack.com",
            "X-Title": "BoonTrack AI Gateway",
        }
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
            res_text = clean_ai_response(res_text)
            usage = data.get("usage", {})
            return res_text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
