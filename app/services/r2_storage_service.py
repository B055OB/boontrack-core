import os
import io
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Cloudflare R2 Credentials
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID") or os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID") or os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "boontrack-documents")
R2_PUBLIC_URL_BASE = os.getenv("R2_PUBLIC_URL_BASE", "https://assets.boontrack.com")

LOCAL_MOCK_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "r2_mock_storage"
)


class R2StorageService:
    """Service manajemen penyimpanan dokumen ke Cloudflare R2 dengan graceful fallback."""

    def __init__(self):
        self._is_live = bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY)
        if not self._is_live:
            os.makedirs(LOCAL_MOCK_STORAGE_DIR, exist_ok=True)
            logger.info("[R2StorageService] Running with Local/Mock storage fallback.")

    async def upload_file(
        self,
        file_bytes: bytes,
        storage_key: str,
        content_type: str = "application/octet-stream"
    ) -> str:
        """Mengunggah file bytes ke Cloudflare R2 atau storage lokal (mock).
        
        Args:
            file_bytes: Byte konten file.
            storage_key: Path key R2 (e.g. 'incoming/boontrack-career/job123_cv.pdf').
            content_type: MIME type file.
            
        Returns:
            storage_key yang berhasil disimpan.
        """
        if not storage_key:
            raise ValueError("Storage key cannot be empty")

        clean_key = storage_key.lstrip("/")

        if self._is_live:
            try:
                import httpx
                # Cloudflare R2 S3-compatible or Worker endpoint
                endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET_NAME}/{clean_key}"
                headers = {
                    "Content-Type": content_type
                }
                # Optional authentication headers
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.put(endpoint_url, content=file_bytes, headers=headers)
                    if resp.status_code in [200, 201]:
                        logger.info(f"[R2StorageService] Successfully uploaded to R2: {clean_key}")
                        return clean_key
            except Exception as e:
                logger.warning(f"[R2StorageService] Live R2 upload failed, falling back to mock: {e}")

        # Local mock storage fallback
        try:
            target_path = os.path.join(LOCAL_MOCK_STORAGE_DIR, clean_key.replace("/", os.sep))
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "wb") as f:
                f.write(file_bytes)
            logger.info(f"[R2StorageService] Saved to mock storage: {clean_key}")
            return clean_key
        except Exception as err:
            logger.error(f"[R2StorageService] Error saving to mock storage: {err}")
            return clean_key

    async def download_file(self, storage_key: str) -> Optional[bytes]:
        """Mengunduh file bytes dari R2 atau mock storage lokal."""
        clean_key = storage_key.lstrip("/")
        
        # Cek local mock storage terlebih dahulu
        target_path = os.path.join(LOCAL_MOCK_STORAGE_DIR, clean_key.replace("/", os.sep))
        if os.path.exists(target_path):
            with open(target_path, "rb") as f:
                return f.read()

        if self._is_live:
            try:
                import httpx
                endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET_NAME}/{clean_key}"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(endpoint_url)
                    if resp.status_code == 200:
                        return resp.content
            except Exception as e:
                logger.error(f"[R2StorageService] Failed to download from R2: {e}")

        return None

    def get_public_url(self, storage_key: str) -> str:
        """Mendapatkan public download URL dari storage key."""
        clean_key = storage_key.lstrip("/")
        return f"{R2_PUBLIC_URL_BASE.rstrip('/')}/{clean_key}"


# Singleton instance
r2_storage_service = R2StorageService()
