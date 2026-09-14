"""app/services/ugc_studio_service.py

Multi-provider resilient UGC script generator — adhering to ARCHITECTURE.md:

  Principle 7  : Business logic MUST NOT be coupled to a specific AI provider.
  Principle 8  : Configuration belongs in environment variables, never hardcoded.
  §10.2        : Failover redundancy (primary_provider / fallback_provider).
  §10.3        : Async AI token telemetry per request (non-blocking).
  §9.3         : Zero Fake Fallback — surface real errors, never mock output.

Execution tiers (all model names read 100% from Railway env vars):

  Tier 1 — Google Gemini        AI_PRIMARY_MODEL          (default: gemini-3.8-flash)
                                 google-genai SDK
                                 Any error → Tier 2

  Tier 2 — Groq (primary)       AI_GROQ_MODEL             (default: qwen/qwen3-27b)
                                 groq SDK (async)
                                 Any error → Groq fallback

  Tier 2b — Groq (fallback)     AI_GROQ_FALLBACK_MODEL    (default: openai/gpt-oss-120b)
                                 same GROQ_API_KEY
                                 Any error → Tier 3 (if enabled)

  Tier 3 — OpenRouter           AI_OPENROUTER_MODEL       (default: mistralai/mixtral-8x7b-instruct)
                                 openai SDK + custom base_url
                                 Enabled only when AI_OPENROUTER_ENABLED=true
"""

import json
import os
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from google import genai
from google.genai import types
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic output schema
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
    content_tone: str = "santai"             # santai | heboh | edukatif | review_jujur
    cta_goal: str = "checkout_keranjang"     # checkout_keranjang | klik_link_bio | tanya_wa
    duration_scenes: int = 9

# ---------------------------------------------------------------------------
# Telemetry  (§10.3 — async, non-blocking)
# ---------------------------------------------------------------------------

async def record_ai_telemetry(
    tenant_id: str,
    prompt_tokens: int,
    candidate_tokens: int,
    model: str,
    provider: str = "gemini",
) -> None:
    """Insert ke telemetry_ai_usage secara asinkron agar tidak memblokir response HTTP."""
    try:
        # TODO: replace print with actual DB insert to telemetry_ai_usage[cite: §10.3]
        print(
            f"[Telemetry] tenant={tenant_id} provider={provider} model={model} "
            f"in={prompt_tokens} out={candidate_tokens}"
        )
    except Exception as exc:
        print(f"[Telemetry Error] {exc}")

# ---------------------------------------------------------------------------
# Shared JSON system-prompt for OpenAI-compatible providers (Groq / OpenRouter)
# ---------------------------------------------------------------------------

_JSON_SCHEMA_HINT = json.dumps(
    {
        "hook_type": "<string>",
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
        "You are a JSON-only API. Respond with a single valid JSON object "
        "matching this schema exactly — no markdown fences, no explanation:\n"
        + _JSON_SCHEMA_HINT
    )

# ---------------------------------------------------------------------------
# Tier 1: Google Gemini  (model 100% from AI_PRIMARY_MODEL env var)
# ---------------------------------------------------------------------------

async def _try_gemini(
    client: genai.Client,
    prompt: str,
) -> Tuple[Dict[str, Any], str, Any]:
    """
    Returns (parsed_json, model_name, usage_metadata).
    Raises on any error — caller handles tier promotion.
    Model name is read from AI_PRIMARY_MODEL at call time (Railway hot-reload safe).
    """
    model = os.environ.get("AI_PRIMARY_MODEL", "gemini-3.8-flash")
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=UGCScriptResponse,
                temperature=0.7,
            ),
        ),
    )
    return json.loads(response.text), model, response.usage_metadata

# ---------------------------------------------------------------------------
# Tier 2 & 2b: Groq  (primary model, then fallback model — same API key)
# ---------------------------------------------------------------------------

