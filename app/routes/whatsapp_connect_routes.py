"""
app/routes/whatsapp_connect_routes.py
---------------------------------------
Self-Service WABA Connection (Manual Token Setup).

Endpoint:
  POST /api/v1/whatsapp/connect-manual
    - Verify credentials via Meta Graph API handshake.
    - Auto-subscribe webhook app to WABA.
    - Upsert connection record to `whatsapp_connections` table in Supabase.
    - Invalidate WhatsApp credentials cache immediately.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

# Module-level imports for easy patching in tests
from app.services.whatsapp.credentials import get_supabase, clear_wa_credentials_cache

logger = logging.getLogger("WHATSAPP_CONNECT_ROUTES")

whatsapp_connect_router = APIRouter(
    prefix="/api/v1/whatsapp",
    tags=["WhatsApp Self-Service Connection"],
)

_META_GRAPH_VERSION = "v26.0"
_META_GRAPH_BASE = f"https://graph.facebook.com/{_META_GRAPH_VERSION}"


# ============================================================================
# REQUEST / RESPONSE SCHEMAS
# ============================================================================

class WABAManualConnectRequest(BaseModel):
    """Request body untuk koneksi WABA manual via permanent access token."""

    tenant_id: str = Field(..., description="Tenant UUID atau slug (wajib)")
    tenant_slug: Optional[str] = Field(None, description="Tenant slug (opsional; fallback ke tenant_id)")
    phone_number_id: str = Field(..., description="Meta WABA Phone Number ID")
    waba_id: str = Field(..., description="Meta WABA (WhatsApp Business Account) ID")
    access_token: str = Field(..., description="Meta Permanent System User Access Token")


class WABAManualConnectResponse(BaseModel):
    """Response sukses setelah koneksi WABA berhasil."""

    status: str
    message: str
    tenant_id: str
    tenant_slug: str
    phone_number_id: str
    waba_id: str
    verified_name: Optional[str] = None
    display_phone_number: Optional[str] = None
    quality_rating: Optional[str] = None
    connection_id: Optional[str] = None
    subscribe_result: Optional[str] = None


# ============================================================================
# HELPER: META GRAPH API CALLS
# ============================================================================

async def _verify_meta_phone_number(
    phone_number_id: str,
    access_token: str,
    client: httpx.AsyncClient,
) -> dict:
    """
    Verifikasi Phone Number ID dan token via Meta Graph API.
    Returns dict: {verified_name, display_phone_number, quality_rating}
    Raises HTTPException 400 jika verifikasi gagal.
    """
    url = (
        f"{_META_GRAPH_BASE}/{phone_number_id}"
        f"?fields=verified_name,display_phone_number,quality_rating"
        f"&access_token={access_token}"
    )
    try:
        resp = await client.get(url, timeout=20.0)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Gagal menghubungi Meta Graph API: {exc}",
        )

    if resp.status_code != 200:
        try:
            err_body = resp.json()
        except Exception:
            err_body = {"raw": resp.text}
        logger.warning(
            f"[WABA Connect] Handshake gagal: phone_number_id={phone_number_id} "
            f"status={resp.status_code} body={resp.text[:300]}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Verifikasi Meta Graph API gagal. Pastikan phone_number_id dan access_token valid.",
                "meta_error": err_body,
                "meta_status_code": resp.status_code,
            },
        )

    data = resp.json()
    logger.info(
        f"[WABA Connect] Handshake OK: phone_number_id={phone_number_id} "
        f"verified_name={data.get('verified_name')}"
    )
    return {
        "verified_name": data.get("verified_name"),
        "display_phone_number": data.get("display_phone_number"),
        "quality_rating": data.get("quality_rating"),
    }


async def _subscribe_app_to_waba(
    waba_id: str,
    access_token: str,
    client: httpx.AsyncClient,
) -> str:
    """
    Daftarkan aplikasi Meta ke WABA subscription agar webhook bisa menerima events.
    Mengembalikan string status (tidak menggagalkan proses utama jika sudah subscribe).
    """
    url = f"{_META_GRAPH_BASE}/{waba_id}/subscribed_apps"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        resp = await client.post(url, headers=headers, timeout=20.0)
        if resp.status_code in (200, 201):
            data = resp.json()
            if data.get("success"):
                logger.info(f"[WABA Connect] App subscribe berhasil untuk waba_id={waba_id}")
                return "subscribed"
            else:
                logger.info(f"[WABA Connect] App subscribe response: {data}")
                return f"responded: {data}"
        else:
            logger.warning(
                f"[WABA Connect] App subscribe warning waba_id={waba_id} "
                f"status={resp.status_code} body={resp.text[:200]}"
            )
            return f"warning:{resp.status_code}"
    except Exception as exc:
        logger.warning(f"[WABA Connect] App subscribe exception waba_id={waba_id}: {exc}")
        return f"error:{exc}"


def _upsert_whatsapp_connection(
    *,
    tenant_id: str,
    tenant_slug: str,
    phone_number_id: str,
    waba_id: str,
    access_token: str,
    display_phone_number: Optional[str],
    verified_name: Optional[str],
    quality_rating: Optional[str],
) -> Optional[str]:
    """
    Upsert baris ke tabel `whatsapp_connections` via Supabase.
    Jika sudah ada record dengan phone_number_id yang sama, update record tersebut.
    Returns connection_id (UUID) dari row yang berhasil di-upsert.
    """
    try:
        sb = get_supabase()
        if not sb:
            logger.error("[WABA Connect] Supabase client tidak tersedia.")
            return None
    except Exception as exc:
        logger.error(f"[WABA Connect] Gagal inisialisasi Supabase: {exc}")
        return None

    now_iso = datetime.now(timezone.utc).isoformat()

    record = {
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "phone_number_id": phone_number_id,
        "phone_number": display_phone_number or "",
        "api_key": access_token,
        "status": "active",
        "is_connected": True,
        "provider": "meta",
        "channel_type": "waba",
        "waba_id": waba_id,
        "ownership_domain": "TENANT",
        "purpose": "COMMERCE",
        "metadata": {
            "waba_id": waba_id,
            "verified_name": verified_name or "",
            "quality_rating": quality_rating or "",
            "token": access_token,
            "connected_via": "self_service_manual",
            "connected_at": now_iso,
        },
        "updated_at": now_iso,
    }

    try:
        # Cek apakah sudah ada record dengan phone_number_id yang sama
        existing = (
            sb.table("whatsapp_connections")
            .select("id")
            .eq("phone_number_id", phone_number_id)
            .execute()
        )

        if existing and existing.data:
            connection_id = existing.data[0]["id"]
            sb.table("whatsapp_connections").update(record).eq("id", connection_id).execute()
            logger.info(
                f"[WABA Connect] Berhasil UPDATE whatsapp_connections id={connection_id} "
                f"phone_number_id={phone_number_id}"
            )
        else:
            record["created_at"] = now_iso
            res = sb.table("whatsapp_connections").insert(record).execute()
            connection_id = res.data[0]["id"] if res.data else None
            logger.info(
                f"[WABA Connect] Berhasil INSERT whatsapp_connections id={connection_id} "
                f"phone_number_id={phone_number_id}"
            )

        return connection_id

    except Exception as exc:
        logger.error(f"[WABA Connect] Upsert whatsapp_connections gagal: {exc}", exc_info=True)
        return None


# ============================================================================
# ENDPOINT: POST /api/v1/whatsapp/connect-manual
# ============================================================================

@whatsapp_connect_router.post(
    "/connect-manual",
    response_model=WABAManualConnectResponse,
    status_code=status.HTTP_200_OK,
    summary="Self-Service WABA Connection (Manual Token Setup)",
    description=(
        "Menghubungkan nomor WhatsApp Business Account (WABA) ke tenant secara manual "
        "menggunakan Permanent System User Access Token. Endpoint ini akan: "
        "(1) Memverifikasi kredensial ke Meta Graph API, "
        "(2) Mendaftarkan app ke WABA subscription, "
        "(3) Menyimpan koneksi ke database Supabase (`whatsapp_connections`), "
        "(4) Langsung mengaktifkan kredensial baru tanpa restart server."
    ),
)
async def connect_waba_manual(payload: WABAManualConnectRequest) -> WABAManualConnectResponse:
    """
    POST /api/v1/whatsapp/connect-manual

    Alur:
    1. Handshake verifikasi ke Meta Graph API (GET /{phone_number_id}?fields=...).
    2. Auto-subscribe webhook app ke WABA (POST /{waba_id}/subscribed_apps).
    3. Upsert record ke tabel `whatsapp_connections` di Supabase.
    4. Clear WhatsApp credentials cache agar token baru aktif seketika.
    """
    clean_tenant_id = str(payload.tenant_id).strip()
    clean_tenant_slug = str(payload.tenant_slug or payload.tenant_id).strip().lower()
    clean_phone_id = str(payload.phone_number_id).strip()
    clean_waba_id = str(payload.waba_id).strip()
    clean_token = str(payload.access_token).strip()

    if not clean_phone_id or not clean_waba_id or not clean_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone_number_id, waba_id, dan access_token tidak boleh kosong.",
        )

    async with httpx.AsyncClient(timeout=25.0) as client:
        # ------------------------------------------------------------------
        # Step 1: Handshake Verifikasi Meta
        # ------------------------------------------------------------------
        meta_info = await _verify_meta_phone_number(
            phone_number_id=clean_phone_id,
            access_token=clean_token,
            client=client,
        )
        verified_name = meta_info.get("verified_name")
        display_phone_number = meta_info.get("display_phone_number")
        quality_rating = meta_info.get("quality_rating")

        # ------------------------------------------------------------------
        # Step 2: Auto-Subscribe Webhook App
        # ------------------------------------------------------------------
        subscribe_result = await _subscribe_app_to_waba(
            waba_id=clean_waba_id,
            access_token=clean_token,
            client=client,
        )

    # ------------------------------------------------------------------
    # Step 3: Upsert ke Supabase `whatsapp_connections`
    # ------------------------------------------------------------------
    connection_id = _upsert_whatsapp_connection(
        tenant_id=clean_tenant_id,
        tenant_slug=clean_tenant_slug,
        phone_number_id=clean_phone_id,
        waba_id=clean_waba_id,
        access_token=clean_token,
        display_phone_number=display_phone_number,
        verified_name=verified_name,
        quality_rating=quality_rating,
    )

    if connection_id is None:
        logger.error(
            f"[WABA Connect] Upsert ke database gagal untuk tenant={clean_tenant_slug} "
            f"phone_number_id={clean_phone_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Verifikasi Meta berhasil, namun gagal menyimpan koneksi ke database. "
                "Periksa koneksi Supabase atau log server."
            ),
        )

    # ------------------------------------------------------------------
    # Step 4: Invalidate credentials cache
    # ------------------------------------------------------------------
    try:
        clear_wa_credentials_cache()
        logger.info("[WABA Connect] WhatsApp credentials cache berhasil di-clear.")
    except Exception as exc:
        logger.warning(f"[WABA Connect] Gagal clear credentials cache: {exc}")

    logger.info(
        f"[WABA Connect] Koneksi WABA berhasil: tenant={clean_tenant_slug} "
        f"phone_number_id={clean_phone_id} waba_id={clean_waba_id} "
        f"verified_name={verified_name} connection_id={connection_id}"
    )

    return WABAManualConnectResponse(
        status="connected",
        message=(
            f"WABA berhasil dihubungkan ke tenant '{clean_tenant_slug}'. "
            f"Nomor '{display_phone_number or clean_phone_id}' ({verified_name}) kini aktif."
        ),
        tenant_id=clean_tenant_id,
        tenant_slug=clean_tenant_slug,
        phone_number_id=clean_phone_id,
        waba_id=clean_waba_id,
        verified_name=verified_name,
        display_phone_number=display_phone_number,
        quality_rating=quality_rating,
        connection_id=connection_id,
        subscribe_result=subscribe_result,
    )
