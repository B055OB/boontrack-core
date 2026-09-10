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
    """Payload pendaftaran & kualifikasi screening mitra affiliate langsung."""
    phone: str
    name: str
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
    agreed_to_rules: bool = False


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
    Mendukung kolom migrasi 013 (bank_name, screening_status, dll) dengan fallback aman.
    """
    if affiliate_id:
        try:
            res = supabase.table("affiliates").update(db_payload).eq("id", affiliate_id).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            logger.warning(f"[Affiliate Save] Update with extended columns failed ({e}), using fallback")
            core_keys = {"name", "phone", "phone_number", "referral_code", "payout_bank_details", "commission_rate", "status"}
            fallback = {k: v for k, v in db_payload.items() if k in core_keys}
            res = supabase.table("affiliates").update(fallback).eq("id", affiliate_id).execute()
            return res.data[0] if res.data else {}
    else:
        try:
            res = supabase.table("affiliates").insert(db_payload).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            logger.warning(f"[Affiliate Save] Insert with extended columns failed ({e}), using fallback")
            core_keys = {"name", "phone", "phone_number", "referral_code", "payout_bank_details", "commission_rate", "status", "tenant_id", "manager_id"}
            fallback = {k: v for k, v in db_payload.items() if k in core_keys}
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

    if not payload.name or len(payload.name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Nama lengkap wajib diisi minimal 2 karakter")

    # Cek apakah nomor telepon sudah terdaftar
    aff_res = supabase.table("affiliates").select("*").eq("phone", phone).execute()
    if not aff_res.data:
        aff_res = supabase.table("affiliates").select("*").eq("phone_number", phone).execute()

    affiliate_code = (
        payload.referral_code.strip().upper()
        if payload.referral_code and payload.referral_code.strip()
        else f"AFF{phone[-4:]}{random.randint(10, 99)}"
    )

    db_payload = {
        "phone": phone,
        "phone_number": phone,
        "name": payload.name.strip(),
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
        db_payload["bank_name"] = payload.bank_name.strip()
    if payload.bank_account_number:
        db_payload["bank_account_number"] = payload.bank_account_number.strip()
    if payload.bank_account_holder:
        db_payload["bank_account_holder"] = payload.bank_account_holder.strip()
    if payload.promotion_strategy_notes:
        db_payload["promotion_strategy_notes"] = payload.promotion_strategy_notes.strip()
    if payload.social_media_links:
        db_payload["social_media_links"] = payload.social_media_links
    if payload.portfolio_url:
        db_payload["portfolio_url"] = payload.portfolio_url.strip()

    # Format backward compatible JSONB
    if payload.bank_name or payload.bank_account_number or payload.bank_account_holder:
        db_payload["payout_bank_details"] = {
            "bank_name": payload.bank_name,
            "account_number": payload.bank_account_number,
            "account_holder": payload.bank_account_holder,
        }

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