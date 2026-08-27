import os
import time
import logging
import httpx
from app.intelligence.canonical import LLMResponse
from app.intelligence.llm.base_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class OpenRouterProvider(BaseLLMProvider):
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.model = os.getenv(
            "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
        )
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.7
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="Maaf, OPENROUTER_API_KEY belum diatur di server.",
                finish_reason="error",
                provider="openrouter",
                model=self.model,
            )

        start_time = time.time()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://boontrack.com",
            "X-Title": "BoonTrack Core",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                response = await client.post(
                    self.url, headers=headers, json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    latency = (time.time() - start_time) * 1000

                    return LLMResponse(
                        text=content,
                        finish_reason="stop",
                        latency_ms=round(latency, 2),
                        provider="openrouter",
                        model=self.model,
                    )
                else:
                    err_msg = f"OpenRouter API Error {response.status_code}: {response.text}"
                    logger.error(err_msg)
                    return LLMResponse(
                        text=f"Maaf, kendala layanan OpenRouter ({response.status_code}).",
                        finish_reason="error",
                        provider="openrouter",
                        model=self.model,
                    )

        except Exception as e:
            logger.error(f"Error panggilan OpenRouter: {str(e)}")
            return LLMResponse(
                text=f"Maaf, gagal menghubungi AI OpenRouter: {str(e)}",
                finish_reason="error",
                provider="openrouter",
                model=self.model,
            )
