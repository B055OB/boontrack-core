"""app/services/ugc_studio_service.py

Multi-provider resilient UGC script generator.

Execution tiers:
  Tier 1 – Google Gemini 3.8 Flash  (google-genai SDK, single model, no deprecated fallbacks)
  Tier 2 – Groq                     (groq SDK, model from AI_GROQ_MODEL env var)
  Tier 3 – OpenRouter               (openai SDK + custom base_url, opt-in via AI_OPENROUTER_ENABLED=true)

On any Tier 1 error (including 503 High Demand) the request is immediately forwarded to Tier 2.
Telemetry always receives the exact provider + model that actually succeeded.
"""

import json
import os
import asyncio
from typing import Dict, Any, List
from google import genai
from google.genai import types
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------

class SceneItem(BaseModel):
    scene_number: int
    duration_sec: int
    visual_direction: str
    on_screen_text: str
    voiceover: str

class UGCScriptResponse(BaseModel):
    hook_type: str
    scenes: List[SceneItem]

class UGCGenerateRequest(BaseModel):
    tenant_id: str
    product_name: str
    product_benefits: str
    target_audience: str
    content_tone: str = "santai"            # santai, heboh, edukatif, review_jujur
    cta_goal: str = "checkout_keranjang"    # checkout_keranjang, klik_link_bio, tanya_wa
    duration_scenes: int = 9

# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

async def record_ai_telemetry(
    tenant_id: str,
    prompt_tokens: int,
    candidate_tokens: int,
    model: str,
    provider: str = "gemini",
):
    """Mencatat token secara asinkron agar tidak memblokir response HTTP."""
    try:
        # Insert ke telemetry_ai_usage[cite: 1]
        print(
            f"[Telemetry] Tenant: {tenant_id} | Provider: {provider} | Model: {model} "
            f"| In: {prompt_tokens} | Out: {candidate_tokens}"
        )
    except Exception as e:
        print(f"[Telemetry Error] {e}")

# ---------------------------------------------------------------------------
# Shared JSON system prompt for non-Gemini providers
# ---------------------------------------------------------------------------

_SCHEMA_EXAMPLE = json.dumps(
    {
        "hook_type": "<string: e.g. Problem-Agitate-Solve>",
        "scenes": [
            {
                "scene_number": 1,
                "duration_sec": 3,
                "visual_direction": "<string>",
                "on_screen_text": "<string>",
                "voiceover": "<string>",
            }
        ],
    },
    ensure_ascii=False,
    indent=2,
)

def _json_system_prompt() -> str:
    return (
        "You are a JSON-only API. Respond with a single valid JSON object matching "
        "this schema exactly — no markdown fences, no explanation:\n"
        f"{_SCHEMA_EXAMPLE}"
    )

# ---------------------------------------------------------------------------
# Tier 1: Google Gemini 3.8 Flash (single model, no deprecated fallbacks)
# ---------------------------------------------------------------------------

_GEMINI_MODEL = os.getenv("AI_PRIMARY_MODEL", "gemini-3.8-flash")

async def _try_gemini(
    client: genai.Client, prompt: str
) -> tuple[Dict[str, Any], str, Any]:
    """Returns (parsed_json, model_name, usage_metadata) or raises."""
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=UGCScriptResponse,
                temperature=0.7,
            ),
        ),
    )
    return json.loads(response.text), _GEMINI_MODEL, response.usage_metadata

# ---------------------------------------------------------------------------
# Tier 2: Groq
# ---------------------------------------------------------------------------

async def _try_groq(user_prompt: str) -> tuple[Dict[str, Any], str, None]:
    """Returns (parsed_json, model_name, None) or raises."""
    try:
        import groq as groq_sdk  # type: ignore
    except ImportError:
        raise RuntimeError("groq package is not installed — run: pip install groq")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")

    model = os.getenv("AI_GROQ_MODEL", "qwen/qwen3-27b")
    groq_client = groq_sdk.AsyncGroq(api_key=api_key)

    response = await groq_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _json_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or ""
    return json.loads(raw), model, None

# ---------------------------------------------------------------------------
# Tier 3: OpenRouter  (opt-in via AI_OPENROUTER_ENABLED=true)
# ---------------------------------------------------------------------------

