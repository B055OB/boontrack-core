import json
import os
import logging
from typing import Dict, Any, List
from app.services.delivery.delivery_service import DeliveryService
# Path import AIGateway yang benar
from app.intelligence.gateway import AIGateway 

logger = logging.getLogger(__name__)


class SolutionEngine:

    def __init__(self, assets_path: str = "data/assets.json"):
        if isinstance(assets_path, list):
            self.assets_path = "data/assets.json"
        else:
            self.assets_path = str(assets_path)

        self.assets = self._load_assets()
        # Inisialisasi AI Gateway
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
            message_lower = str(user_message).lower()

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

            # LAYER 2: Generative AI via AIGateway (Interactive CV Interviewer Mode)
            sys_prompt = (
                "Kamu adalah BoonTrack Assistant, seorang pewawancara & pembuat CV interaktif.\n\n"
                "FOKUS UTAMA:\n"
                "Tugasmu HANYA mengumpulkan data pengguna satu per satu untuk membuat CV. DILARANG KERAS memberikan ceramah, materi edukasi, atau tips karir panjang lebar di tengah proses wawancara.\n\n"
                "ATURAN ALUR PERTANYAAN (WAJIB PATUH):\n"
                "1. DILARANG memberikan daftar/list pertanyaan sekaligus.\n"
                "2. DILARANG memberikan ceramah/tips panjang seperti '1. Pahami dasar digital marketing...'. Jawab singkat dan LANGSUNG NANYA DATA BERIKUTNYA.\n"
                "3. ALUR TANYA-JAWAB:\n"
                "   - Jika baru mulai / sebut nama: Catat nama -> Tanyakan posisi/bidang kerja yang dilamar.\n"
                "   - Jika user menjawab bidang kerja (misal 'digital marketing'): Konfirmasi singkat (misal: 'Sip, posisi Digital Marketing!') -> LANGSUNG tanyakan pendidikan terakhirnya (Nama kampus/sekolah & jurusan).\n"
                "   - Jika user menjawab pendidikan: Catat -> LANGSUNG tanyakan pengalaman kerja atau organisasi terkini.\n"
                "   - Jika user menjawab pengalaman: Catat -> LANGSUNG tanyakan keahlian/skill utama.\n"
                "   - Jika SEMUAH DATA SUDAH TERKUMPUL: Baru hasilkan draft CV yang rapi.\n\n"
                "Contoh balasan saat user jawab 'digital marketing':\n"
                "'Sip, target posisi Digital Marketing! Selanjutnya, apa pendidikan terakhir kamu (nama sekolah/universitas & jurusan)?'\n\n"
                "Gunakan bahasa yang santai, ringkas, dan fokus menanyakan data."
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
