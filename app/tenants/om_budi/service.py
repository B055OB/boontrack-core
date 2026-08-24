import json
import logging
import os
from typing import Dict, Any, Optional
from app.core.ai.fallback.matcher import LocalKnowledgeMatcher
from app.core.ai.fallback.confidence import MatchConfidence
from app.core.messaging.templates import REKENING_OM_BUDI, ZOOM_INFO_OM_BUDI

logger = logging.getLogger("OM_BUDI_SERVICE")
KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")

class OmBudiService:
    def __init__(self):
        self.rules = self._load_rules()
        self.matcher = LocalKnowledgeMatcher(self.rules)
        self.fallback_msg = (
            "Assalamu'alaikum Warahmatullahi Wabarakatuh Bapak/Ibu 🙏😊\n\n"
            "Mohon maaf yang sebesar-besarnya, saat ini kami belum bisa menjawab pertanyaan Bapak/Ibu secara langsung 🙏.\n\n"
            "Pesan dan pertanyaan Bapak/Ibu sudah kami tampung ke dalam catatan tim bimbingan 😊. Semoga Allah SWT senantiasa memudahkan urusan dan memberikan jalan keluar terbaik 🤲🙏.\n\n"
            "_Bapak/Ibu juga dapat membahas hal ini langsung pada sesi Zoom Booster bersama Om Budi setiap Rabu malam ya 😊_"
        )

    def _load_rules(self) -> list:
        try:
            with open(KB_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("rules", [])
        except Exception:
            return []

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

        # 1. OCR Multimodal Verifikasi Struk (Regex Local First -> Vision Fallback)
        if image_bytes:
            from app.services.receipt_ocr_service import analyze_receipt_image
            ocr_res = await analyze_receipt_image(image_bytes, image_mime)
            if ocr_res.get("is_valid_receipt"):
                nominal = ocr_res.get("nominal", 0)
                ref_no = ocr_res.get("reference_no_rrn", "-")
                merchant = ocr_res.get("bank_source", "BSI / Mandiri (Budi Yulianto)")
                reply = (
                    f"Alhamdulillah wa Syukurillah, Bapak/Ibu *{user_name}*! 🤲😊\n\n"
                    f"Bukti transfer sebesar *Rp{nominal:,}* (Ref: `{ref_no}`) ke *{merchant}* telah berhasil diverifikasi 🙏.\n\n"
                    "InsyaAllah kami doakan khusus semoga Allah SWT melimpahkan keberkahan dan kelapangan rezeki. Aamiin ya Rabbal 'Alamin 🤲.\n\n"
                    "Tautan Group Khusus Zoom Booster akan segera kami kirimkan ke nomor ini ya 😊."
                )
                return {"type": "buttons", "reply": reply, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}
            else:
                return {
                    "type": "buttons",
                    "reply": "Bukti transfer belum terlihat jelas 🙏. Mohon kirimkan ulang foto struk dengan nominal dan rekening tujuan yang jelas ya 😊.",
                    "buttons": [{"id": "btn_cara_sedekah", "title": "Kirim Ulang Bukti"}, {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
                }

        # 2. Reset / Menu Utama (Mode Template)
        if button_id == "btn_menu_utama" or clean_text in ["menu", "start", "halo", "hai", "assalamu'alaikum", "assalamualaikum", "p"]:
            menu_text = (
                f"Assalamu'alaikum Warahmatullahi Wabarakatuh Bapak/Ibu *{user_name}* 🙏😊\n\n"
                "Selamat datang di Portal Bimbingan *Om Budi Channel*\n\n"
                "Silakan pilih menu utama di bawah ini:"
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

        # 3. Sub-Menu: Zoom Booster (Mode Template)
        if button_id == "menu_zoom_booster":
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
            return {"type": "list", "reply": "🚀 *[MENU ZOOM BOOSTER]*\n\nSilakan pilih topik informasi yang Bapak/Ibu butuhkan:", "button_text": "Pilih Informasi", "sections": sections}

        zoom_nav = [{"id": "menu_zoom_booster", "title": "📋 Topik Zoom"}, {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
        if button_id == "btn_sub_1_a":
            return {"type": "buttons", "reply": "📝 *Cara Mengikuti Zoom Booster*\n\n1. Pasang aplikasi Zoom di HP/Laptop.\n2. Masuk tautan 10-15 menit sebelum mulai.\n3. Gunakan nama asli agar mudah disapa Om Budi 😊.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_b":
            return {"type": "buttons", "reply": "🗓️ *Jadwal Zoom Booster*\n\nSesi rutin diadakan setiap hari **Rabu malam** pukul 20.00 WIB 🙏.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_c":
            return {"type": "buttons", "reply": "✨ *Tentang Zoom Booster*\n\nSesi penguatan vibrasi energi, bedah sumbatan rezeki, konsultasi langsung, serta bimbingan riyadhoh sholawat bersama Om Budi 😊.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_d":
            return {"type": "buttons", "reply": "👥 *Peserta yang Bisa Mengikuti*\n\nSeluruh alumni terdaftar dan jamaah yang mendukung program Zoom Booster & Orang Tua Asuh 🙏.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_e":
            return {"type": "buttons", "reply": ZOOM_INFO_OM_BUDI, "buttons": zoom_nav}
        if button_id == "btn_sub_1_f":
            return {"type": "buttons", "reply": "📹 *Materi & Rekaman Zoom*\n\nRekaman video sesi sebelumnya diunggah maksimal 1x24 jam ke Portal Alumni 😊.", "buttons": zoom_nav}
        if button_id == "btn_sub_1_g":
            return {"type": "buttons", "reply": "🤝 *Jika Tidak Bisa Hadir Live*\n\nTidak perlu khawatir ya 😊, Bapak/Ibu tetap bisa menyimak siaran ulang rekaman dan mendawamkan amalan secara mandiri 🙏.", "buttons": zoom_nav}

        # 4. Sedekah & Data Kritis (Zero Hallucination Template)
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
                "buttons": [{"id": "btn_cara_sedekah", "title": "Cara Ikut Sedekah"}, {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
            }

        if button_id == "btn_cara_sedekah" or any(k in clean_text for k in ["rekening", "nomor rekening", "qris", "bsi", "mandiri", "transfer", "infaq"]):
            return {
                "type": "buttons",
                "reply": REKENING_OM_BUDI,
                "buttons": [{"id": "btn_upload_struk", "title": "Kirim Bukti Transfer"}, {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
            }

        if button_id == "btn_upload_struk":
            return {"type": "text", "reply": "📸 *Kirim Bukti Transfer*\n\nSilakan lampirkan dan kirimkan foto struk transfer / screenshot m-banking Anda sekarang ya 🙏😊."}

        # 5. Tanya Jawab Bebas -> Cek Tier 4 Matcher Lokal Dulu
        conf, score, answer, intent = self.matcher.find_match(message_text)
        if conf == MatchConfidence.HIGH and answer:
            return {"type": "buttons", "reply": answer, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}
        elif conf == MatchConfidence.MEDIUM and answer:
            return {"type": "buttons", "reply": answer, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}

        # 6. Jika Tidak Cocok di Lokal -> Alihkan ke AI Gateway (Gemini/Groq -> Fallback Statis)
        from app.core.ai.gateway import ai_gateway
        gw_res = await ai_gateway.process_faq_query(
            tenant_id="om_budi",
            query=message_text,
            rules=self.rules,
            fallback_msg=self.fallback_msg,
            user_name=user_name
        )
        return {"type": "buttons", "reply": gw_res["reply"], "buttons": [{# 5. Tanya Jawab Bebas -> Cek Tier 4 Matcher Lokal Dulu
        try:
            conf, score, answer, intent = self.matcher.find_match(message_text)
            if conf == MatchConfidence.HIGH and answer:
                return {"type": "buttons", "reply": answer, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}
            elif conf == MatchConfidence.MEDIUM and answer:
                return {"type": "buttons", "reply": answer, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}
        except Exception as e:
            logger.error(f"[MATCHER ERROR] {e}")

        # 6. Jika Tidak Match di Lokal -> Alihkan ke AI Gateway
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
                return {"type": "buttons", "reply": gw_res["reply"], "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}
        except Exception as e:
            logger.error(f"[GATEWAY ERROR] {e}")

        # 7. Guaranteed Fallback (Anti-Hening)
        return {"type": "buttons", "reply": self.fallback_msg, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}

om_budi_service = OmBudiService()