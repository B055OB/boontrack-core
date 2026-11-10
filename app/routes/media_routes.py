"""
app/routes/media_routes.py
==========================
Endpoint upload media/gambar produk untuk BoonTrack Core.
Mendukung:
- Optimasi dan konversi otomatis ke WebP menggunakan Pillow.
- Upload terintegrasi ke Cloudflare R2 dengan graceful fallback ke Supabase Storage dan penyimpanan lokal.
- Mendukung FastAPI (ASGI) dan aiohttp (Web Runner Railway).
- Mendukung CORS penuh dari domain https://shop.boontrack.com dan storefront lainnya.
- Path aliases: /api/v1/media/upload, /api/v1/upload, /api/upload, /api/media/upload.
"""

import os
import io
import uuid
import logging
import urllib.parse
from datetime import datetime, timezone
from io import BytesIO
from typing import Dict, Any, Optional, Union, Tuple, List
from PIL import Image

from fastapi import APIRouter, UploadFile, File, HTTPException, status, Request
from aiohttp import web

from app.core.jwt_secret import verify_jwt_token_strict

logger = logging.getLogger("MEDIA_UPLOAD_ROUTE")

media_router = APIRouter(prefix="/api/v1/media", tags=["Media Upload"])
general_upload_router = APIRouter(tags=["Media Upload Direct"])

def format_media_upload_error(exc: Exception) -> str:
    raw = str(exc)
    raw_lower = raw.lower()
    if any(k in raw_lower for k in ["eproto", "handshake failure", "ssl alert", "tls", "ssl", "endpointconnectionerror"]):
        return "Gagal mengunggah foto ke cloud storage karena kendala koneksi aman (TLS/SSL Handshake). Silakan coba beberapa saat lagi."
    if any(k in raw_lower for k in ["connection refused", "connection reset", "timed out", "timeout"]):
        return "Koneksi ke server cloud storage terputus atau timeout. Silakan periksa jaringan dan coba lagi."
    if len(raw) > 160 or "traceback" in raw_lower or "file \"" in raw_lower:
        return "Gagal memproses upload gambar. Silakan coba beberapa saat lagi."
    return f"Gagal memproses upload gambar: {raw}"

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_WIDTH = 1200
WEBP_QUALITY = 85

# Project root directory for local fallback uploads
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}

STATUS_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
STATUS_413 = getattr(status, "HTTP_413_CONTENT_TOO_LARGE", None) or getattr(status, "HTTP_413_REQUEST_ENTITY_TOO_LARGE", 413)


def validate_image_file_security(
    raw_content: bytes,
    declared_content_type: str,
    filename: str = "upload.jpg",
) -> str:
    """
    Validasi keamanan file gambar:
    - Ukuran maksimal 5MB. File kosong atau > 5MB ditolak HTTP 422 Unprocessable Entity.
    - Hanya izinkan MIME type: image/jpeg, image/png, image/webp.
    - Inspeksi biner magic-byte untuk mendeteksi MIME spoofing / executable injection.
    - Validasi integritas struktur gambar dengan Pillow.
    Mengembalikan canonical MIME type yang terdeteksi atau melempar HTTPException(422).
    """
    file_size = len(raw_content)
    if file_size == 0:
        raise HTTPException(
            status_code=STATUS_422,
            detail="File upload tidak boleh kosong.",
        )

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=STATUS_413,
            detail=f"Ukuran file ({round(file_size / (1024 * 1024), 2)} MB) melebihi batas maksimal 5 MB.",
        )

    clean_mime = (declared_content_type or "").lower().strip()
    if clean_mime == "image/jpg":
        clean_mime = "image/jpeg"

    if clean_mime not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=STATUS_422,
            detail=f"Tipe MIME '{declared_content_type}' tidak diizinkan. Hanya menerima image/jpeg, image/png, image/webp.",
        )

    # Inspeksi Magic Bytes Biner
    # JPEG: starts with FF D8 FF
    is_jpeg = raw_content.startswith(b"\xFF\xD8\xFF")
    # PNG: starts with 89 50 4E 47 0D 0A 1A 0A
    is_png = raw_content.startswith(b"\x89PNG\r\n\x1a\n")
    # WebP: starts with RIFF (offset 0..4) and has WEBP (offset 8..12)
    is_webp = (
        len(raw_content) >= 12
        and raw_content.startswith(b"RIFF")
        and raw_content[8:12] == b"WEBP"
    )

    detected_mime = None
    if is_jpeg:
        detected_mime = "image/jpeg"
    elif is_png:
        detected_mime = "image/png"
    elif is_webp:
        detected_mime = "image/webp"

    if not detected_mime:
        raise HTTPException(
            status_code=STATUS_422,
            detail="Tanda tangan biner (magic bytes) tidak sesuai dengan format gambar yang diizinkan (JPEG, PNG, WebP).",
        )

    if detected_mime != clean_mime:
        raise HTTPException(
            status_code=STATUS_422,
            detail=f"MIME spoofing terdeteksi: header menyatakan '{declared_content_type}' tetapi tanda tangan file adalah '{detected_mime}'.",
        )

    # Validasi struktur Pillow (mencegah polyglot payload / corrupt image)
    try:
        with Image.open(BytesIO(raw_content)) as img_chk:
            img_chk.verify()
    except Exception as img_err:
        raise HTTPException(
            status_code=STATUS_422,
            detail=f"Struktur file gambar korup atau tidak valid: {img_err}",
        )

    return detected_mime


def extract_raw_auth_token(request: Any) -> Optional[str]:
    """Ekstraksi token sesi mentah dari Authorization header, custom headers, atau cookies."""
    # 1. Header Authorization
    headers = getattr(request, "headers", {}) or {}
    auth_header = headers.get("Authorization") or headers.get("authorization")
    if auth_header:
        clean = auth_header.strip()
        if clean.lower().startswith("bearer "):
            return clean[7:].strip()
        return clean

    # 2. Custom session headers
    for h_name in ("X-Session-Token", "x-session-token", "X-Merchant-Token", "x-merchant-token"):
        custom_tok = headers.get(h_name)
        if custom_tok and str(custom_tok).strip():
            return str(custom_tok).strip()

    # 3. Cookies
    cookies = getattr(request, "cookies", {}) or {}
    for c_name in ("sb-access-token", "sb:token", "access_token", "session", "auth_token", "merchant_session"):
        c_val = cookies.get(c_name)
        if c_val and str(c_val).strip():
            return str(c_val).strip()

    return None



# ---------------------------------------------------------------------------
# Bounded Request & File Size Protection (CTO Security Hardening P1)
# ---------------------------------------------------------------------------
CHUNK_READ_SIZE: int = 64 * 1024  # 64 KB


