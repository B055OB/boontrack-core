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
from app.services.whatsapp_service import send_whatsapp_text

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


def normalize_phone(phone: str) -> str:
    cleaned = "".join(filter(str.isdigit, phone))
    if cleaned.startswith("0"):
        cleaned = "62" + cleaned[1:]
    return cleaned


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

    msg = (
        f"🔐 *KODE LOGIN BOONTRACK AFFILIATE*\n\n"
        f"Kode OTP Anda: *{otp}*\n\n"
        f"_Berlaku 5 menit. Jangan berikan kode ini kepada siapapun._"
    )
    try:
        await send_whatsapp_text(phone, msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal mengirim pesan WhatsApp: {str(e)}")

    return {"status": "success", "message": "Kode OTP berhasil dikirim via WhatsApp"}


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
        affiliate_code = f"AFF{phone[-4:]}{random.randint(10, 99)}"
        new_aff = supabase.table("affiliates").insert({
            "phone": phone,
            "name": "Affiliate Partner",
            "affiliate_code": affiliate_code
        }).execute()
        affiliate_data = new_aff.data[0]
    else:
        affiliate_data = aff_res.data[0]

    # Terbitkan Token JWT
    token_payload = {
        "sub": affiliate_data["id"],
        "phone": affiliate_data["phone"],
        "affiliate_code": affiliate_data["affiliate_code"],
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    access_token = generate_jwt_token(token_payload)

    return {
        "status": "success",
        "access_token": access_token,
        "affiliate": affiliate_data
    }