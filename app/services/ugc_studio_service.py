import json
import os
import asyncio
from typing import Dict, Any, List
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Skema Validasi Output Pydantic
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
    content_tone: str = "santai" # santai, heboh, edukatif, review_jujur
    cta_goal: str = "checkout_keranjang" # checkout_keranjang, klik_link_bio, tanya_wa
    duration_scenes: int = 9

async def record_ai_telemetry(tenant_id: str, prompt_tokens: int, candidate_tokens: int, model: str):
    """Mencatat token secara asinkron agar tidak memblokir response HTTP."""
    try:
        # Panggil database Supabase/PostgreSQL Anda untuk insert ke telemetry_ai_usage[cite: 1]
        print(f"[Telemetry] Tenant: {tenant_id} | In: {prompt_tokens} | Out: {candidate_tokens} | Model: {model}")
    except Exception as e:
        print(f"[Telemetry Error] {e}")

async def generate_ugc_script(payload: UGCGenerateRequest) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

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

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=UGCScriptResponse,
                temperature=0.7
            )
        )
    )

    # Catat telemetri di background[cite: 1]
    usage = response.usage_metadata
    if usage:
        asyncio.create_task(record_ai_telemetry(
            tenant_id=payload.tenant_id,
            prompt_tokens=usage.prompt_token_count or 0,
            candidate_tokens=usage.candidates_token_count or 0,
            model="gemini-3.8-flash"
        ))

    return json.loads(response.text)