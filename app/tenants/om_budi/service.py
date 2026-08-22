import json
import logging
import os
import re
from typing import Dict, Any, Optional

from app.services.ai_gateway import AIGateway
from app.tenants.om_budi.config import TENANT_ID, ESCALATION_KEYWORDS

logger = logging.getLogger(__name__)

OBC_SYSTEM_PROMPT = """
Anda adalah Asisten Pribadi resmi untuk Om Budi (pembimbing spiritual amalan riyadhoh sholawat, magnet rezeki, dan terapi batin).

Profil Audiens:
- Mayoritas adalah bapak-bapak atau ibu-ibu yang sedang menghadapi ujian berat (terlilit hutang, pinjol, masalah rezeki, hajat besar, kegelisahan batin).
- Sangat menghargai kesantunan dan doa.

Prinsip & Karakter:
1. Sapa santun dengan sebutan "Bapak/Ibu" (atau sebut namanya secara hangat).
2. Empatik, menyejukkan, tidak menghakimi, dan selalu mengingatkan pentingnya membenahi hubungan dengan Allah (sholat awal waktu, istighfar, amalan sholawat nabi).
3. Jika Bapak/Ibu curhat atau bertanya, jawab dengan hangat lalu sarankan kelas atau panduan batin yang cocok.
4. Gunakan bahasa Indonesia yang sangat santun, bersahaja, dan mudah dipahami.

KNOWLEDGE BASE:
{knowledge_base}
"""


