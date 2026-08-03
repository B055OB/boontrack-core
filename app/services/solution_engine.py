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
                "TUGAS UTAMA:\n"
                "Mewawancarai dan memandu pengguna secara BERTAHAP (satu per satu) untuk mengumpulkan data pembuatan CV "
                "maupun persiapan kerja, BUKAN memberikan template teks kosong sekaligus.\n\n"
                "ATURAN PERTANYAAN (GUIDED INTERVIEW):\n"
                "1. Jika pengguna ingin membuat/memperbarui CV, TANYAKAN DATA SATU PER SATU. Jangan pernah langsung memberikan template CV "
                "lengkap dengan placeholder seperti [Nama Anda] atau [Email Anda].\n"
                "2. Tanyakan HANYA 1 informasi dalam 1 pesan (Contoh: 'Untuk memulai pembuatan CV, boleh tahu nama lengkap Anda?'). "
                "Setelah pengguna menjawab, baru tanyakan data berikutnya (Kontak, Pendidikan, Pengalaman Kerja, Keahlian, dst).\n"
                "3. Setelah SELURUH data lengkap terkumpul melalui tanya-jawab bertahap, barulah susunkan CV lengkap yang sudah terisi rapi.\n\n"
                "ATURAN FORMAT BALASAN:\n"
                "- Gunakan penomoran/bullet point yang rapi jika memberikan pilihan opsi.\n"
                "- Gunakan kalimat santai, sopan, empati, dan profesional.\n"
                "- Selalu akhiri pesan dengan SATU pertanyaan spesifik atau ajakan bertindak yang jelas."
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
