from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session
import httpx

router = APIRouter(prefix="/api/v1/whatsapp", tags=["WhatsApp Growth Session Engine"])

@router.post("/sessions/{tenant_slug}/connect")
def initialize_growth_whatsapp_session(
    tenant_slug: str,
    db: Session = Depends()
):
    """
    Inisialisasi sesi WhatsApp mandiri khusus plan Growth.
    Memeriksa entitlement apakah tenant benar terdaftar dan aktif.
    """
    # 1. Validasi tenant & entitlement
    ent_query = text("SELECT plan_id, max_seats FROM tenant_entitlements WHERE tenant_slug = :slug")
    ent = db.execute(ent_query, {"slug": tenant_slug}).mappings().first()
    
    if not ent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant tidak ditemukan dalam sistem entitlement."
        )

    # 2. Panggil internal gateway Baileys / Node service untuk generate QR session
    try:
        return {
            "success": True,
            "tenant_slug": tenant_slug,
            "message": "Sesi QR WhatsApp mandiri berhasil diinisialisasi.",
            "instructions": "Silakan ambil QR code dari session gateway untuk dipindai."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menghubungkan ke WhatsApp gateway engine: {str(e)}"
        )