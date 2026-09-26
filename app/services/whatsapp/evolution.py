"""
app/services/whatsapp/evolution.py
--------------------------------------
Evolution API v2 adapter (Growth Plan - QR & Pairing Code).
"""
import asyncio
import os
import logging
from typing import Optional, Dict, Any

import httpx

from app.services.whatsapp.credentials import normalize_phone_number

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EVOLUTION_BASE_URL = (
    os.getenv("EVOLUTION_API_URL")
    or os.getenv("WA_GATEWAY_BASE_URL")
    or "https://evolution-api-production-abb7.up.railway.app"
).rstrip("/")

EVOLUTION_API_KEY = (
    os.getenv("EVOLUTION_API_KEY")
    or os.getenv("AUTHENTICATION_API_KEY")
    or os.getenv("WA_GATEWAY_INTERNAL_API_KEY")
    or "4398809d97f770b1a2b243ed0ee33bf3312d02dec42be8789ea3512f487f4c5e"
)


def get_evolution_headers() -> Dict[str, str]:
    return {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }


def clean_evolution_base64_qr(raw_base64: Optional[str]) -> Optional[str]:
    """
    Membersihkan dan menormalisasi string base64 QR Code dari Evolution API v2:
    - Menghilangkan prefix dobel seperti 'data:image/png;base64,data:image/png;base64,...'
    - Memastikan format valid data URL 'data:image/png;base64,...' tanpa dobel prefix.
    """
    if not raw_base64 or not isinstance(raw_base64, str):
        return None
    val = raw_base64.strip()
    if not val:
        return None

    # Hapus nested/duplicate prefix data:image jika sudah ada
    while val.startswith("data:image"):
        comma_idx = val.find(",")
        if comma_idx != -1:
            rest = val[comma_idx + 1:].strip()
            if rest.startswith("data:image"):
                val = rest
            else:
                break
        else:
            break

    if not val.startswith("data:image"):
        val = f"data:image/png;base64,{val}"
    return val


