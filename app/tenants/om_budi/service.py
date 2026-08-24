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

# Knowledge Base Internal Fallback (Proporsional & Mandiri saat API Limit)
KNOWLEDGE_RULES = {
    "materi": (
        "Bismillah, materi *Kelas Online Bimbingan Om Budi* berfokus pada perbaikan tauhid, vibrasi energi batin, dan ikhtiar langit untuk mengurai sumbatan rezeki.\n\n"
        "Materi utama bimbingan meliputi:\n"
        "1. *Fondasi Tauhid & Sholat Awal Waktu*: Memperbaiki hubungan dasar dengan Allah.\n"
        "2. *Riyadhoh Sholawat Jibril 1.000x*: Pembersihan energi negatif dan pembuka pintu kemudahan.\n"
        "3. *Quantum Energi & Vibrasi Syukur*: Melepaskan dendam, trauma rezeki, dan prasangka buruk.\n"
        "4. *Penyusunan Proposal Doa*: Menyusun hajat spesifik dan terstruktur dengan adab yang benar.\n"
        "5. *Amalan Penunjang*: Sholat Dhuha 4 rakaat, Tahajjud, dan Sedekah Berjamaah.\n\n"
        "Semua materi dirancang praktis agar bisa langsung diamalkan dalam kehidupan sehari-hari."
    ),
    "proposal doa": (
        "Bismillah, perihal *Proposal Doa* dalam ikhtiar Riyadhoh Om Budi, ini adalah metode menuliskan hajat secara spesifik dan penuh adab di hadapan Allah SWT.\n\n"
        "Berikut urutan penyusunannya:\n"
        "1. Awali dengan memuji Allah melalui Asmaul Husna (seperti Ya Mujib, Ya Razzaq, Ya Fattah).\n"
        "2. Baca Sholawat Nabi sebagai pembuka dan pengantar doa.\n"
        "3. Lakukan pengakuan dosa dan kelemahan diri dengan istighfar.\n"
        "4. Tuliskan hajat secara jelas, detail, dan sertakan niat baik penggunaannya.\n"
        "5. Akhiri dengan kepasrahan total (tawakal) atas ketetapan terbaik-Nya.\n\n"
        "Semoga Allah mengijabah setiap butir hajat yang Bapak/Ibu ikhtiarkan."
    ),
    "mindset": (
        "Bismillah, membangun *Mindset Doa yang Mudah Terkabul* berakar pada penyelarasan energi batin dan ketauhidan kepada Allah SWT.\n\n"
        "Poin penting yang perlu dijaga:\n"
        "1. *Husnudzon & Yakin 100%*: Percaya penuh tanpa ragu bahwa Allah Maha Mengabulkan doa pada waktu yang tepat.\n"
        "2. *Pembersihan Batin*: Lepaskan rasa dendam, amarah, dan keluh kesah dengan memaafkan semua orang secara tulus.\n"
        "3. *Vibrasi Syukur*: Fokus mensyukuri apa yang sudah ada saat ini agar menarik energi kelimpahan.\n"
        "4. *Fokus Solusi*: Jangan memelihara rasa cemas atau takut, melainkan fokus pada kemahabesaran pertolongan Allah.\n\n"
        "Tetap jaga kebersihan hati dan optimisme dalam berikhtiar langit."
    ),
    "dhuha": (
        "Bismillah, untuk amalan *Sholat Dhuha Pembuka Rezeki* dalam panduan bimbingan Om Budi, dianjurkan melaksanakannya minimal **4 Rakaat** (dikerjakan dengan 2 rakaat salam, lalu 2 rakaat salam).\n\n"
        "Waktu pelaksanaannya adalah sekitar pukul 08.00 hingga 11.00 WIB. Niatkan ibadah ini semata-mata untuk mendekatkan diri kepada Allah, menghidupkan rasa syukur, dan membuka pintu keberkahan rezeki halal dari segala arah.\n\n"
        "Semoga amalan dhuha Bapak/Ibu senantiasa istiqomah dan membawa ketenangan hidup."
    ),
    "sholawat": (
        "Bismillah, amalan utama dalam bimbingan ini adalah mendawamkan *Sholawat Jibril* (*'Shallallahu 'Ala Muhammad'*) minimal **1.000x setiap hari** secara konsisten.\n\n"
        "Amalan ini berfungsi sebagai wasilah membersihkan energi negatif dalam diri, menenangkan pikiran, serta menarik pertolongan dan kelapangan rezeki dari arah yang tidak disangka-sangka.\n\n"
        "Dawamkan dengan hati yang hadir dan penuh cinta kepada Rasulullah SAW."
    ),
    "tahajjud": (
        "Bismillah, *Sholat Tahajjud & Hajat* merupakan puncak ikhtiar langit di sepertiga malam terakhir (sekitar pukul 02.30 - 04.00 WIB).\n\n"
        "Dikerjakan minimal 2 rakaat Tahajjud ditambah 2 rakaat Hajat dan ditutup Witir. Manfaatkan waktu hening ini untuk membaca Proposal Doa dan bermunajat menumpahkan segala keluh kesah hanya kepada Allah SWT."
    )
}


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

        combined_prompt = f"""Anda adalah Asisten AI Bimbingan Om Budi Channel (Riyadhoh Sholawat & Quantum Energi).

ATURAN PANJANG & FORMAT JAWABAN (WAJIB DIIKUTI):
1. Panjang Jawaban: Proporsional sedang (2 sampai 3 paragraf pendek, sekitar 100 - 150 kata).
2. Jangan terlalu singkat (jangan hanya 1-2 kalimat).
3. Jangan terlalu panjang (hindari membuat teks berbelit-belit).
4. Struktur Jawaban:
   - Paragraf 1: Sambutan Islami yang santun, sejuk, dan langsung menjawab inti pertanyaan.
   - Paragraf 2: Poin-poin praktis amalan/langkahnya (maksimal 3-4 butir poin ringkas).
   - Paragraf 3: Kalimat penutup berisi doa penguat dan motivasi ikhtiar.
5. Sapa jamaah secara ramah (Bapak/Ibu atau Kakak {user_name}).
6. Jika pertanyaan sama sekali di luar materi ikhtiar bimbingan, arahkan untuk dibahas bersama pada sesi Zoom Booster hari Rabu malam.

[SUMBER MATERI RIYADHOH OM BUDI]:
{context_chunks}

[PERTANYAAN JAMAAH]:
{message}"""

        # 1. Panggilan Gemini Flash REST API
        if gemini_key:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": combined_prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 400,
                    "temperature": 0.3
                }
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(endpoint, json=payload, timeout=15) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                        else:
                            logger.warning(f"[GEMINI API STATUS] {resp.status}")
            except Exception as e:
                logger.warning(f"[GEMINI RAG EXCEPTION] {e}")

        # 2. Panggilan Cadangan Groq LLaMA-3.1
        if groq_key:
            try:
                groq_url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                groq_payload = {
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": "Anda adalah Asisten AI Bimbingan Om Budi yang memberikan jawaban proporsional 2-3 paragraf sedang."},
                        {"role": "user", "content": combined_prompt}
                    ],
                    "max_tokens": 400,
                    "temperature": 0.3
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post(groq_url, headers=headers, json=groq_payload, timeout=12) as g_resp:
                        if g_resp.status == 200:
                            g_data = await g_resp.json()
                            return g_data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"[GROQ RAG EXCEPTION] {e}")

        # 3. Dynamic Knowledge Extraction Fallback jika API habis limit/offline
        clean_msg = message.lower()
        for key, answer in KNOWLEDGE_RULES.items():
            if key in clean_msg:
                return answer

        return (
            f"Bismillah Bapak/Ibu *{user_name}*, perihal ikhtiar langit bersama Om Budi, kunci utamanya adalah menjaga keselarasan antara doa dan kebersihan batin.\n\n"
            "Berikut panduan amalan hariannya:\n"
            "1. Jaga sholat 5 waktu tepat pada awal waktu.\n"
            "2. Dawamkan sholawat jibril minimal 1.000x setiap hari.\n"
            "3. Bersihkan batin dengan memaafkan dan senantiasa bersyukur.\n\n"
            "Semoga Allah SWT mempermudah segala urusan dan mengalirkan rezeki berkah berlimpah untuk keluarga."
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

        # 1. OCR Multimodal Bukti Transfer
        if image_bytes:
            from app.services.receipt_ocr_service import analyze_receipt_image
            ocr_res = await analyze_receipt_image(image_bytes, image_mime)

            if ocr_res.get("is_valid_receipt"):
                nominal = ocr_res.get("nominal", 0)
                ref_no = ocr_res.get("reference_no_rrn", "-")
                merchant = ocr_res.get("bank_source", "BSI / Mandiri (Budi Yulianto)")

                reply = (
                    f"Alhamdulillah wa Syukurillah, Bapak/Ibu *{user_name}*! 🤲\n\n"
                    f"Bukti transfer sebesar *Rp{nominal:,}* (Ref: `{ref_no}`) ke *{merchant}* telah berhasil diverifikasi oleh sistem.\n\n"
                    "InsyaAllah kami doakan khusus semoga Allah SWT melimpahkan keberkahan, kesehatan lahir batin, "
                    "kelapangan rezeki, serta melunaskan segala amanah hutang Bapak/Ibu sekeluarga. Aamiin ya Rabbal 'Alamin.\n\n"
                    "Tautan Group Khusus Zoom Booster (setiap Rabu malam) akan segera kami kirimkan ke nomor ini."
                )
                return {"type": "buttons", "reply": reply, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}
            else:
                return {
                    "type": "buttons",
                    "reply": "Gambar belum terdeteksi sebagai bukti transfer yang valid. Pastikan nominal, tanggal, dan nomor rekening tujuan (Budi Yulianto) terlihat jelas ya.",
                    "buttons": [{"id": "btn_cara_sedekah", "title": "Kirim Ulang Bukti"}, {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
                }

        # 2. Reset / Menu Utama
        if button_id == "btn_menu_utama" or clean_text in ["menu", "start", "halo", "hai", "assalamu'alaikum", "assalamualaikum", "p"]:
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

        # 3. Sub-Menu: Zoom Booster (List Menu)
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
            return {
                "type": "list",
                "reply": "🚀 *[MENU ZOOM BOOSTER]*\n\nSilakan pilih topik informasi yang Bapak/Ibu butuhkan:",
                "button_text": "Pilih Informasi",
                "sections": sections
            }

        # Tombol navigasi ganda untuk sub-menu Zoom Booster (Topik Zoom & Menu Utama)
        zoom_nav_buttons = [
            {"id": "menu_zoom_booster", "title": "📋 Topik Zoom"},
            {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
        ]

        if button_id == "btn_sub_1_a":
            return {"type": "buttons", "reply": "📝 *Cara Mengikuti Zoom Booster*\n\n1. Pastikan aplikasi Zoom sudah terpasang di HP/Laptop.\n2. Masuk melalui tautan resmi 10-15 menit sebelum dimulai.\n3. Gunakan nama asli di akun Zoom agar mudah disapa oleh Om Budi.", "buttons": zoom_nav_buttons}
        if button_id == "btn_sub_1_b":
            return {"type": "buttons", "reply": "🗓️ *Jadwal Zoom Booster*\n\nSesi rutin diadakan setiap hari **Rabu malam** pukul 20.00 WIB. Pengingat tautan akan dikirimkan di grup khusus 1 jam sebelum acara dimulai.", "buttons": zoom_nav_buttons}
        if button_id == "btn_sub_1_c":
            return {"type": "buttons", "reply": "✨ *Tentang Zoom Booster*\n\nSesi penguatan vibrasi energi, bedah sumbatan rezeki, konsultasi langsung persoalan amanah/hutang, serta bimbingan riyadhoh sholawat berjamaah bersama Om Budi.", "buttons": zoom_nav_buttons}
        if button_id == "btn_sub_1_d":
            return {"type": "buttons", "reply": "👥 *Peserta yang Bisa Mengikuti*\n\nSeluruh alumni terdaftar dan jamaah yang mendukung program Zoom Booster & Orang Tua Asuh.", "buttons": zoom_nav_buttons}
        if button_id == "btn_sub_1_e":
            return {"type": "buttons", "reply": "🔗 *Link & Cara Masuk Zoom*\n\nLink Ruang Pertemuan:\n👉 *https://zoom.us/j/boontrack-ombudi*\nPasscode: *SHOLAWAT*\n\n_Buka tautan di atas saat jam acara dimulai._", "buttons": zoom_nav_buttons}
        if button_id == "btn_sub_1_f":
            return {"type": "buttons", "reply": "📹 *Materi & Rekaman Zoom*\n\nRekaman video sesi sebelumnya diunggah maksimal 1x24 jam ke Portal Alumni / Google Drive.", "buttons": zoom_nav_buttons}
        if button_id == "btn_sub_1_g":
            return {"type": "buttons", "reply": "🤝 *Jika Tidak Bisa Hadir Live*\n\nTidak perlu khawatir, Bapak/Ibu tetap bisa menyimak siaran ulang rekaman dan tetap mendawamkan amalan riyadhoh secara mandiri.", "buttons": zoom_nav_buttons}

        # 4. Sub-Menu: Sedekah Berjamaah
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
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if button_id == "btn_cara_sedekah" or any(k in clean_text for k in ["rekening", "nomor rekening", "qris", "bsi", "mandiri", "transfer", "infaq"]):
            return {
                "type": "buttons",
                "reply": REKENING_TEMPLATE,
                "buttons": [
                    {"id": "btn_upload_struk", "title": "Kirim Bukti Transfer"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if button_id == "btn_upload_struk":
            return {"type": "text", "reply": "📸 *Kirim Bukti Transfer*\n\nSilakan lampirkan dan kirimkan foto struk transfer / screenshot m-banking Anda sekarang. AI akan memverifikasi transaksi secara otomatis."}

        # 5. Sub-Menu: Tanya Materi
        if button_id == "menu_tanya_materi":
            info_text = (
                f"💬 *[TANYA JAWAB MATERI & BIMBINGAN OM BUDI]*\n\n"
                f"Silakan ketikkan pertanyaan Bapak/Ibu seputar:\n"
                "• Materi bimbingan kelas online & ikhtiar langit\n"
                "• Tata cara amalan Riyadhoh (Sholat Dhuha, Tahajjud, Hajat)\n"
                "• Dawam Sholawat Jibril 1.000x & Proposal Doa\n"
                "• Mindset doa, pembersihan batin & sumbatan rezeki\n\n"
                "Saya siap menjawab dan mendampingi ikhtiar Bapak/Ibu."
            )
            return {"type": "buttons", "reply": info_text, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}

        # 6. RAG Knowledge Base Retrieval & Execution
        rag_context = self._retrieve_relevant_chunks(clean_text)
        ai_reply = await self._generate_rag_response(user_name, message_text, rag_context)
        return {"type": "buttons", "reply": ai_reply, "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]}


om_budi_service = OmBudiService()