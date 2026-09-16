import re
import os
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Header, Request, Response, Depends, Query
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
affiliate_router = APIRouter(prefix="/api/v1/affiliate", tags=["Affiliate Dashboard"])

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


def decode_jwt_token(token: str) -> Dict[str, Any]:
    """
    Safely decodes and validates a signed JWT token.
    Raises HTTPException 401 if token is missing, invalid, or expired.
    """
    clean_token = token.replace("Bearer ", "").strip()
    if not clean_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token autentikasi kosong",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Decode with python-jose or PyJWT
    if jwt is not None:
        try:
            return jwt.decode(clean_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except Exception as e:
            err_str = str(e).lower()
            if "expired" in err_str or "signature has expired" in err_str:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token telah kedaluwarsa",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            logger.warning(f"JWT library decode failed: {e}")

    # 2. Manual HMAC-SHA256 fallback decode
    try:
        import base64
        import json
        import hmac
        import hashlib

        parts = clean_token.split(".")
        if len(parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Format token autentikasi tidak valid",
                headers={"WWW-Authenticate": "Bearer"},
            )
        header_b64, body_b64, sig_b64 = parts

        def b64_decode(data: str) -> bytes:
            padding = 4 - (len(data) % 4)
            if padding and padding != 4:
                data += "=" * padding
            return base64.urlsafe_b64decode(data.encode())

        expected_sig = hmac.new(
            JWT_SECRET.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
        ).digest()
        actual_sig = b64_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tanda tangan token tidak valid",
                headers={"WWW-Authenticate": "Bearer"},
            )

        payload_bytes = b64_decode(body_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        # Check expiration timestamp
        if "exp" in payload:
            exp_val = payload["exp"]
            now_ts = datetime.now(timezone.utc).timestamp()
            if isinstance(exp_val, (int, float)) and now_ts > exp_val:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token telah kedaluwarsa",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fallback JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token autentikasi tidak valid: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_affiliate(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """
    Ekstrak identitas user dari Request State, Authorization Header, atau Cookie.
    - 401 Unauthorized: Jika tidak ada token, token expired, atau tidak valid.
    - 403 Forbidden: Jika user terotentikasi tetapi role/keanggotaannya bukan Affiliate aktif.
    """
    user_state = getattr(request.state, "user", None) if hasattr(request, "state") else None

    token = None
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1].strip()
        else:
            token = authorization.strip()

    if not token and hasattr(request, "cookies") and request.cookies:
        token = (
            request.cookies.get("authSession")
            or request.cookies.get("access_token")
            or request.cookies.get("token")
        )

    payload = None
    if user_state and isinstance(user_state, dict):
        payload = user_state
    elif token:
        payload = decode_jwt_token(token)
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi diperlukan. Sertakan Bearer token atau session cookie.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Simpan ke request.state.user untuk auth context downstream
    if hasattr(request, "state"):
        request.state.user = payload

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
    user_phone = payload.get("phone") or payload.get("phone_number")
    user_role = str(payload.get("role") or "").strip().upper()

    # Jika payload JWT secara eksplisit mendefinisikan non-affiliate role (misal: USER, MERCHANT, CUSTOMER)
    if user_role and user_role not in ["AFFILIATE", "PARTNER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Keanggotaan bukan Affiliate aktif.",
        )

    # Query profil affiliate ke database Supabase berdasarkan user_id / identity terotentikasi
    affiliate = None
    if user_id:
        try:
            res = supabase.table("affiliates").select("*").eq("id", str(user_id)).execute()
            if res.data:
                affiliate = res.data[0]
        except Exception as e:
            logger.warning(f"[Auth] Supabase lookup by id failed: {e}")

    if not affiliate and user_phone:
        norm_phone = normalize_phone(str(user_phone))
        try:
            res = supabase.table("affiliates").select("*").eq("phone", norm_phone).execute()
            if not res.data:
                res = supabase.table("affiliates").select("*").eq("phone_number", norm_phone).execute()
            if res.data:
                affiliate = res.data[0]
        except Exception as e:
            logger.warning(f"[Auth] Supabase lookup by phone failed: {e}")

    # Jika user terotentikasi tapi tidak terdaftar di database affiliates -> 403 Forbidden
    if not affiliate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Akun Anda bukan bagian dari program Affiliate aktif.",
        )

    # Validasi role dan status keanggotaan
    db_role = str(affiliate.get("role") or "AFFILIATE").strip().upper()
    db_status = str(affiliate.get("status") or "ACTIVE").strip().upper()

    if db_role not in ["AFFILIATE", "PARTNER"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Role akun bukan Affiliate.",
        )

    if db_status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Akses ditolak. Status keanggotaan affiliate adalah {db_status}.",
        )

    return affiliate



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
    custom_slug: Optional[str] = None
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

    # Ekstraksi custom slug pendaftar
    custom_slug_input = (payload.custom_slug or "").strip().lower()
    if not custom_slug_input and payload.referral_code:
        # Periksa apakah referral_code yang dikirim berbeda dengan AM pembina (artinya custom slug)
        ref_cand = payload.referral_code.strip().lower()
        am_cand = (payload.am_pembina or payload.am_referral_code or "").strip().lower()
        if ref_cand and ref_cand != am_cand:
            custom_slug_input = ref_cand

    if custom_slug_input:
        clean_slug = re.sub(r"[^a-z0-9-]", "", custom_slug_input)
        if len(clean_slug) < 3 or len(clean_slug) > 30:
            raise HTTPException(status_code=400, detail="Custom slug minimal 3 karakter dan maksimal 30 karakter (hanya huruf kecil, angka, dan strip).")
        
        # Cek keunikan slug di database Supabase
        slug_check = supabase.table("affiliates").select("id, referral_code").ilike("referral_code", clean_slug).execute()
        if slug_check.data:
            # Jika nomor telepon sama dan sedang update, perbolehkan jika milik sendiri
            is_own = any(normalize_phone(r.get("phone", "") or r.get("phone_number", "")) == phone for r in slug_check.data)
            if not is_own:
                raise HTTPException(status_code=400, detail="Slug sudah dipakai, gunakan nama lain")
        affiliate_code = clean_slug
    else:
        affiliate_code = f"AFF{phone[-4:]}{random.randint(10, 99)}"

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


class UpdateSlugRequest(BaseModel):
    model_config = {"extra": "allow"}

    affiliate_id: Optional[str] = None
    partner_id: Optional[str] = None
    id: Optional[str] = None
    current_code: Optional[str] = None
    referral_code: Optional[str] = None
    phone: Optional[str] = None
    new_slug: str


@router.patch("/slug")
@router.post("/slug")
@affiliate_payout_router.patch("/api/v1/affiliate/slug")
@affiliate_payout_router.post("/api/v1/affiliate/slug")
async def update_affiliate_slug(payload: UpdateSlugRequest):
    """
    Endpoint update slug / kode referral kustom mitra affiliate.
    Payload: { affiliate_id / current_code, new_slug }
    """
    raw_slug = (payload.new_slug or "").strip().lower()
    clean_slug = re.sub(r"[^a-z0-9-]", "", raw_slug)

    if not clean_slug or len(clean_slug) < 3 or len(clean_slug) > 30:
        raise HTTPException(
            status_code=400,
            detail="Slug referral minimal 3 karakter dan maksimal 30 karakter (hanya huruf kecil, angka, dan strip)."
        )

    # Reserved keywords check
    RESERVED = {
        "login", "register", "daftar", "api", "dashboard", "auth", "admin",
        "affiliate", "manager", "shop", "creator", "www", "app", "career", "static", "chat"
    }
    if clean_slug in RESERVED:
        raise HTTPException(status_code=400, detail="Slug ini dicadangkan untuk sistem, gunakan nama lain.")

    # Cari partner / affiliate
    aff_id = payload.affiliate_id or payload.partner_id or payload.id
    current_code = (payload.current_code or payload.referral_code or "").strip().lower()
    target_phone = payload.phone

    aff_record = None
    if aff_id:
        res = supabase.table("affiliates").select("*").eq("id", aff_id).execute()
        if res.data:
            aff_record = res.data[0]

    if not aff_record and current_code:
        res = supabase.table("affiliates").select("*").ilike("referral_code", current_code).execute()
        if res.data:
            aff_record = res.data[0]

    if not aff_record and target_phone:
        normalized = normalize_phone(target_phone)
        res = supabase.table("affiliates").select("*").eq("phone", normalized).execute()
        if not res.data:
            res = supabase.table("affiliates").select("*").eq("phone_number", normalized).execute()
        if res.data:
            aff_record = res.data[0]

    if not aff_record:
        raise HTTPException(status_code=404, detail="Data mitra affiliate tidak ditemukan.")

    target_aff_id = aff_record["id"]

    # Cek apakah new_slug sudah dipakai affiliate lain
    slug_check = supabase.table("affiliates").select("id, referral_code").ilike("referral_code", clean_slug).execute()
    if slug_check.data:
        for r in slug_check.data:
            if str(r.get("id")) != str(target_aff_id):
                raise HTTPException(status_code=400, detail="Slug sudah dipakai, gunakan nama lain")

    # Update tabel affiliates
    update_payload = {
        "referral_code": clean_slug,
        "is_ref_customized": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    updated_aff = save_affiliate_record(update_payload, affiliate_id=target_aff_id)
    if not updated_aff:
        updated_aff = {**aff_record, **update_payload}

    logger.info(f"[AFFILIATE_SLUG_UPDATE] Affiliate {target_aff_id} successfully updated slug to '{clean_slug}'")

    return {
        "status": "success",
        "success": True,
        "message": "Slug berhasil diperbarui.",
        "slug": clean_slug,
        "referral_code": clean_slug,
        "affiliate": updated_aff
    }


# ============================================================================
# AFFILIATE DASHBOARD & ATTR PORTAL ENDPOINTS
# ============================================================================

@affiliate_router.get("/me", summary="Get Authenticated Affiliate Profile")
@affiliate_payout_router.get("/api/v1/affiliate/me")
async def get_affiliate_me(
    response: Response,
    current_affiliate: Dict[str, Any] = Depends(get_current_affiliate),
):
    """
    Mengembalikan data profil affiliate dari sesi terotentikasi.
    Strictly auth-only: tidak bergantung pada query parameter ?code= atau subdomain lookup.
    """
    response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"

    aff_id = str(current_affiliate.get("id"))
    aff_code = (
        current_affiliate.get("referral_code")
        or current_affiliate.get("affiliate_code")
        or ""
    )

    available_comm = 0.0
    pending_comm = 0.0

    # 1. Query komisi dari tabel affiliate_commissions
    try:
        comm_res = supabase.table("affiliate_commissions").select("amount, status").eq("affiliate_id", aff_id).execute()
        if comm_res.data:
            for r in comm_res.data:
                amt = float(r.get("amount") or 0.0)
                st = str(r.get("status") or "").strip().upper()
                if st in ["APPROVED", "AVAILABLE", "READY"]:
                    available_comm += amt
                elif st in ["PENDING", "PENDING_PAYOUT", "WAITING"]:
                    pending_comm += amt
    except Exception as e:
        logger.warning(f"[Affiliate Me] Query affiliate_commissions failed: {e}")

    # 2. Fallback query ke commission_ledger jika belum tercatat di affiliate_commissions
    if available_comm == 0 and pending_comm == 0 and aff_code:
        try:
            ledger_res = supabase.table("commission_ledger").select("affiliate_commission_amount, status").eq("affiliate_code", aff_code).execute()
            if ledger_res.data:
                for r in ledger_res.data:
                    amt = float(r.get("affiliate_commission_amount") or 0.0)
                    st = str(r.get("status") or "").strip().upper()
                    if st in ["APPROVED", "AVAILABLE"]:
                        available_comm += amt
                    elif st in ["PENDING", "PENDING_PAYOUT"]:
                        pending_comm += amt
        except Exception:
            pass

    def _format_comm(val: float):
        return int(val) if val.is_integer() else round(val, 2)

    return {
        "id": aff_id,
        "name": current_affiliate.get("name") or "Nama Mitra",
        "phone": current_affiliate.get("phone") or current_affiliate.get("phone_number") or "",
        "role": current_affiliate.get("role") or "AFFILIATE",
        "status": current_affiliate.get("status") or "ACTIVE",
        "referral_code": aff_code,
        "commission": {
            "available": _format_comm(available_comm),
            "pending": _format_comm(pending_comm),
        },
    }


@affiliate_router.get("/portal", summary="Validasi Publik Kode Promo untuk Atribusi Registrasi (Deprecated for Dashboard)")
@affiliate_payout_router.get("/api/v1/affiliate/portal")
async def get_affiliate_portal(
    response: Response,
    code: Optional[str] = Query(None, description="Kode promo / referral"),
    ref: Optional[str] = Query(None, description="Alias kode referral"),
    referral_code: Optional[str] = Query(None, description="Alias kode referral"),
):
    """
    Endpoint atribusi registrasi publik (DEPRECATED untuk data dashboard privat).
    Strictly hanya memvalidasi apakah kode promo aktif untuk atribusi pendaftaran (ref/code).
    TIDAK PERNAH mengembalikan saldo, komisi, rekening bank, atau data dashboard privat.
    """
    response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    response.headers["X-Deprecated"] = "Endpoint ini didepresiasi untuk akses dashboard. Gunakan GET /api/v1/affiliate/me dengan Bearer token."

    cand_code = code or ref or referral_code
    if not cand_code or not cand_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter kode referral ('code' atau 'ref') diperlukan untuk atribusi registrasi.",
        )

    clean_code = cand_code.strip()
    try:
        res = supabase.table("affiliates").select("id, name, referral_code, status").ilike("referral_code", clean_code).execute()
        if res.data:
            record = res.data[0]
            is_active = str(record.get("status") or "ACTIVE").upper() == "ACTIVE"
            return {
                "valid": is_active,
                "referral_code": record.get("referral_code"),
                "name": record.get("name") if is_active else None,
                "attribution_only": True,
                "message": "Kode promo valid untuk atribusi registrasi." if is_active else "Kode promo tidak aktif.",
            }
    except Exception as e:
        logger.warning(f"[Portal] Supabase referral check failed: {e}")

    return {
        "valid": False,
        "referral_code": clean_code,
        "attribution_only": True,
        "message": "Kode promo tidak ditemukan.",
    }


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
        headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
        return web.json_response(data, status=status_code, headers=headers)

    async def aiohttp_affiliate_me(request: web.Request) -> web.Response:
        try:
            auth_header = request.headers.get("Authorization")
            token = None
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1].strip()
            elif auth_header:
                token = auth_header.strip()

            if not token and request.cookies:
                token = (
                    request.cookies.get("authSession")
                    or request.cookies.get("access_token")
                    or request.cookies.get("token")
                )

            if not token:
                return _aiohttp_affiliate_json_response(
                    {"status": "error", "detail": "Autentikasi diperlukan. Sertakan Bearer token atau session cookie."},
                    status_code=401,
                    request=request
                )

            payload = decode_jwt_token(token)
            user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
            user_phone = payload.get("phone") or payload.get("phone_number")
            user_role = str(payload.get("role") or "").strip().upper()

            if user_role and user_role not in ["AFFILIATE", "PARTNER"]:
                return _aiohttp_affiliate_json_response(
                    {"status": "error", "detail": "Akses ditolak. Keanggotaan bukan Affiliate aktif."},
                    status_code=403,
                    request=request
                )

            affiliate = None
            if user_id:
                try:
                    res = supabase.table("affiliates").select("*").eq("id", str(user_id)).execute()
                    if res.data:
                        affiliate = res.data[0]
                except Exception:
                    pass

            if not affiliate and user_phone:
                norm_phone = normalize_phone(str(user_phone))
                try:
                    res = supabase.table("affiliates").select("*").eq("phone", norm_phone).execute()
                    if not res.data:
                        res = supabase.table("affiliates").select("*").eq("phone_number", norm_phone).execute()
                    if res.data:
                        affiliate = res.data[0]
                except Exception:
                    pass

            if not affiliate:
                return _aiohttp_affiliate_json_response(
                    {"status": "error", "detail": "Akses ditolak. Akun Anda bukan bagian dari program Affiliate aktif."},
                    status_code=403,
                    request=request
                )

            db_role = str(affiliate.get("role") or "AFFILIATE").strip().upper()
            db_status = str(affiliate.get("status") or "ACTIVE").strip().upper()

            if db_role not in ["AFFILIATE", "PARTNER"] or db_status != "ACTIVE":
                return _aiohttp_affiliate_json_response(
                    {"status": "error", "detail": "Akses ditolak. Bukan Affiliate aktif."},
                    status_code=403,
                    request=request
                )

            aff_id = str(affiliate.get("id"))
            aff_code = affiliate.get("referral_code") or affiliate.get("affiliate_code") or ""
            available_comm = 0.0
            pending_comm = 0.0

            try:
                comm_res = supabase.table("affiliate_commissions").select("amount, status").eq("affiliate_id", aff_id).execute()
                if comm_res.data:
                    for r in comm_res.data:
                        amt = float(r.get("amount") or 0.0)
                        st = str(r.get("status") or "").strip().upper()
                        if st in ["APPROVED", "AVAILABLE", "READY"]:
                            available_comm += amt
                        elif st in ["PENDING", "PENDING_PAYOUT", "WAITING"]:
                            pending_comm += amt
            except Exception:
                pass

            data = {
                "id": aff_id,
                "name": affiliate.get("name") or "Nama Mitra",
                "phone": affiliate.get("phone") or affiliate.get("phone_number") or "",
                "role": affiliate.get("role") or "AFFILIATE",
                "status": affiliate.get("status") or "ACTIVE",
                "referral_code": aff_code,
                "commission": {
                    "available": int(available_comm) if available_comm.is_integer() else round(available_comm, 2),
                    "pending": int(pending_comm) if pending_comm.is_integer() else round(pending_comm, 2),
                },
            }
            return _aiohttp_affiliate_json_response(data, status_code=200, request=request)
        except HTTPException as he:
            return _aiohttp_affiliate_json_response({"status": "error", "detail": he.detail}, status_code=he.status_code, request=request)
        except Exception as e:
            logger.error(f"[aiohttp Affiliate Me Error] {e}", exc_info=True)
            return _aiohttp_affiliate_json_response({"status": "error", "detail": str(e)}, status_code=500, request=request)

    async def aiohttp_affiliate_portal(request: web.Request) -> web.Response:
        cand_code = request.query.get("code") or request.query.get("ref") or request.query.get("referral_code")
        if not cand_code or not cand_code.strip():
            return _aiohttp_affiliate_json_response(
                {"status": "error", "detail": "Parameter kode referral ('code' atau 'ref') diperlukan."},
                status_code=400,
                request=request
            )
        clean_code = cand_code.strip()
        try:
            res = supabase.table("affiliates").select("id, name, referral_code, status").ilike("referral_code", clean_code).execute()
            if res.data:
                record = res.data[0]
                is_active = str(record.get("status") or "ACTIVE").upper() == "ACTIVE"
                return _aiohttp_affiliate_json_response({
                    "valid": is_active,
                    "referral_code": record.get("referral_code"),
                    "name": record.get("name") if is_active else None,
                    "attribution_only": True,
                    "message": "Kode promo valid untuk atribusi registrasi." if is_active else "Kode promo tidak aktif.",
                }, status_code=200, request=request)
        except Exception as e:
            logger.warning(f"[aiohttp Portal Error] {e}")

        return _aiohttp_affiliate_json_response({
            "valid": False,
            "referral_code": clean_code,
            "attribution_only": True,
            "message": "Kode promo tidak ditemukan.",
        }, status_code=200, request=request)

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


    async def aiohttp_update_slug(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            payload = UpdateSlugRequest(**body)
            result = await update_affiliate_slug(payload)
            return _aiohttp_affiliate_json_response(result, status_code=200, request=request)
        except HTTPException as he:
            return _aiohttp_affiliate_json_response({"status": "error", "detail": he.detail, "message": he.detail}, status_code=he.status_code, request=request)
        except Exception as e:
            logger.error(f"[aiohttp Affiliate Update Slug Error] {e}", exc_info=True)
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
            ("GET", "/api/v1/affiliate/me", aiohttp_affiliate_me),
            ("OPTIONS", "/api/v1/affiliate/me", aiohttp_options_affiliate),
            ("GET", "/api/v1/affiliate/portal", aiohttp_affiliate_portal),
            ("OPTIONS", "/api/v1/affiliate/portal", aiohttp_options_affiliate),
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
            ("PATCH", "/api/v1/affiliate/slug", aiohttp_update_slug),
            ("POST", "/api/v1/affiliate/slug", aiohttp_update_slug),
            ("OPTIONS", "/api/v1/affiliate/slug", aiohttp_options_affiliate),
            ("PATCH", "/api/v1/auth/affiliate/slug", aiohttp_update_slug),
            ("POST", "/api/v1/auth/affiliate/slug", aiohttp_update_slug),
            ("OPTIONS", "/api/v1/auth/affiliate/slug", aiohttp_options_affiliate),
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
            elif method == "GET":
                app.router.add_get(path, handler)
            existing.add((method.upper(), path))
        logger.info("[ROUTER] Affiliate auth & payout routes registered on aiohttp.")

except ImportError:
    def register_affiliate_auth_routes(app):
        pass