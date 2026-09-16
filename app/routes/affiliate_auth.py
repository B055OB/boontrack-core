import os
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

try:
    from jose import jwt
except ImportError:
    try:
        import jwt
    except ImportError:
        jwt = None

from supabase import create_client, Client
from app.services.whatsapp_service import send_whatsapp_text, send_otp_whatsapp

logger = logging.getLogger("AFFILIATE_AUTH")
router = APIRouter(prefix="/api/v1/auth/affiliate", tags=["Affiliate Auth"])
affiliate_payout_router = APIRouter(tags=["Affiliate Payout Account"])

JWT_SECRET = os.getenv("JWT_SECRET", "boontrack-secret-key-production-3000")
JWT_ALGORITHM = "HS256"

supabase_url = os.getenv("SUPABASE_URL", "https://mpluzajlzpregmjwpjqr.supabase.co")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key)


def generate_jwt_token(payload: dict) -> str:
    """Safely generates a signed JWT token supporting python-jose, PyJWT, and built-in fallback."""
    if jwt is not None:
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        if isinstance(token, bytes):
            return token.decode("utf-8")
        return token
    else:
        import base64
        import json
        import hmac
        import hashlib
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        clean_payload = {}
        for k, v in payload.items():
            if isinstance(v, datetime):
                clean_payload[k] = int(v.timestamp())
            else:
                clean_payload[k] = v
        body = base64.urlsafe_b64encode(json.dumps(clean_payload).encode()).rstrip(b"=").decode()
        sig = hmac.new(JWT_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
        sig_str = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{header}.{body}.{sig_str}"


class SendOTPRequest(BaseModel):
    phone: str
    name: Optional[str] = None


class VerifyOTPRequest(BaseModel):
    phone: str
    otp: str
    name: Optional[str] = None
    email: Optional[str] = None
    referral_code: Optional[str] = None
    tenant_id: Optional[str] = "onlineboost"
    manager_id: Optional[str] = None

    # Data Rekening Bank untuk Payout Komisi
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_holder: Optional[str] = None

    # Screening & Kualifikasi Mitra Affiliate
    experience_level: Optional[str] = "BEGINNER"
    promotion_strategy_notes: Optional[str] = None
    social_media_links: Optional[Dict[str, Any]] = None
    portfolio_url: Optional[str] = None
    agreed_to_rules: Optional[bool] = False


class AffiliateRegisterRequest(BaseModel):
    """Payload pendaftaran mitra affiliate (cukup selesai saat pengisian rekening bank)."""
    model_config = {"extra": "allow"}

    phone: str
    name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    referral_code: Optional[str] = None
    am_referral_code: Optional[str] = None
    am_pembina: Optional[str] = None
    tenant_id: Optional[str] = "onlineboost"
    manager_id: Optional[str] = None

    # Data Rekening Bank untuk Payout Komisi (dengan alias toleran)
    bank_name: Optional[str] = None
    bank: Optional[str] = None
    bank_account_number: Optional[str] = None
    account_number: Optional[str] = None
    bank_account_holder: Optional[str] = None
    account_holder: Optional[str] = None
    account_name: Optional[str] = None
    payout_bank_details: Optional[Dict[str, Any]] = None

    # Screening & Kualifikasi (Opsional / Bypass Tahap 3)
    experience_level: Optional[str] = "BEGINNER"
    promotion_strategy_notes: Optional[str] = None
    promotion_plan: Optional[str] = None
    promotion_channels: Optional[Any] = None
    promotion_channel: Optional[str] = None
    audience_size: Optional[str] = None
    social_media_links: Optional[Dict[str, Any]] = None
    portfolio_url: Optional[str] = None
    agreed_to_rules: Optional[bool] = True
    agreed_to_terms: Optional[bool] = True



class UpdatePayoutAccountRequest(BaseModel):
    """Payload pembaruan data rekening pencairan komisi mitra affiliate."""
    model_config = {"extra": "allow"}

    affiliate_id: Optional[str] = None
    partner_id: Optional[str] = None
    id: Optional[str] = None
    phone: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None

    # Kolom resmi bank & aliases
    bank_name: Optional[str] = None
    bank: Optional[str] = None
    bank_account_number: Optional[str] = None
    account_number: Optional[str] = None
    bank_account_holder: Optional[str] = None
    account_holder: Optional[str] = None
    account_name: Optional[str] = None
    payout_bank_details: Optional[Dict[str, Any]] = None

class AffiliateScreeningRequest(BaseModel):
    """Payload pembaruan data screening & rekening bank mitra yang sudah ada."""
    phone: Optional[str] = None
    affiliate_id: Optional[str] = None

    # Data Rekening Bank
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_holder: Optional[str] = None

    # Screening & Kualifikasi
    experience_level: Optional[str] = None
    promotion_strategy_notes: Optional[str] = None
    social_media_links: Optional[Dict[str, Any]] = None
    portfolio_url: Optional[str] = None
    agreed_to_rules: Optional[bool] = None


def normalize_phone(phone: str) -> str:
    cleaned = "".join(filter(str.isdigit, phone))
    if cleaned.startswith("0"):
        cleaned = "62" + cleaned[1:]
    return cleaned


def save_affiliate_record(db_payload: Dict[str, Any], affiliate_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Menyimpan atau memperbarui data affiliate di Supabase.
    Mendukung kolom migrasi 013 (bank_name, bank_account_number, bank_account_holder, screening_status, dll)
    dengan sinkronisasi penuh dan fallback aman.
    """
    allowed_columns = {
        "id", "tenant_id", "name", "phone", "phone_number", "email",
        "referral_code", "commission_rate", "status",
        "bank_name", "bank_account_number", "bank_account_holder",
        "payout_bank_details", "is_bank_verified",
        "screening_status", "experience_level", "promotion_strategy_notes",
        "social_media_links", "portfolio_url", "rejection_reason",
        "agreed_to_rules", "manager_id"
    }

    clean_payload = {k: v for k, v in db_payload.items() if k in allowed_columns}

    # Sinkronisasi dua arah: jika payout_bank_details terisi, isi kolom individual (dan sebaliknya)
    payout_details = clean_payload.get("payout_bank_details")
    if isinstance(payout_details, dict):
        if not clean_payload.get("bank_name") and payout_details.get("bank_name"):
            clean_payload["bank_name"] = str(payout_details["bank_name"]).strip().upper()
        if not clean_payload.get("bank_account_number") and (payout_details.get("account_number") or payout_details.get("bank_account_number")):
            clean_payload["bank_account_number"] = str(payout_details.get("account_number") or payout_details.get("bank_account_number")).strip().replace(" ", "")
        if not clean_payload.get("bank_account_holder") and (payout_details.get("account_holder") or payout_details.get("account_name")):
            clean_payload["bank_account_holder"] = str(payout_details.get("account_holder") or payout_details.get("account_name")).strip().upper()
    elif clean_payload.get("bank_name") or clean_payload.get("bank_account_number") or clean_payload.get("bank_account_holder"):
        clean_payload["payout_bank_details"] = {
            "bank_name": clean_payload.get("bank_name"),
            "account_number": clean_payload.get("bank_account_number"),
            "account_holder": clean_payload.get("bank_account_holder"),
        }

    # Definisi kunci fallback yang tetap mempertahankan data rekening bank & identitas
    fallback_keys = {
        "name", "phone", "phone_number", "email", "referral_code",
        "bank_name", "bank_account_number", "bank_account_holder",
        "payout_bank_details", "commission_rate", "status", "tenant_id", "manager_id"
    }

    if affiliate_id:
        try:
            res = supabase.table("affiliates").update(clean_payload).eq("id", affiliate_id).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            logger.warning(f"[Affiliate Save] Update with full columns failed ({e}), using safe fallback")
            fallback = {k: v for k, v in clean_payload.items() if k in fallback_keys}
            res = supabase.table("affiliates").update(fallback).eq("id", affiliate_id).execute()
            return res.data[0] if res.data else {}
    else:
        try:
            res = supabase.table("affiliates").insert(clean_payload).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            logger.warning(f"[Affiliate Save] Insert with full columns failed ({e}), using safe fallback")
            fallback = {k: v for k, v in clean_payload.items() if k in fallback_keys}
            res = supabase.table("affiliates").insert(fallback).execute()
            return res.data[0] if res.data else {}
    return {}


@router.post("/send-otp")
async def send_affiliate_otp(payload: SendOTPRequest):
    phone = normalize_phone(payload.phone)
    if len(phone) < 10:
        raise HTTPException(status_code=400, detail="Nomor WhatsApp tidak valid")

    otp = f"{random.randint(100000, 999999)}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    supabase.table("affiliate_auth_otps").upsert({
        "phone": phone,
        "otp_code": otp,
        "expires_at": expires_at.isoformat()
    }).execute()

    try:
        await send_otp_whatsapp(phone, otp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengirim pesan WhatsApp: {str(e)}")

    return {"status": "success", "message": "Kode OTP berhasil dikirim via WhatsApp resmi"}


@router.post("/verify-otp")
async def verify_affiliate_otp(payload: VerifyOTPRequest):
    phone = normalize_phone(payload.phone)
    res = supabase.table("affiliate_auth_otps").select("*").eq("phone", phone).execute()
    
    if not res.data:
        raise HTTPException(status_code=400, detail="Kode OTP tidak ditemukan atau belum diminta")

    record = res.data[0]
    expires_at = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))

    if datetime.now(timezone.utc) > expires_at:
        supabase.table("affiliate_auth_otps").delete().eq("phone", phone).execute()
        raise HTTPException(status_code=400, detail="Kode OTP telah kedaluwarsa")

    if record["otp_code"] != payload.otp.strip():
        raise HTTPException(status_code=400, detail="Kode OTP salah")

    # Hapus OTP yang sudah digunakan
    supabase.table("affiliate_auth_otps").delete().eq("phone", phone).execute()

    # Dapatkan atau buat entri profil affiliate
    aff_res = supabase.table("affiliates").select("*").eq("phone", phone).execute()
    if not aff_res.data:
        aff_res = supabase.table("affiliates").select("*").eq("phone_number", phone).execute()

    affiliate_code = payload.referral_code or f"AFF{phone[-4:]}{random.randint(10, 99)}"

    if not aff_res.data:
        insert_payload = {
            "phone": phone,
            "phone_number": phone,
            "name": payload.name or "Affiliate Partner",
            "referral_code": affiliate_code,
            "tenant_id": payload.tenant_id or "onlineboost",
            "manager_id": payload.manager_id,
            "status": "ACTIVE",
            "commission_rate": 25.0,
            "screening_status": "PENDING",
            "is_bank_verified": False,
            "agreed_to_rules": bool(payload.agreed_to_rules),
            "experience_level": payload.experience_level or "BEGINNER",
        }
        if payload.bank_name:
            insert_payload["bank_name"] = payload.bank_name.strip()
        if payload.bank_account_number:
            insert_payload["bank_account_number"] = payload.bank_account_number.strip()
        if payload.bank_account_holder:
            insert_payload["bank_account_holder"] = payload.bank_account_holder.strip()
        if payload.promotion_strategy_notes:
            insert_payload["promotion_strategy_notes"] = payload.promotion_strategy_notes.strip()
        if payload.social_media_links:
            insert_payload["social_media_links"] = payload.social_media_links
        if payload.portfolio_url:
            insert_payload["portfolio_url"] = payload.portfolio_url.strip()

        # Format backward compatible JSONB
        if payload.bank_name or payload.bank_account_number or payload.bank_account_holder:
            insert_payload["payout_bank_details"] = {
                "bank_name": payload.bank_name,
                "account_number": payload.bank_account_number,
                "account_holder": payload.bank_account_holder,
            }

        affiliate_data = save_affiliate_record(insert_payload)
    else:
        affiliate_data = aff_res.data[0]
        # Update field jika dikirimkan bersama payload verify-otp
        update_payload = {}
        if payload.name and affiliate_data.get("name") in ["Affiliate Partner", None, ""]:
            update_payload["name"] = payload.name
        if payload.bank_name:
            update_payload["bank_name"] = payload.bank_name.strip()
        if payload.bank_account_number:
            update_payload["bank_account_number"] = payload.bank_account_number.strip()
        if payload.bank_account_holder:
            update_payload["bank_account_holder"] = payload.bank_account_holder.strip()
        if payload.experience_level:
            update_payload["experience_level"] = payload.experience_level
        if payload.promotion_strategy_notes:
            update_payload["promotion_strategy_notes"] = payload.promotion_strategy_notes.strip()
        if payload.social_media_links:
            update_payload["social_media_links"] = payload.social_media_links
        if payload.portfolio_url:
            update_payload["portfolio_url"] = payload.portfolio_url.strip()
        if payload.agreed_to_rules is not None:
            update_payload["agreed_to_rules"] = payload.agreed_to_rules

        if payload.bank_name or payload.bank_account_number or payload.bank_account_holder:
            update_payload["payout_bank_details"] = {
                "bank_name": payload.bank_name or affiliate_data.get("bank_name"),
                "account_number": payload.bank_account_number or affiliate_data.get("bank_account_number"),
                "account_holder": payload.bank_account_holder or affiliate_data.get("bank_account_holder"),
            }

        if update_payload:
            updated = save_affiliate_record(update_payload, affiliate_id=affiliate_data["id"])
            if updated:
                affiliate_data = updated

    # Alias affiliate_code untuk kompatibilitas frontend
    aff_code = affiliate_data.get("referral_code") or affiliate_data.get("affiliate_code") or affiliate_code
    affiliate_data["affiliate_code"] = aff_code

    # Terbitkan Token JWT (masa aktif 7 hari)
    token_payload = {
        "sub": affiliate_data.get("id"),
        "phone": affiliate_data.get("phone") or affiliate_data.get("phone_number") or phone,
        "affiliate_code": aff_code,
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    access_token = generate_jwt_token(token_payload)

    return {
        "status": "success",
        "access_token": access_token,
        "affiliate": affiliate_data
    }


@router.post("/register")
async def register_affiliate(payload: AffiliateRegisterRequest):
    """
    Endpoint registrasi langsung mitra affiliate baru dengan data screening dan rekening bank.
    Menyimpan field bank & screening langsung ke database Supabase.
    """
    phone = normalize_phone(payload.phone)
    if len(phone) < 10:
        raise HTTPException(status_code=400, detail="Nomor WhatsApp tidak valid (minimal 10 digit)")

    affiliate_name = (payload.name or payload.full_name or "").strip()
    if not affiliate_name or len(affiliate_name) < 2:
        raise HTTPException(status_code=400, detail="Nama lengkap wajib diisi minimal 2 karakter")

    # Cek apakah nomor telepon sudah terdaftar
    aff_res = supabase.table("affiliates").select("*").eq("phone", phone).execute()
    if not aff_res.data:
        aff_res = supabase.table("affiliates").select("*").eq("phone_number", phone).execute()

    raw_ref = payload.referral_code or payload.am_referral_code or payload.am_pembina
    affiliate_code = (
        raw_ref.strip().upper()
        if raw_ref and raw_ref.strip()
        else f"AFF{phone[-4:]}{random.randint(10, 99)}"
    )

    db_payload = {
        "phone": phone,
        "phone_number": phone,
        "name": affiliate_name,
        "referral_code": affiliate_code,
        "tenant_id": payload.tenant_id or "onlineboost",
        "manager_id": payload.manager_id,
        "status": "ACTIVE",
        "commission_rate": 25.0,
        "screening_status": "PENDING",
        "is_bank_verified": False,
        "agreed_to_rules": bool(payload.agreed_to_rules),
        "experience_level": payload.experience_level or "BEGINNER",
    }

    if payload.email:
        db_payload["email"] = payload.email.strip().lower()
    # Ekstraksi field rekening bank dengan fallback alias lengkap
    resolved_bank = (
        payload.bank_name
        or payload.bank
        or (payload.payout_bank_details.get("bank_name") if isinstance(payload.payout_bank_details, dict) else None)
    )
    resolved_account_number = (
        payload.bank_account_number
        or payload.account_number
        or (payload.payout_bank_details.get("account_number") if isinstance(payload.payout_bank_details, dict) else None)
        or (payload.payout_bank_details.get("bank_account_number") if isinstance(payload.payout_bank_details, dict) else None)
    )
    resolved_account_holder = (
        payload.bank_account_holder
        or payload.account_holder
        or payload.account_name
        or (payload.payout_bank_details.get("account_holder") if isinstance(payload.payout_bank_details, dict) else None)
        or (payload.payout_bank_details.get("bank_account_holder") if isinstance(payload.payout_bank_details, dict) else None)
    )

    if resolved_bank:
        db_payload["bank_name"] = resolved_bank.strip().upper()
    if resolved_account_number:
        db_payload["bank_account_number"] = resolved_account_number.strip().replace(" ", "")
    if resolved_account_holder:
        db_payload["bank_account_holder"] = resolved_account_holder.strip().upper()

    # Format backward compatible JSONB
    if resolved_bank or resolved_account_number or resolved_account_holder:
        db_payload["payout_bank_details"] = {
            "bank_name": resolved_bank.strip().upper() if resolved_bank else None,
            "account_number": resolved_account_number.strip().replace(" ", "") if resolved_account_number else None,
            "account_holder": resolved_account_holder.strip().upper() if resolved_account_holder else None,
        }

    if payload.promotion_strategy_notes or payload.promotion_plan:
        db_payload["promotion_strategy_notes"] = (payload.promotion_strategy_notes or payload.promotion_plan or "").strip()
    if payload.social_media_links:
        db_payload["social_media_links"] = payload.social_media_links
    if payload.portfolio_url:
        db_payload["portfolio_url"] = payload.portfolio_url.strip()

    try:
        logger.info(f"[AFFILIATE_REGISTRATION] Processing affiliate '{affiliate_name}' (phone: {phone}, bank: {payload.bank_name})")
        if aff_res.data:
            # Mitra sudah terdaftar: perbarui profil & screening
            existing_id = aff_res.data[0]["id"]
            update_data = {k: v for k, v in db_payload.items() if k not in ["phone", "phone_number", "referral_code"]}
            affiliate_data = save_affiliate_record(update_data, affiliate_id=existing_id)
            if not affiliate_data:
                affiliate_data = aff_res.data[0]
        else:
            # Pendaftaran mitra baru
            affiliate_data = save_affiliate_record(db_payload)

        if not affiliate_data:
            raise ValueError("Data affiliate tidak berhasil disimpan ke database")

        logger.info(f"[AFFILIATE_REGISTRATION ✓] Successfully saved affiliate record ID: {affiliate_data.get('id')}")
    except HTTPException:
        raise
    except Exception as save_err:
        logger.error(f"[AFFILIATE_REGISTRATION ERROR] Failed saving affiliate {phone}: {save_err}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan data pendaftaran affiliate: {str(save_err)}")

    aff_code = affiliate_data.get("referral_code") or affiliate_data.get("affiliate_code") or affiliate_code
    affiliate_data["affiliate_code"] = aff_code

    token_payload = {
        "sub": affiliate_data.get("id"),
        "phone": affiliate_data.get("phone") or affiliate_data.get("phone_number") or phone,
        "affiliate_code": aff_code,
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    access_token = generate_jwt_token(token_payload)

    return {
        "status": "success",
        "message": "Pendaftaran mitra affiliate dan data kualifikasi berhasil disimpan",
        "access_token": access_token,
        "affiliate": affiliate_data
    }


@router.post("/screening")
async def submit_affiliate_screening(payload: AffiliateScreeningRequest):
    """
    Endpoint khusus untuk memperbarui atau melengkapi data screening & rekening bank
    bagi mitra affiliate yang sudah terdaftar.
    """
    if not payload.phone and not payload.affiliate_id:
        raise HTTPException(status_code=400, detail="Wajib menyertakan phone atau affiliate_id")

    if payload.affiliate_id:
        res = supabase.table("affiliates").select("*").eq("id", payload.affiliate_id).execute()
    else:
        clean_phone = normalize_phone(payload.phone)
        res = supabase.table("affiliates").select("*").eq("phone", clean_phone).execute()
        if not res.data:
            res = supabase.table("affiliates").select("*").eq("phone_number", clean_phone).execute()

    if not res.data:
        raise HTTPException(status_code=404, detail="Data mitra affiliate tidak ditemukan")

    affiliate_id = res.data[0]["id"]
    update_data: Dict[str, Any] = {
        "screening_status": "PENDING"
    }

    if payload.bank_name:
        update_data["bank_name"] = payload.bank_name.strip()
    if payload.bank_account_number:
        update_data["bank_account_number"] = payload.bank_account_number.strip()
    if payload.bank_account_holder:
        update_data["bank_account_holder"] = payload.bank_account_holder.strip()
    if payload.experience_level:
        update_data["experience_level"] = payload.experience_level
    if payload.promotion_strategy_notes:
        update_data["promotion_strategy_notes"] = payload.promotion_strategy_notes.strip()
    if payload.social_media_links is not None:
        update_data["social_media_links"] = payload.social_media_links
    if payload.portfolio_url:
        update_data["portfolio_url"] = payload.portfolio_url.strip()
    if payload.agreed_to_rules is not None:
        update_data["agreed_to_rules"] = payload.agreed_to_rules

    if payload.bank_name or payload.bank_account_number or payload.bank_account_holder:
        update_data["payout_bank_details"] = {
            "bank_name": payload.bank_name or res.data[0].get("bank_name"),
            "account_number": payload.bank_account_number or res.data[0].get("bank_account_number"),
            "account_holder": payload.bank_account_holder or res.data[0].get("bank_account_holder"),
        }

    updated = save_affiliate_record(update_data, affiliate_id=affiliate_id)
    if not updated:
        updated = res.data[0]

    return {
        "status": "success",
        "message": "Data kualifikasi screening dan rekening bank berhasil diperbarui",
        "affiliate": updated
    }



@router.patch("/payout-account")
@router.post("/payout-account")
@router.post("/update-bank")
@affiliate_payout_router.patch("/api/v1/affiliate/payout-account")
@affiliate_payout_router.post("/api/v1/affiliate/payout-account")
@affiliate_payout_router.post("/api/v1/auth/affiliate/update-bank")
async def update_affiliate_payout_account(payload: UpdatePayoutAccountRequest):
    """
    Endpoint pembaruan rekening bank / e-wallet pencairan komisi mitra affiliate.
    Mendukung PATCH/POST /api/v1/affiliate/payout-account dan POST /api/v1/auth/affiliate/update-bank.
    """
    # 1. Ekstraksi bank info dengan toleransi alias lengkap
    resolved_bank = (
        payload.bank_name
        or payload.bank
        or (payload.payout_bank_details.get("bank_name") if isinstance(payload.payout_bank_details, dict) else None)
    )
    resolved_account_number = (
        payload.bank_account_number
        or payload.account_number
        or (payload.payout_bank_details.get("account_number") if isinstance(payload.payout_bank_details, dict) else None)
        or (payload.payout_bank_details.get("bank_account_number") if isinstance(payload.payout_bank_details, dict) else None)
    )
    resolved_account_holder = (
        payload.bank_account_holder
        or payload.account_holder
        or payload.account_name
        or (payload.payout_bank_details.get("account_holder") if isinstance(payload.payout_bank_details, dict) else None)
        or (payload.payout_bank_details.get("bank_account_holder") if isinstance(payload.payout_bank_details, dict) else None)
    )

    if not resolved_bank or not resolved_account_number or not resolved_account_holder:
        raise HTTPException(
            status_code=400,
            detail="Pilihan bank/e-wallet, nomor rekening, dan nama pemilik rekening wajib diisi lengkap."
        )

    clean_bank = str(resolved_bank).strip().upper()
    clean_account = str(resolved_account_number).strip().replace(" ", "")
    clean_holder = str(resolved_account_holder).strip().upper()

    # 2. Cari partner / affiliate
    aff_id = payload.affiliate_id or payload.partner_id or payload.id
    target_phone = payload.phone or payload.phone_number

    aff_record = None
    if aff_id:
        res = supabase.table("affiliates").select("*").eq("id", aff_id).execute()
        if res.data:
            aff_record = res.data[0]

    if not aff_record and target_phone:
        normalized = normalize_phone(target_phone)
        res = supabase.table("affiliates").select("*").eq("phone", normalized).execute()
        if not res.data:
            res = supabase.table("affiliates").select("*").eq("phone_number", normalized).execute()
        if res.data:
            aff_record = res.data[0]

    if not aff_record and payload.email:
        res = supabase.table("affiliates").select("*").eq("email", str(payload.email).strip().lower()).execute()
        if res.data:
            aff_record = res.data[0]

    if not aff_record:
        raise HTTPException(status_code=404, detail="Data mitra affiliate tidak ditemukan.")

    target_aff_id = aff_record["id"]

    update_payload = {
        "bank_name": clean_bank,
        "bank_account_number": clean_account,
        "bank_account_holder": clean_holder,
        "payout_bank_details": {
            "bank_name": clean_bank,
            "account_number": clean_account,
            "account_holder": clean_holder,
        },
        "is_bank_verified": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    updated_aff = save_affiliate_record(update_payload, affiliate_id=target_aff_id)
    if not updated_aff:
        updated_aff = {**aff_record, **update_payload}

    logger.info(f"[AFFILIATE_BANK_UPDATE] Updated bank for affiliate {target_aff_id}: {clean_bank} - {clean_account} ({clean_holder})")

    return {
        "success": True,
        "status": "success",
        "message": "Rekening pencairan komisi berhasil diperbarui.",
        "affiliate": updated_aff,
        "bank_account": {
            "bank_name": clean_bank,
            "account_number": clean_account,
            "account_holder": clean_holder,
        }
    }


# ============================================================================
# aiohttp Handlers & Registrar (Dual-Runner Railway Compliance)
# ============================================================================

try:
    from aiohttp import web

    def _aiohttp_affiliate_cors_headers(request: web.Request) -> Dict[str, str]:
        origin = request.headers.get("Origin", "*")
        req_headers = request.headers.get("Access-Control-Request-Headers", "*")
        return {
            "Access-Control-Allow-Origin": origin if origin else "*",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT, DELETE, PATCH",
            "Access-Control-Allow-Headers": req_headers if req_headers != "*" else "Content-Type, Authorization, X-Requested-With, apikey, Accept, Origin, x-tenant-id",
        }

    async def aiohttp_options_affiliate(request: web.Request) -> web.Response:
        return web.Response(status=200, headers=_aiohttp_affiliate_cors_headers(request))

    def _aiohttp_affiliate_json_response(data: dict, status_code: int = 200, request: web.Request = None) -> web.Response:
        headers = _aiohttp_affiliate_cors_headers(request) if request else {}
        return web.json_response(data, status=status_code, headers=headers)

    async def aiohttp_register_affiliate(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            payload = AffiliateRegisterRequest(**body)
            result = await register_affiliate(payload)
            return _aiohttp_affiliate_json_response(result, status_code=200, request=request)
        except HTTPException as he:
            return _aiohttp_affiliate_json_response({"status": "error", "detail": he.detail}, status_code=he.status_code, request=request)
        except Exception as e:
            logger.error(f"[aiohttp Affiliate Register Error] {e}", exc_info=True)
            return _aiohttp_affiliate_json_response({"status": "error", "detail": str(e)}, status_code=400, request=request)

    async def aiohttp_send_otp(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            payload = SendOTPRequest(**body)
            result = await send_affiliate_otp(payload)
            return _aiohttp_affiliate_json_response(result, status_code=200, request=request)
        except HTTPException as he:
            return _aiohttp_affiliate_json_response({"status": "error", "detail": he.detail}, status_code=he.status_code, request=request)
        except Exception as e:
            logger.error(f"[aiohttp Affiliate Send OTP Error] {e}", exc_info=True)
            return _aiohttp_affiliate_json_response({"status": "error", "detail": str(e)}, status_code=400, request=request)

    async def aiohttp_verify_otp(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            payload = VerifyOTPRequest(**body)
            result = await verify_affiliate_otp(payload)
            return _aiohttp_affiliate_json_response(result, status_code=200, request=request)
        except HTTPException as he:
            return _aiohttp_affiliate_json_response({"status": "error", "detail": he.detail}, status_code=he.status_code, request=request)
        except Exception as e:
            logger.error(f"[aiohttp Affiliate Verify OTP Error] {e}", exc_info=True)
            return _aiohttp_affiliate_json_response({"status": "error", "detail": str(e)}, status_code=400, request=request)

    async def aiohttp_screening(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            payload = AffiliateScreeningRequest(**body)
            result = await submit_affiliate_screening(payload)
            return _aiohttp_affiliate_json_response(result, status_code=200, request=request)
        except HTTPException as he:
            return _aiohttp_affiliate_json_response({"status": "error", "detail": he.detail}, status_code=he.status_code, request=request)
        except Exception as e:
            logger.error(f"[aiohttp Affiliate Screening Error] {e}", exc_info=True)
            return _aiohttp_affiliate_json_response({"status": "error", "detail": str(e)}, status_code=400, request=request)

    
    async def aiohttp_update_payout_account(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            payload = UpdatePayoutAccountRequest(**body)
            result = await update_affiliate_payout_account(payload)
            return _aiohttp_affiliate_json_response(result, status_code=200, request=request)
        except HTTPException as he:
            return _aiohttp_affiliate_json_response({"status": "error", "detail": he.detail, "message": he.detail}, status_code=he.status_code, request=request)
        except Exception as e:
            logger.error(f"[aiohttp Affiliate Update Payout Account Error] {e}", exc_info=True)
            return _aiohttp_affiliate_json_response({"status": "error", "detail": str(e), "message": str(e)}, status_code=400, request=request)

    def register_affiliate_auth_routes(app: web.Application):
        """Mendaftarkan rute auth affiliate ke aiohttp web server dengan proteksi duplikasi penuh."""
        existing = set()
        for r in app.router.routes():
            if r.resource:
                canon = getattr(r.resource, "canonical", None)
                if canon:
                    existing.add((r.method.upper(), canon))

        routes = [
            ("POST", "/api/v1/auth/affiliate/register", aiohttp_register_affiliate),
            ("OPTIONS", "/api/v1/auth/affiliate/register", aiohttp_options_affiliate),
            ("POST", "/api/v1/auth/affiliate/send-otp", aiohttp_send_otp),
            ("OPTIONS", "/api/v1/auth/affiliate/send-otp", aiohttp_options_affiliate),
            ("POST", "/api/v1/auth/affiliate/verify-otp", aiohttp_verify_otp),
            ("OPTIONS", "/api/v1/auth/affiliate/verify-otp", aiohttp_options_affiliate),
            ("POST", "/api/v1/auth/affiliate/screening", aiohttp_screening),
            ("OPTIONS", "/api/v1/auth/affiliate/screening", aiohttp_options_affiliate),
            ("PATCH", "/api/v1/affiliate/payout-account", aiohttp_update_payout_account),
            ("POST", "/api/v1/affiliate/payout-account", aiohttp_update_payout_account),
            ("OPTIONS", "/api/v1/affiliate/payout-account", aiohttp_options_affiliate),
            ("POST", "/api/v1/auth/affiliate/update-bank", aiohttp_update_payout_account),
            ("OPTIONS", "/api/v1/auth/affiliate/update-bank", aiohttp_options_affiliate),
            ("PATCH", "/api/v1/auth/affiliate/payout-account", aiohttp_update_payout_account),
            ("POST", "/api/v1/auth/affiliate/payout-account", aiohttp_update_payout_account),
        ]
        for method, path, handler in routes:
            if (method.upper(), path) in existing:
                continue
            if method == "POST":
                app.router.add_post(path, handler)
            elif method == "OPTIONS":
                app.router.add_options(path, handler)
            elif method == "PATCH":
                app.router.add_patch(path, handler)
            existing.add((method.upper(), path))
        logger.info("[ROUTER] Affiliate auth & payout routes registered on aiohttp.")

except ImportError:
    def register_affiliate_auth_routes(app):
        pass