async def get_or_create_evolution_session(tenant_slug: str = "") -> Dict[str, Any]:
    clean_tenant = (tenant_slug or "").strip().lower()
    if not clean_tenant:
        return {"success": False, "error": "tenant_slug is required"}

    # 1. Resolusikan otoritas instance_name dari database whatsapp_connections
    instance_name = clean_tenant
    try:
        from app.services.whatsapp_service import get_supabase
        sb = get_supabase()
        if sb:
            db_res = sb.table("whatsapp_connections").select("instance_name, metadata").or_(f"tenant_id.eq.{clean_tenant},tenant_slug.eq.{clean_tenant}").order("created_at", desc=True).limit(1).execute()
            if db_res.data and len(db_res.data) > 0:
                registered_name = db_res.data[0].get("instance_name")
                if registered_name and registered_name != "boontrack-gateway":
                    instance_name = registered_name
    except Exception as db_lookup_err:
        logger.debug(f"[Evolution API] Lookup whatsapp_connections note: {db_lookup_err}")

    headers = get_evolution_headers()

    async with httpx.AsyncClient(timeout=25.0) as client:
        try:
            status_res = await client.get(
                f"{EVOLUTION_BASE_URL}/instance/connectionState/{instance_name}",
                headers=headers
            )

            if status_res.status_code == 200:
                data = status_res.json()
                state = (data.get("instance", {}).get("state") or data.get("state") or "").lower()

                if state == "open":
                    owner = data.get("instance", {}).get("ownerJid") or ""
                    phone_number = owner.split("@")[0] if "@" in owner else owner
                    try:
                        from app.services.whatsapp_service import get_supabase
                        sb = get_supabase()
                        if sb:
                            sb.table("whatsapp_connections").upsert({
                                "tenant_id": clean_tenant,
                                "tenant_slug": clean_tenant,
                                "instance_name": instance_name,
                                "provider": "EVOLUTION",
                                "channel_type": "BAILEYS",
                                "status": "open",
                                "is_connected": True,
                                "phone_number": phone_number or None,
                                "metadata": {
                                    "mode": "DEDICATED",
                                    "instance_name": instance_name,
                                    "tenant_slug": clean_tenant,
                                    "provider": "EVOLUTION"
                                }
                            }, on_conflict="instance_name").execute()
                    except Exception as upsert_err:
                        logger.debug(f"[Evolution API] Upsert whatsapp_connections open note: {upsert_err}")

                    return {
                        "success": True,
                        "status": "CONNECTED",
                        "provider": "EVOLUTION",
                        "mode": "DEDICATED",
                        "instance_name": instance_name,
                        "tenant_slug": clean_tenant,
                        "phone_number": phone_number or None,
                        "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
                    }
                elif state in ("close", "refused", "disconnected"):
                    logger.info(f"[Evolution API] Instance {instance_name} berstatus '{state}'. Memulai restart socket...")
                    try:
                        await client.post(f"{EVOLUTION_BASE_URL}/instance/restart/{instance_name}", headers=headers)
                        await asyncio.sleep(1.5)
                    except Exception as restart_err:
                        logger.warning(f"[Evolution API] Restart note on {instance_name}: {restart_err}")

            if status_res.status_code in (404, 400):
                create_payload = {
                    "instanceName": instance_name,
                    "token": EVOLUTION_API_KEY,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS",
                    "clientName": "BoonTrack Engine",
                    "browser": ["BoonTrack Engine", "Chrome", "1.0.0"],
                    "browserName": "BoonTrack Engine"
                }
                await client.post(
                    f"{EVOLUTION_BASE_URL}/instance/create",
                    headers=headers,
                    json=create_payload
                )
                await asyncio.sleep(1.0)

            backend_url = os.getenv("BACKEND_WEBHOOK_URL") or os.getenv("FASTAPI_BASE_URL", "https://api.boontrack.com").rstrip("/")
            try:
                await client.post(
                    f"{EVOLUTION_BASE_URL}/webhook/set/{instance_name}",
                    headers=headers,
                    json={
                        "webhook": {
                            "enabled": True,
                            "url": f"{backend_url}/api/v1/whatsapp/webhook/evolution/{instance_name}",
                            "byEvents": False,
                            "base64": True,
                            "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE", "QRCODE_UPDATED"]
                        }
                    }
                )
            except Exception as hook_err:
                logger.debug(f"[Evolution Webhook Setup Note] {hook_err}")

            qr_res = await client.get(
                f"{EVOLUTION_BASE_URL}/instance/connect/{instance_name}",
                headers=headers
            )

            if qr_res.status_code not in (200, 201) or (
                qr_res.status_code in (200, 201)
                and not (qr_res.json().get("base64") or (qr_res.json().get("qrcode") or {}).get("base64"))
                and not (qr_res.json().get("code") or (qr_res.json().get("qrcode") or {}).get("code"))
            ):
                logger.info(f"[Evolution API] Connect untuk {instance_name} perlu disegarkan (status {qr_res.status_code}). Melakukan restart socket...")
                try:
                    await client.post(f"{EVOLUTION_BASE_URL}/instance/restart/{instance_name}", headers=headers)
                    await asyncio.sleep(1.5)
                    qr_res = await client.get(
                        f"{EVOLUTION_BASE_URL}/instance/connect/{instance_name}",
                        headers=headers
                    )
                except Exception as restart_err:
                    logger.warning(f"[Evolution API] Retry connect error on {instance_name}: {restart_err}")

            if qr_res.status_code in (200, 201):
                qr_data = qr_res.json()
                qr_raw = qr_data.get("code") or (qr_data.get("qrcode") or {}).get("code") or qr_data.get("pairingCode")
                qr_base64 = qr_data.get("base64") or (qr_data.get("qrcode") or {}).get("base64") or qr_data.get("qr_image")
                clean_b64 = clean_evolution_base64_qr(qr_base64)

                try:
                    from app.services.whatsapp_service import get_supabase
                    sb = get_supabase()
                    if sb:
                        sb.table("whatsapp_connections").upsert({
                            "tenant_id": clean_tenant,
                            "tenant_slug": clean_tenant,
                            "instance_name": instance_name,
                            "provider": "EVOLUTION",
                            "channel_type": "BAILEYS",
                            "status": "connecting",
                            "is_connected": False,
                            "metadata": {
                                "mode": "DEDICATED",
                                "instance_name": instance_name,
                                "tenant_slug": clean_tenant,
                                "provider": "EVOLUTION"
                            }
                        }, on_conflict="instance_name").execute()
                except Exception as upsert_err:
                    logger.debug(f"[Evolution API] Upsert whatsapp_connections connecting note: {upsert_err}")

                return {
                    "success": True,
                    "status": "CONNECTING",
                    "provider": "EVOLUTION",
                    "mode": "DEDICATED",
                    "instance_name": instance_name,
                    "tenant_slug": clean_tenant,
                    "code": qr_raw,
                    "qr_raw": qr_raw,
                    "base64": clean_b64,
                    "qr_image": clean_b64,
                    "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
                }

            return {
                "success": False,
                "status": "DEGRADED",
                "disconnect_reason": "GATEWAY_SESSION_PENDING",
                "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
            }

        except Exception as e:
            logger.error(f"[Evolution API Handshake Error] {e}")
            return {
                "success": False,
                "status": "DEGRADED",
                "disconnect_reason": "GATEWAY_UNREACHABLE",
                "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
            }


