import httpx
import os
import logging
from app.intelligence.canonical import LLMResponse
from app.intelligence.llm.base_provider import BaseLLMProvider

logger = logging.getLogger(__name__)

class OpenRouterProvider(BaseLLMProvider):
    def __init__(self):
        self.api_key = os.getenv(
            "OPENROUTER_API_KEY", 
            "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"
        )
        self.model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate(self, prompt: str, system_prompt: str = "") -> LLMResponse:
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY tidak ditemukan!")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://boontrack.com",
            "X-Title": "BoonTrack Core",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            
            text_result = data["choices"][0]["message"]["content"]
            return LLMResponse(
                text=text_result, 
                provider="openrouter",
                finish_reason="stop"
            )