async def _try_openrouter(user_prompt: str) -> tuple[Dict[str, Any], str, None]:
    """Returns (parsed_json, model_name, None) or raises."""
    try:
        import openai as openai_sdk  # type: ignore
    except ImportError:
        raise RuntimeError("openai package is not installed — run: pip install openai")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set")

    model = os.getenv("AI_OPENROUTER_MODEL", "mistralai/mixtral-8x7b-instruct")
    site_url = os.getenv("OPENROUTER_SITE_URL", "https://bossob.boontrack.com")
    app_name = os.getenv("OPENROUTER_APP_NAME", "boontrack-ugc-studio")

    openrouter_client = openai_sdk.AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": site_url,
            "X-Title": app_name,
        },
    )

    response = await openrouter_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _json_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or ""
    return json.loads(raw), model, None

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_ugc_script(payload: UGCGenerateRequest) -> Dict[str, Any]:
    """
    Generates a UGC script with a 3-tier provider fallback:
      Tier 1 → Google Gemini 3.8 Flash  (any error → Tier 2)
      Tier 2 → Groq                     (any error → Tier 3 if enabled)
      Tier 3 → OpenRouter               (opt-in via AI_OPENROUTER_ENABLED=true)
    """
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    errors: List[str] = []

    prompt = f"""
    Kamu adalah UGC Content Strategist handal untuk TikTok Ads, Shopee Video, dan IG Reels.
    Tugasmu membuat naskah iklan UGC sebanyak tepat {payload.duration_scenes} scene dengan retensi tinggi.

    Informasi Produk:
    - Nama Produk: {payload.product_name}
    - Keunggulan Utama: {payload.product_benefits}
    - Target Audiens: {payload.target_audience}
    - Nada Bahasa (Tone): {payload.content_tone}
    - Target Call to Action (CTA): {payload.cta_goal}

    Format output WAJIB JSON dengan struktur:
    {{
      "hook_type": "Tipe hook yang dipakai (contoh: Problem-Agitate-Solve, Curiosity, Stop Scroll)",
      "scenes": [
        {{
          "scene_number": 1,
          "duration_sec": 3,
          "visual_direction": "Instruksi kamera, gestur model, atau angle pengambilan video",
          "on_screen_text": "Teks singkat yang muncul di layar (subtitle punchline)",
          "voiceover": "Kata-kata yang diucapkan oleh talent/voiceover"
        }}
      ]
    }}
    Pastikan scene 1-2 adalah Hook kuat (3 detik pertama), scene 3-7 edukasi/solusi/demonstrasi produk, scene 8-9 call to action yang meyakinkan.
    """

    # ------------------------------------------------------------------
    # Tier 1: Gemini 3.8 Flash
    # ------------------------------------------------------------------
    try:
        result, model_used, usage_meta = await _try_gemini(gemini_client, prompt)
        prompt_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
        candidate_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
        asyncio.create_task(record_ai_telemetry(
            tenant_id=payload.tenant_id,
            prompt_tokens=prompt_tokens,
            candidate_tokens=candidate_tokens,
            model=model_used,
            provider="gemini",
        ))
        return result
    except Exception as e:
        print(f"[UGC] Tier 1 (Gemini {_GEMINI_MODEL}) failed: {e}")
        errors.append(f"Gemini: {e}")

    # ------------------------------------------------------------------
    # Tier 2: Groq
    # ------------------------------------------------------------------
    try:
        result, model_used, _ = await _try_groq(prompt)
        asyncio.create_task(record_ai_telemetry(
            tenant_id=payload.tenant_id,
            prompt_tokens=0,
            candidate_tokens=0,
            model=model_used,
            provider="groq",
        ))
        return result
    except Exception as e:
        print(f"[UGC] Tier 2 (Groq) failed: {e}")
        errors.append(f"Groq: {e}")

    # ------------------------------------------------------------------
    # Tier 3: OpenRouter (opt-in)
    # ------------------------------------------------------------------
    if os.getenv("AI_OPENROUTER_ENABLED", "false").lower() == "true":
        try:
            result, model_used, _ = await _try_openrouter(prompt)
            asyncio.create_task(record_ai_telemetry(
                tenant_id=payload.tenant_id,
                prompt_tokens=0,
                candidate_tokens=0,
                model=model_used,
                provider="openrouter",
            ))
            return result
        except Exception as e:
            print(f"[UGC] Tier 3 (OpenRouter) failed: {e}")
            errors.append(f"OpenRouter: {e}")

    raise RuntimeError(
        f"All AI providers exhausted. Errors — {' | '.join(errors)}"
    )