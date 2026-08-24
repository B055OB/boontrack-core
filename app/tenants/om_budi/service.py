import json
import logging
import os
import aiohttp
from typing import Dict, Any, Optional

logger = logging.getLogger("OM_BUDI_SERVICE")

KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))

USER_STATES: Dict[str, str] = {}


class OmBudiService:
    def __init__(self):
        self.kb = self._load_knowledge_base()

    def _load_knowledge_base(self) -> Dict[str, Any]:
        try:
            with open(KB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[KB LOAD ERROR] {e}")
            return {"faq_data": [], "rag_knowledge_clusters": []}

    def clear_session(self, phone_number: str):
        """Reset session cache nomor user."""
        if phone_number in USER_STATES:
            del USER_STATES[phone_number]

    def _retrieve_relevant_chunks(self, query: str) -> str:
        """Pencarian materi RAG berdasarkan topik kluster PDF."""
        query_words = set(query.lower().split())
        matched_chunks = []
        for cluster in self.kb.get("rag_knowledge_clusters", []):
            content = cluster.get("content", "")
            topic = cluster.get("topic", "")
            match_score = sum(1 for w in query_words if w in content.lower() or w in topic.lower())
            if match_score > 0:
                matched_chunks.append((match_score, content))

        matched_chunks.sort(key=lambda x: x[0], reverse=True)
        top_chunks = [c[1] for c in matched_chunks[:3]]
        return "\n\n---\n\n".join(top_chunks) if top_chunks else ""

    async def _generate_rag_response(self, user_name: str, message: str, context_chunks: str) -> str:
        """Memanggil LLM dengan System Prompt & Guardrails Ringkas (Max 250 Tokens)."""
        if not GEMINI_API_KEY:
            return (
                f"Assalamu'alaikum Warahmatullahi Wabarakatuh Kak *{user_name}*.\n\n"
                "Bersama Om Budi, kita berikhtiar memperbaiki hubungan dengan Allah melalui sholat tepat waktu, "
                "riyadhoh sholawat jibril 1.000x, dan pembersihan batin agar sumbatan rezeki terurai.\n\n"
                "Tetap istiqomah dalam ikhtiar langit ya Kak."
            )

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        system_instruction = (
            "Anda adalah Asisten AI Resmi Om Budi (Alumni Kelas Riyadhoh Sholawat & Quantum Energi).\n"
            "PANDUAN MENJAWAB:\n"
            "1. Persona: Islami, ramah, sejuk, santun, menyejukkan, penuh empati.\n"
            "2. Panjang Jawaban: Ringkas maksimal 2-3 paragraf pendek (to the point, batasi di bawah 250 token).\n"
            "3. RAG Context: Berpatokan pada konteks modul PDF 'Riyadhoh Sholawat + Quantum Energi' yang disediakan.\n"
            "4. Proaktif Sedekah: Jika user berniat/bertanya sedekah di tengah chat bebas, jangan cuma terima kasih, "
            "wajib sertakan rekening BSI 7200-1122-3344 a.n Sedekah Om Budi dan minta bukti transfer.\n"
            "5. Fallback Guardrail: Jika pertanyaan di luar modul PDF, jawab santun: "
            "'Untuk pertanyaan di luar modul ini, yuk kita bahas bersama di sesi Zoom Booster berikutnya ya Kak. Tetap istiqomah!'"
        )

        user_content = f"Nama Jamaah: {user_name}\n\nKonteks Modul Riyadhoh:\n{context_chunks}\n\nPertanyaan Jamaah: {message}"

        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "maxOutputTokens": 250,
                "temperature": 0.3
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    else:
                        err_msg = await resp.text()
                        logger.error(f"[LLM API ERROR] Status {resp.status}: {err_msg}")
        except Exception as e:
            logger.error(f"[LLM GEN EXCEPTION] {e}")

        return (
            f"Alhamdulillah Kak *{user_name}*, tetap istiqomah dalam ikhtiar langit bersama Om Budi. "
            "Perbaiki sholat di awal waktu, dawamkan sholawat jibril 1.000x, dan jaga hati senantiasa berprasangka baik kepada Allah."
        )

    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        button_id: Optional[str] = None,
        user_name: str = "Kakak",
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg"
    ) -> Dict[str, Any]:
        """Entry point pengelolaan pesan multi-menu & multimodal OCR."""
        state = USER_STATES.get(phone_number, "IDLE")
        clean_text = (message_text or "").strip().lower()

        # =========================================================================
        # 1. OCR Multimodal: Handler Bukti Transfer / Struk QRIS BSI
        # =========================================================================
        if image_bytes:
            from app.services.receipt_ocr_service import analyze_receipt_image
            ocr_res = await analyze_receipt_image(image_bytes, image_mime)

            if ocr_res.get("is_valid_receipt"):
                nominal = ocr_res.get("nominal", 0)
                ref_no = ocr_res.get("reference_no_rrn", "-")
                merchant = ocr_res.get("bank_source", "BSI / QRIS")
                USER_STATES[phone_number] = "IDLE"
                
                reply = (
                    f"Alhamdulillah wa Syukurillah, Kak *{user_name}*! 🤲\n\n"
                    f"Bukti transaksi/sedekah berhasil diverifikasi oleh sistem:\n"
                    f"• *Nominal:* Rp{nominal:,}\n"
                    f"• *Tujuan/Channel:* {merchant}\n"
                    f"• *No. Ref / RRN:* `{ref_no}`\n\n"
                    "Semoga Allah SWT melipatgandakan rezeki, melunaskan segala amanah, dan mengalirkan keberkahan berlimpah bagi Kakak sekeluarga. Aamiin ya Rabbal 'Alamin."
                )
                buttons = [{"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]
                return {"type": "buttons", "reply": reply, "buttons": buttons}
            else:
                buttons = [
                    {"id": "btn_sub_2_e", "title": "Kirim Ulang Bukti"},
                    {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}
                ]
                return {
                    "type": "buttons",
                    "reply": "Gambar belum terdeteksi sebagai bukti transfer yang valid. Pastikan nominal, tanggal, dan nomor referensi transaksi terlihat jelas ya Kak.",
                    "buttons": buttons
                }

        # Reset / Kembali ke Menu Utama
        if button_id == "btn_menu_utama" or clean_text in ["menu", "start", "halo", "hai", "assalamu'alaikum", "assalamualaikum", "p"]:
            USER_STATES[phone_number] = "IDLE"
            menu_text = (
                f"Assalamu'alaikum Warahmatullahi Wabarakatuh Kak *{user_name}* 🙏\n\n"
                "Selamat datang di Portal Alumni *Bimbingan Om Budi* (Riyadhoh Sholawat & Quantum Energi).\n\n"
                "Silakan pilih menu utama di bawah ini:"
            )
            sections = [
                {
                    "title": "Menu Utama",
                    "rows": [
                        {"id": "menu_zoom_booster", "title": "🚀 Zoom Booster", "description": "Jadwal, link, & materi live bimbingan"},
                        {"id": "menu_sedekah_berjamaah", "title": "🤲 Sedekah Berjamaah", "description": "Infaq percepatan, rekening, & konfirmasi"},
                        {"id": "menu_tanya_admin", "title": "💬 Tanya Admin", "description": "Bantuan langsung dari Tim Admin"}
                    ]
                }
            ]
            return {
                "type": "list",
                "reply": menu_text,
                "button_text": "Pilih Menu",
                "sections": sections
            }

        # =========================================================================
        # 2. SUB-MENU 1: ZOOM BOOSTER
        # =========================================================================
        if button_id == "menu_zoom_booster":
            USER_STATES[phone_number] = "IN_ZOOM_MENU"
            sections = [
                {
                    "title": "Topik Zoom Booster",
                    "rows": [
                        {"id": "btn_sub_1_a", "title": "1.a. Cara Mengikuti", "description": "Langkah bergabung ke sesi live"},
                        {"id": "btn_sub_1_b", "title": "1.b. Jadwal Zoom", "description": "Waktu & tanggal pelaksanaan"},
                        {"id": "btn_sub_1_c", "title": "1.c. Zoom Tentang Apa?", "description": "Penjelasan materi & bedah energi"},
                        {"id": "btn_sub_1_d", "title": "1.d. Siapa Bisa Ikut?", "description": "Kriteria peserta jamaah"},
                        {"id": "btn_sub_1_e", "title": "1.e. Link Masuk Zoom", "description": "Tautan resmi ruang pertemuan"},
                        {"id": "btn_sub_1_f", "title": "1.f. Rekaman Zoom", "description": "Akses video siaran ulang"},
                        {"id": "btn_sub_1_g", "title": "1.g. Tidak Bisa Live", "description": "Solusi jika berhalangan hadir"}
                    ]
                }
            ]
            return {
                "type": "list",
                "reply": "🚀 *[MENU ZOOM BOOSTER]*\n\nSilakan pilih informasi Zoom Booster yang Kakak butuhkan:",
                "button_text": "Pilih Informasi",
                "sections": sections
            }

        if button_id == "btn_sub_1_a":
            return {"type": "buttons", "reply": "📝 *1.a. Cara Mengikuti Zoom Booster*\n\n1. Pastikan aplikasi Zoom sudah terpasang di HP/Laptop.\n2. Masuk melalui tautan resmi 10-15 menit sebelum dimulai.\n3. Gunakan nama asli di akun Zoom agar mudah disapa oleh Om Budi.", "buttons": [{"id": "menu_zoom_booster", "title": "Kembali ke Zoom"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}
        
        if button_id == "btn_sub_1_b":
            return {"type": "buttons", "reply": "🗓️ *1.b. Jadwal Zoom Booster*\n\nSesi rutin diadakan setiap hari **Rabu malam & Ahad pagi** pukul 20.00 WIB. Pengingat tautan akan dikirimkan di grup WA 1 jam sebelum acara dimulai.", "buttons": [{"id": "menu_zoom_booster", "title": "Kembali ke Zoom"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}
        
        if button_id == "btn_sub_1_c":
            return {"type": "buttons", "reply": "✨ *1.c. Zoom Booster Tentang Apa?*\n\nSesi penguatan vibrasi energi, bedah sumbatan rezeki, konsultasi langsung persoalan amanah/hutang, serta bimbingan riyadhoh sholawat berjamaah bersama Om Budi.", "buttons": [{"id": "menu_zoom_booster", "title": "Kembali ke Zoom"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}
        
        if button_id == "btn_sub_1_d":
            return {"type": "buttons", "reply": "👥 *1.d. Siapa yang Bisa Mengikuti?*\n\nSeluruh alumni terdaftar kelas bimbingan Riyadhoh Sholawat & Quantum Energi Om Budi.", "buttons": [{"id": "menu_zoom_booster", "title": "Kembali ke Zoom"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}
        
        if button_id == "btn_sub_1_e":
            return {"type": "buttons", "reply": "🔗 *1.e. Link & Cara Masuk Zoom*\n\nLink Ruang Pertemuan:\n👉 *https://zoom.us/j/boontrack-ombudi*\nPasscode: *SHOLAWAT*\n\n_Buka tautan di atas saat jam acara dimulai._", "buttons": [{"id": "menu_zoom_booster", "title": "Kembali ke Zoom"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}
        
        if button_id == "btn_sub_1_f":
            return {"type": "buttons", "reply": "📹 *1.f. Materi / Rekaman Zoom*\n\nRekaman video sesi sebelumnya diunggah maksimal 1x24 jam ke Google Drive / Portal Alumni. Tautan akses tersedia di grup bimbingan.", "buttons": [{"id": "menu_zoom_booster", "title": "Kembali ke Zoom"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}
        
        if button_id == "btn_sub_1_g":
            return {"type": "buttons", "reply": "🤝 *1.g. Jika Tidak Bisa Hadir Live*\n\nTidak perlu khawatir Kak, Kakak tetap bisa menyimak siaran ulang rekaman dan tetap mendawamkan riyadhoh sholawat harian secara mandiri.", "buttons": [{"id": "menu_zoom_booster", "title": "Kembali ke Zoom"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        # =========================================================================
        # 3. SUB-MENU 2: SEDEKAH BERJAMAAH
        # =========================================================================
        if button_id == "menu_sedekah_berjamaah":
            USER_STATES[phone_number] = "IN_SEDEKAH_MENU"
            sections = [
                {
                    "title": "Menu Sedekah Berjamaah",
                    "rows": [
                        {"id": "btn_sub_2_a", "title": "2.a. Apa Itu Sedekah?", "description": "Tujuan & keutamaan amalan"},
                        {"id": "btn_sub_2_b", "title": "2.b. Cara Mengikuti", "description": "Alur penyaluran sedekah"},
                        {"id": "btn_sub_2_c", "title": "2.c. Jadwal Sedekah", "description": "Waktu penyaluran amalan"},
                        {"id": "btn_sub_2_d", "title": "2.d. Rekening & QRIS", "description": "No Rekening BSI & QRIS"},
                        {"id": "btn_sub_2_e", "title": "2.e. Kirim Bukti Transfer", "description": "Upload struk untuk verifikasi"},
                        {"id": "btn_sub_2_f", "title": "2.f. Belum Terdata?", "description": "Cek status mutasi / bantuan"},
                        {"id": "btn_sub_2_g", "title": "2.g. Siapa Bisa Ikut?", "description": "Peserta sedekah berjamaah"}
                    ]
                }
            ]
            return {
                "type": "list",
                "reply": "🤲 *[MENU SEDEKAH BERJAMAAH]*\n\nSilakan pilih informasi sedekah berjamaah di bawah ini:",
                "button_text": "Pilih Informasi",
                "sections": sections
            }

        if button_id == "btn_sub_2_a":
            return {"type": "buttons", "reply": "🤲 *2.a. Sedekah Berjamaah Itu Apa?*\n\nGerakan ikhtiar langit bersama untuk mempercepat lunasnya amanah hutang dan membuka pintu rezeki dengan menyalurkan bantuan kepada yatim, dhuafa, dan orang tua.", "buttons": [{"id": "menu_sedekah_berjamaah", "title": "Kembali ke Sedekah"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        if button_id == "btn_sub_2_b":
            return {"type": "buttons", "reply": "📌 *2.b. Cara Mengikuti Sedekah Berjamaah*\n\n1. Transfer nominal ke rekening resmi BSI Om Budi.\n2. Niatkan: *'Ya Allah, saya niatkan sedekah ini agar Engkau mudahkan lunasnya hutangku dan derasnya rezekiku.'*\n3. Kirimkan foto bukti transfer ke chat ini.", "buttons": [{"id": "btn_sub_2_d", "title": "Lihat Rekening BSI"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        if button_id == "btn_sub_2_c":
            return {"type": "buttons", "reply": "⏰ *2.c. Jadwal Sedekah Berjamaah*\n\nPenyaluran dilakukan rutin setiap hari Jumat berkah subuh kepada yayasan anak yatim dan dhuafa binaan.", "buttons": [{"id": "menu_sedekah_berjamaah", "title": "Kembali ke Sedekah"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        if button_id == "btn_sub_2_d" or "rekening" in clean_text or "qris" in clean_text:
            USER_STATES[phone_number] = "WAITING_RECEIPT"
            rekening_info = (
                "💳 *REKENING RESMI & QRIS SEDEKAH / BIMBINGAN*\n\n"
                "🏦 *Bank Syariah Indonesia (BSI)*\n"
                "No. Rekening: *7200-1122-3344*\n"
                "Atas Nama: *BoonTrack / Sedekah Om Budi*\n\n"
                "Atau scan QRIS resmi di atas.\n\n"
                "Setelah mentransfer, silakan *kirimkan foto / screenshot struk bukti transfer* langsung ke chat ini untuk verifikasi otomatis."
            )
            return {"type": "buttons", "reply": rekening_info, "buttons": [{"id": "btn_sub_2_e", "title": "Kirim Bukti Transfer"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        if button_id == "btn_sub_2_e":
            USER_STATES[phone_number] = "WAITING_RECEIPT"
            return {"type": "text", "reply": "📸 *Kirim Bukti Transfer*\n\nSilakan lampirkan dan kirimkan foto struk transfer / tangkapan layar m-banking Anda sekarang. AI akan memverifikasinya secara otomatis."}

        if button_id == "btn_sub_2_f":
            return {"type": "buttons", "reply": "🔍 *2.f. Sudah Transfer tapi Belum Terdata?*\n\nSilakan kirimkan ulang foto struk transfer atau hubungi Admin agar tim kami dapat melakukan pengecekan mutasi manual.", "buttons": [{"id": "menu_tanya_admin", "title": "Hubungi Admin"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        if button_id == "btn_sub_2_g":
            return {"type": "buttons", "reply": "👥 *2.g. Siapa yang Bisa Mengikuti?*\n\nTerbuka untuk seluruh jamaah, alumni, maupun keluarga yang ingin berikhtiar membersihkan sumbatan rezeki.", "buttons": [{"id": "menu_sedekah_berjamaah", "title": "Kembali ke Sedekah"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        # =========================================================================
        # 4. SUB-MENU 3: TANYA ADMIN (HUMAN HANDOVER)
        # =========================================================================
        if button_id == "menu_tanya_admin" or "tanya admin" in clean_text or "hubungi admin" in clean_text:
            USER_STATES[phone_number] = "HUMAN_HANDOVER"
            logger.info(f"[HANDOVER] Pengguna {phone_number} dialihkan ke antrean CS Human Admin.")
            handover_reply = (
                f"💬 *[BANTUAN TIM ADMIN OM BUDI]*\n\n"
                f"Pertanyaan Kakak *{user_name}* telah diteruskan ke antrean Tim Admin kami.\n\n"
                "Silakan ketikkan detail pertanyaan atau kendala Kakak di bawah ini. Tim kami akan segera merespons."
            )
            return {"type": "buttons", "reply": handover_reply, "buttons": [{"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        # Jika user sedang dalam mode Handover dan mengirim chat
        if state == "HUMAN_HANDOVER":
            return {
                "type": "buttons",
                "reply": f"Pesan Kakak: *\"{message_text}\"* telah dicatat di sistem admin. Mohon ditunggu ya Kak.",
                "buttons": [{"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]
            }

        # =========================================================================
        # 5. INTENT SEDEKAH PROAKTIF DI TENGAH CHAT BEBAS
        # =========================================================================
        if any(k in clean_text for k in ["mau sedekah", "infaq", "transfer sedekah", "nomor rekening", "minta rekening", "bayar kelas"]):
            USER_STATES[phone_number] = "WAITING_RECEIPT"
            reply_sedekah = (
                f"MasyaAllah Tabarakallah, niat mulia Kak *{user_name}* sangat kami sambut hangat.\n\n"
                "Berikut rekening resmi penyaluran sedekah bimbingan:\n\n"
                "🏦 *Bank Syariah Indonesia (BSI)*\n"
                "No. Rekening: *7200-1122-3344*\n"
                "Atas Nama: *BoonTrack / Sedekah Om Budi*\n\n"
                "Mohon *kirimkan foto struk bukti transfer* ke chat ini setelah transaksi berhasil ya Kak."
            )
            return {"type": "buttons", "reply": reply_sedekah, "buttons": [{"id": "btn_sub_2_e", "title": "Kirim Bukti Transfer"}, {"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]}

        # =========================================================================
        # 6. RAG KNOWLEDGE BASE (TANYA JAWAB BEBAS PDF 2026)
        # =========================================================================
        rag_context = self._retrieve_relevant_chunks(clean_text)
        if not rag_context:
            rag_context = (
                "Prinsip Utama: Sholat awal waktu, sholawat jibril 1000x, istighfar petang, senyum sebelum tidur & bangun pagi 10 detik, "
                "jurnal syukur, proposal doa, hindari mengeluh dan berprasangka buruk."
            )

        ai_reply = await self._generate_rag_response(user_name, message_text, rag_context)
        buttons = [{"id": "btn_menu_utama", "title": "↩️ Menu Utama"}]
        return {"type": "buttons", "reply": ai_reply, "buttons": buttons}


om_budi_service = OmBudiService()