async def _call_groq(model: str, user_prompt: str) -> Dict[str, Any]:
    """Single Groq completion call. Raises on failure."""
    try:
        import groq as groq_sdk  # type: ignore  # lazy import — optional dependency
    except ImportError:
        raise RuntimeError("groq package not installed — run: pip install groq")

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set in environment")

    client = groq_sdk.AsyncGroq(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _json_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    return json.loads(raw)

async def _try_groq(user_prompt: str) -> Tuple[Dict[str, Any], str]:
    """
    Tries AI_GROQ_MODEL first.  On failure falls back to AI_GROQ_FALLBACK_MODEL.
    Returns (parsed_json, model_that_succeeded).
    """
    primary = os.environ.get("AI_GROQ_MODEL", "qwen/qwen3-27b")
    fallback = os.environ.get("AI_GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b")

    try:
        result = await _call_groq(primary, user_prompt)
        return result, primary
    except Exception as e_primary:
        print(f"[UGC][Groq] Primary model {primary!r} failed: {e_primary}. Trying fallback {fallback!r}…")

    result = await _call_groq(fallback, user_prompt)   # raises if this also fails
    return result, fallback

# ---------------------------------------------------------------------------
# Tier 3: OpenRouter  (opt-in — AI_OPENROUTER_ENABLED=true)
# ---------------------------------------------------------------------------

async def _try_openrouter(user_prompt: str) -> Tuple[Dict[str, Any], str]:
    """
    Returns (parsed_json, model_name).
    Uses the openai SDK pointed at OpenRouter's API endpoint.
    """
    try:
        import openai as openai_sdk  # type: ignore  # lazy import — optional dependency
    except ImportError:
        raise RuntimeError("openai package not installed — run: pip install openai")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set in environment")

    model = os.environ.get("AI_OPENROUTER_MODEL", "mistralai/mixtral-8x7b-instruct")
    site_url = os.environ.get("OPENROUTER_SITE_URL", "https://bossob.boontrack.com")
    app_name = os.environ.get("OPENROUTER_APP_NAME", "boontrack-ugc-studio")

    or_client = openai_sdk.AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": site_url,
            "X-Title": app_name,
        },
    )
    response = await or_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _json_system_prompt()},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    return json.loads(raw), model

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_ugc_script(payload: UGCGenerateRequest) -> Dict[str, Any]:
    """
    Generates a UGC script with a 3-tier provider failover:

      Tier 1  → Gemini (AI_PRIMARY_MODEL)                   any error → Tier 2
      Tier 2  → Groq   (AI_GROQ_MODEL)                      any error → Tier 2b
      Tier 2b → Groq   (AI_GROQ_FALLBACK_MODEL)             any error → Tier 3
      Tier 3  → OpenRouter (AI_OPENROUTER_ENABLED=true)      any error → raise

    All model names are resolved from environment variables at runtime.
    Telemetry records the actual provider + model that succeeded (§10.3).
    """
    gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
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
    # Tier 1: Gemini
    # ------------------------------------------------------------------
    try:
        result, model_used, usage_meta = await _try_gemini(gemini_client, prompt)
        asyncio.create_task(record_ai_telemetry(
            tenant_id=payload.tenant_id,
            prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
            candidate_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
            model=model_used,
            provider="gemini",
        ))
        return result
    except Exception as exc:
        tier1_model = os.environ.get("AI_PRIMARY_MODEL", "gemini-3.8-flash")
        print(f"[UGC] Tier 1 (Gemini/{tier1_model}) failed: {exc}")
        errors.append(f"Gemini/{tier1_model}: {exc}")

    # ------------------------------------------------------------------
    # Tier 2 + 2b: Groq  (primary model → fallback model, same key)
    # ------------------------------------------------------------------
    try:
        result, model_used = await _try_groq(prompt)
        asyncio.create_task(record_ai_telemetry(
            tenant_id=payload.tenant_id,
            prompt_tokens=0,
            candidate_tokens=0,
            model=model_used,
            provider="groq",
        ))
        return result
    except Exception as exc:
        print(f"[UGC] Tier 2 (Groq — both models) failed: {exc}")
        errors.append(f"Groq: {exc}")

    # ------------------------------------------------------------------
    # Tier 3: OpenRouter  (only if AI_OPENROUTER_ENABLED=true)
    # ------------------------------------------------------------------
    if os.environ.get("AI_OPENROUTER_ENABLED", "false").lower() == "true":
        try:
            result, model_used = await _try_openrouter(prompt)
            asyncio.create_task(record_ai_telemetry(
                tenant_id=payload.tenant_id,
                prompt_tokens=0,
                candidate_tokens=0,
                model=model_used,
                provider="openrouter",
            ))
            return result
        except Exception as exc:
            print(f"[UGC] Tier 3 (OpenRouter) failed: {exc}")
            errors.append(f"OpenRouter: {exc}")

    # §9.3 Zero Fake Fallback — surface real error, never return mock data
    raise RuntimeError(
        f"All AI providers exhausted. Errors — {' | '.join(errors)}"
    )