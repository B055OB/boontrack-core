import os
import time
import logging
import httpx
from app.intelligence.canonical import LLMResponse
from app.intelligence.llm.base_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class GroqProvider(BaseLLMProvider):

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama-3.1-8b-instant"

    async def generate(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.2
    ) -> LLMResponse:
        if not self.api_key:
            return LLMResponse(
                text="Maaf, GROQ_API_KEY belum diatur di server.",
                finish_reason="error",
                provider="groq",
                model=self.model,
            )

        start_time = time.time()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self.api_url, headers=headers, json=payload
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    latency = (time.time() - start_time) * 1000

                    return LLMResponse(
                        text=content,
                        finish_reason="stop",
                        latency_ms=round(latency, 2),
                        provider="groq",
                        model=self.model,
                    )
                else:
                    err_msg = f"Groq API Error {response.status_code}: {response.text}"
                    logger.error(err_msg)
                    return LLMResponse(
                        text=f"Maaf, terjadi kendala pada layanan Groq API ({response.status_code}).",
                        finish_reason="error",
                        provider="groq",
                        model=self.model,
                    )

        except Exception as e:
            logger.error(f"Error panggilan Groq API: {str(e)}")
            return LLMResponse(
                text=f"Maaf, gagal menghubungi AI Groq: {str(e)}",
                finish_reason="error",
                provider="groq",
                model=self.model,
            )
