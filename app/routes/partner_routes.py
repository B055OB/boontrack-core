from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Header, Request, status, Query
from pydantic import BaseModel, Field

from app.services.partner_service import (
    partner_service,
    validate_referral_slug,
    decode_jwt_token,
    ALLOWED_BANKS,
    MINIMUM_PAYOUT_AMOUNT,
)

partner_router = APIRouter(prefix="/api/v1/partners", tags=["Partners (AM & Affiliate)"])
manager_router = APIRouter(prefix="/api/v1/manager", tags=["Manager Control Tower"])


# =============================================================================
# Request & Response Schemas
# =============================================================================

class CheckSlugRequest(BaseModel):
    slug: str = Field(..., description="Slug custom referral yang ingin dicek")


class ClaimSlugRequest(BaseModel):
    slug: str = Field(..., description="Slug custom referral yang ingin diklaim (3-20 karakter alfanumerik)")
    partner_id: Optional[str] = Field(None, description="Opsional jika tidak menyertakan Authorization Bearer header")


class BankAccountRequest(BaseModel):
    bank_name: str = Field(..., description="Nama Bank / E-Wallet (BCA, Mandiri, BRI, BNI, BSI, CIMB, GoPay, DANA, OVO)")
    account_number: str = Field(..., description="Nomor rekening bank atau nomor akun e-wallet")
    account_holder_name: str = Field(..., description="Nama lengkap pemilik rekening / akun")
    partner_id: Optional[str] = Field(None, description="Opsional jika tidak menyertakan Authorization Bearer header")


class PayoutRequestPayload(BaseModel):
    amount: float = Field(..., ge=50000, description="Jumlah saldo komisi yang ingin ditarik (minimal Rp 50.000)")
    bank_account_id: Optional[str] = Field(None, description="ID rekening bank tujuan pencairan (opsional, default rekening utama)")
    partner_id: Optional[str] = Field(None, description="Opsional jika tidak menyertakan Authorization Bearer header")


class WhitelistPartnerRequest(BaseModel):
    name: str = Field(..., description="Nama lengkap mitra")
    phone: str = Field(..., description="Nomor WhatsApp mitra")
    role: str = Field("AFFILIATE", description="Peran mitra: 'AM' atau 'AFFILIATE'")
    ref_code: Optional[str] = Field(None, description="Custom referral slug (opsional, jika kosong di-generate otomatis)")
    registered_by_am_id: Optional[str] = Field(None, description="ID Account Manager pembina (opsional)")
    email: Optional[str] = Field(None, description="Alamat email mitra (opsional)")


class MarkPaidRequest(BaseModel):
    proof_attachment_url: Optional[str] = Field(None, description="URL bukti transfer / struk pembayaran")
    notes: Optional[str] = Field(None, description="Catatan konfirmasi pembayaran")


# =============================================================================
# Auth Helper
# =============================================================================

def resolve_partner_id(
    authorization: Optional[str] = None,
    x_partner_id: Optional[str] = None,
    explicit_partner_id: Optional[str] = None,
) -> str:
    """
    Ekstraksi ID mitra dari Authorization Bearer Token, header X-Partner-Id,
    atau eksplisit body partner_id.
    """
    if explicit_partner_id:
        return explicit_partner_id

    if x_partner_id:
        return x_partner_id

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        decoded = decode_jwt_token(token)
        if decoded and (decoded.get("sub") or decoded.get("partner_id")):
            return str(decoded.get("sub") or decoded.get("partner_id"))

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Autentikasi diperlukan. Sertakan header Authorization: Bearer <token> atau partner_id.",
    )


# =============================================================================
# PARTNER ENDPOINTS (/api/v1/partners)
# =============================================================================

@partner_router.post("/check-ref-slug", summary="Cek Ketersediaan Slug Referral")
async def check_referral_slug(payload: CheckSlugRequest):
    """
    Memeriksa apakah custom slug referral valid dan tersedia:
    - Regex: ^[A-Z0-9]{3,20}$
    - Blacklist kata sistem: ADMIN, ROOT, API, DASHBOARD, SHOP, dll.
    - Cek keunikan di database secara case-insensitive.
    """
    result = partner_service.check_slug_availability(payload.slug)
    return result


@partner_router.put("/claim-ref-slug", summary="Klaim dan Kunci Slug Custom")
async def claim_referral_slug(
    payload: ClaimSlugRequest,
    authorization: Optional[str] = Header(None),
    x_partner_id: Optional[str] = Header(None, alias="X-Partner-Id"),
):
    """
    Klaim dan kunci slug custom untuk mitra yang sedang login.
    Slug hanya dapat diklaim 1 kali; setelah berhasil, status is_ref_customized
    akan bernilai True dan terkunci secara permanen.
    """
    partner_id = resolve_partner_id(
        authorization=authorization,
        x_partner_id=x_partner_id,
        explicit_partner_id=payload.partner_id,
    )

    success, message, partner_data = partner_service.claim_custom_referral_slug(
        partner_id=partner_id, slug=payload.slug
    )
    if not success:
        if "sudah digunakan" in message:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return {
        "success": True,
        "message": message,
        "ref_code": partner_data.get("ref_code"),
        "is_ref_customized": partner_data.get("is_ref_customized", True),
        "partner": partner_data,
    }


