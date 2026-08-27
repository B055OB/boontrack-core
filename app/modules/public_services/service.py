import datetime
import json
import logging
import random
import re
from typing import Any, Dict, List, Optional

from app.modules.public_services.knowledge import (
    PublicServiceKnowledgeProvider,
)

logger = logging.getLogger(__name__)

# In-Memory Storage Tiket Multi-Tenant
TENANT_TICKETS_STORE: Dict[str, List[Dict[str, Any]]] = {
    "bale-pananggeuhan": [
        {
            "id": "PS-20260822-1001",
            "waktu": "2026-08-22 09:15",
            "aduan": "Pipa air bersih bocor di Jl. Asia Afrika",
            "kategori": "PDAM",
            "status": "PROSES"
        },
        {
            "id": "PS-20260822-1002",
            "waktu": "2026-08-22 10:30",
            "aduan": "Tiang listrik korsleting padam satu blok di Dago",
            "kategori": "PLN",
            "status": "OPEN"
        },
        {
            "id": "PS-20260822-1003",
            "waktu": "2026-08-22 11:45",
            "aduan": "Lampu PJU dan jalan berlubang parah di Pasteur",
            "kategori": "Bina Marga / Dishub",
            "status": "SELESAI"
        }
    ],
    "kelurahan-indra": [
        {
            "id": "KL-20260822-001",
            "waktu": "2026-08-22 08:30",
            "aduan": "Pengajuan SKU mendesak untuk syarat KUR Bank",
            "kategori": "Loket Pelayanan",
            "status": "PROSES"
        }
    ]
}


def safe_parse_ai_json(raw_text: str) -> dict:
    if not raw_text or not raw_text.strip():
        return {}
    cleaned = str(raw_text).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    json_match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(1).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        return {"reply": str(parsed), "is_escalated": False}
    except Exception:
        return {
            "reply": raw_text.strip(),
            "identified_service_slug": None,
            "is_escalated": False,
            "escalation_reason": None,
        }


