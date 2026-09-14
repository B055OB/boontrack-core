"""app/services/storage/__init__.py
Storage package for BoonTrack Core.
Exports R2 client, upload_bytes, and legacy media helpers.
"""

from app.services.storage.r2 import (
    R2Client,
    r2_client,
    upload_bytes,
    upload_bytes_async,
    upload_media_to_r2,
    upload_qris_to_r2,
)

__all__ = [
    "R2Client",
    "r2_client",
    "upload_bytes",
    "upload_bytes_async",
    "upload_media_to_r2",
    "upload_qris_to_r2",
]