@partner_router.post("/bank-account", summary="Simpan / Perbarui Rekening Bank Payout")
async def save_bank_account(
    payload: BankAccountRequest,
    authorization: Optional[str] = Header(None),
    x_partner_id: Optional[str] = Header(None, alias="X-Partner-Id"),
):
    """
    Simpan atau perbarui data rekening bank mitra untuk penyaluran komisi (payout).
    Mendukung bank & e-wallet: BCA, Mandiri, BRI, BNI, BSI, CIMB, GoPay, DANA, OVO.
    """
    partner_id = resolve_partner_id(
        authorization=authorization,
        x_partner_id=x_partner_id,
        explicit_partner_id=payload.partner_id,
    )

    success, message, bank_record = partner_service.upsert_bank_account(
        partner_id=partner_id,
        bank_name=payload.bank_name,
        account_number=payload.account_number,
        account_holder_name=payload.account_holder_name,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return {
        "success": True,
        "message": message,
        "data": bank_record,
    }


@partner_router.get("/bank-account", summary="Lihat Data Rekening Bank Mitra")
async def get_bank_account(
    authorization: Optional[str] = Header(None),
    x_partner_id: Optional[str] = Header(None, alias="X-Partner-Id"),
    partner_id: Optional[str] = Query(None),
):
    """
    Melihat data rekening bank aktif mitra.
    """
    pid = resolve_partner_id(
        authorization=authorization,
        x_partner_id=x_partner_id,
        explicit_partner_id=partner_id,
    )
    account = partner_service.get_bank_account_by_partner(pid)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rekening bank belum didaftarkan.")
    return {"success": True, "data": account}


@partner_router.post("/payouts/request", summary="Ajukan Penarikan Saldo Komisi")
async def request_payout(
    payload: PayoutRequestPayload,
    authorization: Optional[str] = Header(None),
    x_partner_id: Optional[str] = Header(None, alias="X-Partner-Id"),
):
    """
    Mengajukan penarikan dana / komisi mitra (payout).
    Validasi batas minimum payout adalah Rp 50.000 dan mitra wajib memiliki rekening terdaftar.
    """
    partner_id = resolve_partner_id(
        authorization=authorization,
        x_partner_id=x_partner_id,
        explicit_partner_id=payload.partner_id,
    )

    success, message, payout_record = partner_service.request_payout(
        partner_id=partner_id,
        amount=payload.amount,
        bank_account_id=payload.bank_account_id,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return {
        "success": True,
        "message": message,
        "payout": payout_record,
    }


# =============================================================================
# MANAGER / CONTROL TOWER ENDPOINTS (/api/v1/manager)
# =============================================================================

@manager_router.get("/partners", summary="List Semua Mitra Whitelist (AM & Affiliate)")
async def list_partners(
    role: Optional[str] = Query(None, description="Filter peran mitra ('AM' atau 'AFFILIATE')"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter status ('ACTIVE' atau 'SUSPENDED')"),
):
    """
    Menampilkan daftar seluruh mitra Account Manager (AM) dan Affiliate
    beserta status keanggotaan dan performa jaringan.
    """
    partners = partner_service.list_all_partners(role=role, status=status_filter)
    return {
        "success": True,
        "total": len(partners),
        "partners": partners,
    }


@manager_router.post("/partners/whitelist", summary="Pendaftaran Mitra Baru oleh AM / Admin")
async def whitelist_partner(payload: WhitelistPartnerRequest):
    """
    Mendaftarkan mitra baru (AM atau Affiliate) ke dalam sistem whitelist.
    Jika ref_code kustom disertakan, dilakukan validasi reserved keywords & keunikan.
    """
    success, message, partner_data = partner_service.whitelist_new_partner(
        name=payload.name,
        phone=payload.phone,
        role=payload.role,
        ref_code=payload.ref_code,
        registered_by_am_id=payload.registered_by_am_id,
        email=payload.email,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

    return {
        "success": True,
        "message": message,
        "partner": partner_data,
    }


@manager_router.get("/payouts", summary="Antrean Permohonan Penarikan Dana")
async def list_payout_queue(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter status ('PENDING', 'APPROVED', 'PAID', 'REJECTED')"),
):
    """
    Menampilkan daftar antrean permohonan penarikan dana dari mitra.
    """
    payouts = partner_service.list_payout_requests(status=status_filter)
    return {
        "success": True,
        "total": len(payouts),
        "payouts": payouts,
    }


@manager_router.put("/payouts/{payout_id}/mark-paid", summary="Konfirmasi Pembayaran Payout")
async def mark_payout_paid(payout_id: str, payload: MarkPaidRequest):
    """
    Mengonfirmasi pencairan dana kepada mitra oleh Admin/Finance.
    Mengubah status payout menjadi 'PAID', mencatat URL bukti transfer, dan waktu selesai.
    """
    success, message, payout_data = partner_service.mark_payout_as_paid(
        payout_id=payout_id,
        proof_attachment_url=payload.proof_attachment_url,
        notes=payload.notes,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)

    return {
        "success": True,
        "message": message,
        "payout": payout_data,
    }