def is_valid_whatsapp_pairing_code(code_candidate: Any) -> bool:
    """
    Validasi resmi pairing code WhatsApp:
    - Panjang maksimal 12 karakter (biasanya 8 karakter alfanumerik, misal ABCD-1234).
    - TIDAK mengandung '@', '=', ',', ';', '/', atau karakter QR raw lainnya.
    - Mengandung tepat 8 karakter alfanumerik saat tanda strip/spasi dihapus.
    """
    if not code_candidate or not isinstance(code_candidate, str):
        return False
    candidate = code_candidate.strip()
    if "@" in candidate or "=" in candidate or "," in candidate or ";" in candidate or len(candidate) > 12:
        return False
    alphanumeric = "".join(c for c in candidate if c.isalnum()).upper()
    return len(alphanumeric) == 8


def format_whatsapp_pairing_code(raw_code: str) -> str:
    """Format kode pairing resmi WhatsApp ke pola 4-4 (XXXX-XXXX)."""
    alphanumeric = "".join(c for c in raw_code if c.isalnum()).upper()
    if len(alphanumeric) == 8:
        return f"{alphanumeric[:4]}-{alphanumeric[4:]}"
    return raw_code.strip()


async def request_evolution_pairing_code(tenant_slug: str, phone: str) -> Dict[str, Any]:
    """
    Mengambil kode pairing resmi WhatsApp (8 karakter alfanumerik) dari Evolution API v2 di Railway.
    1. Pastikan instance tenant dibuat via POST /instance/create jika belum ada.
    2. Panggil GET /instance/connect/{instance}?number={clean_phone} dengan header apikey: {EVOLUTION_API_KEY}.
    3. Ambil nilai pairingCode atau code resmi (tepat 8 digit alfanumerik XXXX-XXXX).
    4. Sesuai Section 0 Poin 12 & Section 9 ARCHITECTURE.md: Dilarang keras fallback acak.
       Jika Evolution API error atau belum mengembalikan pairingCode, kembalikan respons error transparan.
    """
    clean_tenant = (tenant_slug or "").strip().lower()
    if not clean_tenant:
        return {"success": False, "error": "tenant_slug is required"}
    clean_phone = normalize_phone_number(phone)
    if not clean_phone or len(clean_phone) < 9:
        return {
            "success": False,
            "error": "Nomor WhatsApp tidak valid. Masukkan nomor dengan format internasional (awali 62, contoh: 628123456789).",
            "detail": "Nomor WhatsApp kosong atau tidak memenuhi standar E.164."
        }

    instance_name = f"tenant_{clean_tenant.replace('-', '_')}"
    headers = get_evolution_headers()

    async with httpx.AsyncClient(timeout=25.0) as client:
        # 1. Cek & pastikan instance ada di Evolution API v2
        try:
            status_res = await client.get(
                f"{EVOLUTION_BASE_URL}/instance/connectionState/{instance_name}",
                headers=headers
            )

            if status_res.status_code in (404, 400):
                logger.info(f"[Evolution API] Instance {instance_name} belum ada. Membuat instance baru...")
                create_payload = {
                    "instanceName": instance_name,
                    "token": EVOLUTION_API_KEY,
                    "number": clean_phone,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS",
                    "clientName": "BoonTrack Engine",
                    "browser": ["BoonTrack Engine", "Chrome", "1.0.0"],
                    "browserName": "BoonTrack Engine"
                }
                create_res = await client.post(
                    f"{EVOLUTION_BASE_URL}/instance/create",
                    headers=headers,
                    json=create_payload
                )
                logger.info(f"[Evolution API] POST /instance/create status={create_res.status_code}")
                # Berikan jeda singkat agar socket Baileys di Evolution API siap
                await asyncio.sleep(1.5)
            elif status_res.status_code == 200:
                data = status_res.json()
                state = (data.get("instance", {}).get("state") or data.get("state") or "").lower()
                if state == "open":
                    owner = data.get("instance", {}).get("ownerJid") or ""
                    phone_number = owner.split("@")[0] if "@" in owner else owner
                    return {
                        "success": False,
                        "error": f"WhatsApp pada instance '{instance_name}' sudah terhubung aktif (nomor: {phone_number}).",
                        "detail": "Instance already authenticated and open.",
                        "status": "CONNECTED"
                    }
                elif state in ("close", "refused", "disconnected"):
                    logger.info(f"[Evolution API] Instance {instance_name} berstatus '{state}' (gagal taut sebelumnya). Memulai restart socket...")
                    try:
                        await client.post(f"{EVOLUTION_BASE_URL}/instance/restart/{instance_name}", headers=headers)
                        await asyncio.sleep(1.5)
                    except Exception as restart_err:
                        logger.warning(f"[Evolution API] Restart note on {instance_name}: {restart_err}")
        except Exception as check_err:
            logger.warning(f"[Evolution API] Error saat memeriksa instance {instance_name}: {check_err}")

        # 2. Panggil GET /instance/connect/{instance}?number={clean_phone}
        connect_url = f"{EVOLUTION_BASE_URL}/instance/connect/{instance_name}?number={clean_phone}"
        logger.info(f"[Evolution API] Meminta pairing code ke {connect_url}...")

        try:
            conn_res = await client.get(connect_url, headers=headers)
            res_data = conn_res.json() if conn_res.status_code in (200, 201) else {}
            if "base64" in res_data and res_data.get("base64"):
                res_data["base64"] = clean_evolution_base64_qr(res_data.get("base64"))
            raw_pairing = res_data.get("pairingCode")

            # Jika pairingCode belum terbit, trigger restart socket instance lalu ambil ulang pairing code
            if not raw_pairing:
                try:
                    await client.post(f"{EVOLUTION_BASE_URL}/instance/restart/{instance_name}", headers=headers)
                    await asyncio.sleep(1.5)
                    retry_res = await client.get(connect_url, headers=headers)
                    if retry_res.status_code in (200, 201):
                        res_data = retry_res.json()
                        if "base64" in res_data and res_data.get("base64"):
                            res_data["base64"] = clean_evolution_base64_qr(res_data.get("base64"))
                        raw_pairing = res_data.get("pairingCode")
                except Exception as restart_err:
                    logger.debug(f"[Evolution API] Restart note: {restart_err}")

            if raw_pairing and is_valid_whatsapp_pairing_code(str(raw_pairing)):
                code_formatted = format_whatsapp_pairing_code(str(raw_pairing))
                logger.info(f"[Evolution API] Berhasil menerima pairing code resmi: {code_formatted}")
                return {
                    "success": True,
                    "pairing_code": code_formatted,
                    "raw_code": str(raw_pairing),
                    "tenant_slug": clean_tenant,
                    "instance": instance_name,
                    "phone": clean_phone,
                    "message": f"Kode pairing resmi diterima dari Evolution API: {code_formatted}"
                }
            elif conn_res.status_code not in (200, 201):
                err_text = conn_res.text
                logger.error(f"[Evolution API Error] Connect failed ({conn_res.status_code}): {err_text}")
                return {
                    "success": False,
                    "error": f"Evolution API Gateway Error ({conn_res.status_code}): {err_text[:200]}",
                    "detail": err_text,
                    "status_code": conn_res.status_code
                }
            else:
                # Tanpa fake fallback!
                logger.warning(f"[Evolution API] Respons tidak memuat pairingCode valid: {res_data}")
                return {
                    "success": False,
                    "error": "Evolution API belum menerbitkan kode pairing 8-digit resmi. Pastikan nomor HP aktif dan muat ulang sesi.",
                    "detail": res_data,
                    "status_code": 502
                }
        except Exception as conn_err:
            logger.error(f"[Evolution API Connection Error] {conn_err}")
            return {
                "success": False,
                "error": f"Tidak dapat terhubung ke server Evolution API di {EVOLUTION_BASE_URL}: {str(conn_err)}",
                "detail": str(conn_err),
                "status_code": 502
            }


