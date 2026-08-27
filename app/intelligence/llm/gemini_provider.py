import os
import time
import logging
import asyncio
from google import genai
from google.genai import types
from app.intelligence.canonical import LLMResponse
from app.intelligence.llm.base_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):

    def __init__(self):
        # Mengambil API Key dari environment variable GEMINI_API_KEY
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()

        if not self.api_key:
            logger.warning(
                "GEMINI_API_KEY tidak ditemukan di environment variable!"
            )
            self.client = None
        else:
            # Menggunakan Client resmi dari SDK google-genai
            self.client = genai.Client(api_key=self.api_key)

    async def generate(self, prompt: str, system_prompt: str = "", temperature: float = 0.2) -> LLMResponse:
        if not self.client:
            return LLMResponse(
                text="Maaf, konfigurasi API Key Gemini belum diatur di server.",
                finish_reason="error",
                provider="gemini",
                model="gemini-3.6-flash",
            )

        start_time = time.time()

        try:
            config = types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_prompt if system_prompt else None,
            )

            # Memanggil endpoint SDK dalam thread pool agar non-blocking
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model="gemini-3.6-flash", 
                contents=prompt, 
                config=config
            )

            latency = (time.time() - start_time) * 1000

            # Ekstraksi statistik token jika tersedia
            usage_metadata = getattr(response, "usage_metadata", None)
            prompt_tokens = getattr(usage_metadata, "prompt_token_count", 0) if usage_metadata else 0
            completion_tokens = getattr(usage_metadata, "candidates_token_count", 0) if usage_metadata else 0

            return LLMResponse(
                text=response.text,
                finish_reason="stop",
                latency_ms=round(latency, 2),
                provider="gemini",
                model="gemini-3.6-flash",
                token_usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            )

        except Exception as e:
            logger.error(f"Error panggilan Gemini API: {str(e)}")
            return LLMResponse(
                text=f"Maaf, kendala koneksi AI: {str(e)}",
                finish_reason="error",
                provider="gemini",
                model="gemini-3.6-flash",
            )
