import json
import os
import logging
from typing import Dict, Any, List
from app.services.delivery.delivery_service import DeliveryService
from app.intelligence.gateway import AIGateway 

logger = logging.getLogger(__name__)


class SolutionEngine:

    def __init__(self, assets_path: str = "data/assets.json"):
        if isinstance(assets_path, list):
            self.assets_path = "data/assets.json"
        else:
            self.assets_path = str(assets_path)

        self.assets = self._load_assets()
        self.ai_gateway = AIGateway()

    def _load_assets(self) -> List[Dict[str, Any]]:
        possible_paths = [
            self.assets_path,
            "data/assets.json",
            os.path.join(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    )
                ),
                "data",
                "assets.json",
            ),
        ]

        for p in possible_paths:
            try:
                if isinstance(p, str) and os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return data
            except Exception:
                continue

        logger.warning(
            "Menggunakan fallback assets hardcoded karena file JSON tidak ditemukan."
        )
        return [
            {
                "asset_uuid": "AST-000101",
                "delivery_provider": "GOOGLE_DRIVE",
                "delivery_reference": "1HZHdlzPrud-Z3GqOtVLEt0g_Pxnsn2iK",
                "search_keywords": ["minta template", "download cv", "master template", "file cv"],
            }
        ]

    async def search(self, raw_query: str = "", **kwargs) -> Dict[str, Any]:
        return await self.find_solution(user_message=raw_query)

    async def find_solution(self, user_message: str = "") -> Dict[str, Any]:
        try:
            message_lower = str(user_message).lower().strip()

            # LAYER 1: Match Keyword Asset khusus jika user minta download file/template langsung
            for asset in self.assets:
                keywords = asset.get(
                    "search_keywords", ["minta template", "download cv", "master template", "file cv"]
                )
                if any(keyword in message_lower for keyword in keywords):
                    download_url = DeliveryService.resolve_url(asset)

                    response_text = (
                        f"Bikin CV ATS-friendly itu kuncinya simpel:\n\n"
                        f"1. Format 1 Kolom: Pakai desain bersih tanpa ikon/chart skill bertitik-titik.\n"
                        f"2. Gunakan Font Standar: Pakai Arial, Calibri, atau Helvetica ukuran 10-12pt.\n"
                        f"3. Kata Kunci Tepat: Masukkan nama skill & posisi yang persis sama dengan lowongan.\n\n"
                        f"Kamu bisa pakai master template CV ATS-Friendly siap edit yang sudah saya siapkan di sini:\n\n"
                        f"📄 Download Master Template CV ATS (Word):\n"
                        f"{download_url}\n\n"
                        f"Silakan di-download dan diedit sesuai riwayat pengalaman kamu ya! 😊"
                    )

                    return {
                        "status": "FOUND",
                        "success": True,
                        "asset_uuid": asset.get("asset_uuid", "AST-000101"),
                        "text": response_text,
                        "message": response_text,
                        "response": response_text,
                        "download_url": download_url,
                    }

            # LAYER 2: Generative AI via AIGateway (Interactive Guided Interviewer)
            sys_prompt = (
                "Kamu adalah BoonTrack Assistant, seorang konsultan karir & pembuat CV interaktif.\n\n"
                "TUGAS UTAMA:\n"
                "Klasifikasikan isi pesan pengguna berdasarkan jenis informasinya, lalu ajukan pertanyaan berikutnya. DILARANG KERAS MENGULANG PERTANYAAN YANG SAMA!\n\n"
                "PANDUAN KLASIFIKASI INPUT PENGGUNA:\n"
                "1. JIKA INPUT BERUPA PERINTAH '1' / 'BUAT CV':\n"
                "   -> Jawab: 'Siap, mari kita buat/perbarui CV kamu! Pertama-tama, boleh tahu siapa nama lengkap kamu?'\n\n"
                "2. JIKA INPUT BERUPA NAMA ORANG (misal: 'Suji', 'Rayi', 'Aldi'):\n"
                "   -> Jawab: 'Salam kenal! Selanjutnya, posisi atau bidang pekerjaan apa yang ingin kamu lamar?'\n\n"
                "3. JIKA INPUT BERUPA POSISI/PEKERJAAN/PROFESI (misal: 'sekretaris', 'admin', 'auditor', 'kasir', 'programmer', 'manager'):\n"
                "   -> DILARANG SALAM KENAL LAGI!\n"
                "   -> Jawab: 'Oke, bidang tersebut sangat menarik! Apa pendidikan terakhir kamu (Nama sekolah/kampus & jurusan)?'\n\n"
                "4. JIKA INPUT BERUPA PENDIDIKAN/SEKOLAH (misal: 'S1 ITB', 'SMA 1', 'D3 Akuntansi'):\n"
                "   -> Jawab: 'Sip! Apa pengalaman kerja terakhir atau organisasi yang pernah kamu ikuti? (Jika belum pernah kerja, ketik: belum pernah kerja)'\n\n"
                "5. JIKA INPUT BERUPA PENGALAMAN / 'BELUM PERNAH' (misal: 'belum pernah', 'PT ABC', 'Gojek'):\n"
                "   -> Jawab: 'Catatan pengalaman/organisasi dicatat! Terakhir, apa saja keahlian/skill utama atau sertifikasi yang kamu miliki?'\n\n"
                "6. JIKA INPUT BERUPA KEAHLIAN / SKILL (misal: 'microsoft office', 'koding', 'bahasa inggris'):\n"
                "   -> TAMPILKAN DRAFT STRUCTURE CV LENGKAP RAPI (Ringkasan Profil, Pendidikan, Pengalaman, Keahlian) dan tanyakan apakah ada yang perlu disesuaikan."
            )

            # Panggil method generate() milik AIGateway
            llm_res = await self.ai_gateway.generate(
                prompt=user_message, 
                system_prompt=sys_prompt
            )
            ai_reply = llm_res.text

            return {
                "status": "AI_ANSWERED",
                "success": True,
                "text": ai_reply,
                "message": ai_reply,
                "response": ai_reply,
            }

        except Exception as e:
            logger.error(f"Error pada SolutionEngine: {str(e)}")
            err_msg = "Terjadi kendala saat memproses pertanyaan kamu. Coba ulangi sebentar lagi ya! 😊"
            return {
                "status": "ERROR",
                "success": False,
                "text": err_msg,
                "message": err_msg,
                "response": err_msg,
            }