async def read_bounded_upload_file(upload_file: UploadFile, max_bytes: int = MAX_FILE_SIZE) -> bytes:
    """
    Reads an UploadFile in bounded chunks.
    Aborts immediately with HTTP 413 as soon as accumulated bytes exceed max_bytes.
    Ensures the underlying file handle is closed on completion or error.
    """
    chunks = []
    total = 0
    try:
        while True:
            chunk = await upload_file.read(CHUNK_READ_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                await upload_file.close()
                raise HTTPException(
                    status_code=STATUS_413,
                    detail=f"Ukuran file melebihi batas maksimal 5 MB. Pembacaan dibatalkan untuk mencegah kelebihan memori.",
                )
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        try:
            await upload_file.close()
        except Exception:
            pass


def read_bounded_sync_file(file_obj: Any, max_bytes: int = MAX_FILE_SIZE) -> bytes:
    """Reads a sync file-like object in bounded chunks; raises ValueError if > max_bytes."""
    chunks = []
    total = 0
    try:
        while True:
            chunk = file_obj.read(CHUNK_READ_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Ukuran file melebihi batas maksimal 5 MB.")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        try:
            file_obj.close()
        except Exception:
            pass


async def read_bounded_async_field(field: Any, max_bytes: int = MAX_FILE_SIZE) -> bytes:
    """Reads an aiohttp multipart field in bounded chunks; raises ValueError if > max_bytes."""
    chunks = []
    total = 0
    while True:
        if hasattr(field, "read_chunk"):
            chunk = await field.read_chunk(CHUNK_READ_SIZE)
        else:
            chunk = await field.read(CHUNK_READ_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("Ukuran file melebihi batas maksimal 5 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# Merchant-to-Tenant Active Membership Registry & Validator (CTO P1)
# ---------------------------------------------------------------------------
_merchant_memberships: Dict[Any, Dict[str, Any]] = {}


def register_merchant_membership(
    merchant_id: str,
    tenant_id: str,
    is_active: bool = True,
    role: str = "merchant",
) -> None:
    """Registers an authoritative merchant-tenant membership relationship."""
    clean_m = str(merchant_id).strip().lower()
    clean_t = str(tenant_id).strip()
    _merchant_memberships[(clean_m, clean_t)] = {
        "merchant_id": clean_m,
        "tenant_id": clean_t,
        "is_active": is_active,
        "role": role,
    }


def revoke_merchant_membership(merchant_id: str, tenant_id: str) -> None:
    """Explicitly revokes active membership of a merchant principal in a tenant."""
    clean_m = str(merchant_id).strip().lower()
    clean_t = str(tenant_id).strip()
    if (clean_m, clean_t) in _merchant_memberships:
        _merchant_memberships[(clean_m, clean_t)]["is_active"] = False
    else:
        _merchant_memberships[(clean_m, clean_t)] = {
            "merchant_id": clean_m,
            "tenant_id": clean_t,
            "is_active": False,
        }


def clear_merchant_membership_registry() -> None:
    """Clears the in-memory merchant membership registry."""
    _merchant_memberships.clear()


def _query_db_tenant_active(tenant_id: str) -> Tuple[bool, Optional[str]]:
    """
    Queries public.tenants table to verify tenant exists and is active.
    Returns (is_active: bool, error_msg: Optional[str]).
    If error_msg is not None, lookup failed or tenant does not exist.
    """
    clean_t = str(tenant_id).strip()
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
    except Exception as exc:
        return False, f"DB_CONN_ERROR: {exc}"

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT is_active, status FROM public.tenants
                WHERE id::text = %s OR slug = %s
                LIMIT 1;
                """,
                (clean_t, clean_t),
            )
            row = cur.fetchone()
            if row is None:
                return False, "NOT_FOUND"
            is_active_val = row[0] if row[0] is not None else True
            status_val = str(row[1] or "ACTIVE").upper()
            if not is_active_val or status_val not in ("ACTIVE", "TRIAL", "PROVISIONED"):
                return False, None  # Explicitly inactive
            return True, None
    except Exception as q_err:
        return False, f"DB_QUERY_ERROR: {q_err}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _query_db_merchant_membership(merchant_id: str, tenant_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Authoritative query against cs_agents and merchants tables in PostgreSQL.
    Returns (result_dict, error_msg).
    - If result_dict is dict and error_msg is None: matching membership row found.
    - If result_dict is None and error_msg is None: cleanly executed, 0 rows found.
    - If error_msg is str: database lookup could not complete (fail-closed trigger).
    """
    clean_m = str(merchant_id).strip().lower()
    clean_t = str(tenant_id).strip()

    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
    except Exception as exc:
        return None, f"DB_CONN_ERROR: {exc}"

    cs_err = None
    merch_err = None

    try:
        with conn.cursor() as cur:
            # 1. cs_agents (tenant operational team members: owner, admin, supervisor, agent)
            try:
                cur.execute(
                    """
                    SELECT is_active, role FROM cs_agents
                    WHERE (tenant_id = %s OR tenant_id = %s)
                      AND (lower(email) = %s OR id::text = %s)
                    LIMIT 1;
                    """,
                    (clean_t, clean_t.lower(), clean_m, clean_m),
                )
                row = cur.fetchone()
                if row:
                    return {"is_active": bool(row[0]), "role": str(row[1])}, None
            except Exception as e1:
                cs_err = str(e1)
                logger.debug(f"[MEMBERSHIP_DB] cs_agents query note: {e1}")

            # 2. merchants (tenant owner)
            try:
                cur.execute(
                    """
                    SELECT status FROM merchants
                    WHERE (slug = %s OR id::text = %s)
                      AND (lower(owner_email) = %s OR id::text = %s)
                    LIMIT 1;
                    """,
                    (clean_t.lower(), clean_t, clean_m, clean_m),
                )
                m_row = cur.fetchone()
                if m_row:
                    return {"is_active": str(m_row[0]).upper() == "ACTIVE", "role": "owner"}, None
            except Exception as e2:
                merch_err = str(e2)
                logger.debug(f"[MEMBERSHIP_DB] merchants query note: {e2}")

        # If both sub-queries suffered SQL/operational errors, report DB error
        if cs_err and merch_err:
            return None, f"DB_LOOKUP_ERROR: cs_agents({cs_err}), merchants({merch_err})"

        # Both queries finished without fatal connection failure, 0 rows found
        return None, None
    except Exception as overall_err:
        return None, f"DB_ERROR: {overall_err}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def validate_merchant_tenant_membership(
    merchant_id: str,
    tenant_id: str,
    verified_claims: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Validates that the authenticated merchant principal actually possesses active
    authorized membership in the claimed tenant. Fail-closed on all paths.

    Raises:
    - HTTP 403 Forbidden if membership is inactive, revoked, or non-existent.
    - HTTP 503 Service Unavailable if database is unreachable or lookup fails.
    """
    claims = verified_claims or {}
    clean_m = str(merchant_id).strip().lower()
    clean_t = str(tenant_id).strip()

    # 1. Claim-level active flag check
    if claims.get("membership_active") is False or claims.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Status keanggotaan merchant '{merchant_id}' tidak aktif dalam klaim sesi.",
        )

    # 2. Check tenant-level active status
    # 2a. Check _test_tenants_registry (test fixture override)
    in_test_registry = False
    try:
        from app.api.deps import _test_tenants_registry
        if clean_t in _test_tenants_registry:
            in_test_registry = True
            t_data = _test_tenants_registry[clean_t]
            if not t_data.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Tenant '{clean_t}' dinonaktifkan atau tidak aktif.",
                )
    except ImportError:
        pass

    # 3. Check explicit test fixtures in _merchant_memberships registry
    # The in-memory registry may only be used as an explicit test fixture.
    if (clean_m, clean_t) in _merchant_memberships:
        mem = _merchant_memberships[(clean_m, clean_t)]
        if not mem.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Keanggotaan merchant '{merchant_id}' pada tenant '{tenant_id}' telah dicabut atau dinonaktifkan.",
            )
        return  # Explicitly active test fixture

    # If test fixtures exist for this tenant, but this merchant is not in them:
    tenant_fixtures = [m for (m, t) in _merchant_memberships.keys() if t == clean_t]
    if tenant_fixtures and clean_m not in tenant_fixtures:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Merchant principal '{merchant_id}' tidak memiliki keanggotaan aktif pada tenant '{tenant_id}'.",
        )

    # 4. Check production database: verify tenant status if not in test registry
    if not in_test_registry:
        is_active_tenant, tenant_err = _query_db_tenant_active(clean_t)
        if tenant_err is not None:
            if tenant_err == "NOT_FOUND":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Tenant '{clean_t}' tidak ditemukan di sistem.",
                )
            logger.error(f"[FAIL-CLOSED] Database tenant status lookup failed for '{clean_t}': {tenant_err}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan otorisasi database tidak tersedia (fail-closed tenant lookup).",
            )
        if not is_active_tenant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tenant '{clean_t}' dinonaktifkan atau tidak aktif.",
            )

    # 5. Check production database: verify merchant membership
    db_membership, db_err = _query_db_merchant_membership(clean_m, clean_t)

    # Database unavailable: FAIL CLOSED with HTTP 503
    if db_err is not None:
        logger.error(f"[FAIL-CLOSED] Database authorization lookup failed for {clean_m}@{clean_t}: {db_err}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan otorisasi database tidak tersedia (fail-closed).",
        )

    # No membership found: FAIL CLOSED with HTTP 403
    if db_membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Merchant principal '{merchant_id}' tidak memiliki keanggotaan aktif pada tenant '{tenant_id}'.",
        )

    # Membership row found: verify is_active flag
    if not db_membership.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Keanggotaan merchant '{merchant_id}' pada tenant '{tenant_id}' dinonaktifkan di database.",
        )


def authorize_tenant_upload(
    request: Any,
    expected_slug: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Centralized authorization guard for ALL tenant-owned upload routes.
    1. Enforces signed merchant session (HTTP 401 if missing/invalid).
    2. Validates path slug matches the verified tenant (HTTP 403 if mismatch).
    3. Validates active merchant membership (HTTP 403 if revoked/absent, HTTP 503 if DB error).
    4. Enforces subscription mutation guard (HTTP 403 if blocked).
    Returns verified session dict: {"tenant_id": ..., "merchant_id": ..., "claims": ...}.
    """
    # 1. Signed merchant session verification
    session = verify_signed_merchant_session(request)
    verified_tenant_id = session["tenant_id"]
    verified_merchant_id = session["merchant_id"]
    claims = session.get("claims", {})

    # 2. Path slug match enforcement (Anti-Cross-Tenant)
    if expected_slug:
        clean_expected = str(expected_slug).strip().lower()
        verified_slug = str(claims.get("tenant_slug") or verified_tenant_id).strip().lower()
        verified_id_lower = str(verified_tenant_id).strip().lower()
        if clean_expected not in (verified_slug, verified_id_lower):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Akses cross-tenant ditolak: path tenant '{expected_slug}' "
                    f"tidak cocok dengan session tenant '{verified_tenant_id}'."
                ),
            )

    # 3. Active membership validation (Fail-Closed)
    validate_merchant_tenant_membership(
        merchant_id=verified_merchant_id,
        tenant_id=verified_tenant_id,
        verified_claims=claims,
    )

    # 4. Subscription mutation guard (AFTER authentication & authorization)
    slug_to_check = expected_slug or claims.get("tenant_slug") or verified_tenant_id
    try:
        from app.core.subscription_guard import assert_tenant_mutation_allowed
        assert_tenant_mutation_allowed(str(slug_to_check))
    except HTTPException:
        raise
    except Exception as sub_err:
        logger.debug(f"[SUBSCRIPTION_GUARD] check note: {sub_err}")

    return session


def verify_signed_merchant_session(request: Any) -> Dict[str, Any]:
    """
    Memvalidasi sesi/token merchant yang tertandatangan kriptografis.
    Mendukung Core JWT realm dan Supabase JWT realm.
    Raises:
    - HTTP 401 Unauthorized jika token tidak ada, kedaluwarsa, atau tanda tangan tidak valid.
    """
    token = extract_raw_auth_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi merchant diperlukan: header Authorization Bearer atau token sesi tidak ditemukan.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    verified_claims = None
    resolved_realm = None

    # Realm 1: Core JWT
    try:
        verified_claims = verify_jwt_token_strict(token, realm="core")
        resolved_realm = "core"
    except Exception as core_err:
        logger.debug(f"[UPLOAD AUTH] Core realm verification rejected: {core_err}")

    # Realm 2: Supabase JWT fallback
    if not verified_claims:
        try:
            verified_claims = verify_jwt_token_strict(token, realm="supabase")
            resolved_realm = "supabase"
        except Exception as supa_err:
            logger.debug(f"[UPLOAD AUTH] Supabase realm verification rejected: {supa_err}")

    if not verified_claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sesi merchant tidak valid, telah kedaluwarsa, atau tanda tangan kriptografis gagal.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Ekstraksi identitas server-side murni
    merchant_id = (
        verified_claims.get("merchant_id")
        or verified_claims.get("sub")
        or verified_claims.get("user_id")
        or verified_claims.get("email")
    )
    if not merchant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Klaim merchant_id ('sub' atau 'merchant_id') tidak ditemukan dalam sesi tertanda.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Role Authorization (server-side claim only) ---
    # Role diekstrak dari top-level JWT claim (Core JWT) atau dari app_metadata (Supabase, server-set).
    # Jangan percayai user_metadata.role karena dapat dimanipulasi pengguna.
    _authorized_roles: frozenset = frozenset({"merchant", "owner", "admin", "staff", "supervisor"})
    role = (
        verified_claims.get("role")
        or (verified_claims.get("app_metadata") or {}).get("role")
        or ""
    ).lower().strip()
    if role not in _authorized_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Role '{role}' tidak memiliki otorisasi untuk mengakses endpoint upload merchant. "
                f"Hanya role merchant, owner, admin, supervisor, atau staff yang diizinkan."
            ),
        )

    # --- Tenant Identity (server-side only; user_metadata DILARANG) ---
    # Hierarki kepercayaan:
    # 1. top-level tenant_id  (Core JWT - diterbitkan server setelah auth terverifikasi)
    # 2. top-level tenant_slug (Core JWT)
    # 3. app_metadata.tenant_id (Supabase - server-set, tidak dapat dimanipulasi pengguna)
    # 4. app_metadata.tenant_slug (Supabase - server-set)
    # Sumber yang TIDAK diizinkan: user_metadata.* (user-editable, tidak dapat dipercaya)
    tenant_id = (
        verified_claims.get("tenant_id")
        or verified_claims.get("tenant_slug")
        or (verified_claims.get("app_metadata") or {}).get("tenant_id")
        or (verified_claims.get("app_metadata") or {}).get("tenant_slug")
    )
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Klaim tenant_id / tenant_slug tidak ditemukan dalam sesi tertanda (atau hanya tersedia di user_metadata yang tidak dipercaya).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validasi keanggotaan aktif merchant pada tenant (CTO P1)
    validate_merchant_tenant_membership(
        merchant_id=str(merchant_id).strip(),
        tenant_id=str(tenant_id).strip(),
        verified_claims=verified_claims,
    )

    return {
        "tenant_id": str(tenant_id).strip(),
        "merchant_id": str(merchant_id).strip(),
        "realm": resolved_realm,
        "claims": verified_claims,
    }


