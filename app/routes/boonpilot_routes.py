"""app/routes/boonpilot_routes.py
FastAPI Routes for Agentic AI BoonPilot.
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.boonpilot_service import boonpilot_service

router = APIRouter(prefix="/api/v1/boonpilot", tags=["Agentic AI BoonPilot"])


# =============================================================================
# Request & Response Models
# =============================================================================

class BoonPilotChatRequest(BaseModel):
    tenant_slug: str = Field(..., description="Slug tenant toko (contoh: 'onlineboost')")
    message: str = Field(..., description="Pesan / instruksi pengguna untuk BoonPilot")
    session_id: Optional[str] = Field(None, description="ID sesi percakapan (opsional)")
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        default_factory=list,
        description="Riwayat percakapan multi-turn [{'role': 'user'|'assistant', 'content': '...'}]"
    )


class BoonPilotExecuteActionRequest(BaseModel):
    tenant_slug: str = Field(..., description="Slug tenant toko")
    action_id: str = Field(..., description="UUID proposal aksi yang ingin disetujui/dibatalkan")
    approved: bool = Field(..., description="True jika pengguna menyetujui mutasi, False jika membatalkan")


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/chat", summary="Chat Interaktif dengan Agentic AI BoonPilot")
async def chat_with_boonpilot(payload: BoonPilotChatRequest):
    """
    Endpoint interaksi utama BoonPilot:
    - Menjawab pertanyaan laporan penjualan & inventory secara langsung (Query-only tools).
    - Merespons informasi kapabilitas WhatsApp Automation toko secara taktis (anti greeting-loop).
    - Mendukung riwayat percakapan multi-turn (conversation_history).
    - Menghasilkan Action Proposal terstruktur dengan status AWAITING_APPROVAL jika mendeteksi instruksi mutasi data.
    - Menjawab konsultasi operasional toko dengan sistem prompt & guardrails yang ketat.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pesan tidak boleh kosong.",
        )

    response = await boonpilot_service.chat(
        tenant_slug=payload.tenant_slug,
        message=payload.message,
        session_id=payload.session_id,
        conversation_history=payload.conversation_history,
    )
    return response


@router.post("/execute-action", summary="Eksekusi / Pembatalan Proposal Aksi Mutasi Data")
async def execute_boonpilot_action(payload: BoonPilotExecuteActionRequest):
    """
    Human-in-the-Loop Safeguard:
    - Jika approved == True: Mengeksekusi mutasi data (stok, alamat pengiriman, kurir) ke database toko.
    - Jika approved == False: Membatalkan proposal aksi dengan status REJECTED.
    - Memvalidasi TTL 10 menit. Jika kedaluwarsa, mengembalikan pesan error.
    """
    success, message, proposal = boonpilot_service.execute_action(
        tenant_slug=payload.tenant_slug,
        action_id=payload.action_id,
        approved=payload.approved,
    )

    if not success:
        if "tidak ditemukan" in message or "kedaluwarsa" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return {
        "success": True,
        "status": proposal.get("status"),
        "message": message,
        "action_id": payload.action_id,
        "action_type": proposal.get("action_type"),
        "result": proposal.get("result"),
    }
