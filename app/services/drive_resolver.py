import json
import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "drive_catalog.json")

class DriveResolver:
    def __init__(self):
        self.catalog = self._load_catalog()

    def _load_catalog(self):
        try:
            if os.path.exists(CATALOG_PATH):
                with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"DriveResolver: Berhasil memuat {len(data)} folder/katalog Drive.")
                    return data
            logger.warning(f"DriveResolver: File katalog {CATALOG_PATH} tidak ditemukan.")
            return []
        except Exception as e:
            logger.error(f"DriveResolver: Gagal membaca katalog Drive: {str(e)}")
            return []

    def find_asset_by_query(self, user_text: str) -> Optional[Dict]:
        """
        Mencari folder/file di Drive berdasarkan kata kunci dalam obrolan user.
        """
        text_lower = user_text.lower()
        
        # 1. Cek kecocokan kata kunci langsung (sub-string match)
        for item in self.catalog:
            for kw in item.get("keywords", []):
                if kw in text_lower:
                    logger.info(f"DriveResolver: Direct match ditemukan untuk keyword '{kw}' -> {item['folder_name']}")
                    return item
                    
        # 2. Cek pemisahan kata (tokenization match)
        user_words = set(text_lower.split())
        for item in self.catalog:
            for kw in item.get("keywords", []):
                if set(kw.split()).issubset(user_words):
                    logger.info(f"DriveResolver: Token match ditemukan untuk keyword '{kw}' -> {item['folder_name']}")
                    return item

        return None
