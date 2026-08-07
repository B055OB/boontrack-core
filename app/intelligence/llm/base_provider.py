from abc import ABC, abstractmethod
from app.intelligence.canonical import LLMResponse


class BaseLLMProvider(ABC):

    @abstractmethod
    async def generate(
        self, prompt: str, system_prompt: str = "", temperature: float = 0.2
    ) -> LLMResponse:
        """Menghasilkan respons LLM secara asynchronous dan stateless."""
        pass
