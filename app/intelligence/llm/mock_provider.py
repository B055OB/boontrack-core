import time
from app.intelligence.canonical import LLMResponse
from app.intelligence.llm.base_provider import BaseLLMProvider


class MockProvider(BaseLLMProvider):

    async def generate(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.2
    ) -> LLMResponse:
        start_time = time.time()

        # Respon deterministik simulasi tanpa koneksi internet / API Key
        response_text = (
            "Halo! Ini adalah respons simulasi dari Mock LLM Provider BoonTrack. "
            "Sistem berjalan 100% lokal, instan, dan siap melayani permintaan solusi karir."
        )

        latency = (time.time() - start_time) * 1000

        return LLMResponse(
            text=response_text,
            finish_reason="stop",
            latency_ms=round(latency, 2),
            provider="mock",
            model="mock-deterministic-v1",
            token_usage={
                "prompt_tokens": len(prompt.split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(prompt.split()) + len(response_text.split()),
            },
        )
