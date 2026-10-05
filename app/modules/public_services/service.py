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
    "kelurahan-margasari": [
        {
            "id": "MGS-20261004-001",
            "waktu": "2026-10-04 08:30",
            "aduan": "Aktivasi IKD di Loket PTSP SIMDUK Kelurahan Margasari",
            "kategori": "Loket PTSP / Kependudukan",
            "status": "SELESAI"
        },
        {
            "id": "MGS-20261004-002",
            "waktu": "2026-10-04 09:15",
            "aduan": "Pengajuan SKDU Usaha Kuliner RW 04 Margasari",
            "kategori": "Pelayanan Umum",
            "status": "PROSES"
        }
    ]
}
# Backward compatibility mapping
TENANT_TICKETS_STORE["kelurahan-indra"] = TENANT_TICKETS_STORE["kelurahan-margasari"]
TENANT_TICKETS_STORE["margasari"] = TENANT_TICKETS_STORE["kelurahan-margasari"]


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
        return json.loads(cleaned)
    except Exception:
        return {}


class PublicServiceService:
    """Service pemrosesan pertanyaan warga, eskalasi tiket, dan informasi SOP multi-tenant."""

    @classmethod
    def get_tickets(cls, tenant_id: str = "kelurahan-margasari") -> List[Dict[str, Any]]:
        clean_t = str(tenant_id or "").strip().lower().replace("_", "-")
        target = "bale-pananggeuhan" if clean_t in ("bale-pananggeuhan", "bale_pananggeuhan", "balai-pananggeuhan") else "kelurahan-margasari"
        return TENANT_TICKETS_STORE.get(target, [])

    @classmethod
    def update_ticket_status(cls, tenant_id: str, ticket_id: str, new_status: str) -> bool:
        clean_t = str(tenant_id or "").strip().lower().replace("_", "-")
        target = "bale-pananggeuhan" if clean_t in ("bale-pananggeuhan", "bale_pananggeuhan", "balai-pananggeuhan") else "kelurahan-margasari"
        tickets = TENANT_TICKETS_STORE.get(target, [])
        for t in tickets:
            if t.get("id") == ticket_id:
                t["status"] = new_status
                return True
        return False

    @classmethod
    def detect_jabar_category(cls, text: str) -> str:
        text_lower = text.lower()
        if any(w in text_lower for w in ["air", "pdam", "kran", "bocor", "pipa"]):
            return "PDAM Tirtawening"
        if any(w in text_lower for w in ["listrik", "pln", "mati lampu", "padam", "korslet", "tiang"]):
            return "PLN Distribusi Jabar"
        if any(w in text_lower for w in ["jalan", "lubang", "rusak", "aspal", "jembatan"]):
            return "Dinas Bina Marga & Penataan Ruang Jabar"
        if any(w in text_lower for w in ["pju", "lampu jalan", "rambu", "dishub", "macet"]):
            return "Dinas Perhubungan Jabar"
        if any(w in text_lower for w in ["sampah", "kebersihan", "dlh", "limbah"]):
            return "Dinas Lingkungan Hidup Jabar"
        return "Posko Pengaduan Umum Balai Pananggeuhan"

    @classmethod
    async def handle_query(
        cls,
        user_text: str,
        user_id: str = "0",
        session_id: Optional[str] = None,
        channel: str = "webchat",
        tenant_id: str = "margasari"
    ) -> Dict[str, Any]:
        text = user_text.strip()
        text_lower = text.lower()
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        today_str = datetime.datetime.now().strftime("%Y%m%d")

        # -------------------------------------------------------------
        clean_tenant = str(tenant_id or "margasari").strip().lower().replace("_", "-")
        # -------------------------------------------------------------
        # 1. LOGIKA BALE PANANGGEUHAN JABAR
        # -------------------------------------------------------------
        if clean_tenant in ("bale-pananggeuhan", "bale_pananggeuhan", "balai-pananggeuhan"):
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
                    f"📢 **Laporan Berhasil Diterbitkan**\n"
                    f"• No. Tiket : `{ticket_id}`\n"
                    f"• Instansi  : {category}\n"
                    f"• Status    : **OPEN** (Menunggu Tindak Lanjut)\n\n"
                    f"Laporan Anda telah diteruskan ke Posko Balai Pananggeuhan Gedung Sate untuk segera dikoordinasikan dengan dinas terkait."
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
                        "💳 **Biaya:** Gratis (Rp 0)"
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
                        "💳 **Biaya:** Gratis (Rp 0)"
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
                    "Sampurasun! Saya asisten virtual Balai Pananggeuhan Jawa Barat.\n\n"
                    "Anda dapat menanyakan syarat dokumen kependudukan (KTP, KK, Bansos) atau melaporkan keluhan fasilitas umum (PDAM bocor, listrik PLN padam, jalan rusak/PJU)."
                ),
                "type": "information",
                "ticket": None
            }

        # -------------------------------------------------------------
        # 2. LOGIKA KELURAHAN MARGASARI (KEC. BUAHBATU, KOTA BANDUNG)
        # -------------------------------------------------------------
        # Eskalasi / Pengaduan warga Margasari
        aduan_words = ["lapor", "aduan", "pungli", "keluhan", "sampah liar", "sengketa"]
        if any(w in text_lower for w in aduan_words):
            ticket_id = f"MGS-{today_str}-{random.randint(1000, 9999)}"
            kategori = "Seksi Trantib & Kebersihan" if "sampah" in text_lower else "Loket Pelayanan Kelurahan"
            new_ticket = {
                "id": ticket_id,
                "waktu": now_str,
                "aduan": text,
                "kategori": kategori,
                "status": "OPEN"
            }
            if "kelurahan-margasari" not in TENANT_TICKETS_STORE:
                TENANT_TICKETS_STORE["kelurahan-margasari"] = []
            TENANT_TICKETS_STORE["kelurahan-margasari"].insert(0, new_ticket)

            msg = (
                f"📢 **Laporan Pengaduan Warga Margasari Diterima**\n"
                f"• No. Registrasi : `{ticket_id}`\n"
                f"• Bidang Penanganan: {kategori}\n"
                f"• Status: **OPEN** (Menunggu Tindak Lanjut Pamong Kelurahan)\n\n"
                f"Laporan Bapak/Ibu Warga telah diteruskan ke Seksi terkait di Kantor Kelurahan Margasari (Jl. Cipagalo Girang No. 09) untuk segera ditindaklanjuti.\n\n"
                f"🌐 Pantau status pengaduan di: https://app.boontrack.com/margasari"
            )
            return {"reply": msg, "type": "ticket", "ticket": new_ticket, "is_escalated": True}

        # Knowledge Matching
        provider = PublicServiceKnowledgeProvider(tenant_id=clean_tenant)
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
                f"💳 **Biaya:** {svc['cost']}\n\n"
                f"📍 *Lokasi Pelayanan:* Kantor Kelurahan Margasari, Jl. Cipagalo Girang No. 09, Kec. Buahbatu, Kota Bandung (Senin - Jumat, 08:00 - 15:00 WIB)\n\n"
                f"🌐 *Portal Resmi Pelayanan Warga:* https://app.boontrack.com/margasari"
            )
            return {"reply": reply_text, "type": "information", "ticket": None}

        # Default Kelurahan Margasari Welcome
        return {
            "reply": (
                "Sampurasun! Selamat datang Bapak/Ibu Warga di layanan resmi Loket Digital Kelurahan Margasari, Kec. Buahbatu, Kota Bandung.\n\n"
                "📍 *Kantor Kelurahan:* Jl. Cipagalo Girang No. 09, Margasari (Senin - Jumat, 08:00 - 15:00 WIB)\n"
                "👨‍💼 *Lurah Margasari:* Wahyu A. Affandi, S.IP., M.Si.\n"
                "🌐 *Portal Resmi:* https://app.boontrack.com/margasari\n\n"
                "Silakan sampaikan kebutuhan administrasi kependudukan atau surat pengantar Bapak/Ibu, seperti:\n"
                "• Aktivasi IKD / KTP Online Digital\n"
                "• Surat Keterangan Domisili & Usaha (SKDU / SKU)\n"
                "• Pengantar KTP-el / Kartu Keluarga (KK)\n"
                "• Surat Pengantar Nikah (Model N1 - N4)\n"
                "• Surat Keterangan Tidak Mampu (SKTM)\n"
                "• Layanan Kebersihan & Kawasan Bebas Sampah (KBS Margasari)\n"
                "• Akta Kelahiran & Akta Kematian"
            ),
            "type": "information",
            "ticket": None
        }


# Singleton Instance
public_service_service = PublicServiceService()
