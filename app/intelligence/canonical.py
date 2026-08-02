from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    text: str = Field(..., description="Teks respons utama dari LLM/Mock")
    finish_reason: str = Field(
        default="stop", description="Alasan penghentian (e.g., stop, length, error)"
    )
    latency_ms: float = Field(
        default=0.0, description="Waktu eksekusi respons dalam milidetik"
    )
    provider: str = Field(
        default="mock", description="Nama provider yang digunakan (mock, gemini, openai)"
    )
    model: str = Field(
        default="mock-deterministic-v1", description="Nama model yang dipanggil"
    )
    token_usage: Dict[str, int] = Field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        description="Statistik penggunaan token",
    )
    request_id: Optional[str] = Field(
        default=None, description="ID unik untuk pelacakan telemetri"
    )
