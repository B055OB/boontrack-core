"""
app/services/whatsapp/meta_cloud_api_provider.py
-------------------------------------------------
MetaCloudApiProvider — Official Meta WhatsApp Cloud API (Graph API v26.0) Outbound Adapter.

Architecture Contract (ARCHITECTURE.md §25.1 & §25.2):
  - Provider ini HANYA diaktifkan saat WHATSAPP_ACTIVE_PROVIDER == "meta_cloud".
  - Resolution chain: tenant_id -> whatsapp_connections -> provider -> credential_ref.
  - DILARANG meresolusi berdasarkan slug, nomor HP, atau hardcoded ID.
  - phone_number_id = Identity Provider, BUKAN otoritas bisnis.
  - Kegagalan / expired token wajib mengembalikan error eksplisit, bukan fallback ke tenant lain.

Supported operations:
  - send_text()        : Free-form text message (dalam 24-jam session window)
  - send_template()    : HSM template message (di luar session window)
  - send_image()       : Image message dengan optional caption
  - send_document()    : Document message

Usage:
    provider = MetaCloudApiProvider.from_env()
    result = await provider.send_text(to_phone="6285181830080", text="Halo!")
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("META_CLOUD_API_PROVIDER")

# ---------------------------------------------------------------------------
# Provider Config
# ---------------------------------------------------------------------------

META_GRAPH_BASE = "https://graph.facebook.com"


class MetaCloudApiConfig:
    """Immutable configuration snapshot for a single Meta Cloud API send operation."""

    def __init__(
        self,
        api_version: str,
        phone_number_id: str,
        system_user_token: str,
        business_account_id: str = "",
    ):
        self.api_version = api_version
        self.phone_number_id = phone_number_id
        self.system_user_token = system_user_token
        self.business_account_id = business_account_id

    @property
    def messages_endpoint(self) -> str:
        return f"{META_GRAPH_BASE}/{self.api_version}/{self.phone_number_id}/messages"

    @property
    def auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.system_user_token}",
            "Content-Type": "application/json",
        }

    def is_ready(self) -> bool:
        """Returns True only when all required credentials are populated."""
        return bool(self.api_version and self.phone_number_id and self.system_user_token)


# ---------------------------------------------------------------------------
# MetaCloudApiProvider
# ---------------------------------------------------------------------------

class MetaCloudApiProvider:
    """
    Official Meta WhatsApp Cloud API Outbound Adapter (v26.0).

    Architecture §25.1: Provider ini terisolasi penuh dari tenant business logic.
    Semua credential WAJIB berasal dari environment — DILARANG hardcode.
    """

    def __init__(self, config: MetaCloudApiConfig):
        self.config = config

    @classmethod
    def from_env(cls) -> "MetaCloudApiProvider":
        """
        Factory: buat provider dari environment variables resmi.

        Required env keys:
          META_WABA_API_VERSION          (default: "v26.0")
          META_WABA_PHONE_NUMBER_ID      (wajib diisi)
          META_SYSTEM_USER_TOKEN         (wajib diisi)
          META_WABA_BUSINESS_ACCOUNT_ID  (opsional)
        """
        config = MetaCloudApiConfig(
            api_version=(
                os.getenv("META_WABA_API_VERSION")
                or os.getenv("META_GRAPH_VERSION")
                or "v26.0"
            ).strip(),
            phone_number_id=(
                os.getenv("META_WABA_PHONE_NUMBER_ID")
                or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
                or ""
            ).strip(),
            system_user_token=(
                os.getenv("META_SYSTEM_USER_TOKEN")
                or os.getenv("META_WA_PERMANENT_TOKEN")
                or os.getenv("WHATSAPP_TOKEN")
                or ""
            ).strip(),
            business_account_id=(
                os.getenv("META_WABA_BUSINESS_ACCOUNT_ID")
                or os.getenv("WHATSAPP_WABA_ID")
                or ""
            ).strip(),
        )
        return cls(config)

    def _check_readiness(self) -> Optional[Dict[str, Any]]:
        """Guard: kembalikan error dict jika provider belum siap; None = aman."""
        if not self.config.is_ready():
            missing = []
            if not self.config.phone_number_id:
                missing.append("META_WABA_PHONE_NUMBER_ID")
            if not self.config.system_user_token:
                missing.append("META_SYSTEM_USER_TOKEN")
            msg = f"MetaCloudApiProvider tidak siap. Env vars belum diset: {', '.join(missing)}"
            logger.error(f"[META_CLOUD_PROVIDER] {msg}")
            return {"success": False, "error": "PROVIDER_NOT_CONFIGURED", "detail": msg}
        return None

    async def send_text(
        self,
        to_phone: str,
        text: str,
        preview_url: bool = False,
    ) -> Dict[str, Any]:
        """
        Kirim free-form text message via Meta Cloud API.
        Hanya valid dalam 24-jam customer service session window.

        Args:
            to_phone: Nomor tujuan format E.164 tanpa '+' (contoh: '6285181830080').
            text: Teks pesan (maks 4096 karakter).
            preview_url: Aktifkan link preview di dalam pesan.
        """
        guard = self._check_readiness()
        if guard:
            return guard

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "text",
            "text": {"body": text, "preview_url": preview_url},
        }
        return await self._post(payload, context=f"send_text to {to_phone}")

    async def send_template(
        self,
        to_phone: str,
        template_name: str,
        language_code: str = "id",
        components: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Kirim HSM template message via Meta Cloud API.
        Digunakan saat di luar 24-jam session window (notifikasi transaksional, dll).

        Args:
            to_phone: Nomor tujuan format E.164.
            template_name: Nama template yang telah diapprove di Meta Business Manager.
            language_code: Kode bahasa template (default: 'id').
            components: List komponen template (header, body, button parameters).
        """
        guard = self._check_readiness()
        if guard:
            return guard

        template_payload: Dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template_payload["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone.lstrip("+"),
            "type": "template",
            "template": template_payload,
        }
        return await self._post(payload, context=f"send_template '{template_name}' to {to_phone}")

    async def send_image(
        self,
        to_phone: str,
        image_url: str,
        caption: str = "",
    ) -> Dict[str, Any]:
        """
        Kirim image message via Meta Cloud API.

        Args:
            to_phone: Nomor tujuan format E.164.
            image_url: URL publik gambar (HTTPS, format JPG/PNG/WEBP, maks 5MB).
            caption: Caption opsional di bawah gambar (maks 1024 karakter).
        """
        guard = self._check_readiness()
        if guard:
            return guard

        image_obj: Dict[str, Any] = {"link": image_url}
        if caption:
            image_obj["caption"] = caption

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "image",
            "image": image_obj,
        }
        return await self._post(payload, context=f"send_image to {to_phone}")

    async def send_document(
        self,
        to_phone: str,
        document_url: str,
        filename: str = "",
        caption: str = "",
    ) -> Dict[str, Any]:
        """
        Kirim document message via Meta Cloud API.

        Args:
            to_phone: Nomor tujuan format E.164.
            document_url: URL publik dokumen (PDF, DOCX, dll).
            filename: Nama file yang ditampilkan di chat.
            caption: Caption opsional.
        """
        guard = self._check_readiness()
        if guard:
            return guard

        doc_obj: Dict[str, Any] = {"link": document_url}
        if filename:
            doc_obj["filename"] = filename
        if caption:
            doc_obj["caption"] = caption

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone.lstrip("+"),
            "type": "document",
            "document": doc_obj,
        }
        return await self._post(payload, context=f"send_document to {to_phone}")

    async def _post(self, payload: Dict[str, Any], context: str = "") -> Dict[str, Any]:
        """Internal HTTP POST ke Meta Graph API messages endpoint."""
        url = self.config.messages_endpoint
        headers = self.config.auth_headers
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(url, headers=headers, json=payload)
            if res.status_code in (200, 201):
                logger.info(f"[META_CLOUD_PROVIDER] OK — {context}")
                return {"success": True, "data": res.json(), "status_code": res.status_code}
            else:
                logger.error(
                    f"[META_CLOUD_PROVIDER ERROR] {context} — "
                    f"HTTP {res.status_code}: {res.text[:400]}"
                )
                return {
                    "success": False,
                    "error": f"HTTP_{res.status_code}",
                    "detail": res.text[:400],
                    "status_code": res.status_code,
                }
        except httpx.TimeoutException as e:
            logger.error(f"[META_CLOUD_PROVIDER TIMEOUT] {context}: {e}")
            return {"success": False, "error": "TIMEOUT", "detail": str(e)}
        except Exception as e:
            logger.error(f"[META_CLOUD_PROVIDER EXCEPTION] {context}: {e}")
            return {"success": False, "error": "EXCEPTION", "detail": str(e)}