def _validate_folder_path_components(raw_folder: str, verified_tenant_id: str, label: str = "folder") -> None:
    """
    Validasi komponen path folder dengan component-safe logic (bukan string-prefix).

    Pemeriksaan:
    - Menolak absolute path (diawali '/')
    - Menolak backslash separator ('\\')
    - Menolak literal path traversal ('..')
    - Menolak URL-encoded path traversal ('%2e%2e', '%2f', dll.)
    - Jika diawali 'tenants/', memastikan komponen kedua PERSIS sama dengan verified_tenant_id
      (menolak lookalike seperti tenant-alpha-evil jika tenant adalah tenant-alpha).
    """
    clean = raw_folder.strip()

    # Reject absolute paths
    if clean.startswith("/") or clean.startswith("\\"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Percobaan path traversal terdeteksi pada {label}: absolute path tidak diizinkan.",
        )

    # Reject backslash
    if "\\" in clean:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Percobaan path traversal terdeteksi pada {label}: karakter backslash tidak diizinkan.",
        )

    # Reject URL-encoded traversal (decode and check)
    decoded = urllib.parse.unquote(clean)
    if decoded != clean:
        # URL encoding was present - always reject to prevent bypass
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Percobaan path traversal terdeteksi pada {label}: URL encoding pada path dilarang.",
        )

    # Reject literal '..'
    parts = clean.split("/")
    if ".." in parts or "." in parts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Percobaan path traversal terdeteksi pada {label}: '..' atau '.' dalam path dilarang.",
        )

    # Component-safe tenant namespace validation
    if parts and parts[0] == "tenants":
        if len(parts) < 2 or parts[1] != verified_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses cross-tenant ditolak: komponen tenant '{parts[1] if len(parts) > 1 else '(empty)'}' tidak cocok dengan session tenant '{verified_tenant_id}'.",
            )


