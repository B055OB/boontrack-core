"""app/tenants/digilife_indra/service.py
Service layer untuk pilot B2G DigiLife Indra (Kelurahan Kebon Melati).
"""

import logging
from typing import Dict, Any, Optional

from app.tenants.base import BaseTenantService
from app.tenants.digilife_indra.config import (
    TENANT_ID,
    TENANT_NAME,
    OPERATIONAL_HOURS,
    LOCATION,
    HOTLINE_PHONE,
    SERVICE_CATALOG,
    WELCOME_MESSAGE,
)

logger = logging.getLogger("DIGILIFE_INDRA_SERVICE")


class DigiLifeIndraService(BaseTenantService):
    """Service pemrosesan permohonan layanan publik dan konsultasi dokumen warga

    untuk pilot B2G DigiLife Indra (Kelurahan Kebon Melati).
    """

    tenant_id: str = TENANT_ID
    tenant_name: str = TENANT_NAME

    def __init__(self) -> None:
        super().__init__(tenant_id=TENANT_ID, tenant_name=TENANT_NAME)
        self.catalog = SERVICE_CATALOG

    def _format_service_response(self, svc: Dict[str, Any]) -> str:
        reqs = "\n".join([f"• {r}" for r in svc.get("requirements", [])])
        flow = "\n".join([f"{idx+1}. {step}" for idx, step in enumerate(svc.get("flow", []))])
        return (
            f"🏛️ *{svc['title']}*\n\n"
            f"📋 *Persyaratan Wajib:*\n{reqs}\n\n"
            f"🔄 *Alur Pengurusan:*\n{flow}\n\n"
            f"⏱️ *Estimasi Waktu:* {svc.get('processing_time', '-')}\n"
            f"💰 *Biaya Administrasi:* {svc.get('cost', 'Gratis (Rp 0)')}\n\n"
            f"📍 *Lokasi Pelayanan:* {LOCATION}\n"
            f"⏰ *Jam Operasional:* {OPERATIONAL_HOURS}"
        )

    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Menangani pesan masuk dari warga untuk konsultasi layanan kelurahan."""
        clean_text = (message_text or "").strip().lower()
        clean_phone = self.clean_phone(phone_number)

        logger.info(f"[{TENANT_ID}] Processing query from {clean_phone}: {clean_text[:50]}")

        # 1. Cek Jam Operasional / Lokasi Kantor
        if any(w in clean_text for w in ["jam", "jadwal", "buka", "tutup", "lokasi", "alamat", "kantor"]):
            reply = (
                f"🏛️ *INFORMASI KANTOR KELURAHAN KEBON MELATI*\n\n"
                f"📍 *Alamat:* {LOCATION}\n"
                f"⏰ *Jam Operasional:* {OPERATIONAL_HOURS}\n"
                f"📞 *Hotline / WhatsApp:* {HOTLINE_PHONE}\n\n"
                f"Silakan datang pada hari & jam kerja dengan membawa berkas lengkap."
            )
            return {"reply": reply, "type": "information", "tenant_id": TENANT_ID}

        # 2. Cek Surat Keterangan Usaha (SKU / NIB)
        if any(w in clean_text for w in ["sku", "usaha", "nib", "kur", "dagang", "toko"]):
            svc = self.catalog.get("sku", {})
            return {"reply": self._format_service_response(svc), "type": "service_detail", "service_id": "sku"}

        # 3. Cek Surat Pengantar Nikah (N1-N4)
        if any(w in clean_text for w in ["nikah", "kawin", "n1", "n4", "kua", "pengantin"]):
            svc = self.catalog.get("nikah", {})
            return {"reply": self._format_service_response(svc), "type": "service_detail", "service_id": "nikah"}

        # 4. Cek Pengantar Akta Kelahiran
        if any(w in clean_text for w in ["lahir", "akta lahir", "kelahiran", "bayi"]):
            svc = self.catalog.get("akta_lahir", {})
            return {"reply": self._format_service_response(svc), "type": "service_detail", "service_id": "akta_lahir"}

        # 5. Cek SKTM (Surat Keterangan Tidak Mampu)
        if any(w in clean_text for w in ["sktm", "tidak mampu", "miskin", "beasiswa", "kjp"]):
            svc = self.catalog.get("sktm", {})
            return {"reply": self._format_service_response(svc), "type": "service_detail", "service_id": "sktm"}

        # 6. Default Welcome & Menu Pilihan
        return {
            "reply": WELCOME_MESSAGE,
            "type": "welcome",
            "tenant_id": TENANT_ID
        }


digilife_indra_service = DigiLifeIndraService()
