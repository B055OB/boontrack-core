import json
import logging
import os
from typing import Dict, Any, Optional
from app.core.ai.fallback.matcher import LocalKnowledgeMatcher
from app.core.ai.fallback.confidence import MatchConfidence
from app.core.messaging.templates import REKENING_OM_BUDI, ZOOM_INFO_OM_BUDI

logger = logging.getLogger("OM_BUDI_SERVICE")
KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
MEMBERS_PATH = os.path.join(os.path.dirname(__file__), "alumni_members.json")


class OmBudiService:
    def __init__(self):
        self.rules = self._load_rules()
        self.matcher = LocalKnowledgeMatcher(self.rules)
        self.fallback_msg = (
            "Assalamu'alaikum Warahmatullahi Wabarakatuh Bapak/Ibu 🙏😊\n\n"
            "Mohon maaf yang sebesar-besarnya, saat ini kami belum bisa menjawab pertanyaan Bapak/Ibu secara langsung 🙏.\n\n"
            "Pesan dan pertanyaan Bapak/Ibu sudah kami tampung ke dalam catatan tim bimbingan 😊. Semoga Allah SWT senantiasa memudahkan urusan dan memberikan jalan keluar terbaik atas setiap ikhtiar Bapak/Ibu sekeluarga 🤲🙏.\n\n"
            "_Bapak/Ibu juga dapat membahas hal ini langsung pada sesi Zoom Booster bersama Om Budi setiap Rabu malam ya 😊_"
        )

    def _load_rules(self) -> list:
        try:
            with open(KB_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("rules", [])
        except Exception as e:
            logger.error(f"[KB LOAD ERROR] {e}")
            return []

    def _load_members(self) -> set:
        try:
            if not os.path.exists(MEMBERS_PATH):
                return set()
            with open(MEMBERS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("members", []))
        except Exception as e:
            logger.error(f"[MEMBERS LOAD ERROR] {e}")
            return set()

    def _save_member(self, clean_phone: str):
        try:
            members = self._load_members()
            members.add(clean_phone)
            with open(MEMBERS_PATH, "w", encoding="utf-8") as f:
                json.dump({"members": list(members)}, f, indent=2)
            logger.info(f"[ALUMNI REGISTERED] Phone {clean_phone} successfully whitelisted.")
        except Exception as e:
            logger.error(f"[SAVE MEMBER ERROR] {e}")

    def _clean_phone(self, phone: str) -> str:
        return "".join(filter(str.isdigit, str(phone or "")))

    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        button_id: Optional[str] = None,
        user_name: str = "Bapak/Ibu",
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg"
    ) -> Dict[str, Any]:
        clean_text = (message_text or "").strip().lower()
        clean_phone = self._clean_phone(phone_number)

        # 1. OCR Multimodal Verifikasi Struk Pendaftaran / Sedekah
        if image_bytes:
            from app.services.receipt_ocr_service import analyze_receipt_image
            ocr_res = await analyze_receipt_image(image_bytes, image_mime)
            if ocr_res.get("is_valid_receipt"):
                nominal = ocr_res.get("nominal", 0)
                ref_no = ocr_res.get("reference_no_rrn", "-")
                merchant = ocr_res.get("bank_source", "BSI / Mandiri (Budi Yulianto)")
                
                # Otomatis aktivasi status alumni
                self._save_member(clean_phone)
                
                reply = (
                    f"Alhamdulillah wa Syukurillah, Bapak/Ibu *{user_name}*! 🤲😊\n\n"
                    f"Bukti transfer sebesar *Rp{nominal:,}* (Ref: `{ref_no}`) ke *{merchant}* telah terverifikasi 🙏.\n\n"
                    "Status keanggotaan Kelas Bimbingan Anda telah *AKTIF*. Sekarang Anda memiliki akses penuh ke seluruh panduan materi, konsultasi bot, dan tautan Zoom Booster rutin 🤲."
                )
                return {
                    "type": "buttons",
                    "reply": reply,
                    "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
                }
            else:
                return {
                    "type": "buttons",
                    "reply": "Bukti transfer belum terbaca jelas 🙏. Mohon kirimkan ulang foto struk dengan nominal dan rekening tujuan yang terlihat jelas ya 😊.",
                    "buttons": [
                        {"id": "btn_cara_sedekah", "title": "Kirim Ulang Bukti"},
                        {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                    ]
                }

        # 2. Token Aktivasi Mandiri Khusus Anggota Grup Alumni
        if "aktifkan alumni om budi" in clean_text or button_id == "btn_claim_alumni":
            self._save_member(clean_phone)
            welcome_alumni = (
                f"Alhamdulillah wa Syukurillah! Selamat datang kembali Bapak/Ibu *{user_name}* 🙏😊\n\n"
                "Nomor Anda telah berhasil terverifikasi sebagai **Alumni Resmi Kelas Bimbingan Om Budi** 🤲.\n\n"
                "Seluruh fitur konsultasi materi 5 modul, jadwal live, rekaman, dan link Zoom Booster kini sudah aktif sepenuhnya."
            )
            return {
                "type": "buttons",
                "reply": welcome_alumni,
                "buttons": [
                    {"id": "menu_zoom_booster", "title": "🚀 Zoom Booster"},
                    {"id": "menu_tanya_materi", "title": "💬 Tanya Materi"},
                    {"id": "menu_sedekah_berjamaah", "title": "🤲 Sedekah"}
                ]
            }

        # 3. Handle Tombol / Teks Menu Utama & Reset
        if button_id == "btn_menu_utama" or clean_text in [
            "menu", "start", "halo", "hai", "assalamu'alaikum", 
            "assalamualaikum", "p", "🏠 menu utama", "menu utama"
        ]:
            menu_text = (
                f"Assalamu'alaikum Warahmatullahi Wabarakatuh Bapak/Ibu *{user_name}* 🙏😊\n\n"
                "Portal Bimbingan *Om Budi Channel* siap mendampingi ikhtiar Anda.\n\n"
                "Silakan pilih menu yang ingin diakses:"
            )
            return {
                "type": "buttons",
                "reply": menu_text,
                "buttons": [
                    {"id": "menu_zoom_booster", "title": "🚀 Zoom Booster"},
                    {"id": "menu_sedekah_berjamaah", "title": "🤲 Sedekah"},
                    {"id": "menu_tanya_materi", "title": "💬 Tanya Materi"}
                ]
            }

        # 4. Handle Tombol / Teks Tanya Materi
        if button_id == "menu_tanya_materi" or "tanya materi" in clean_text:
            return {
                "type": "text",
                "reply": (
                    "💬 *Ruang Tanya Materi Bimbingan*\n\n"
                    "Silakan ketik langsung pertanyaan Anda seputar materi bimbingan "
                    "(contoh: *'berapa rakaat sholat dhuha'*, *'langkah keluar hutang'*, "
                    "atau *'pantangan audio brainwave'*).\n\n"
                    "Bot akan langsung menjawab seketika 😊🙏."
                )
            }

        # 5. Handle Tombol & Sub-Menu Zoom Booster
        if button_id == "menu_zoom_booster" or "zoom booster" in clean_text:
            sections = [
                {
                    "title": "Informasi Zoom Booster",
                    "rows": [
                        {"id": "btn_sub_1_a", "title": "Cara Mengikuti", "description": "Langkah bergabung ke sesi live"},
                        {"id": "btn_sub_1_b", "title": "Jadwal Zoom", "description": "Waktu & tanggal pelaksanaan"},
                        {"id": "btn_sub_1_c", "title": "Tentang Zoom Booster", "description": "Penjelasan materi & bedah energi"},
                        {"id": "btn_sub_1_d", "title": "Peserta yang Bisa Ikut", "description": "Kriteria peserta jamaah"},
                        {"id": "btn_sub_1_e", "title": "Link Masuk Zoom", "description": "Tautan resmi ruang pertemuan"},
                        {"id": "btn_sub_1_f", "title": "Materi & Rekaman Zoom", "description": "Akses video siaran ulang"},
                        {"id": "btn_sub_1_g", "title": "Tidak Bisa Hadir Live", "description": "Solusi jika berhalangan hadir"}
                    ]
                }
            ]
            return {
                "type": "list",
                "reply": "🚀 *[MENU ZOOM BOOSTER]*\n\nSilakan pilih topik informasi yang Bapak/Ibu butuhkan:",
                "button_text": "Pilih Informasi",
                "sections": sections
            }

        zoom_nav = [
            {"id": "menu_zoom_booster", "title": "📋 Topik Zoom"},
            {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
        ]

        if button_id == "btn_sub_1_a" or "cara mengikuti" in clean_text:
            return {"type": "buttons", "reply": "📝 *Cara Mengikuti Zoom Booster*\n\n1. Pasang aplikasi Zoom di HP/Laptop.\n2. Masuk tautan 10-15 menit sebelum mulai.\n3. Gunakan nama asli agar mudah disapa Om Budi 😊.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_b" or "jadwal zoom" in clean_text:
            return {"type": "buttons", "reply": "🗓️ *Jadwal Zoom Booster*\n\nSesi rutin diadakan setiap hari **Rabu malam** pukul 20.00 WIB 🙏.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_c" or "tentang zoom" in clean_text:
            return {"type": "buttons", "reply": "✨ *Tentang Zoom Booster*\n\nSesi penguatan vibrasi energi, bedah sumbatan rezeki, konsultasi langsung, serta bimbingan riyadhoh sholawat bersama Om Budi 😊.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_d" or "peserta" in clean_text:
            return {"type": "buttons", "reply": "👥 *Peserta yang Bisa Mengikuti*\n\nSeluruh alumni terdaftar dan jamaah yang mendukung program Zoom Booster & Orang Tua Asuh 🙏.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_e" or "link masuk zoom" in clean_text or "link zoom" in clean_text:
            return {"type": "buttons", "reply": ZOOM_INFO_OM_BUDI, "buttons": zoom_nav}
        if button_id == "btn_sub_1_f" or "materi & rekaman" in clean_text:
            return {"type": "buttons", "reply": "📹 *Materi & Rekaman Zoom*\n\nRekaman video sesi sebelumnya diunggah maksimal 1x24 jam ke Portal Alumni 😊.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_g" or "tidak bisa hadir" in clean_text:
            return {"type": "buttons", "reply": "🤝 *Jika Tidak Bisa Hadir Live*\n\nTidak perlu khawatir ya 😊, Bapak/Ibu tetap bisa menyimak siaran ulang rekaman dan mendawamkan amalan secara mandiri 🙏.", "buttons": zoom_nav}

        # 6. Handle Sedekah & Info Rekening
        if button_id == "menu_sedekah_berjamaah" or clean_text == "sedekah":
            return {
                "type": "buttons",
                "reply": "🤲 *[PROGRAM SEDEKAH BERJAMAAH]*\n\nSilakan pilih informasi yang ingin Bapak/Ibu lihat:",
                "buttons": [
                    {"id": "btn_penjelasan_sedekah", "title": "Penjelasan Sedekah"},
                    {"id": "btn_cara_sedekah", "title": "Cara Ikut Sedekah"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if button_id == "btn_penjelasan_sedekah":
            return {
                "type": "buttons",
                "reply": "🤲 *Penjelasan Sedekah Berjamaah*\n\nGerakan ikhtiar langit bersama Om Budi Channel untuk mendukung anak yatim, dakwah, dan operasional majelis ilmu 🙏😊.",
                "buttons": [
                    {"id": "btn_cara_sedekah", "title": "Cara Ikut Sedekah"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if button_id == "btn_cara_sedekah" or any(k in clean_text for k in ["rekening", "nomor rekening", "qris", "bsi", "mandiri", "transfer", "infaq"]):
            return {
                "type": "buttons",
                "reply": REKENING_OM_BUDI,
                "buttons": [
                    {"id": "btn_upload_struk", "title": "Kirim Bukti Transfer"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if button_id == "btn_upload_struk":
            return {"type": "text", "reply": "📸 *Kirim Bukti Transfer*\n\nSilakan lampirkan dan kirimkan foto struk transfer / screenshot m-banking Anda sekarang ya 🙏😊."}

        # 7. Tanya Jawab Bebas: Tier 4 Matcher Lokal
        try:
            conf, score, answer, intent = self.matcher.find_match(message_text)
            if conf in [MatchConfidence.HIGH, MatchConfidence.MEDIUM] and answer:
                return {
                    "type": "buttons",
                    "reply": answer,
                    "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
                }
        except Exception as e:
            logger.error(f"[MATCHER ERROR] {e}")

        # 8. AI Gateway Fallback (Gemini / Groq)
        try:
            from app.core.ai.gateway import ai_gateway
            gw_res = await ai_gateway.process_faq_query(
                tenant_id="om_budi",
                query=message_text,
                rules=self.rules,
                fallback_msg=self.fallback_msg,
                user_name=user_name
            )
            if gw_res and gw_res.get("reply"):
                return {
                    "type": "buttons",
                    "reply": gw_res["reply"],
                    "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
                }
        except Exception as e:
            logger.error(f"[GATEWAY ERROR] {e}")

        # 9. Fallback Penampungan Statis Terjamin
        return {
            "type": "buttons",
            "reply": self.fallback_msg,
            "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
        }


om_budi_service = OmBudiService()