def validate_no_cross_tenant_tampering(
    verified_tenant_id: str,
    request: Any,
    form_data: Optional[Dict[str, Any]] = None,
    folder_param: Optional[str] = None,
) -> None:
    """
    Validasi mutlak anti-cross-tenant & anti-path-traversal:
    - Jika client mengirimkan X-Tenant-ID / X-Tenant-Slug yang tidak cocok -> HTTP 403 Forbidden.
    - Jika client mengirimkan parameter tenant_id / tenant_slug yang tidak cocok -> HTTP 403 Forbidden.
    - Jika client mencoba path traversal ('..', '/', '\\') pada folder -> HTTP 403 Forbidden.
    - Jika client mencoba mengarahkan folder ke namespace tenant lain -> HTTP 403 Forbidden.
    """
    headers = getattr(request, "headers", {}) or {}

    # 1. Validasi Header Client
    h_tenant_id = headers.get("X-Tenant-ID") or headers.get("x-tenant-id")
    if h_tenant_id and str(h_tenant_id).strip() and str(h_tenant_id).strip() != verified_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Akses cross-tenant ditolak: header X-Tenant-ID '{h_tenant_id}' tidak cocok dengan session tenant '{verified_tenant_id}'.",
        )

    h_tenant_slug = headers.get("X-Tenant-Slug") or headers.get("x-tenant-slug")
    if h_tenant_slug and str(h_tenant_slug).strip() and str(h_tenant_slug).strip() != verified_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Akses cross-tenant ditolak: header X-Tenant-Slug '{h_tenant_slug}' tidak cocok dengan session tenant '{verified_tenant_id}'.",
        )

    # 2. Validasi Query Parameters
    query_params = getattr(request, "query_params", None)
    if query_params is None and hasattr(request, "query"):
        query_params = request.query
    if query_params:
        q_tenant = query_params.get("tenant_id") or query_params.get("tenant_slug")
        if q_tenant and str(q_tenant).strip() and str(q_tenant).strip() != verified_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses cross-tenant ditolak: query param tenant '{q_tenant}' tidak cocok dengan session tenant '{verified_tenant_id}'.",
            )

    # 3. Validasi Path Parameters (jika rute menyertakan /tenants/{slug})
    path_params = getattr(request, "path_params", {}) or {}
    p_slug = path_params.get("slug")
    if not p_slug and hasattr(request, "match_info"):
        p_slug = request.match_info.get("slug")
    if p_slug and str(p_slug).strip() and str(p_slug).strip() != verified_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Akses cross-tenant ditolak: path tenant '{p_slug}' tidak cocok dengan session tenant '{verified_tenant_id}'.",
        )

    # 4. Validasi Form Data
    if form_data:
        f_tenant = form_data.get("tenant_id") or form_data.get("tenant_slug") or form_data.get("tenant")
        if f_tenant and str(f_tenant).strip() and str(f_tenant).strip() != verified_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses cross-tenant ditolak: form field tenant '{f_tenant}' tidak cocok dengan session tenant '{verified_tenant_id}'.",
            )

        f_folder = form_data.get("folder")
        if f_folder and isinstance(f_folder, str):
            _validate_folder_path_components(f_folder, verified_tenant_id, label="form folder")

    # 5. Validasi folder_param langsung
    if folder_param:
        _validate_folder_path_components(folder_param, verified_tenant_id, label="folder param")


