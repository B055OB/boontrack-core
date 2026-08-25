import json
import logging
import os
from typing import Dict, Any, Optional
from app.core.ai.fallback.matcher import LocalKnowledgeMatcher
from app.core.ai.fallback.confidence import MatchConfidence
from app.core.messaging.templates import (
    REKENING_OM_BUDI,
    REKENING_KELAS_OM_BUDI,
    ZOOM_INFO_OM_BUDI,
    AUDIO_BRAINWAVE_OM_BUDI,
    MATERI_RIYADHOH_OM_BUDI,
    PENJELASAN_SEDEKAH_OM_BUDI,
    PENDAFTARAN_KELAS_OM_BUDI,
    PANDUAN_QRIS_OM_BUDI,
    RINGKASAN_KELAS_ONLINE_OM_BUDI,
    CARA_IKUT_SEDEKAH_OM_BUDI,
    PESERTA_ZOOM_INFO_OM_BUDI
)

logger = logging.getLogger("OM_BUDI_SERVICE")
KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
MEMBERS_PATH = os.path.join(os.path.dirname(__file__), "alumni_members.json")


def _resolve_qris_asset_path() -> str:
    """Mencari path gambar QRIS Om Budi lokal yang valid."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    candidates = [
        os.path.join(base_dir, "app", "assets", "qrisombudi.png"),
        os.path.join(base_dir, "app", "assets", "qrisombudi.jpg"),
        os.path.join(base_dir, "assets", "qrisombudi.png"),
        os.path.join(base_dir, "assets", "qrisombudi.jpg"),
        os.path.join(os.getcwd(), "app", "assets", "qrisombudi.png"),
        os.path.join(os.getcwd(), "assets", "qrisombudi.png"),
        "app/assets/qrisombudi.png",
        "assets/qrisombudi.png",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "app/assets/qrisombudi.png"


def _resolve_qris_public_url() -> str:
    """Membentuk URL HTTPS publik dinamis untuk gambar QRIS Om Budi (Meta Cloud API compliant)."""
    env_url = os.getenv("OM_BUDI_QRIS_URL") or os.getenv("QRIS_OM_BUDI_URL")
    if env_url and env_url.startswith(("http://", "https://")):
        return env_url

    public_base = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("RAILWAY_STATIC_URL")
        or os.getenv("RAILWAY_PUBLIC_DOMAIN")
        or os.getenv("DOMAIN_URL")
        or os.getenv("APP_URL")
        or "https://boontrack-core.up.railway.app"
    ).strip().rstrip("/")

    if not public_base.startswith("http"):
        public_base = f"https://{public_base}"

    return f"{public_base}/static/qrisombudi.png"


SYSTEM_PROMPT_OM_BUDI = (
    "Kamu adalah AI Admin Bimbingan Resmi Om Budi Channel.\n"
    "Tugasmu adalah menjawab pertanyaan jemaah dan alumni kelas bimbingan secara empatik, hangat, menenangkan batin, dan praktis sesuai 6 materi utama Om Budi:\n"
    "1. Jalan Sunyi Orang Berhutang (menghentikan keluhan, menyelaraskan rasa, jujur pada amanah).\n"
    "2. Riyadhoh Sholawat & Quantum Energi (Sholawat Jibril 1.000x/hari, Dhuha min 4 rakaat, Tahajud/Taubat, Sedekah Subuh, 3 Audio Brainwave).\n"
    "3. Ketika Hidup Diuji, Saatnya Kembali (ujian sebagai alarm cinta Allah, 5 tanda pertolongan dekat, istiqomah).\n"
    "4. Rencana 30 Hari Bebas Hutang (tahapan mingguan, stop hutang baru, disiplin alur uang).\n"
    "5. Sangat Sederhana Cara Praktis Lunas Hutang (10 langkah praktis lahiriah, metode snowball/avalanche, negosiasi).\n"
    "6. Yuk Keluar Dari Riba (bahaya bunga pinjol/bank, negosiasi bayar pokok, doa perlindungan).\n\n"
    "PENTING TERKAIT AUDIO BRAINWAVE & MATERI RIYADHOH:\n"
    "- Jika user meminta file/link download audio brainwave, meditasi syukur, terapi rezeki, atau materi riyadhoh, kamu WAJIB memberikan link download resmi Google Drive berikut:\n"
    "  1) Digital Prayers Quantum Ikhlas: https://drive.google.com/file/d/18GjQd8SMymV8kxfvOPodvIXNxlVLbhW9/view?usp=drivesdk\n"
    "  2) Meditasi Syukur (Kekayaan & Kesehatan): https://drive.google.com/file/d/1yw1fVPT6mpPiqj27P0qu_yiNfrTKv4tr/view?usp=drive_link\n"
    "  3) Audio Terapi Menarik Rezeki: https://drive.google.com/file/d/1zJOXiu-A-Jlh713tIvULS-tfbBBUEKLp/view?usp=drive_link\n"
    "- Jangan pernah menolak atau mengatakan 'belum memiliki link' untuk audio brainwave/riyadhoh.\n"
    "- Ingatkan pantangan: Dilarang mendengarkan saat menyetir atau mengoperasikan mesin.\n\n"
    "Aturan Format Balasan:\n"
    "- Awali jawaban dengan salam dan doa hangat: 'Bismillah, peluk hangat dan doa tulus untuk Bapak/Ibu 🙏😊'.\n"
    "- Jawab pertanyaan secara ringkas, terstruktur (gunakan bullet/nomor jika perlu), dan kuatkan tauhid jemaah.\n"
    "- Jangan mengarang dalil/teori baru di luar ajaran Om Budi.\n"
    "- Tutup balasan dengan doa kelapangan rezeki 🤲."
)


class OmBudiService:
    def __init__(self):
        self.rules = self._load_rules()
        self.matcher = LocalKnowledgeMatcher(self.rules)
        self.qris_asset_path = _resolve_qris_asset_path()
        self.qris_public_url = _resolve_qris_public_url()
        self.fallback_msg = (
            "Assalamu'alaikum Warahmatullahi Wabarakatuh Bapak/Ibu 🙏😊\n\n"
            "Mohon maaf yang sebesar-besarnya, saat ini kami belum bisa menjawab pertanyaan Bapak/Ibu secara langsung 🙏.\n\n"
            "Pesan dan pertanyaan Bapak/Ibu sudah kami tampung ke dalam catatan tim bimbingan 😊. Semoga Allah SWT senantiasa memudahkan urusan dan memberikan jalan keluar terbaik atas setiap ikhtiar Bapak/Ibu sekeluarga 🤲🙏.\n\n"
            "_Bapak/Ibu juga dapat membahas hal ini langsung pada sesi Zoom Booster bersama Om Budi setiap Rabu malam ya 😊_"
        )

    def _load_rules(self) -> list:
        try:
            with open(KB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("rules", [])
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
            try:
                from app.services.receipt_ocr_service import analyze_receipt_image
                ocr_res = await analyze_receipt_image(image_bytes, image_mime)
                if ocr_res.get("is_valid_receipt"):
                    nominal = ocr_res.get("nominal", 0)
                    ref_no = ocr_res.get("reference_no_rrn", "-")
                    merchant = ocr_res.get("bank_source", "BSI / Mandiri (Budi Yulianto)")
                    
                    self._save_member(clean_phone)
                    
                    reply = (
                        f"Alhamdulillah wa Syukurillah, Bapak/Ibu *{user_name}*! 🤲😊\n\n"
                        f"Bukti transfer sebesar *Rp{nominal:,}* (Ref: `{ref_no}`) ke *{merchant}* telah terverifikasi 🙏.\n\n"
                        "Status keanggotaan Kelas Bimbingan Anda telah *AKTIF*. Sekarang Anda memiliki akses penuh ke seluruh panduan materi, riyadhoh, dan tautan Zoom Booster rutin 🤲."
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
            except Exception as err:
                logger.error(f"[OCR PROCESSING ERROR] {err}")

        # 2. Token Aktivasi Mandiri Khusus Anggota Grup Alumni
        if "aktifkan alumni om budi" in clean_text or button_id == "btn_claim_alumni":
            self._save_member(clean_phone)
            welcome_alumni = (
                f"Alhamdulillah wa Syukurillah! Selamat datang kembali Bapak/Ibu *{user_name}* 🙏😊\n\n"
                "Nomor Anda telah berhasil terverifikasi sebagai **Alumni Resmi Kelas Bimbingan Om Budi** 🤲.\n\n"
                "Seluruh fitur konsultasi, pendaftaran kelas online, dan link Zoom Booster kini sudah aktif sepenuhnya."
            )
            return {
                "type": "buttons",
                "reply": welcome_alumni,
                "buttons": [
                    {"id": "menu_zoom_booster", "title": "🚀 Zoom Booster"},
                    {"id": "menu_sedekah_berjamaah", "title": "🤲 Sedekah"},
                    {"id": "menu_daftar_kelas", "title": "Daftar Kelas Online"}
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
                    {"id": "menu_daftar_kelas", "title": "Daftar Kelas Online"}
                ]
            }

        # 4. Handle Menu Baru: Daftar Kelas Online (Investasi Rp100.000 + 2 Pilihan Pembayaran)
        if button_id in ["menu_daftar_kelas", "btn_daftar_kelas", "menu_kelas_online", "btn_kelas_online"] or any(
            k in clean_text for k in ["daftar kelas", "kelas online", "daftar kelas online", "pendaftaran kelas", "ikut kelas", "daftar bimbingan"]
        ):
            return {
                "type": "buttons",
                "reply": RINGKASAN_KELAS_ONLINE_OM_BUDI,
                "buttons": [
                    {"id": "btn_kelas_qris", "title": "QRIS"},
                    {"id": "btn_kelas_bank", "title": "Transfer Bank"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        # 5. Handle Pilihan Pembayaran QRIS (Panduan Screenshot & Upload Galeri)
        if button_id in ["btn_kelas_qris", "btn_sedekah_qris", "btn_qris"] or any(
            k == clean_text or k in clean_text.split() for k in ["qris", "bayar qris", "scan qris", "kode qris"]
        ):
            public_url = _resolve_qris_public_url()
            return {
                "type": "image",
                "image_url": public_url,
                "image_link": public_url,
                "image_path": self.qris_asset_path,
                "image": {
                    "link": public_url,
                    "caption": PANDUAN_QRIS_OM_BUDI
                },
                "reply": PANDUAN_QRIS_OM_BUDI,
                "caption": PANDUAN_QRIS_OM_BUDI,
                "buttons": [
                    {"id": "btn_upload_struk", "title": "Kirim Bukti Transfer"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        # 6. Handle Pilihan Pembayaran Transfer Bank (Rekening Resmi & Instruksi)
        if button_id in ["btn_kelas_bank", "btn_sedekah_bank", "btn_transfer_bank"] or any(
            k in clean_text for k in ["transfer bank", "no rekening", "nomor rekening", "rekening bsi", "rekening mandiri", "transfer manual"]
        ):
            bank_reply = REKENING_KELAS_OM_BUDI if button_id == "btn_kelas_bank" else REKENING_OM_BUDI
            return {
                "type": "buttons",
                "reply": bank_reply,
                "buttons": [
                    {"id": "btn_upload_struk", "title": "Kirim Bukti Transfer"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        # 7. Handle Tombol & Sub-Menu Zoom Booster (4 Opsi Utama)
        if button_id == "menu_zoom_booster" or "zoom booster" in clean_text:
            sections = [
                {
                    "title": "Informasi Zoom Booster",
                    "rows": [
                        {"id": "btn_sub_1_a", "title": "Cara Mengikuti", "description": "Langkah bergabung ke sesi live"},
                        {"id": "btn_sub_1_b", "title": "Jadwal Zoom", "description": "Waktu & tanggal pelaksanaan"},
                        {"id": "btn_sub_1_c", "title": "Tentang Zoom Booster", "description": "Penjelasan materi & bedah energi"},
                        {"id": "btn_sub_1_d", "title": "Peserta Zoom Rabu", "description": "Kenapa Zoom tidak untuk semua?"}
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
            {"id": "menu_zoom_booster", "title": "Pilih Info Lain"},
            {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
        ]

        if button_id == "btn_sub_1_a" or "cara mengikuti" in clean_text:
            return {
                "type": "buttons",
                "reply": "📝 *Cara Mengikuti Zoom Booster*\n\n1. Pasang aplikasi Zoom Cloud Meetings di HP atau Laptop.\n2. Masuk melalui tautan Zoom resmi yang dibagikan 10-15 menit sebelum acara dimulai.\n3. Gunakan nama asli akun Zoom agar mudah disapa oleh Om Budi 😊.",
                "buttons": zoom_nav
            }
        if button_id == "btn_sub_1_b" or "jadwal zoom" in clean_text:
            return {
                "type": "buttons",
                "reply": "🗓️ *Jadwal Zoom Booster*\n\nSesi rutin bimbingan diadakan setiap hari **Rabu malam** pukul **20.00 WIB** secara live online 🙏.",
                "buttons": zoom_nav
            }
        if button_id == "btn_sub_1_c" or "tentang zoom" in clean_text:
            return {
                "type": "buttons",
                "reply": "✨ *Tentang Zoom Booster*\n\nSesi khusus penguatan vibrasi energi, bedah sumbatan rezeki, konsultasi langsung, serta bimbingan riyadhoh sholawat bersama Om Budi 😊.",
                "buttons": zoom_nav
            }
        if button_id == "btn_sub_1_d" or any(k in clean_text for k in ["peserta", "peserta zoom", "peserta zoom rabu", "kenapa zoom"]):
            return {
                "type": "buttons",
                "reply": PESERTA_ZOOM_INFO_OM_BUDI,
                "buttons": zoom_nav
            }

        # 8. Handle Sedekah & Info Pilihan Penyaluran
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

        if button_id == "btn_penjelasan_sedekah" or clean_text in ["penjelasan sedekah", "tentang sedekah"]:
            return {
                "type": "buttons",
                "reply": PENJELASAN_SEDEKAH_OM_BUDI,
                "buttons": [
                    {"id": "btn_cara_sedekah", "title": "Cara Ikut Sedekah"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if button_id == "btn_cara_sedekah" or clean_text in ["cara ikut sedekah", "cara sedekah"]:
            return {
                "type": "buttons",
                "reply": CARA_IKUT_SEDEKAH_OM_BUDI,
                "buttons": [
                    {"id": "btn_sedekah_qris", "title": "QRIS"},
                    {"id": "btn_sedekah_bank", "title": "Transfer Bank"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if any(k in clean_text for k in ["rekening", "nomor rekening", "bsi", "mandiri", "transfer", "infaq"]):
            return {
                "type": "buttons",
                "reply": REKENING_OM_BUDI,
                "buttons": [
                    {"id": "btn_upload_struk", "title": "Kirim Bukti Transfer"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        if button_id == "btn_upload_struk" or any(k in clean_text for k in ["kirim bukti", "upload struk", "bukti transfer"]):
            return {"type": "text", "reply": "📸 *Kirim Bukti Transfer*\n\nSilakan lampirkan dan kirimkan foto struk transfer / screenshot m-banking Anda sekarang ya 🙏😊."}

        # 7. Direct Keywords & Buttons untuk Audio & Materi
        audio_keywords = [
            "audio", "brainwave", "link audio", "minta audio", "kirim audio",
            "download audio", "file audio", "rekaman audio", "audio riyadhoh",
            "audio meditasi", "quantum ikhlas", "terapi rezeki", "mp3",
            "suara brainwave", "dengerin audio", "putar audio", "lagu brainwave"
        ]
        if button_id in ["btn_audio_brainwave", "btn_sub_1_h"] or any(k in clean_text for k in audio_keywords):
            return {
                "type": "text",
                "reply": AUDIO_BRAINWAVE_OM_BUDI,
                "buttons": [
                    {"id": "menu_daftar_kelas", "title": "Daftar Kelas Online"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        materi_keywords = [
            "materi riyadhoh", "buku riyadhoh", "pdf riyadhoh", "panduan riyadhoh",
            "modul riyadhoh", "jadwal riyadhoh", "tata cara riyadhoh", "amalan riyadhoh",
            "download riyadhoh", "file riyadhoh"
        ]
        if button_id == "btn_materi_riyadhoh" or any(k in clean_text for k in materi_keywords):
            return {
                "type": "text",
                "reply": MATERI_RIYADHOH_OM_BUDI,
                "buttons": [
                    {"id": "menu_daftar_kelas", "title": "Daftar Kelas Online"},
                    {"id": "btn_menu_utama", "title": "🏠 Menu Utama"}
                ]
            }

        # 8. Pencocokan Tier 4 Local Knowledge Base (Cepat & Akurat)
        try:
            conf, score, answer, intent = self.matcher.find_match(message_text)
            if conf in [MatchConfidence.HIGH, MatchConfidence.MEDIUM] and answer:
                return {
                    "type": "text",
                    "reply": answer,
                    "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
                }
        except Exception as e:
            logger.error(f"[MATCHER ERROR] {e}")

        # 9. Fallback AI Gateway (Memanggil AIGateway di app/services/ai_gateway.py)
        try:
            from app.services.ai_gateway import AIGateway
            gateway = AIGateway()
            ai_reply = await gateway.generate(
                user_message=message_text,
                context={"user_id": clean_phone, "feature": "om_budi_consultation"},
                system_prompt=SYSTEM_PROMPT_OM_BUDI
            )
            if ai_reply and len(ai_reply.strip()) > 10:
                return {
                    "type": "text",
                    "reply": ai_reply,
                    "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
                }
        except Exception as gw_err:
            logger.error(f"[AI GATEWAY ERROR] {gw_err}")

        # 10. Penampungan Pertanyaan
        return {
            "type": "buttons",
            "reply": self.fallback_msg,
            "buttons": [{"id": "btn_menu_utama", "title": "🏠 Menu Utama"}]
        }


om_budi_service = OmBudiService()