class PublicServiceService:
    @classmethod
    def detect_jabar_category(cls, text: str) -> str:
        t = text.lower()
        if any(k in t for k in ["air", "pdam", "kran", "saluran", "ledeng", "pipa"]):
            return "PDAM"
        if any(k in t for k in ["listrik", "pln", "padam", "gardu", "korslet", "mati lampu"]):
            return "PLN"
        if any(k in t for k in ["jalan", "lubang", "pju", "lampu", "rambu", "dishub", "aspal"]):
            return "Bina Marga / Dishub"
        return "Bale Pananggeuhan (Umum)"

    @classmethod
    def get_tickets(cls, tenant_id: str) -> List[Dict[str, Any]]:
        return TENANT_TICKETS_STORE.get(tenant_id, [])

    @classmethod
    def update_ticket_status(cls, tenant_id: str, ticket_id: str, new_status: str) -> bool:
        tickets = TENANT_TICKETS_STORE.get(tenant_id, [])
        for t in tickets:
            if t["id"] == ticket_id:
                t["status"] = new_status
                return True
        return False

    @classmethod
    async def handle_query(
        cls,
        user_text: str,
        user_id: str = "0",
        session_id: Optional[str] = None,
        channel: str = "webchat",
        tenant_id: str = "bale-pananggeuhan"
    ) -> Dict[str, Any]:
        text = user_text.strip()
        text_lower = text.lower()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        today_str = datetime.datetime.now().strftime("%Y%m%d")

        # -------------------------------------------------------------
        # 1. LOGIKA BALE PANANGGEUHAN JABAR
        # -------------------------------------------------------------
        if tenant_id == "bale-pananggeuhan":
            escalation_words = ["lapor", "aduan", "rusak", "pungli", "keluhan", "jalan", "air", "listrik", "padam", "bocor", "lubang", "pju"]
            if any(w in text_lower for w in escalation_words):
                ticket_id = f"PS-{today_str}-{random.randint(1000, 9999)}"
                category = cls.detect_jabar_category(text)

                new_ticket = {
                    "id": ticket_id,
                    "waktu": now_str,
                    "aduan": text,
                    "kategori": category,
                    "status": "OPEN"
                }
                if "bale-pananggeuhan" not in TENANT_TICKETS_STORE:
                    TENANT_TICKETS_STORE["bale-pananggeuhan"] = []
                TENANT_TICKETS_STORE["bale-pananggeuhan"].insert(0, new_ticket)

                msg = (
                    f"🚨 **Laporan Berhasil Diterbitkan**\n"
                    f"• No. Tiket : `{ticket_id}`\n"
                    f"• Instansi  : {category}\n"
                    f"• Status    : **OPEN** (Menunggu Tindak Lanjut)\n\n"
                    f"Laporan Anda telah diteruskan ke Posko Balé Pananggeuhan Gedung Sate untuk segera dikoordinasikan dengan dinas terkait."
                )
                return {"reply": msg, "type": "ticket", "ticket": new_ticket, "is_escalated": True}

            if "ktp" in text_lower:
                return {
                    "reply": (
                        "📋 **Persyaratan Pengurusan KTP-el (Jawa Barat):**\n\n"
                        "1. Fotokopi Kartu Keluarga (KK) terbaru\n"
                        "2. Surat Pengantar RT/RW (khusus pemula/baru)\n"
                        "3. KTP-el lama (jika rusak atau permohonan ganti data)\n"
                        "4. Surat Keterangan Hilang Polsek (jika hilang)\n\n"
                        "⏱️ **Estimasi:** 1 - 3 Hari Kerja\n"
                        "💰 **Biaya:** Gratis (Rp 0)"
                    ),
                    "type": "information",
                    "ticket": None
                }

            if "kk" in text_lower or "kartu keluarga" in text_lower:
                return {
                    "reply": (
                        "📋 **Persyaratan Pembaruan Kartu Keluarga (KK):**\n\n"
                        "1. Kartu Keluarga (KK) asli yang lama\n"
                        "2. Buku Nikah / Akta Cerai (jika ubah status)\n"
                        "3. Surat Keterangan Lahir (jika tambah anak)\n\n"
                        "⏱️ **Estimasi:** 3 - 5 Hari Kerja\n"
                        "💰 **Biaya:** Gratis (Rp 0)"
                    ),
                    "type": "information",
                    "ticket": None
                }

            if "bansos" in text_lower or "bantuan" in text_lower or "dtks" in text_lower:
                return {
                    "reply": (
                        "📋 **Informasi Bantuan Sosial (DTKS / PKH / BPNT):**\n\n"
                        "Pengecekan bansos Jawa Barat terpusat melalui DTKS Kemensos.\n"
                        "• Syarat: NIK e-KTP dan No. KK yang valid.\n"
                        "• Pendaftaran: Melalui musyawarah kelurahan/desa setempat."
                    ),
                    "type": "information",
                    "ticket": None
                }

            return {
                "reply": (
                    "Sampurasun! Saya asisten virtual Balé Pananggeuhan Jawa Barat.\n\n"
                    "Anda dapat menanyakan syarat dokumen kependudukan (KTP, KK, Bansos) atau melaporkan keluhan fasilitas umum (PDAM bocor, listrik PLN padam, jalan rusak/PJU)."
                ),
                "type": "information",
                "ticket": None
            }

        # -------------------------------------------------------------
        # 2. LOGIKA KELURAHAN KEBON MELATI (INDRA)
        # -------------------------------------------------------------
        provider = PublicServiceKnowledgeProvider(tenant_id="kelurahan-indra")
        matched = provider.search_service(text)

        if matched:
            svc = matched[0]
            reqs = "\n".join([f"- {r}" for r in svc.get("requirements", [])])
            flow = "\n".join(svc.get("flow", []))
            reply_text = (
                f"🏛️ **{svc['service_name']}**\n"
                f"*{svc['description']}*\n\n"
                f"**Persyaratan Wajib:**\n{reqs}\n\n"
                f"**Alur Pengurusan:**\n{flow}\n\n"
                f"⏱️ **Estimasi:** {svc['processing_time']}\n"
                f"💰 **Biaya:** {svc['cost']}"
            )
            return {"reply": reply_text, "type": "information", "ticket": None}

        # Default Kelurahan
        return {
            "reply": (
                "Halo! Selamat datang di layanan informasi Kelurahan Kebon Melati.\n\n"
                "Silakan tanyakan syarat pengurusan dokumen warga, seperti:\n"
                "• Surat Keterangan Usaha (SKU / NIB)\n"
                "• Surat Pengantar Nikah (N1-N4)\n"
                "• Akta Kelahiran / Akta Kematian\n"
                "• Izin Tanah Makam (IPTM) / SKTM"
            ),
            "type": "information",
            "ticket": None
        }


# Singleton Instance
public_service_service = PublicServiceService()
