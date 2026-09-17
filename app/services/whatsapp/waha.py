"""
app/services/whatsapp/waha.py
--------------------------------------
WAHA (WhatsApp HTTP API) adapter - pairing code via WAHA server.
"""
import asyncio
import os
import logging
from typing import Dict, Any

import httpx

from app.services.whatsapp.credentials import normalize_phone_number

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

WAHA_URL = (
    os.getenv("WAHA_URL")
    or os.getenv("WAHA_BASE_URL")
    or os.getenv("WHATSAPP_GATEWAY_URL")
    or "http://localhost:3000"
).rstrip("/")

WAHA_API_KEY = (
    os.getenv("WAHA_API_KEY")
    or os.getenv("WHATSAPP_API_KEY")
    or ""
)


def get_waha_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if WAHA_API_KEY:
        headers["X-Api-Key"] = WAHA_API_KEY
    return headers


async def request_waha_pairing_code(tenant_slug: str, phone: str) -> Dict[str, Any]:
    """
    Mengambil kode pairing resmi WhatsApp dari WAHA API:
    1. Pastikan session WAHA dalam status 'SCAN_QR_CODE'.
       Jika session stopped/failed, panggil POST /api/sessions/{session}/start.
    2. Tembak endpoint resmi WAHA:
       POST {WAHA_URL}/api/{clean_session}/auth/request-code
       Header: Content-Type: application/json, X-Api-Key: {WAHA_API_KEY}
       Body: {"phoneNumber": clean_phone}
    3. Parsing respons resmi WAHA: WAHA akan mengembalikan JSON {"code": "ABCD-1234"}.
       Kembalikan kode asli tersebut ke frontend.
    4. Tanpa silent fallback acak. Jika error, kembalikan status error aslinya.
    """
    clean_tenant = (tenant_slug or "default").strip()
    clean_phone = normalize_phone_number(phone)
    if not clean_phone:
        return {
            "success": False,
            "error": "Nomor WhatsApp tidak valid. Masukkan nomor dengan format internasional (awali 62).",
            "detail": "Nomor WhatsApp kosong atau tidak valid."
        }

    clean_session = clean_tenant.replace("tenant_", "")
    headers = get_waha_headers()

    async with httpx.AsyncClient(timeout=25.0) as client:
        target_session = clean_session
        session_data = None

        try:
            # 1. Cek session di WAHA
            status_res = await client.get(f"{WAHA_URL}/api/sessions/{target_session}", headers=headers)
            if status_res.status_code == 200:
                session_data = status_res.json()
            elif status_res.status_code == 404:
                # Coba dengan prefix tenant_
                alt_session = f"tenant_{clean_session.replace('-', '_')}"
                alt_res = await client.get(f"{WAHA_URL}/api/sessions/{alt_session}", headers=headers)
                if alt_res.status_code == 200:
                    target_session = alt_session
                    session_data = alt_res.json()
                else:
                    # Cek session default
                    def_res = await client.get(f"{WAHA_URL}/api/sessions/default", headers=headers)
                    if def_res.status_code == 200:
                        target_session = "default"
                        session_data = def_res.json()
                    else:
                        # Buat session baru di WAHA
                        create_res = await client.post(
                            f"{WAHA_URL}/api/sessions",
                            headers=headers,
                            json={"name": target_session, "start": True}
                        )
                        if create_res.status_code in (200, 201):
                            session_data = create_res.json()
                        else:
                            logger.warning(f"[WAHA] Buat session {target_session} response: {create_res.text}")
        except Exception as conn_err:
            logger.error(f"[WAHA] Gagal menghubungi WAHA di {WAHA_URL}: {conn_err}")
            return {
                "success": False,
                "error": f"Tidak dapat terhubung ke server WAHA di {WAHA_URL}: {str(conn_err)}",
                "detail": str(conn_err)
            }

        # 2. Cek status session
        current_status = (session_data.get("status") if isinstance(session_data, dict) else "") or ""

        # Jika session STOPPED atau FAILED, panggil POST /api/sessions/{session}/start
        if current_status in ("STOPPED", "FAILED"):
            logger.info(f"[WAHA] Session {target_session} status: {current_status}. Memulai session...")
            try:
                start_res = await client.post(f"{WAHA_URL}/api/sessions/{target_session}/start", headers=headers)
                if start_res.status_code in (200, 201):
                    current_status = "STARTING"
            except Exception as start_err:
                logger.warning(f"[WAHA] Start session {target_session} error: {start_err}")

        # Polling singkat jika session masih dalam proses STARTING/INITIALIZING
        if current_status in ("STARTING", "INITIALIZING", ""):
            for _ in range(6):
                await asyncio.sleep(1.0)
                try:
                    chk_res = await client.get(f"{WAHA_URL}/api/sessions/{target_session}", headers=headers)
                    if chk_res.status_code == 200:
                        current_status = chk_res.json().get("status", "")
                        if current_status in ("SCAN_QR_CODE", "WORKING"):
                            break
                except Exception:
                    pass

        # Jika sudah terhubung aktif
        if current_status == "WORKING":
            return {
                "success": False,
                "error": f"WhatsApp pada session '{target_session}' sudah terhubung aktif (status: WORKING).",
                "detail": "Session is already active and authenticated.",
                "status": "WORKING"
            }

        # 3. Tembak endpoint resmi WAHA: POST {WAHA_URL}/api/{clean_session}/auth/request-code
        request_code_url = f"{WAHA_URL}/api/{target_session}/auth/request-code"
        logger.info(f"[WAHA] Requesting pairing code via {request_code_url} for phone {clean_phone} (session status: {current_status})...")

        try:
            req_res = await client.post(
                request_code_url,
                headers=headers,
                json={"phoneNumber": clean_phone}
            )

            # Fallback path jika endpoint versi WAHA menggunakan query-param
            if req_res.status_code == 404:
                alt_req_url = f"{WAHA_URL}/api/auth/request-code"
                alt_res = await client.post(
                    alt_req_url,
                    headers=headers,
                    json={"session": target_session, "phoneNumber": clean_phone}
                )
                if alt_res.status_code in (200, 201):
                    req_res = alt_res

            if req_res.status_code in (200, 201):
                res_json = req_res.json()
                pairing_code = res_json.get("code") or res_json.get("pairingCode")
                if pairing_code:
                    code_str = str(pairing_code).strip()
                    logger.info(f"[WAHA] Berhasil menerima pairing code resmi: {code_str}")
                    return {
                        "success": True,
                        "pairing_code": code_str,
                        "tenant_slug": clean_tenant,
                        "session": target_session,
                        "phone": clean_phone,
                        "message": f"Pairing code resmi diterima dari WAHA: {code_str}"
                    }
                else:
                    return {
                        "success": False,
                        "error": "Server WAHA tidak mengembalikan atribut 'code'.",
                        "detail": res_json
                    }
            else:
                err_text = req_res.text
                try:
                    err_json = req_res.json()
                    err_detail = err_json.get("message") or err_json.get("error") or str(err_json)
                except Exception:
                    err_detail = err_text

                logger.error(f"[WAHA Error] request-code gagal ({req_res.status_code}): {err_detail}")
                return {
                    "success": False,
                    "error": f"WAHA Error ({req_res.status_code}): {err_detail}",
                    "detail": err_detail,
                    "session_status": current_status,
                    "status_code": req_res.status_code
                }
        except Exception as post_err:
            logger.error(f"[WAHA Post Error] {post_err}")
            return {
                "success": False,
                "error": f"Gagal mengeksekusi request-code ke server WAHA: {str(post_err)}",
                "detail": str(post_err)
            }