# ---------------------------------------------------------------------------
# Outgoing Message Helpers (Interactive List & Buttons for APP_SHOP_V1)
# ---------------------------------------------------------------------------

def normalize_evolution_instance(instance: str) -> str:
    inst = str(instance or "").strip()
    if inst.lower() in ("app_shop_v1", "app_shop", "app-shop-v1", "app-shop", "boon"):
        return "boontrack-app-shop"
    return inst or "boontrack-app-shop"


async def send_evolution_list(
    number: str,
    title: str,
    description: str,
    button_text: str,
    sections: list,
    instance_name: str = "boontrack-app-shop",
    footer_text: str = "BoonTrack Official",
) -> Dict[str, Any]:
    """Sends an Interactive List message via Evolution API v2 (/message/sendList/{instance})."""
    actual_instance = normalize_evolution_instance(instance_name)
    clean_num = normalize_phone_number(number) or number
    headers = get_evolution_headers()
    payload = {
        "number": clean_num,
        "title": title,
        "description": description,
        "buttonText": button_text,
        "footerText": footer_text,
        "sections": sections,
    }
    url = f"{EVOLUTION_BASE_URL}/message/sendList/{actual_instance}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                return {"success": True, "data": res.json()}
            logger.warning(f"[Evolution API sendList] Failed ({res.status_code}): {res.text}")
            return {"success": False, "error": res.text, "status_code": res.status_code}
        except Exception as e:
            logger.error(f"[Evolution API sendList Error] {e}")
            return {"success": False, "error": str(e)}


