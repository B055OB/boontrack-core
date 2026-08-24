import json
import logging
import os
import aiohttp
from typing import Dict, Any, Optional

logger = logging.getLogger("OM_BUDI_SERVICE")

KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

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

    def _retrieve_relevant_chunks(self, query: str) -> str:
        """Pencarian chunk materi RAG berdasarkan relevansi topik."""
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
        """Memanggil LLM dengan System Prompt & Guardrails Asisten Om Budi."""
        if not GEMINI_API_KEY:
            return (
                f"Alhamdulillah Bapak/Ibu *{user_name}*, terima kasih telah menghubungi Bimbingan Om Budi. "
                "Mari kita dawamkan sholat awal waktu dan sholawat jibril agar Allah mudahkan urusan kita."
            )

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        system_instruction = (
            "Anda adalah Asisten AI Resmi Om Budi (Alumni Bimbingan Riyadhoh Sholawat & Quantum Energi). "
            "PANDUAN MENJAWAB:\n"
            "1. Persona: Islami, hangat, santun, menyejukkan, penuh empati, dan optimis.\n"
            "2. Panjang Jawaban: Ringkas maksimal 2 paragraf pendek.\n"
            "3. Sumber Jawaban: Utamakan konteks materi RAG yang disediakan.\n"
            "4. Guardrail / Fallback: Jika pertanyaan sama sekali di luar modul/materi bimbingan, jawab santun: "
            "'Untuk pertanyaan di luar modul ini, yuk kita bahas bersama di sesi Zoom Booster berikutnya ya Kak. Tetap istiqomah!'\n"
            "5. Jangan pernah mengarang fatwa agama."
        )

        user_content = f"Nama Jamaah: {user_name}\n\nKonteks Modul Riyadhoh:\n{context_chunks}\n\nPertanyaan Jamaah: {message}"

        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "maxOutputTokens": 300,
                "temperature": 0.3
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, timeout=20) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as e:
            logger.error(f"[LLM GEN ERROR] {e}")

        return (
            f"Alhamdulillah Bapak/Ibu {user_name}, tetap istiqomah dalam ikhtiar langit bersama Om Budi. "
            "Perbaiki sholat di awal waktu dan perbanyak sholawat jibril."
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
        """Entry point pengolahan pesan Om Budi."""
        state = USER_STATES.get(phone_number, "IDLE")

        # 1. Alur OCR Penerimaan Bukti Transfer (Multimodal)
        if image_bytes:
            from app.services.receipt_ocr_service import analyze_receipt_image
            ocr_res = await analyze_receipt_image(image_bytes, image_mime)

            if ocr_res.get("is_valid_receipt"):
                nominal = ocr_res.get("nominal", 0)
                ref_no = ocr_res.get("reference_no_rrn", "-")
                USER_STATES[phone_number] = "IDLE"
                reply = (
                    f"Alhamdulillah wa Syukurillah, Bapak/Ibu *{user_name}*! 🤲\n\n"
                    f"Bukti transfer/infaq sebesar *Rp{nominal:,}* (Ref: `{ref_no}`) telah berhasil diverifikasi oleh sistem.\n\n"
                    "Selamat bergabung di *Kelas Bimbingan Riyadhoh Sholawat & Quantum Energi Om Budi*. "
                    "Admin kami akan segera mengirimkan tautan akses materi dan jadwal Zoom Booster."
                )
                return {"type": "text", "reply": reply}
            else:
                return {
                    "type": "text",
                    "reply": "Gambar yang dikirim belum terdeteksi sebagai bukti transfer yang valid. Mohon pastikan nominal, tanggal, dan nomor referensi transaksi terlihat jelas ya Bapak/Ibu."
                }

        clean_text = (message_text or "").strip().lower()

        # 2. Interaksi Tombol / Niat Pendaftaran
        if button_id == "btn_daftar_kelas" or any(k in clean_text for k in ["daftar kelas", "mau gabung", "biaya kelas", "harga kelas", "rekening", "qris", "cara bayar"]):
            USER_STATES[phone_number] = "WAITING_PAYMENT"
            reply = (
                f"MasyaAllah, Alhamdulillah Bapak/Ibu *{user_name}*.\n\n"
                "Untuk bergabung dengan *Kelas Online Pembuka Rezeki & Tauhid* (Investasi Bimbingan: Rp200.000), silakan transfer ke rekening resmi bimbingan:\n\n"
                "🏦 *Bank Syariah Indonesia (BSI)*\n"
                "No. Rekening: *7200-1122-3344*\n"
                "Atas Nama: *BoonTrack / Bimbingan Om Budi*\n\n"
                "Setelah transfer, *kirimkan foto struk/screenshot bukti transfer* langsung ke nomor WhatsApp ini untuk verifikasi otomatis."
            )
            return {"type": "text", "reply": reply}

        if button_id == "btn_tanya_curhat":
            USER_STATES[phone_number] = "IDLE"
            reply = (
                f"Bismillah, Bapak/Ibu *{user_name}*... Silakan tuliskan apa yang sedang menjadi beban pikiran, "
                "hajat besar, atau ujian amanah yang dihadapi. Saya siap mendengarkan dan mendampingi ikhtiar Bapak/Ibu."
            )
            return {"type": "text", "reply": reply}

        # 3. Tangani Jawaban Kesiapan Transfer ("iya siap", "siap", "oke")
        if state == "WAITING_PAYMENT" and any(k in clean_text for k in ["siap", "iya", "oke", "mau bayar", "transfer", "sudah"]):
            reply = (
                f"Alhamdulillah, terima kasih atas kesiapan dan niat tulus Bapak/Ibu *{user_name}*.\n\n"
                "Silakan transfer ke *Bank Syariah Indonesia (BSI) 7200-1122-3344* a.n *BoonTrack / Bimbingan Om Budi* "
                "sebesar *Rp200.000*.\n\n"
                "Setelah transaksi selesai, silakan *kirimkan foto/tangkapan layar bukti transfer* ke chat ini ya."
            )
            return {"type": "text", "reply": reply}

        # 4. RAG Retrieval & LLM Generation
        rag_context = self._retrieve_relevant_chunks(clean_text)
        if not rag_context:
            rag_context = (
                "Prinsip Utama: Sholat awal waktu, sholawat jibril 1000x, istighfar, senyum sebelum tidur & bangun pagi, "
                "jurnal syukur, proposal doa, hindari mengeluh/berprasangka buruk."
            )

        ai_reply = await self._generate_rag_response(user_name, message_text, rag_context)
        return {"type": "text", "reply": ai_reply}


om_budi_service = OmBudiService()