async def process_and_upload_image_bytes(
    raw_content: bytes,
    original_filename: str = "upload.jpg",
    content_type: str = "image/jpeg",
    base_url: str = "",
    folder: Optional[str] = None,
    is_qris: bool = False,
    custom_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Memvalidasi gambar (mendukung QRIS dan gambar produk), mengoptimasi:
    - QRIS: Menggunakan format PNG crisp tanpa lossy compression, komposit latar belakang putih
      (mencegah transparansi QR rusak saat dibuka di dark mode), dan disimpan ke storage path 'qris/'.
    - Gambar Umum/Produk: Mengoptimasi ke format WebP (resize max 1200px, quality 85) ke path 'media/'.
    - Mengunggah ke Cloudflare R2 (dengan fallback Supabase Storage / local assets).
    """
    file_size = len(raw_content)
    if file_size == 0:
        raise ValueError("File kosong tidak dapat diproses")

    # 1. Validasi Ukuran File (maksimal 5 MB)
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"Ukuran file melebihi batas maksimal 5 MB ({round(file_size / (1024 * 1024), 2)} MB)")

    # Deteksi QRIS
    fn_lower = (original_filename or "").lower()
    clean_mime = (content_type or "").lower().strip()
    if is_qris or folder == "qris" or "qris" in fn_lower or ("qr" in fn_lower and ("code" in fn_lower or "upload" in fn_lower or "pay" in fn_lower)):
        is_qris_mode = True
        target_folder = "qris"
    else:
        is_qris_mode = False
        target_folder = (folder or "media").strip("/ ") or "media"

    # 2. Validasi MIME Type / Ekstensi
    ext = os.path.splitext(original_filename)[1].lower()
    valid_exts = (
        ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
        ".tiff", ".svg", ".jfif", ".heic", ".heif", ".avif"
    )

    if not clean_mime.startswith("image/") and ext not in valid_exts:
        # Coba periksa apakah PIL mengenali format gambar
        try:
            test_img = Image.open(BytesIO(raw_content))
            test_img.verify()
        except Exception:
            raise ValueError(f"File tidak valid. MIME type harus berupa gambar (image/*), diterima: '{content_type}'")

    # 3. Proses Gambar dengan Pillow (PIL)
    try:
        img = Image.open(BytesIO(raw_content))
    except Exception as e:
        raise ValueError(f"Format gambar korup atau tidak dapat diproses: {str(e)}")

    original_width, original_height = img.size

    # Resize jika width > 1200px (maintain aspect ratio)
    if original_width > MAX_WIDTH:
        ratio = MAX_WIDTH / float(original_width)
        new_height = int(float(original_height) * ratio)
        new_width = MAX_WIDTH
        resample_filter = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((new_width, new_height), resample=resample_filter)
    else:
        new_width = original_width
        new_height = original_height

    # Convert mode ke RGB jika RGBA / P / LA atau mode lain
    # Khusus QRIS / barcode: Background putih solid mencegah modul QR hitam menyatu dengan dark-mode
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if "A" in img.mode:
            background.paste(img, mask=img.split()[-1])
            img = background
        else:
            img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    unique_id = uuid.uuid4().hex

    if custom_filename:
        filename = custom_filename
        fn_low = filename.lower()
        if is_qris_mode or fn_low.endswith(".png"):
            out_buffer = BytesIO()
            img.save(out_buffer, "PNG", optimize=True)
            final_bytes = out_buffer.getvalue()
            file_size_kb = round(len(final_bytes) / 1024, 2)
            out_content_type = "image/png"
        elif fn_low.endswith((".jpg", ".jpeg")):
            jpg_buffer = BytesIO()
            img.save(jpg_buffer, "JPEG", quality=WEBP_QUALITY, optimize=True)
            final_bytes = jpg_buffer.getvalue()
            file_size_kb = round(len(final_bytes) / 1024, 2)
            out_content_type = "image/jpeg"
        else:
            webp_buffer = BytesIO()
            img.save(webp_buffer, "WEBP", quality=WEBP_QUALITY, optimize=True)
            final_bytes = webp_buffer.getvalue()
            file_size_kb = round(len(final_bytes) / 1024, 2)
            out_content_type = "image/webp"
    elif is_qris_mode:
        # QRIS disimpan sebagai PNG lossless agar module barcode tidak mengalami kompresi blur
        out_buffer = BytesIO()
        img.save(out_buffer, "PNG", optimize=True)
        final_bytes = out_buffer.getvalue()
        file_size_kb = round(len(final_bytes) / 1024, 2)
        out_content_type = "image/png"
        filename = f"qris_{unique_id}.png"
    else:
        # Gambar produk standar di-export ke WebP
        webp_buffer = BytesIO()
        img.save(webp_buffer, "WEBP", quality=WEBP_QUALITY, optimize=True)
        final_bytes = webp_buffer.getvalue()
        file_size_kb = round(len(final_bytes) / 1024, 2)
        out_content_type = "image/webp"
        filename = f"img_{unique_id}.webp"

    # 4. Upload ke Cloudflare R2 (Primary Storage)
    image_url: Optional[str] = None
    try:
        from app.services.storage import upload_media_to_r2
        image_url = upload_media_to_r2(
            file_bytes=final_bytes,
            file_name=filename,
            content_type=out_content_type,
            folder=target_folder,
        )
        logger.info(f"[MEDIA UPLOAD] Sukses upload ke Cloudflare R2 ({target_folder}/): {image_url}")
    except Exception as r2_err:
        logger.warning(f"[MEDIA UPLOAD] Cloudflare R2 tidak aktif/gagal ({r2_err}), mencoba fallback storage...")

    # 5. Fallback ke Supabase Storage jika R2 belum di-set
    if not image_url:
        try:
            from app.services.whatsapp_service import get_supabase
            supabase = get_supabase()
            if supabase:
                buckets_to_try = [target_folder, "qris", "media", "product-images", "products", "public"]
                for bucket_name in buckets_to_try:
                    try:
                        storage_path = f"{target_folder}/{filename}"
                        supabase.storage.from_(bucket_name).upload(
                            path=storage_path,
                            file=final_bytes,
                            file_options={"content-type": out_content_type}
                        )
                        public_url_res = supabase.storage.from_(bucket_name).get_public_url(storage_path)
                        if public_url_res:
                            image_url = str(public_url_res)
                            logger.info(f"[MEDIA UPLOAD] Sukses upload ke Supabase Storage ({bucket_name}): {image_url}")
                            break
                    except Exception:
                        continue
        except Exception as sb_err:
            logger.debug(f"[MEDIA UPLOAD] Supabase storage fallback note: {sb_err}")

    # 6. Simpan backup lokal untuk StaticFiles /assets/uploads/{filename}
    target_upload_dir = os.path.join(UPLOAD_DIR, target_folder) if target_folder != "media" else UPLOAD_DIR
    os.makedirs(target_upload_dir, exist_ok=True)
    local_path = os.path.join(target_upload_dir, filename)
    try:
        with open(local_path, "wb") as f:
            f.write(final_bytes)
        # Jika di subfolder, simpan juga di root UPLOAD_DIR agar selalu terbaca via static mount
        if target_upload_dir != UPLOAD_DIR:
            with open(os.path.join(UPLOAD_DIR, filename), "wb") as f_root:
                f_root.write(final_bytes)
    except Exception as save_err:
        logger.error(f"[MEDIA UPLOAD] Gagal simpan backup lokal: {save_err}")

    # Fallback terakhir jika kedua cloud storage offline
    if not image_url:
        base_clean = str(base_url or "").rstrip("/")
        if base_clean:
            image_url = f"{base_clean}/assets/uploads/{filename}"
        else:
            image_url = f"/assets/uploads/{filename}"

    return {
        "status": "success",
        "url": image_url,
        "public_url": image_url,
        "secure_url": image_url,
        "image_url": image_url,
        "qris_url": image_url,
        "qris_image_url": image_url,
        "path": f"/{target_folder}/{filename}",
        "storage_path": f"{target_folder}/{filename}",
        "filename": filename,
        "folder": target_folder,
        "is_qris": is_qris_mode,
        "width": new_width,
        "height": new_height,
        "file_size_kb": file_size_kb,
        "content_type": out_content_type,
        "data": {
            "url": image_url,
            "public_url": image_url,
            "secure_url": image_url,
            "qris_url": image_url,
            "filename": filename,
            "path": f"/{target_folder}/{filename}",
            "storage_path": f"{target_folder}/{filename}",
            "folder": target_folder,
        }
    }


# ============================================================================
# FastAPI Route Handlers
# ============================================================================

async def _fastapi_handle_upload(
    request: Request,
    file: Optional[UploadFile] = None,
    image: Optional[UploadFile] = None,
    qris: Optional[UploadFile] = None,
    qris_image: Optional[UploadFile] = None,
    folder: Optional[str] = None,
    is_qris: bool = False,
    slug: Optional[str] = None,
    verified_session: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    upload_file = file or image or qris or qris_image

    # Periksa query params atau path
    path_lower = request.url.path.lower()
    query_folder = request.query_params.get("folder")
    query_type = request.query_params.get("type")
    if "qris" in path_lower or query_folder == "qris" or query_type == "qris" or qris is not None or qris_image is not None:
        is_qris = True
        folder = "qris"
    elif query_folder:
        folder = query_folder

    form_data = {}
    try:
        raw_form = await request.form()
        form_data = dict(raw_form)
        form_folder = form_data.get("folder")
        form_type = form_data.get("type")
        if form_folder == "qris" or form_type == "qris":
            is_qris = True
            folder = "qris"
        elif form_folder and not folder:
            folder = str(form_folder)

        if upload_file is None:
            for key in ("file", "image", "qris", "qris_image", "qris_file", "qr", "qr_image", "photo", "picture", "media", "upload"):
                val = form_data.get(key)
                if isinstance(val, UploadFile):
                    upload_file = val
                    if "qris" in key.lower() or "qr" in key.lower():
                        is_qris = True
                        folder = "qris"
                    break

            if upload_file is None:
                for k, val in form_data.items():
                    if isinstance(val, UploadFile):
                        upload_file = val
                        if "qris" in k.lower() or "qr" in k.lower():
                            is_qris = True
                            folder = "qris"
                        break
    except Exception:
        pass

    if upload_file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File gambar tidak ditemukan dalam request (pastikan form field bernama 'file', 'image', atau 'qris')"
        )

    # Deteksi apakah rute merupakan rute milik tenant (/tenants/{slug} atau /tenant/{slug})
    detected_slug = slug
    if not detected_slug:
        parts = [p for p in request.url.path.split("/") if p]
        if "tenants" in parts:
            idx = parts.index("tenants")
            if idx + 1 < len(parts):
                detected_slug = parts[idx + 1]
        elif "tenant" in parts:
            idx = parts.index("tenant")
            if idx + 1 < len(parts):
                detected_slug = parts[idx + 1]

    # 1. Sentralisasi Otorisasi: Rute tenant WAJIB memiliki sesi merchant tertanda dan keanggotaan aktif
    if detected_slug and verified_session is None:
        verified_session = authorize_tenant_upload(request, expected_slug=detected_slug)

    # 2. Rute Publik / Global: DILARANG menulis ke namespace tenant dan tidak boleh mengubah settings tenant
    if not detected_slug:
        if folder and ("tenants" in folder or "tenant" in folder):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses cross-tenant ditolak: endpoint upload publik dilarang menulis ke namespace tenant.",
            )

    # 3. Validasi Anti-Tampering untuk rute tenant
    if detected_slug and verified_session:
        validate_no_cross_tenant_tampering(
            verified_tenant_id=verified_session["tenant_id"],
            request=request,
            form_data=form_data,
            folder_param=folder,
        )

    # Bounded chunk read with max 5MB abort (CTO P1)
    try:
        raw_content = await read_bounded_upload_file(upload_file, max_bytes=MAX_FILE_SIZE)
    except HTTPException as he:
        if he.status_code == STATUS_413:
            # Preserve backward-compatibility for legacy /api/v1/media/upload endpoint (HTTP 400)
            if not detected_slug:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ukuran file melebihi batas maksimal 5 MB."
                )
            raise HTTPException(
                status_code=STATUS_413,
                detail="Ukuran file melebihi batas maksimal 5 MB."
            )
        raise
    base_url = str(request.base_url).rstrip("/")

    # Tenant-scoped storage path derivation
    custom_final_filename = None
    target_upload_folder = folder
    if detected_slug and verified_session:
        now = datetime.now(timezone.utc)
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")
        unique_id = uuid.uuid4().hex
        ext = "png" if is_qris else "webp"
        custom_final_filename = f"{unique_id}.{ext}"
        verified_tenant_id = verified_session["tenant_id"]
        target_upload_folder = f"tenants/{verified_tenant_id}/uploads/{year_str}/{month_str}"

    try:
        res = await process_and_upload_image_bytes(
            raw_content=raw_content,
            original_filename=upload_file.filename or ("qris.png" if is_qris else "upload.jpg"),
            content_type=upload_file.content_type or ("image/png" if is_qris else "image/jpeg"),
            base_url=base_url,
            folder=target_upload_folder,
            is_qris=is_qris,
            custom_filename=custom_final_filename,
        )

        if detected_slug and verified_session:
            verified_tenant_id = verified_session["tenant_id"]
            verified_merchant_id = verified_session["merchant_id"]
            storage_path = f"{target_upload_folder}/{custom_final_filename}"
            res["tenant_id"] = verified_tenant_id
            res["merchant_id"] = verified_merchant_id
            res["storage_path"] = storage_path
            res["path"] = f"/{storage_path}"
            res["folder"] = target_upload_folder
            res["filename"] = custom_final_filename
            if "data" in res and isinstance(res["data"], dict):
                res["data"]["tenant_id"] = verified_tenant_id
                res["data"]["merchant_id"] = verified_merchant_id
                res["data"]["storage_path"] = storage_path
                res["data"]["path"] = f"/{storage_path}"
                res["data"]["folder"] = target_upload_folder
                res["data"]["filename"] = custom_final_filename

            # Auto-sync settings HANYA untuk verified_tenant_id (anti-overwrite tenant lain)
            if is_qris and res.get("url"):
                try:
                    from app.services.onboarding_service import onboarding_service
                    onboarding_service.update_tenant_settings(verified_tenant_id, {
                        "qris_image_url": res["url"],
                        "qris_url": res["url"],
                    })
                except Exception as auto_sync_err:
                    logger.debug(f"[auto_sync_tenant_qris note]: {auto_sync_err}")

        return res
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as exc:
        logger.error(f"[FastAPI Upload Exception] {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=format_media_upload_error(exc)
        )


@media_router.post("/upload", summary="Upload and convert product/landing image to WebP")
async def upload_image(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    qris: Optional[UploadFile] = File(None),
    qris_image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    return await _fastapi_handle_upload(request, file=file, image=image, qris=qris, qris_image=qris_image)


@media_router.post("/upload/qris", summary="Upload QRIS image to R2/Storage (qris/ path)")
@media_router.post("/qris/upload", summary="Upload QRIS image alias")
async def upload_qris_image_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    qris: Optional[UploadFile] = File(None),
    qris_image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    return await _fastapi_handle_upload(request, file=file, image=image, qris=qris, qris_image=qris_image, is_qris=True, folder="qris")


# General & direct upload aliases
@general_upload_router.post(
    "/api/v1/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Hardened tenant upload endpoint with signed merchant authorization",
)
async def hardened_tenant_upload_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    qris: Optional[UploadFile] = File(None),
    qris_image: Optional[UploadFile] = File(None),
    folder: Optional[str] = None,
) -> Dict[str, Any]:
    """
    POST /api/v1/upload (Security Remediation Issue #27)
    - Validasi Sesi Merchant Tertanda (Signed Authentication): HTTP 401 jika anonim / token tidak valid.
    - Server-Derived Identity: tenant_id dan merchant_id diambil murni dari klaim sesi server-side.
    - Anti-Cross-Tenant Tampering: HTTP 403 jika client mencoba spoofing X-Tenant-ID / form tenant_id / folder path traversal.
    - File & Magic Bytes Validation: HTTP 422 jika file > 5MB, format non-gambar, atau magic bytes spoofed.
    - Tenant-Scoped Storage Namespace: tenants/{verified_tenant_id}/uploads/{YYYY}/{MM}/{uuid4}.{ext}.
    - Status Code: HTTP 201 Created.
    """
    # 1. Validasi Sesi Merchant & Keanggotaan Aktif Tenant (MANDATORY)
    session = authorize_tenant_upload(request, expected_slug=None)
    verified_tenant_id = session["tenant_id"]
    verified_merchant_id = session["merchant_id"]

    # 1b. Content-Length pre-check (before reading body into memory)
    # Reject clearly oversized requests early to prevent DoS via full-body allocation.
    # +65536 provides headroom for form field overhead beyond the binary payload.
    _cl_header = request.headers.get("content-length")
    if _cl_header:
        try:
            _cl_int = int(_cl_header)
            if _cl_int > MAX_FILE_SIZE + 65536:
                raise HTTPException(
                    status_code=413,
                    detail=f"Ukuran request ({round(_cl_int / (1024 * 1024), 2)} MB) melebihi batas maksimal yang diizinkan. Tolak sebelum membaca body.",
                )
        except ValueError:
            pass  # Malformed Content-Length - will fail at body read stage

    # 2. Ekstrak Form Data untuk Cek Spoofing & Deteksi File
    upload_file = file or image or qris or qris_image
    form_data = {}
    try:
        raw_form = await request.form()
        form_data = dict(raw_form)
        if upload_file is None:
            for key in ("file", "image", "qris", "qris_image", "qris_file", "qr", "qr_image", "photo", "picture", "media", "upload"):
                val = raw_form.get(key)
                if isinstance(val, UploadFile):
                    upload_file = val
                    break
            if upload_file is None:
                for k, v in raw_form.items():
                    if isinstance(v, UploadFile):
                        upload_file = v
                        break
    except Exception:
        pass

    # 3. Validasi Mutlak Anti Cross-Tenant & Anti-Path-Traversal
    validate_no_cross_tenant_tampering(
        verified_tenant_id=verified_tenant_id,
        request=request,
        form_data=form_data,
        folder_param=folder,
    )

    if upload_file is None:
        raise HTTPException(
            status_code=STATUS_422,
            detail="File gambar tidak ditemukan dalam request form data.",
        )

    # Bounded chunk read with max 5MB abort (CTO P1)
    raw_content = await read_bounded_upload_file(upload_file, max_bytes=MAX_FILE_SIZE)
    orig_filename = upload_file.filename or "upload.jpg"
    declared_mime = upload_file.content_type or "image/jpeg"

    # 4. Validasi Keamanan File & Magic Bytes (Max 5MB, MIME, Magic bytes, Pillow verify)
    detected_mime = validate_image_file_security(
        raw_content=raw_content,
        declared_content_type=declared_mime,
        filename=orig_filename,
    )

    # 5. Deteksi QRIS
    fn_lower = orig_filename.lower()
    form_folder = form_data.get("folder")
    form_type = form_data.get("type")
    is_qris = (
        "qris" in fn_lower
        or folder == "qris"
        or form_folder == "qris"
        or form_type == "qris"
        or qris is not None
        or qris_image is not None
    )

    # 6. Tenant-Scoped Storage Namespace:
    # tenants/{verified_tenant_id}/uploads/{YYYY}/{MM}/{uuid4}.{ext}
    now = datetime.now(timezone.utc)
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")
    unique_id = uuid.uuid4().hex

    if is_qris:
        ext = "png"
    else:
        ext = "webp"

    final_filename = f"{unique_id}.{ext}"
    storage_folder = f"tenants/{verified_tenant_id}/uploads/{year_str}/{month_str}"
    storage_path = f"{storage_folder}/{final_filename}"
    base_url = str(request.base_url).rstrip("/")

    res = await process_and_upload_image_bytes(
        raw_content=raw_content,
        original_filename=orig_filename,
        content_type=detected_mime,
        base_url=base_url,
        folder=storage_folder,
        is_qris=is_qris,
        custom_filename=final_filename,
    )

    # 7. Bind Identitas & Metadata Namespace
    res["tenant_id"] = verified_tenant_id
    res["merchant_id"] = verified_merchant_id
    res["storage_path"] = storage_path
    res["path"] = f"/{storage_path}"
    res["folder"] = storage_folder
    res["filename"] = final_filename
    if "data" in res and isinstance(res["data"], dict):
        res["data"]["tenant_id"] = verified_tenant_id
        res["data"]["merchant_id"] = verified_merchant_id
        res["data"]["storage_path"] = storage_path
        res["data"]["path"] = f"/{storage_path}"
        res["data"]["folder"] = storage_folder
        res["data"]["filename"] = final_filename

    return res


@general_upload_router.post("/api/upload", summary="Direct upload endpoint")
@general_upload_router.post("/api/media/upload", summary="Direct media upload endpoint")
@general_upload_router.post("/api/v1/products/upload-image", summary="Products image upload endpoint")
@general_upload_router.post("/api/v1/product/upload-image", summary="Product image upload endpoint singular")
@general_upload_router.post("/api/v1/qris/upload", summary="Direct v1 QRIS upload endpoint")
@general_upload_router.post("/api/v1/upload/qris", summary="Direct v1 QRIS upload alias")
@general_upload_router.post("/api/v1/media/upload/qris", summary="Media QRIS upload alias")
@general_upload_router.post("/api/qris/upload", summary="Legacy QRIS upload alias")
@general_upload_router.post("/api/v1/tenants/{slug}/qris/upload", summary="Tenant specific QRIS upload")
@general_upload_router.post("/api/v1/tenants/{slug}/upload-qris", summary="Tenant specific QRIS upload alias")
@general_upload_router.post("/api/v1/tenants/{slug}/upload", summary="Tenant specific general upload")
@general_upload_router.post("/api/v1/tenant/{slug}/qris/upload", summary="Tenant singular QRIS upload")
@general_upload_router.post("/api/v1/tenant/{slug}/upload", summary="Tenant singular general upload")
async def general_upload_endpoint(
    request: Request,
    slug: Optional[str] = None,
    file: Optional[UploadFile] = File(None),
    image: Optional[UploadFile] = File(None),
    qris: Optional[UploadFile] = File(None),
    qris_image: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    # Extract slug ONLY from URL path segments for tenant-specific routes
    parts = [p for p in request.url.path.split("/") if p]
    extracted_slug = None
    if "tenants" in parts:
        idx = parts.index("tenants")
        if idx + 1 < len(parts):
            extracted_slug = parts[idx + 1]
    elif "tenant" in parts:
        idx = parts.index("tenant")
        if idx + 1 < len(parts):
            extracted_slug = parts[idx + 1]

    verified_session = None
    if extracted_slug:
        # Tenant-owned route: MUST enforce signed merchant authorization matching slug!
        verified_session = authorize_tenant_upload(request, expected_slug=extracted_slug)

    return await _fastapi_handle_upload(
        request,
        file=file,
        image=image,
        qris=qris,
        qris_image=qris_image,
        slug=extracted_slug,
        verified_session=verified_session,
    )


# ============================================================================
# aiohttp Route Handlers & Registrar (Runner Aktif Server Railway)
# ============================================================================

def _build_cors_headers(request: web.Request) -> Dict[str, str]:
    origin = request.headers.get("Origin", "*")
    req_headers = request.headers.get("Access-Control-Request-Headers", "*")
    return {
        "Access-Control-Allow-Origin": origin if origin != "*" else "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT, DELETE, PATCH",
        "Access-Control-Allow-Headers": req_headers if req_headers != "*" else "Content-Type, Authorization, X-Requested-With, apikey, Accept, Origin",
    }


async def aiohttp_upload_image(request: web.Request) -> web.Response:
    """Handler upload gambar multipart untuk aiohttp server pada Railway."""
    cors_headers = _build_cors_headers(request)

    req_slug = request.match_info.get("slug")
    if not req_slug:
        parts = [p for p in request.path.split("/") if p]
        if "tenants" in parts:
            idx = parts.index("tenants")
            if idx + 1 < len(parts):
                req_slug = parts[idx + 1]
        elif "tenant" in parts:
            idx = parts.index("tenant")
            if idx + 1 < len(parts):
                req_slug = parts[idx + 1]

    is_hardened_route = request.path.rstrip("/") == "/api/v1/upload"
    is_tenant_route = is_hardened_route or bool(req_slug)
    verified_tenant_id = None
    verified_merchant_id = None
    verified_session = None

    if is_tenant_route:
        try:
            verified_session = authorize_tenant_upload(request, expected_slug=req_slug)
            verified_tenant_id = verified_session["tenant_id"]
            verified_merchant_id = verified_session["merchant_id"]
        except HTTPException as auth_exc:
            return web.json_response(
                {"status": "error", "detail": auth_exc.detail},
                status=auth_exc.status_code,
                headers=cors_headers,
            )

    # Content-Length pre-check for aiohttp (before reading body)
    if is_tenant_route:
        _aio_cl = request.content_length
        if _aio_cl is not None and _aio_cl > MAX_FILE_SIZE + 65536:
            return web.json_response(
                {"status": "error", "detail": f"Ukuran request ({round(_aio_cl / (1024 * 1024), 2)} MB) melebihi batas maksimal yang diizinkan."},
                status=413,
                headers=cors_headers,
            )

    raw_content: Optional[bytes] = None
    content_type: str = "image/jpeg"
    filename: str = "upload.jpg"
    folder: Optional[str] = request.query.get("folder")
    type_param: Optional[str] = request.query.get("type")
    path_lower = request.path.lower()
    is_qris = "qris" in path_lower or folder == "qris" or type_param == "qris"
    post_data = None

    # 1. Chunked streaming handling: stream directly via request.multipart() when Content-Length is missing
    is_chunked = request.headers.get("Transfer-Encoding", "").lower() == "chunked" or request.content_length is None
    if is_chunked and request.content_type == "multipart/form-data":
        try:
            reader = await request.multipart()
            field = await reader.next()
            while field is not None:
                field_name = getattr(field, "name", "")
                if field_name == "folder" and not folder:
                    folder = await field.text()
                elif hasattr(field, "filename") and field.filename:
                    if is_tenant_route:
                        try:
                            raw_content = await read_bounded_async_field(field, max_bytes=MAX_FILE_SIZE)
                        except ValueError as ve:
                            return web.json_response(
                                {"status": "error", "detail": str(ve)},
                                status=413,
                                headers=cors_headers,
                            )
                    else:
                        raw_content = await field.read()
                    filename = field.filename
                    content_type = field.headers.get("Content-Type", "image/jpeg")
                    if "qris" in str(field_name).lower() or "qr" in str(field_name).lower():
                        is_qris = True
                        folder = "qris"
                    break
                field = await reader.next()
        except web.HTTPRequestEntityTooLarge as multi_large_err:
            return web.json_response(
                {"status": "error", "detail": f"Ukuran request melebihi batas maksimal yang diizinkan: {multi_large_err}"},
                status=413,
                headers=cors_headers,
            )
        except Exception as multi_err:
            logger.debug(f"[aiohttp_upload_image chunked multipart note]: {multi_err}")

    # 2. Coba ekstrak via request.post() jika belum mendapatkan file
    if raw_content is None:
        try:
            post_data = await request.post()
            if post_data.get("folder") == "qris" or post_data.get("type") == "qris":
                is_qris = True
                folder = "qris"
            elif post_data.get("folder") and not folder:
                folder = str(post_data.get("folder"))

            for key in ("file", "image", "qris", "qris_image", "qris_file", "qr", "qr_image", "photo", "picture", "media", "upload"):
                field = post_data.get(key)
                if field and hasattr(field, "file"):
                    if is_tenant_route:
                        try:
                            raw_content = read_bounded_sync_file(field.file, max_bytes=MAX_FILE_SIZE)
                        except ValueError as ve:
                            return web.json_response(
                                {"status": "error", "detail": str(ve)},
                                status=413,
                                headers=cors_headers,
                            )
                    else:
                        raw_content = field.file.read()
                    filename = getattr(field, "filename", "upload.jpg") or "upload.jpg"
                    content_type = getattr(field, "content_type", "image/jpeg") or "image/jpeg"
                    if "qris" in key or "qr" in key:
                        is_qris = True
                        folder = "qris"
                    break

            if raw_content is None:
                for k, v in post_data.items():
                    if v and hasattr(v, "file"):
                        if is_tenant_route:
                            try:
                                raw_content = read_bounded_sync_file(v.file, max_bytes=MAX_FILE_SIZE)
                            except ValueError as ve:
                                return web.json_response(
                                    {"status": "error", "detail": str(ve)},
                                    status=413,
                                    headers=cors_headers,
                                )
                        else:
                            raw_content = v.file.read()
                        filename = getattr(v, "filename", "upload.jpg") or "upload.jpg"
                        content_type = getattr(v, "content_type", "image/jpeg") or "image/jpeg"
                        if "qris" in str(k).lower() or "qr" in str(k).lower():
                            is_qris = True
                            folder = "qris"
                        break
        except web.HTTPRequestEntityTooLarge as too_large_err:
            return web.json_response(
                {"status": "error", "detail": f"Ukuran request melebihi batas maksimal yang diizinkan: {too_large_err}"},
                status=413,
                headers=cors_headers,
            )
        except web.HTTPException as web_exc:
            if getattr(web_exc, "status", getattr(web_exc, "status_code", 0)) == 413:
                return web.json_response(
                    {"status": "error", "detail": f"Ukuran request melebihi batas maksimal yang diizinkan: {web_exc}"},
                    status=413,
                    headers=cors_headers,
                )
            logger.debug(f"[aiohttp_upload_image post extract web_exc]: {web_exc}")
        except Exception as post_err:
            logger.debug(f"[aiohttp_upload_image post extract note]: {post_err}")

    # 2. Coba ekstrak via request.multipart() jika post_data belum mendapatkan file
    if raw_content is None:
        try:
            reader = await request.multipart()
            field = await reader.next()
            while field is not None:
                if hasattr(field, "filename") and field.filename:
                    if is_tenant_route:
                        try:
                            raw_content = await read_bounded_async_field(field, max_bytes=MAX_FILE_SIZE)
                        except ValueError as ve:
                            return web.json_response(
                                {"status": "error", "detail": str(ve)},
                                status=413,
                                headers=cors_headers,
                            )
                    else:
                        raw_content = await field.read()
                    filename = field.filename
                    content_type = field.headers.get("Content-Type", "image/jpeg")
                    field_name = getattr(field, "name", "")
                    if "qris" in str(field_name).lower() or "qr" in str(field_name).lower():
                        is_qris = True
                        folder = "qris"
                    break
                field = await reader.next()
        except web.HTTPRequestEntityTooLarge as multi_large_err:
            return web.json_response(
                {"status": "error", "detail": f"Ukuran request melebihi batas maksimal yang diizinkan: {multi_large_err}"},
                status=413,
                headers=cors_headers,
            )
        except Exception as multi_err:
            logger.debug(f"[aiohttp_upload_image multipart extract note]: {multi_err}")

    if not is_tenant_route and folder and ("tenants" in folder or "tenant" in folder):
        return web.json_response(
            {"status": "error", "detail": "Akses cross-tenant ditolak: endpoint publik dilarang menulis ke namespace tenant."},
            status=403,
            headers=cors_headers,
        )

    if is_tenant_route:
        # Cek anti cross-tenant tampering
        try:
            validate_no_cross_tenant_tampering(
                verified_tenant_id=verified_tenant_id,
                request=request,
                form_data=dict(post_data) if post_data is not None else None,
                folder_param=folder,
            )
        except HTTPException as ct_exc:
            return web.json_response(
                {"status": "error", "detail": ct_exc.detail},
                status=ct_exc.status_code,
                headers=cors_headers,
            )

    if raw_content is None:
        err_status = 422 if is_tenant_route else 400
        return web.json_response(
            {"status": "error", "detail": "File gambar tidak ditemukan dalam form data (gunakan field 'file', 'image', atau 'qris')"},
            status=err_status,
            headers=cors_headers
        )

    base_url = f"{request.scheme}://{request.host}"

    custom_final_filename = None
    target_folder = folder

    if is_tenant_route:
        try:
            detected_mime = validate_image_file_security(
                raw_content=raw_content,
                declared_content_type=content_type,
                filename=filename,
            )
            content_type = detected_mime
        except HTTPException as val_exc:
            return web.json_response(
                {"status": "error", "detail": val_exc.detail},
                status=val_exc.status_code,
                headers=cors_headers,
            )

        now = datetime.now(timezone.utc)
        year_str = now.strftime("%Y")
        month_str = now.strftime("%m")
        unique_id = uuid.uuid4().hex

        if is_qris:
            ext = "png"
        else:
            ext = "webp"

        custom_final_filename = f"{unique_id}.{ext}"
        target_folder = f"tenants/{verified_tenant_id}/uploads/{year_str}/{month_str}"

    try:
        res = await process_and_upload_image_bytes(
            raw_content=raw_content,
            original_filename=filename,
            content_type=content_type,
            base_url=base_url,
            folder=target_folder,
            is_qris=is_qris,
            custom_filename=custom_final_filename,
        )

        if is_tenant_route:
            storage_path = f"{target_folder}/{custom_final_filename}"
            res["tenant_id"] = verified_tenant_id
            res["merchant_id"] = verified_merchant_id
            res["storage_path"] = storage_path
            res["path"] = f"/{storage_path}"
            res["folder"] = target_folder
            res["filename"] = custom_final_filename
            if "data" in res and isinstance(res["data"], dict):
                res["data"]["tenant_id"] = verified_tenant_id
                res["data"]["merchant_id"] = verified_merchant_id
                res["data"]["storage_path"] = storage_path
                res["data"]["path"] = f"/{storage_path}"
                res["data"]["folder"] = target_folder
                res["data"]["filename"] = custom_final_filename

        # Jika rute milik tenant, sinkronkan otomatis ke settings HANYA untuk verified_tenant_id
        if is_tenant_route and is_qris and res.get("url"):
            try:
                from app.services.onboarding_service import onboarding_service
                onboarding_service.update_tenant_settings(verified_tenant_id, {
                    "qris_image_url": res["url"],
                    "qris_url": res["url"],
                })
            except Exception as auto_sync_err:
                logger.debug(f"[auto_sync_tenant_qris note]: {auto_sync_err}")

        resp_status = 201 if is_tenant_route else 200
        return web.json_response(res, status=resp_status, headers=cors_headers)
    except ValueError as ve:
        err_code = 422 if is_hardened_route else 400
        return web.json_response(
            {"status": "error", "detail": str(ve)},
            status=err_code,
            headers=cors_headers
        )
    except Exception as exc:
        logger.error(f"[aiohttp_upload_image Exception] {exc}", exc_info=True)
        return web.json_response(
            {"status": "error", "detail": format_media_upload_error(exc)},
            status=500,
            headers=cors_headers
        )


async def aiohttp_options_upload(request: web.Request) -> web.Response:
    """Preflight OPTIONS handler untuk upload gambar dari domain storefront."""
    cors_headers = _build_cors_headers(request)
    return web.Response(status=200, headers=cors_headers)


def register_media_routes(app: web.Application):
    """Mendaftarkan seluruh endpoint upload media dan OPTIONS handler ke aiohttp web.Application."""
    upload_paths = [
        "/api/v1/media/upload",
        "/api/v1/upload",
        "/api/media/upload",
        "/api/upload",
        "/api/v1/products/upload-image",
        "/api/v1/product/upload-image",
        "/api/v1/qris/upload",
        "/api/v1/upload/qris",
        "/api/v1/media/upload/qris",
        "/api/qris/upload",
        "/api/v1/tenants/{slug}/qris/upload",
        "/api/v1/tenants/{slug}/upload-qris",
        "/api/v1/tenants/{slug}/upload",
        "/api/v1/tenant/{slug}/qris/upload",
        "/api/v1/tenant/{slug}/upload",
    ]
    existing_routes = set()
    for r in app.router.routes():
        try:
            canonical = getattr(getattr(r, "resource", None), "canonical", None)
            method = getattr(r, "method", None)
            if canonical and method:
                existing_routes.add((method.upper(), canonical.rstrip("/")))
        except Exception:
            pass

    for path in upload_paths:
        norm_path = path.rstrip("/")
        if ("POST", norm_path) not in existing_routes:
            app.router.add_post(path, aiohttp_upload_image)
        if ("OPTIONS", norm_path) not in existing_routes:
            app.router.add_options(path, aiohttp_options_upload)

    logger.info(f"[ROUTER] Media & QRIS upload routes ({len(upload_paths)} paths) registered to aiohttp.")