class OmBudiService:
    def __init__(self, ai_gateway: Optional[AIGateway] = None):
        self.ai_gateway = ai_gateway or AIGateway()
        self.knowledge_data = self._load_fallback_knowledge()

    def _load_fallback_knowledge(self) -> Dict[str, Any]:
        kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
        try:
            if os.path.exists(kb_path):
                with open(kb_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[OM_BUDI] Gagal membaca KB: {e}")
        return {}

    def check_manual_escalation(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in ESCALATION_KEYWORDS) or "bantuan admin" in t or "bicara admin" in t

    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        button_id: Optional[str] = None,
        user_name: str = "Bapak/Ibu",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = message_text.strip()
        t_lower = text.lower()

        # 1. Cek Tombol / Pilihan Menu Interaktif
        if button_id == "BTN_KELAS" or "kelas bimbingan" in t_lower:
            msg = (
                f"Bismillah, Bapak/Ibu {user_name}... Berikut pilihan jenjang kelas bimbingan bersama Om Budi:\n\n"
                "1️⃣ *Kelas Online Pembuka Rezeki* (Rp200.000)\n"
                "• Pengenalan amalan riyadhoh, tata cara sholat tobat, dan pembersihan sumbatan rezeki.\n\n"
                "2️⃣ *Kelas Member Eksklusif* (Rp500.000)\n"
                "• Bimbingan intensif 40 hari, konsultasi berkala & akses Zoom Booster rutin.\n\n"
                "3️⃣ *Kelas Private Magnet Rezeki* (Rp1.000.000)\n"
                "• Pendampingan khusus pelunasan hutang besar & bedah pola pertolongan Allah.\n\n"
                "Silakan tekan tombol di bawah untuk memilih kelas yang ingin diikuti:"
            )
            buttons = [
                {"id": "BUY_KLS_ONLINE", "title": "Kelas Online 200rb"},
                {"id": "BUY_KLS_MEMBER", "title": "Kelas Member 500rb"},
                {"id": "BUY_KLS_MAGNET", "title": "Magnet Rezeki 1jt"}
            ]
            return {"type": "buttons", "reply": msg, "buttons": buttons}

        if button_id == "BTN_PRODUK" or "materi digital" in t_lower:
            msg = (
                f"Bismillah, Bapak/Ibu {user_name}... Berikut panduan dan sarana batin mandiri dari Om Budi:\n\n"
                "📖 *Ebook Magnet Rezeki* (Rp99.000)\n"
                "• Rahasia pola pertolongan Allah saat terhimpit hutang & cara membuka pintu rezeki.\n\n"
                "🎧 *Audio Therapy Gelombang Batin* (Rp149.000)\n"
                "• Relaksasi & dzikir penenang hati saat panik/cemas akibat beban hidup.\n\n"
                "📦 *Bundle Kit Riyadhoh 40 Hari* (Rp199.000)\n"
                "• Paket lengkap Ebook + Audio Amalan Harian.\n\n"
                "Silakan tekan tombol untuk memesan via WhatsApp:"
            )
            buttons = [
                {"id": "BUY_EBOOK", "title": "Ebook 99rb"},
                {"id": "BUY_AUDIO", "title": "Audio Terapi 149rb"},
                {"id": "BUY_BUNDLE", "title": "Kit Amalan 199rb"}
            ]
            return {"type": "buttons", "reply": msg, "buttons": buttons}

        if button_id == "BTN_KONSUL" or "tanya / curhat" in t_lower:
            return {
                "type": "text",
                "reply": (
                    f"Bismillah, Bapak/Ibu {user_name}... Silakan tuliskan apa yang sedang menjadi beban pikiran "
                    f"atau hajat yang ingin dicapai (misal perihal hutang, keluarga, atau ketenangan batin).\n\n"
                    f"Saya siap mendengarkan dan mendampingi ikhtiar Bapak/Ibu. 🙏"
                )
            }

        # 2. Handler Checkout Transaksi Langsung di WhatsApp
        if button_id and button_id.startswith("BUY_"):
            item_map = {
                "BUY_KLS_ONLINE": ("Kelas Online Pembuka Rezeki & Tauhid", "Rp200.000"),
                "BUY_KLS_MEMBER": ("Kelas Member Eksklusif Om Budi", "Rp500.000"),
                "BUY_KLS_MAGNET": ("Kelas Private Magnet Rezeki", "Rp1.000.000"),
                "BUY_EBOOK": ("Ebook Rahasia Magnet Rezeki", "Rp99.000"),
                "BUY_AUDIO": ("Audio Therapy Gelombang Batin", "Rp149.000"),
                "BUY_BUNDLE": ("Bundle Kit Riyadhoh Sholawat 40 Hari", "Rp199.000"),
            }
            item_name, item_price = item_map.get(button_id, ("Pemesanan Bimbingan", "Sesuai Pilihan"))
            return {
                "type": "text",
                "reply": (
                    f"Alhamdulillah, terima kasih niat baiknya Bapak/Ibu {user_name}. 🙏✨\n\n"
                    f"📋 *Rincian Pendaftaran / Pemesanan:*\n"
                    f"• Program: *{item_name}*\n"
                    f"• Infaq / Biaya: *{item_price}*\n\n"
                    f"💳 *Pembayaran via QRIS / Rekening Resmi Om Budi:*\n"
                    f"Bapak/Ibu dapat melakukan transfer atau scan QRIS melalui m-banking/e-wallet.\n\n"
                    f"Setelah transfer, mohon kirimkan *foto/screenshot bukti transfer* di chat ini ya Bapak/Ibu. "
                    f"Admin kami akan langsung memverifikasi dan mengirimkan akses materi/grup bimbingan."
                )
            }

        # 3. Cek Eskalasi Manual
        if self.check_manual_escalation(text):
            return {
                "type": "text",
                "reply": (
                    f"Bismillah, Bapak/Ibu {user_name}. Pesan Bapak/Ibu sudah kami tandai untuk admin manusia. "
                    f"Admin Om Budi akan segera menyapa dan membalas langsung di chat ini ya."
                ),
                "is_escalated": True
            }

        # 4. Greeting Awal Otomatis dengan Tombol jika User Baru / Menyapa Sederhana
        if t_lower in ["halo", "assalamu'alaikum", "assalamualaikum", "halo om budi", "selamat siang", "selamat pagi", "tes", "p"]:
            greeting_body = (
                f"Assalamu’alaikum Warahmatullahi Wabarakatuh.\n\n"
                f"Selamat datang Bapak/Ibu {user_name} di ruang bimbingan **Om Budi**. 😊🙏\n\n"
                f"Semoga Allah senantiasa melimpahkan ketenangan batin, kesehatan, dan melapangkan jalan rezeki untuk Bapak/Ibu sekeluarga.\n\n"
                f"Di sini, kita bersama-sama belajar membenahi hubungan dengan Allah melalui sholat tepat waktu, riyadhoh sholawat nabi, dan pembersihan batin.\n\n"
                f"Silakan tekan salah satu tombol di bawah untuk memulai:"
            )
            buttons = [
                {"id": "BTN_KELAS", "title": "Daftar Kelas Online"},
                {"id": "BTN_PRODUK", "title": "Buku & Audio Terapi"},
                {"id": "BTN_KONSUL", "title": "Tanya / Curhat"}
            ]
            return {"type": "buttons", "reply": greeting_body, "buttons": buttons}

        # 5. Tanya Jawab Bebas Menggunakan AI Gemini
        system_instruction = OBC_SYSTEM_PROMPT.format(
            knowledge_base=json.dumps(self.knowledge_data, ensure_ascii=False, indent=2)
        )
        try:
            raw_response = await self.ai_gateway.generate(
                user_message=text,
                context={"tenant": TENANT_ID, "phone": phone_number, "user_name": user_name},
                system_prompt=system_instruction,
            )
            res_str = str(raw_response).strip()
            if "```" in res_str:
                res_str = re.sub(r"^```(?:json)?|```$", "", res_str, flags=re.MULTILINE).strip()

            return {"type": "text", "reply": res_str}
        except Exception as e:
            logger.error(f"[OM_BUDI AI ERROR] {e}", exc_info=True)
            return {
                "type": "text",
                "reply": f"Bismillah, Bapak/Ibu {user_name}. Ada yang bisa kami bantu seputar amalan batin, pendaftaran kelas, atau materi panduan Om Budi?"
            }


om_budi_service = OmBudiService()