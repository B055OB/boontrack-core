import json
import logging
import os
import aiohttp
from typing import Dict, Any, Optional

logger = logging.getLogger("OM_BUDI_SERVICE")

KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")

USER_STATES: Dict[str, str] = {}

REKENING_TEMPLATE = (
    "PROGRAM SEDEKAH BERJAMAAH & ORANG TUA ASUH\n"
    "Bersama Om Budi Channel\n\n"
    "Bapak Ibu yang dirahmati Allah,\n\n"
    "Mari bersama-sama mendukung keberlangsungan dakwah, majelis ilmu, dan berbagai program kebaikan melalui Program Zoom Booster.\n\n"
    "Sesuai kesepakatan bersama, kontribusi program ini dimulai dari Rp50.000 atau lebih setiap bulan sesuai kemampuan masing-masing.\n\n"
    "Dana yang terkumpul akan kami salurkan untuk:\n"
    "✅ Anak Yatim Piatu & Program Orang Tua Asuh\n"
    "✅ Fakir Miskin & Sedekah Nasi\n"
    "✅ Guru Ngaji, Majelis Ilmu & Media Dakwah\n"
    "✅ Wakaf Al-Qur'an (event tertentu)\n"
    "✅ Operasional Zoom, Internet, dan Sarana Pendukung Dakwah\n\n"
    "💳 *Rekening Penyaluran:*\n"
    "Bank Syariah Indonesia (BSI)\n"
    "a.n. Budi Yulianto\n"
    "• Program Zoom Booster : *7251759094*\n"
    "• Program Orang Tua Asuh : *7262970951*\n\n"
    "💳 *Bank Mandiri:*\n"
    "a.n. Budi Yulianto\n"
    "• Program Zoom Booster : *1320022006077*\n\n"
    "📲 *Konfirmasi Transfer:*\n"
    "Setelah transfer, mohon kirim bukti transfer ke nomor admin ini dan ketik:\n"
    "👉 *Sudah ikut Sedekah*\n"
    "ATAU\n"
    "👉 *Sudah ikut Program Orang Tua Asuh*\n\n"
    "Insya Allah kami akan balas dengan doa khusus untuk Bapak/Ibu dan keluarga serta memberikan tautan Group Khusus Untuk Zoom yang insyaAllah dilaksanakan setiap Rabu malam.\n\n"
    "Semoga Allah melimpahkan keberkahan, kesehatan, kelapangan rezeki, serta kemudahan dalam setiap urusan.\n\n"
    "Jazakumullahu Khairan Katsiran\n"
    "Om Budi Channel 🙏"
)


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

    def _retrieve_relevant_chunks(self, query: str) -> str:
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
        gemini_key = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", "")).strip()
        groq_key = os.getenv("GROQ_API_KEY", "").strip()

        combined_prompt = f"""Anda adalah Asisten AI Resmi Om Budi Channel (Bimbingan Materi Kelas Online, Riyadhoh Sholawat, & Quantum Energi).

PANDUAN MENJAWAB:
1. Persona: Islami, ramah, sejuk, santun, hangat, dan menenangkan batin. Sapa jamaah dengan sebutan Bapak/Ibu *{user_name}*.
2. Sumber Pengetahuan: Jawab pertanyaan berdasarkan Modul Materi Kelas Online Om Budi di bawah. Berikan penjelasan yang jelas, terstruktur, dan to-the-point (maksimal 2-3 paragraf).
3. Jika ditanya tentang amalan (seperti Sholat Dhuha, Tahajjud, Sholawat Jibril 1000x, Istighfar, Proposal Doa, atau Brainwave), jelaskan tata cara dan keutamaannya secara praktis.
4. Fallback: Jika pertanyaan sama sekali tidak terkait materi ikhtiar bimbingan, arahkan untuk dibahas bersama di sesi Zoom Booster hari Rabu malam.

[MODUL KNOWLEDGE BASE OM BUDI]:
{context_chunks}

[PERTANYAAN JAMAAH]:
{message}"""

        # 1. Panggilan REST API Gemini Flash
        if gemini_key:
            # Fallback nama model untuk fleksibilitas API
            models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
            for model_name in models_to_try:
                endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [{"text": combined_prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 400,
                        "temperature": 0.2
                    }
                }
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(endpoint, json=payload, timeout=15) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                            else:
                                err_t = await resp.text()
                                logger.warning(f"[GEMINI {model_name} ERROR] Status {resp.status}: {err_t}")
                except Exception as e:
                    logger.warning(f"[GEMINI {model_name} EXCEPTION] {e}")

        # 2. Fallback Groq LLaMA-3.1
        if groq_key:
            try:
                groq_url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                groq_payload = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": "Anda adalah Asisten AI Bimbingan Materi Om Budi Channel yang ramah dan Islami."},
                        {"role": "user", "content": combined_prompt}
                    ],
                    "max_tokens": 400,
                    "temperature": 0.2
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(groq_url, headers=headers, json=groq_payload, timeout=12) as g_resp:
                        if g_resp.status == 200:
                            g_data = await g_resp.json()
                            return g_data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"[GROQ RAG EXCEPTION] {e}")

        # 3. Jawaban Kontekstual Langsung Jika Koneksi API Mengalami Kendala
        q_lower = message.lower()
        if "dhuha" in q_lower:
            return (
                f"Bismillah Bapak/Ibu *{user_name}*, dalam materi bimbingan Om Budi, amalan Sholat Dhuha sangat dianjurkan dilaksanakan minimal **4 Rakaat** (dikerjakan dengan 2 rakaat salam, lalu 2 rakaat salam).\n\n"
                "Waktu terbaik adalah saat matahari mulai naik setinggi tombak (sekitar pukul 08.00 - 11.00). Niatkan dengan tulus memohon kelapangan rezeki yang halal dan keberkahan dalam setiap urusan."
            )

        return (
            f"Alhamdulillah Bapak/Ibu *{user_name}*, kunci utama keberkahan ikhtiar langit adalah istiqomah menjaga sholat tepat waktu di awal waktu, "
            "mendawamkan sholawat jibril minimal 1.000x setiap hari, serta senantiasa membersihkan hati dari prasangka buruk."
        )

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

        # 1. OCR Bukti Transfer
        if image_bytes:
            from app.services.receipt_ocr_service import analyze_receipt_image
            ocr_res = await analyze_receipt_image(image_bytes, image_mime)

            if ocr_res.get("is_valid_receipt"):
                nominal = ocr_res.get("nominal", 0)
                ref_no = ocr_res.get("reference_no_rrn", "-")
                merchant = ocr_res.get("bank_source", "BSI / Mandiri (Budi Yulianto)")
                USER_STATES[phone_number] = "IDLE"

                reply = (
                    f"Alhamdulillah wa Syukurillah, Bapak/Ibu *{user_name}*! 🤲\n\n"
                    f"Bukti transfer sebesar *Rp{nominal:,}* (Ref: `{ref_no}`) ke *{merchant}* telah berhasil diverifikasi oleh sistem.\n\n"
                    "InsyaAllah kami doakan khusus semoga Allah SWT melimpahkan keberkahan, kesehatan lahir batin, "
                    "kelapangan rezeki, serta melunaskan segala amanah hutang Bapak/Ibu sekeluarga. Aamiin ya Rabbal 'Alamin.\n\n"
                    "Tautan Group Khusus Zoom Booster (setiap Rabu malam) akan segera kami kirimkan ke nomor ini."
                )
                return {"type": "buttons", "reply": reply, "buttons": [{"id": "btn_menu_utama", "title": "↩️ Kembali"}]}
            else:
                return {
                    "type": "buttons",
                    "reply": "Gambar belum terdeteksi sebagai bukti transfer yang valid. Pastikan nominal, tanggal, dan nomor rekening tujuan (Budi Yulianto) terlihat jelas ya.",
                    "buttons": [{"id": "btn_cara_sedekah", "title": "Kirim Ulang Bukti"}, {"id": "btn_menu_utama", "title": "↩️ Kembali"}]
                }

        # 2. Reset / Menu Utama
        if button_id == "btn_menu_utama" or clean_text in ["menu", "start", "halo", "hai", "assalamu'alaikum", "assalamualaikum", "p"]:
            USER_STATES[phone_number] = "IDLE"
            menu_text = (
                f"Assalamu'alaikum Warahmatullahi Wabarakatuh Bapak/Ibu *{user_name}* 🙏\n\n"
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

        # 3. Sub-Menu: Zoom Booster
        if button_id == "menu_zoom_booster":
            USER_STATES[phone_number] = "IN_ZOOM_MENU"
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

        if button_id == "btn_sub_1_a":
            return {"type": "buttons", "reply": "📝 *Cara Mengikuti Zoom Booster*\n\n1. Pastikan aplikasi Zoom sudah terpasang di HP/Laptop.\n2. Masuk melalui tautan resmi 10-15 menit sebelum dimulai.\n3. Gunakan nama asli di akun Zoom agar mudah disapa oleh Om Budi.", "buttons": [{"id": "menu_zoom_booster", "title": "↩️ Kembali"}]}
        if button_id == "btn_sub_1_b":
            return {"type": "buttons", "reply": "🗓️ *Jadwal Zoom Booster*\n\nSesi rutin diadakan setiap hari **Rabu malam** pukul 20.00 WIB. Pengingat tautan akan dikirimkan di grup khusus 1 jam sebelum acara dimulai.", "buttons": [{"id": "menu_zoom_booster", "title": "↩️ Kembali"}]}
        if button_id == "btn_sub_1_c":
            return {"type": "buttons", "reply": "✨ *Tentang Zoom Booster*\n\nSesi penguatan vibrasi energi, bedah sumbatan rezeki, konsultasi langsung persoalan amanah/hutang, serta bimbingan riyadhoh sholawat berjamaah bersama Om Budi.", "buttons": [{"id": "menu_zoom_booster", "title": "↩️ Kembali"}]}
        if button_id == "btn_sub_1_d":
            return {"type": "buttons", "reply": "👥 *Peserta yang Bisa Mengikuti*\n\nSeluruh alumni terdaftar dan jamaah yang mendukung program Zoom Booster & Orang Tua Asuh.", "buttons": [{"id": "menu_zoom_booster", "title": "↩️ Kembali"}]}
        if button_id == "btn_sub_1_e":
            return {"type": "buttons", "reply": "🔗 *Link & Cara Masuk Zoom*\n\nLink Ruang Pertemuan:\n👉 *https://zoom.us/j/boontrack-ombudi*\nPasscode: *SHOLAWAT*\n\n_Buka tautan di atas saat jam acara dimulai._", "buttons": [{"id": "menu_zoom_booster", "title": "↩️ Kembali"}]}
        if button_id == "btn_sub_1_f":
            return {"type": "buttons", "reply": "📹 *Materi & Rekaman Zoom*\n\nRekaman video sesi sebelumnya diunggah maksimal 1x24 jam ke Portal Alumni / Google Drive.", "buttons": [{"id": "menu_zoom_booster", "title": "↩️ Kembali"}]}
        if button_id == "btn_sub_1_g":
            return {"type": "buttons", "reply": "🤝 *Jika Tidak Bisa Hadir Live*\n\nTidak perlu khawatir, Bapak/Ibu tetap bisa menyimak siaran ulang rekaman dan tetap mendawamkan amalan riyadhoh secara mandiri.", "buttons": [{"id": "menu_zoom_booster", "title": "↩️ Kembali"}]}

        # 4. Sub-Menu: Sedekah Berjamaah
        if button_id == "menu_sedekah_berjamaah" or clean_text == "sedekah":
            USER_STATES[phone_number] = "IN_SEDEKAH_MENU"
            return {
                "type": "buttons",
                "reply": "🤲 *[PROGRAM SEDEKAH BERJAMAAH]*\n\nSilakan pilih informasi yang ingin Bapak/Ibu lihat:",
                "buttons": [
                    {"id": "btn_penjelasan_sedekah", "title": "Penjelasan Sedekah"},
                    {"id": "btn_cara_sedekah", "title": "Cara Ikut Sedekah"},
                    {"id": "btn_menu_utama", "title": "↩️ Kembali"}
                ]
            }

        if button_id == "btn_penjelasan_sedekah":
            penjelasan_text = (
                "🤲 *Penjelasan Sedekah Berjamaah & Orang Tua Asuh*\n\n"
                "Gerakan ini merupakan program ikhtiar langit bersama *Om Budi Channel* untuk mendukung kelangsungan dakwah, majelis ilmu, dan berbagai program kebaikan melalui Program Zoom Booster.\n\n"
                "Dana yang terkumpul disalurkan untuk:\n"
                "✅ Anak Yatim Piatu & Program Orang Tua Asuh\n"
                "✅ Fakir Miskin & Sedekah Nasi\n"
                "✅ Guru Ngaji, Majelis Ilmu & Media Dakwah\n"
                "✅ Wakaf Al-Qur'an (event tertentu)\n"
                "✅ Operasional Zoom, Internet, dan Sarana Pendukung Dakwah"
            )
            return {
                "type": "buttons",
                "reply": penjelasan_text,
                "buttons": [
                    {"id": "btn_cara_sedekah", "title": "Cara Ikut Sedekah"},
                    {"id": "btn_menu_utama", "title": "↩️ Kembali"}
                ]
            }

        if button_id == "btn_cara_sedekah" or any(k in clean_text for k in ["rekening", "nomor rekening", "qris", "bsi", "mandiri", "transfer", "infaq"]):
            USER_STATES[phone_number] = "WAITING_RECEIPT"
            return {
                "type": "buttons",
                "reply": REKENING_TEMPLATE,
                "buttons": [
                    {"id": "btn_upload_struk", "title": "Kirim Bukti Transfer"},
                    {"id": "btn_menu_utama", "title": "↩️ Kembali"}
                ]
            }

        if button_id == "btn_upload_struk":
            USER_STATES[phone_number] = "WAITING_RECEIPT"
            return {"type": "text", "reply": "📸 *Kirim Bukti Transfer*\n\nSilakan lampirkan dan kirimkan foto struk transfer / screenshot m-banking Anda sekarang. AI akan memverifikasi transaksi secara otomatis."}

        # 5. Tombol Tanya Materi / Konsultasi (Membuka Pintu RAG Tanya Jawab)
        if button_id in ["menu_tanya_materi", "menu_tanya_admin"]:
            USER_STATES[phone_number] = "IDLE"
            info_text = (
                f"💬 *[TANYA JAWAB MATERI & BIMBINGAN OM BUDI]*\n\n"
                f"Silakan ketikkan pertanyaan Bapak/Ibu *{user_name}* seputar:\n"
                "• Tata cara & amalan Riyadhoh (Sholat Dhuha, Tahajjud, Hajat)\n"
                "• Dawam Sholawat Jibril 1.000x & Proposal Doa\n"
                "• Pembersihan batin & penguraian sumbatan rezeki\n\n"
                "Saya siap menjawab dan mendampingi ikhtiar Bapak/Ibu."
            )
            return {"type": "buttons", "reply": info_text, "buttons": [{"id": "btn_menu_utama", "title": "↩️ Kembali"}]}

        # 6. RAG Knowledge Base Engine: Menjawab Semua Pertanyaan Bebas
        rag_context = self._retrieve_relevant_chunks(clean_text)
        if not rag_context:
            rag_context = (
                "Prinsip Utama: Sholat awal waktu, sholat dhuha 4 rakaat, tahajjud, sholawat jibril 1000x, istighfar petang, "
                "senyum 10 detik sebelum tidur & bangun pagi, jurnal syukur, proposal doa, hindari mengeluh dan berprasangka buruk."
            )

        ai_reply = await self._generate_rag_response(user_name, message_text, rag_context)
        return {"type": "buttons", "reply": ai_reply, "buttons": [{"id": "btn_menu_utama", "title": "↩️ Kembali"}]}


om_budi_service = OmBudiService()