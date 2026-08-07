import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class DeliveryService:

    @staticmethod
    def resolve_url(asset_data: Dict[str, Any]) -> str:
        """
        Mengubah metadata reference menjadi URL siap pakai berdasarkan provider.
        Menerapkan CTO Decision #082 (Delivery Layer Abstraction).
        """
        provider = asset_data.get("delivery_provider", "GOOGLE_DRIVE").upper()
        reference = asset_data.get("delivery_reference", "")

        if not reference:
            logger.error(
                f"Delivery reference kosong untuk asset_uuid: {asset_data.get('asset_uuid')}"
            )
            return "#"

        if provider == "GOOGLE_DRIVE":
            # Menghasilkan URL Google Drive langsung dari reference ID
            return f"https://docs.google.com/document/d/{reference}/edit?usp=sharing"

        elif provider == "DIRECT":
            return reference

        else:
            # Fallback default ke Google Drive URL
            logger.warning(
                f"Provider '{provider}' tidak dikenal, fallback ke Google Drive URL."
            )
            return f"https://docs.google.com/document/d/{reference}/edit?usp=sharing"
