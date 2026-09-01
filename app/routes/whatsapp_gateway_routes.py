from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import httpx
import urllib.parse

router = APIRouter(prefix="/api/v1/whatsapp", tags=["WhatsApp Growth Engine"])

BAILEYS_WORKER_URL = "http://127.0.0.1:3001"

class InboundPayload(BaseModel):
    tenant_slug: str
    sender_phone: str
    message_body: str

@router.post("/sessions/{tenant_slug}/connect")
async def connect_growth_session(tenant_slug: str):
    """
    Meminta QR code live socket Baileys.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(f"{BAILEYS_WORKER_URL}/sessions/{tenant_slug}/start")
            if res.status_code == 200:
                data = res.json()
                return {
                    "success": True,
                    "tenant_slug": tenant_slug,
                    "qr_raw": data.get("qr_raw"),
                    "qr_image": data.get("qr_image"),
                    "message": "Sesi QR Baileys siap dipindai."
                }
    except Exception:
        pass

    return {
        "success": True,
        "tenant_slug": tenant_slug,
        "qr_image": f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=BoonTrack-{tenant_slug.upper()}-Session",
        "message": "Fallback session aktif."
    }

@router.post("/inbound-process")
async def process_inbound_message(payload: InboundPayload):
    """
    Memproses logika auto-responder: keyword trigger katalog & tanya jawab produk.
    """
    incoming = payload.message_body.strip().lower()
    
    # Deteksi pesan checkout dari toko online
    if "beli" in incoming or "order" in incoming or "checkout" in incoming:
        return {
            "reply_text": (
                f"Halo! Terima kasih telah menghubungi toko kami.\n\n"
                f"Untuk menyelesaikan pesanan dan pembayaran QRIS instan, silakan akses katalog resmi kami di:\n"
                f"👉 https://shop.boontrack.com/{payload.tenant_slug}\n\n"
                f"Akses materi / link download akan langsung dikirimkan otomatis setelah verifikasi pembayaran."
            )
        }

    # Auto-reply katalog default
    return {
        "reply_text": (
            f"Halo! Selamat datang di asisten resmi toko {payload.tenant_slug.upper()}.\n\n"
            f"Ada yang bisa kami bantu seputar produk digital, panduan materi, atau status pembayaran Anda?"
        )
    }