async def send_evolution_buttons(
    number: str,
    title: str,
    description: str,
    buttons: list,
    instance_name: str = "boontrack-app-shop",
    footer: str = "BoonTrack Official",
) -> Dict[str, Any]:
    """Sends an Interactive Buttons message via Evolution API v2 (/message/sendButtons/{instance})."""
    actual_instance = normalize_evolution_instance(instance_name)
    clean_num = normalize_phone_number(number) or number
    headers = get_evolution_headers()
    payload = {
        "number": clean_num,
        "title": title,
        "description": description,
        "footer": footer,
        "buttons": buttons,
    }
    url = f"{EVOLUTION_BASE_URL}/message/sendButtons/{actual_instance}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                return {"success": True, "data": res.json()}
            logger.warning(f"[Evolution API sendButtons] Failed ({res.status_code}): {res.text}")
            return {"success": False, "error": res.text, "status_code": res.status_code}
        except Exception as e:
            logger.error(f"[Evolution API sendButtons Error] {e}")
            return {"success": False, "error": str(e)}


async def send_evolution_app_shop_catalog(
    number: str,
    instance_name: str = "boontrack-app-shop"
) -> Dict[str, Any]:
    """Helper to send internal package catalog for APP_SHOP_V1 via interactive List message."""
    actual_instance = normalize_evolution_instance(instance_name)
    sections = [
        {
            "title": "📦 PILIHAN PAKET BOONTRACK SHOP",
            "rows": [
                {
                    "title": "Paket Checkout Lite",
                    "description": "Rp 59.000/bln - Single page checkout, QRIS 0% fee",
                    "rowId": "pkg_checkout_lite"
                },
                {
                    "title": "Paket Starter",
                    "description": "Rp 199.000/bln - Multi-ekspedisi, katalog & bot WA",
                    "rowId": "pkg_starter"
                },
                {
                    "title": "Paket Pro Scale",
                    "description": "Rp 299.000/bln - Meta & TikTok CAPI + 2 CS Seats",
                    "rowId": "pkg_pro_scale"
                },
                {
                    "title": "Paket Enterprise",
                    "description": "Rp 499.000/bln - WABA resmi, broadcast, unlimited seats",
                    "rowId": "pkg_enterprise"
                },
            ]
        }
    ]
    return await send_evolution_list(
        number=number,
        title="🛍️ Katalog Paket Resmi BoonTrack Shop",
        description="Pilih paket langganan yang paling tepat untuk mengakselerasi penjualan tokomu:",
        button_text="Lihat Paket",
        sections=sections,
        instance_name=actual_instance,
        footer_text="BoonTrack Shop V1 • Closed Economic Loop"
    )
