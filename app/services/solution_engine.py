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

            # LAYER 2: Generative AI via AIGateway (Guided Interactive Interview)
            sys_prompt = (
                "Kamu adalah BoonTrack Assistant, seorang konsultan karir profesional dan interaktif.\n\n"
                "ATURAN KETAT (PERINTAH UTAMA):\n"
                "1. Kamu HARUS mewawancarai pengguna SATU PER SATU. DILARANG KERAS menanyakan lebih dari 1 hal dalam 1 pesan!\n"
                "2. DILARANG KERAS memberikan daftar/list pertanyaan sekaligus (seperti '1. Nama, 2. Pengalaman, 3. Pendidikan...').\n"
                "3. DILARANG KERAS memberikan template CV berformat placeholder seperti [Nama Anda].\n"
                "4. Jika pengguna ingin membuat CV atau memulai sesi, TANYAKAN HANYA NAMA LENGKAPNYA TERLEBIH DAHULU.\n"
                "   Contoh balasan pertama: 'Siap, mari kita buat CV kamu! Pertama-tama, siapa nama lengkap kamu?'\n"
                "5. Setelah pengguna menjawab nama, baru tanyakan 1 hal berikutnya (misal: posisi yang dilamar), dan seterusnya sampai seluruh data lengkap baru buatkan susunan CV-nya.\n\n"
                "Gunakan bahasa yang ramah, santai, empati, dan profesional."
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
