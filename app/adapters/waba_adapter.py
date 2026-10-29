"""app/adapters/waba_adapter.py
Official Meta Cloud API (WABA) Provider Adapter for OnlineBoost / Multi-Tenant.

Implements:
1. Native WABA WhatsApp Flows Form dispatch (interactive: flow)
2. Text message dispatch via Meta Graph API
3. Media / QRIS image dispatch via Meta Media endpoint
4. Parsing nfm_reply (Flows Form response) and CTA Landing Page Fallback text
5. Server-side Meta CAPI integration (InitiateCheckout & Purchase)
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional, Tuple, Union

from app.services.whatsapp.cloud_api import (
    get_wa_credentials,
    send_whatsapp_text,
    send_whatsapp_image,
    send_whatsapp_image_link,
    upload_whatsapp_media,
    log_to_supabase_messages,
)
from app.modules.tracking.capi_dispatcher import capi_dispatcher

logger = logging.getLogger("WABA_PROVIDER_ADAPTER")

FAST_TRACK_PATTERN = re.compile(
    r"Halo Admin, saya atas nama (.+?) \((.+?)\) sudah daftar kelas",
    re.IGNORECASE,
)


class WabaProviderAdapter:
    """Official Meta Cloud API (WABA) Provider Adapter."""

    def __init__(self, tenant_id: str = "onlineboost"):
        self.tenant_id = tenant_id

    async def send_text(
        self,
        to_phone: str,
        text: str,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send plain text message via Meta Graph API."""
        return await send_whatsapp_text(
            to_phone=to_phone,
            text=text,
            tenant_id=self.tenant_id,
            phone_number_id=phone_number_id,
            access_token=access_token,
        )

    async def send_flow(
        self,
        to_phone: str,
        flow_id: Optional[str] = None,
        flow_token: str = "ctwa_flow_token",
        flow_cta: str = "📝 Isi Data Pendaftaran",
        header_text: str = "Pendaftaran Batch 1",
        body_text: str = (
            "Amankan slot promo Rp249.000 dengan melengkapi data singkat di bawah ini. "
            "Invoice resmi akan langsung diterbitkan:"
        ),
        footer_text: str = "OnlineBoost x BoonTrack",
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send interactive WhatsApp Flow message."""
        from app.services.whatsapp.cloud_api import send_whatsapp_flow
        return await send_whatsapp_flow(
            to_phone=to_phone,
            flow_id=flow_id,
            flow_token=flow_token,
            flow_cta=flow_cta,
            header_text=header_text,
            body_text=body_text,
            footer_text=footer_text,
            tenant_id=self.tenant_id,
            phone_number_id=phone_number_id,
            access_token=access_token,
        )

    async def send_qris_image(
        self,
        to_phone: str,
        image_bytes: bytes,
        caption: str,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send QRIS PNG image via Meta Media endpoint."""
        return await send_whatsapp_image(
            to_phone=to_phone,
            image_path_or_bytes=image_bytes,
            caption=caption,
            tenant_id=self.tenant_id,
            phone_number_id=phone_number_id,
            access_token=access_token,
        )

    @staticmethod
    def parse_inbound_lead(
        raw_msg: Optional[Dict[str, Any]],
        incoming_text: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        """
        Inbound Webhook Parser for:
        1. Flows Response (nfm_reply): interactive.type == 'nfm_reply' -> extracts full_name & email.
        2. Fallback text: FAST_TRACK_PATTERN.
        """
        # 1. Check interactive nfm_reply (WhatsApp Flows Form)
        if isinstance(raw_msg, dict):
            interactive = raw_msg.get("interactive")
            if isinstance(interactive, dict) and interactive.get("type") == "nfm_reply":
                nfm = interactive.get("nfm_reply", {})
                resp_json_raw = nfm.get("response_json", {})
                data = {}
                if isinstance(resp_json_raw, str):
                    try:
                        data = json.loads(resp_json_raw)
                    except Exception:
                        pass
                elif isinstance(resp_json_raw, dict):
                    data = resp_json_raw

                name = str(data.get("full_name") or data.get("name") or "").strip()
                email = str(data.get("email") or "").strip()
                if name or email:
                    return name or "Kakak", email

        # 2. Check line parser & fallback text pattern
        text_to_check = str(incoming_text or "")
        if not text_to_check and isinstance(raw_msg, dict):
            text_to_check = str(raw_msg.get("text", {}).get("body", "")).strip()

        if text_to_check:
            name_line = re.search(r"(?im)^\s*nama\s*:\s*(.+)$", text_to_check)
            email_line = re.search(r"(?im)^\s*email\s*:\s*(.+)$", text_to_check)
            if name_line and email_line:
                name_val = name_line.group(1).strip()
                name_val = re.split(r"(?i)\s*(?:\\n|\n)?\s*email\s*:", name_val)[0].strip()
                email_extracted = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", email_line.group(1).strip())
                if email_extracted:
                    return name_val, email_extracted.group(0).lower().strip()

            match = FAST_TRACK_PATTERN.search(text_to_check)
            if match:
                name = match.group(1).strip()
                email = match.group(2).strip()
                return name, email

        return None

    async def dispatch_initiate_checkout(
        self,
        phone: str,
        total_amount: float,
        product_ids: Optional[list] = None,
        ctwa_clid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatch server-side Meta CAPI InitiateCheckout."""
        p_ids = product_ids or ["kelas-inkubasi-ctwa-batch-1-scale"]
        return await capi_dispatcher.dispatch_initiate_checkout(
            tenant_id=self.tenant_id,
            phone=phone,
            total_amount=total_amount,
            product_ids=p_ids,
            ctwa_clid=ctwa_clid,
        )

    async def dispatch_purchase(
        self,
        phone: str,
        total_amount: float,
        order_id: str,
        product_ids: Optional[list] = None,
        ctwa_clid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatch server-side Meta CAPI Purchase."""
        p_ids = product_ids or ["kelas-inkubasi-ctwa-batch-1-scale"]
        return await capi_dispatcher.dispatch_purchase(
            tenant_id=self.tenant_id,
            phone=phone,
            total_amount=total_amount,
            product_ids=p_ids,
            order_id=order_id,
            ctwa_clid=ctwa_clid,
        )
