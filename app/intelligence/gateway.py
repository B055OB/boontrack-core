import os
import logging
from app.intelligence.canonical import LLMResponse
from app.intelligence.llm.base_provider import BaseLLMProvider
from app.intelligence.llm.mock_provider import MockProvider
from app.intelligence.llm.gemini_provider import GeminiProvider
from app.intelligence.llm.groq_provider import GroqProvider
from app.intelligence.llm.openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


class AIGateway:

    def __init__(self):
        self.provider_name = os.getenv("LLM_PROVIDER", "openrouter").lower().strip()
        self.primary_provider = self._resolve_provider()
        self.fallback_provider = MockProvider()

    def _resolve_provider(self) -> BaseLLMProvider:
        if self.provider_name == "openrouter":
            logger.info("Mengaktifkan OpenRouterProvider sebagai Engine AI Utama.")
            return OpenRouterProvider()
        elif self.provider_name == "groq":
            logger.info("Mengaktifkan GroqProvider (Llama-3.3-70b) sebagai Engine AI Utama.")
            return GroqProvider()
        elif self.provider_name == "gemini":
            logger.info("Mengaktifkan GeminiProvider sebagai Engine AI Utama.")
            return GeminiProvider()
        else:
            logger.warning(
                f"Provider '{self.provider_name}' tidak dikenal. Fallback ke MockProvider."
            )
            return MockProvider()

    async def generate(self, prompt: str, system_prompt: str = "") -> LLMResponse:
        try:
            res = await self.primary_provider.generate(
                prompt=prompt, system_prompt=system_prompt
            )

            # Jika provider utama berhasil membalas
            if res.finish_reason == "stop" and res.text and not res.text.startswith("Maaf,"):
                return res

            logger.warning(
                f"Primary provider ({self.provider_name}) bermasalah. Memicu fallback ke MockProvider..."
            )

        except Exception as e:
            logger.error(f"Error pada AIGateway generate: {str(e)}")

        # Fallback cadangan jika primary mengalami error
        return await self.fallback_provider.generate(
            prompt=prompt, system_prompt=system_prompt
        )
