"""app/routes/boonpilot_routes.py
FastAPI Routes for Agentic AI BoonPilot with Scope Lock Architecture.
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field

from app.services.boonpilot_service import boonpilot_service
from app.services.entitlement_service import tenant_context_resolver

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
    untrusted_tenant_id: Optional[str] = Field(
        None,
        description="Arbitrary tenant_id dari client yang akan divalidasi ketat oleh context resolver"
    )
    rbac_role: Optional[str] = Field(
        "MERCHANT",
        description="Peran pengguna e.g. MERCHANT, ADMIN, STAFF"
    )


class BoonPilotExecuteActionRequest(BaseModel):
    tenant_slug: str = Field(..., description="Slug tenant toko")
    action_id: str = Field(..., description="UUID proposal aksi yang ingin disetujui/dibatalkan")
    approved: bool = Field(..., description="True jika pengguna menyetujui mutasi, False jika membatalkan")


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/chat", summary="Chat Interaktif dengan BoonPilot Copilot")
async def chat_with_boonpilot(payload: BoonPilotChatRequest):
    """
    Endpoint interaksi utama BoonPilot Copilot dengan Scope Lock:
    - Menolak arbitrary tenant_id dari client jika tidak cocok dengan konteks runtime.
    - Menolak akses atau perutean ke nomor WABA resmi platform (+6285179555449).
    - Menghitung prorata billing dan komisi affiliate secara otoritatif dari backend (No LLM Business Truth).
    - Menyaring menu navigasi/button secara dinamis berbasis entitlement.
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pesan tidak boleh kosong.",
        )

    try:
        response = await boonpilot_service.chat(
            tenant_slug=payload.tenant_slug,
            message=payload.message,
            session_id=payload.session_id,
            conversation_history=payload.conversation_history,
            untrusted_client_tenant_id=payload.untrusted_tenant_id,
            rbac_role=payload.rbac_role or "MERCHANT",
        )
        return response
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{tenant_slug}/menu", summary="Ambil Dynamic Button-Driven Menu Berbasis Entitlement & RBAC")
async def get_dynamic_menu(
    tenant_slug: str,
    role: str = Query("MERCHANT", description="RBAC Role pengguna e.g. MERCHANT, ADMIN, OWNER")
):
    """
    Capability Resolver Endpoint:
    Mengembalikan tombol menu yang telah disaring ketat berdasarkan:
    TenantRuntimeContext + RBAC + Plan/Entitlement + Feature Flags.
    - Tier tanpa CAPI/Powertools tidak akan menerima tombol CAPI.
    - Tenant tanpa entitlement program affiliate tidak akan menerima tombol Affiliate.
    """
    try:
        context = await tenant_context_resolver.resolve(tenant_slug)
        menu_data = boonpilot_service.resolve_dynamic_menu(context, rbac_role=role)
        return menu_data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil menu dinamis BoonPilot: {str(e)}"
        )


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
