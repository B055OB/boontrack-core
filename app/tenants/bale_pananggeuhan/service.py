"""app/tenants/bale_pananggeuhan/service.py
Service layer untuk pilot B2G Balé Pananggeuhan (Setda Pemprov Jawa Barat).
"""

import datetime
import logging
import random
from typing import Dict, Any, List, Optional

from app.tenants.base import BaseTenantService
from app.tenants.bale_pananggeuhan.config import (
    TENANT_ID,
    TENANT_NAME,
    DISPATCH_DEPARTMENTS,
    ESCALATION_KEYWORDS,
    WELCOME_MESSAGE,
    LOCATION,
)

logger = logging.getLogger("BALE_PANANGGEUHAN_SERVICE")


class BalePananggeuhanService(BaseTenantService):
    """Service pengaduan terpadu dan layanan informasi publik

    untuk pilot B2G Balé Pananggeuhan (Setda Pemprov Jawa Barat).
    """

    tenant_id: str = TENANT_ID
    tenant_name: str = TENANT_NAME

    def __init__(self) -> None:
        super().__init__(tenant_id=TENANT_ID, tenant_name=TENANT_NAME)
        self.tickets: List[Dict[str, Any]] = []

    def _detect_category(self, text: str) -> Dict[str, Any]:
        """Klasifikasi instansi penanggung jawab berdasarkan kata kunci aduan."""
        text_lower = text.lower()
        for dept_code, dept_data in DISPATCH_DEPARTMENTS.items():
            for kw in dept_data.get("keywords", []):
                if kw in text_lower:
                    return {
                        "code": dept_code,
                        "name": dept_data["name"],
                        "sla_hours": dept_data.get("sla_hours", 24)
                    }
        return {
            "code": "UMUM",
            "name": DISPATCH_DEPARTMENTS["UMUM"]["name"],
            "sla_hours": DISPATCH_DEPARTMENTS["UMUM"]["sla_hours"]
        }

    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Menangani pesan masuk dan aduan warga Jawa Barat."""
        clean_text = (message_text or "").strip().lower()
        clean_phone = self.clean_phone(phone_number)
        now_dt = datetime.datetime.now()
        now_str = now_dt.strftime("%Y-%m-%d %H:%M")
        today_str = now_dt.strftime("%Y%m%d")

        logger.info(f"[{TENANT_ID}] Processing message from {clean_phone}: {clean_text[:50]}")

        # 1. Konsultasi Syarat KTP-el
        if "ktp" in clean_text:
            reply = (
                "📋 *PERSYARATAN PENGURUSAN KTP-EL (JAWA BARAT)*\n\n"
                "1. Fotokopi Kartu Keluarga (KK) terbaru\n"
                "2. Surat Pengantar RT/RW (khusus pemula usia 17 tahun)\n"
                "3. KTP-el lama (jika rusak atau permohonan ganti data)\n"
                "4. Surat Keterangan Hilang Kepolisian (jika hilang)\n\n"
                "⏱️ *Estimasi:* 1 - 3 Hari Kerja\n"
                "💰 *Biaya:* Gratis (Rp 0)"
            )
            return {"reply": reply, "type": "information", "tenant_id": TENANT_ID}

        # 2. Konsultasi Syarat Kartu Keluarga (KK)
        if any(w in clean_text for w in ["kk", "kartu keluarga"]):
            reply = (
                "📋 *PERSYARATAN PEMBARUAN KARTU KELUARGA (KK)*\n\n"
                "1. Kartu Keluarga (KK) asli yang lama\n"
                "2. Buku Nikah / Akta Cerai (jika perubahan status perkawinan)\n"
                "3. Surat Keterangan Lahir (jika penambahan anggota keluarga)\n"
                "4. Surat Keterangan Pindah (jika mutasi domisili)\n\n"
                "⏱️ *Estimasi:* 3 - 5 Hari Kerja\n"
                "💰 *Biaya:* Gratis (Rp 0)"
            )
            return {"reply": reply, "type": "information", "tenant_id": TENANT_ID}

        # 3. Konsultasi Bantuan Sosial (DTKS / PKH / BPNT)
        if any(w in clean_text for w in ["bansos", "bantuan", "dtks", "pkh", "bpnt"]):
            reply = (
                "📋 *INFORMASI BANTUAN SOSIAL PEMPROV JABAR*\n\n"
                "Pengecekan dan usulan data bansos Jawa Barat terintegrasi melalui DTKS Kemensos RI.\n"
                "• Syarat: NIK KTP-el dan Nomor KK valid padan Dukcapil.\n"
                "• Usulan Baru: Dilakukan melalui Musyawarah Desa / Kelurahan setempat.\n"
                "• Portal Mandiri: Aplikasi Cek Bansos Kemensos RI.\n\n"
                "Hubungi pendamping PKH atau Posko Balé Pananggeuhan jika terdapat dugaan salah sasaran."
            )
            return {"reply": reply, "type": "information", "tenant_id": TENANT_ID}

        # 4. Deteksi Aduan Warga (Escalation / Tiket Baru)
        if any(w in clean_text for w in ESCALATION_KEYWORDS):
            ticket_id = f"PS-{today_str}-{random.randint(1000, 9999)}"
            dept_info = self._detect_category(clean_text)

            new_ticket = {
                "id": ticket_id,
                "phone": clean_phone,
                "waktu": now_str,
                "aduan": message_text.strip(),
                "kategori": dept_info["name"],
                "dept_code": dept_info["code"],
                "sla_hours": dept_info["sla_hours"],
                "status": "OPEN"
            }
            self.tickets.insert(0, new_ticket)

            reply = (
                f"🚨 *LAPORAN PENGADUAN DITERBITKAN*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🎫 *Nomor Tiket:* `{ticket_id}`\n"
                f"🏢 *Instansi Penanganan:* {dept_info['name']}\n"
                f"⏱️ *Target Respon (SLA):* {dept_info['sla_hours']} Jam\n"
                f"📊 *Status:* *OPEN (Telah Disposisikan)*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Laporan Anda telah berhasil diteruskan ke tim reaksi cepat {dept_info['name']} "
                f"melalui koordinasi {LOCATION}.\n\n"
                f"_Simpan nomor tiket Anda untuk memantau status tindak lanjut petugas._"
            )
            return {
                "reply": reply,
                "type": "ticket",
                "ticket": new_ticket,
                "is_escalated": True,
                "tenant_id": TENANT_ID
            }

        # 5. Default Welcome & Petunjuk Penggunaan
        return {
            "reply": WELCOME_MESSAGE,
            "type": "welcome",
            "tenant_id": TENANT_ID
        }


bale_pananggeuhan_service = BalePananggeuhanService()
