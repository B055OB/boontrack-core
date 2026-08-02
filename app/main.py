import logging
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.intelligence.gateway import AIGateway
from app.services.drive_resolver import DriveResolver

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="BoonTrack Core API",
    description="Backend API untuk BoonTrack dengan AI Gateway & Drive Resolver",
    version="1.0.0"
)

# Inisialisasi Service Engine
ai_gateway = AIGateway()
drive_resolver = DriveResolver()


class SearchQuery(BaseModel):
    query: str
    user_id: Optional[str] = "default_user"


class SearchResponse(BaseModel):
    text: str
    provider: str


@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "BoonTrack Core API",
        "llm_provider": ai_gateway.provider_name
    }


@app.api_route("/api/v1/search", methods=["GET", "POST"], response_model=SearchResponse)
async def search_endpoint(request: Request, payload: Optional[SearchQuery] = None):
    # 1. Ekstraksi query user dari POST JSON body atau GET query parameters (q/query)
    user_message = ""
    user_id = "default_user"

    if request.method == "POST":
        try:
            body = await request.json()
            user_message = body.get("query", "").strip()
            user_id = body.get("user_id", "default_user")
        except Exception:
            if payload:
                user_message = payload.query.strip()
                user_id = payload.user_id or "default_user"
    else:  # Method GET
        user_message = request.query_params.get("q", "") or request.query_params.get("query", "")
        user_message = user_message.strip()
        user_id = request.query_params.get("user_id", "default_user")

    if not user_message:
        raise HTTPException(status_code=400, detail="Query tidak boleh kosong.")

    logger.info(f"Menerima query [{request.method}] dari user [{user_id}]: {user_message}")

    # 2. Cek apakah ada folder/file di Google Drive yang cocok dengan keyword user
    matched_asset = drive_resolver.find_asset_by_query(user_message)

    # 3. Susun System Prompt yang mengarahkan LLM memberikan link Drive resmi BoonTrack
    system_prompt = (
        "Kamu adalah BoonTrack Assistant, konsultan karir yang sangat ramah, empatik, dan solutif. "
        "Tugasmu adalah membimbing job seeker (pencari kerja) dalam persiapan melamar kerja, pemetaan karir, "
        "pembuatan CV, dan persiapan wawancara secara praktis serta mendukung mental mereka."
    )

    if matched_asset:
        logger.info(f"Aset Drive cocok ditemukan: {matched_asset['folder_name']}")
        system_prompt += (
            f"\n\n[INSTRUKSI KHUSUS - ASET TERSEDIA]:\n"
            f"Sistem menemukan materi/dokumen resmi BoonTrack yang sangat relevan dengan pertanyaan user:\n"
            f"- Judul Aset: {matched_asset['title']}\n"
            f"- Deskripsi: {matched_asset['description']}\n"
            f"- Link Akses Google Drive: {matched_asset['drive_link']}\n"
            f"WAJIB sertakan link Google Drive tersebut di dalam balasanmu dengan bahasa yang hangat dan mengajak user "
            f"untuk membuka/mengunduhnya!"
        )

    # 4. Minta jawaban dari AI Gateway (OpenRouter)
    try:
        ai_response = await ai_gateway.generate(
            prompt=user_message,
            system_prompt=system_prompt
        )
        return SearchResponse(
            text=ai_response.text,
            provider=ai_response.provider
        )
    except Exception as e:
        logger.error(f"Error saat memproses AI response: {str(e)}")
        raise HTTPException(status_code=500, detail="Terjadi kesalahan pada engine AI.")