# ---------------------------------------------------------------------------
# Provider Factory / Dispatcher (WHATSAPP_ACTIVE_PROVIDER switch)
# ---------------------------------------------------------------------------

def get_active_whatsapp_provider() -> str:
    """
    Membaca WHATSAPP_ACTIVE_PROVIDER dari env.
    Nilai valid: 'evolution' | 'meta_cloud'
    Default: 'evolution' (backward-compatible).
    """
    raw = os.getenv("WHATSAPP_ACTIVE_PROVIDER", "evolution").strip().lower()
    if raw not in ("evolution", "meta_cloud"):
        logger.warning(
            f"[PROVIDER_FACTORY] WHATSAPP_ACTIVE_PROVIDER='{raw}' tidak dikenal. "
            "Fallback ke 'evolution'."
        )
        return "evolution"
    return raw


async def dispatch_text_via_active_provider(
    to_phone: str,
    text: str,
    # Evolution-specific params (dilewatkan jika provider == evolution)
    wa_token: str = "",
    wa_phone_number_id: str = "",
    tenant_id: str = "shop",
) -> Dict[str, Any]:
    """
    High-level dispatcher: mengirim text message via provider yang aktif.

    Saat WHATSAPP_ACTIVE_PROVIDER == 'meta_cloud':
      - Gunakan MetaCloudApiProvider.from_env().
      - wa_token dan wa_phone_number_id diabaikan (digantikan oleh env META_*).

    Saat WHATSAPP_ACTIVE_PROVIDER == 'evolution' (default):
      - Delegasikan ke send_whatsapp_text dari app.services.whatsapp.cloud_api.
    """
    provider = get_active_whatsapp_provider()
    logger.info(f"[PROVIDER_DISPATCH] Provider aktif: '{provider}' | to: {to_phone}")

    if provider == "meta_cloud":
        meta_provider = MetaCloudApiProvider.from_env()
        return await meta_provider.send_text(to_phone=to_phone, text=text)
    else:
        # Evolution / Baileys path (backward-compat)
        from app.services.whatsapp.cloud_api import send_whatsapp_text
        ok = await send_whatsapp_text(
            to_phone=to_phone,
            text=text,
            tenant_id=tenant_id,
            phone_number_id=wa_phone_number_id or None,
        )
        return {"success": bool(ok), "provider": "evolution"}
