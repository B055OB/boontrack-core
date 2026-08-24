import asyncio
from typing import Optional, Callable, Awaitable

class MessageComposer:
    @staticmethod
    async def compose_hybrid(
        llm_coro: Optional[Awaitable[str]], 
        static_data: str, 
        timeout_sec: float = 1.5
    ) -> str:
        """
        Parallel Execution & Timeout Guard:
        Jika LLM lambat/error (>1.5s), abaikan kalimat AI dan langsung kirim static template.
        """
        if not llm_coro:
            return static_data

        try:
            greeting_ai = await asyncio.wait_for(llm_coro, timeout=timeout_sec)
            if greeting_ai:
                return f"{greeting_ai}\n\n{static_data}"
        except Exception:
            pass

        return static_data