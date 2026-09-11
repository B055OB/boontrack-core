"""
app/services/storage.py
=======================
Cloudflare R2 storage service untuk BoonTrack.

Menangani upload file/media ke Cloudflare R2 menggunakan boto3 (S3-compatible API).
Mengembalikan URL publik file yang di-upload.

Environment variables yang diperlukan:
    R2_ENDPOINT_URL        – Endpoint Cloudflare R2, contoh: https://<accountid>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID       – R2 API Token Access Key ID
    R2_SECRET_ACCESS_KEY   – R2 API Token Secret Access Key
    R2_BUCKET_NAME         – Nama bucket (default: boontrack-media)
    R2_PUBLIC_URL          – Public base URL bucket (default: https://pub-cdf9b905df884053a60ef8bdb777d463.r2.dev)
"""

import logging
import os
import uuid
from pathlib import PurePosixPath
from typing import Optional

logger = logging.getLogger("R2_STORAGE")

# ── Environment ─────────────────────────────────────────────────────────────
R2_ENDPOINT_URL: Optional[str] = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID: Optional[str] = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY: Optional[str] = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "boontrack-media")
R2_PUBLIC_URL: str = os.getenv(
    "R2_PUBLIC_URL",
    "https://pub-cdf9b905df884053a60ef8bdb777d463.r2.dev",
).rstrip("/")


def _get_r2_client():
    """
    Inisialisasi dan kembalikan boto3 S3 client yang dikonfigurasi untuk Cloudflare R2.
    Menggunakan path-style URL dan region 'auto' sesuai requirement Cloudflare.
    """
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise ImportError(
            "boto3 tidak terinstall. Jalankan: pip install boto3"
        ) from exc

    if not R2_ENDPOINT_URL:
        raise EnvironmentError(
            "R2_ENDPOINT_URL belum di-set. Tambahkan ke environment variables."
        )
    if not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY:
        raise EnvironmentError(
            "R2_ACCESS_KEY_ID dan R2_SECRET_ACCESS_KEY harus di-set."
        )

    client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(s3={"addressing_style": "path"}),
    )
    return client


def upload_media_to_r2(
    file_bytes: bytes,
    file_name: str,
    content_type: str = "image/jpeg",
) -> str:
    """
    Upload file/media ke Cloudflare R2 dan kembalikan URL publik-nya.

    Args:
        file_bytes:   Raw bytes dari file yang akan di-upload.
        file_name:    Nama file asli (dipakai untuk mengambil ekstensinya).
        content_type: MIME type file, default "image/jpeg".

    Returns:
        URL publik lengkap file yang sudah di-upload, contoh:
        https://pub-cdf9b905df884053a60ef8bdb777d463.r2.dev/media/abc123.jpg

    Raises:
        EnvironmentError: Jika env vars R2 belum di-set.
        ImportError:      Jika boto3 belum terinstall.
        Exception:        Jika upload ke R2 gagal.
    """
    # Ambil ekstensi dari nama file asli (termasuk titik, misal ".jpg")
    suffix = PurePosixPath(file_name).suffix or ".bin"
    unique_key = f"media/{uuid.uuid4().hex}{suffix}"

    client = _get_r2_client()

    try:
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=unique_key,
            Body=file_bytes,
            ContentType=content_type,
        )
        logger.info(f"[R2] Upload sukses: {unique_key} ({len(file_bytes)} bytes)")
    except Exception as exc:
        logger.error(f"[R2] Upload gagal untuk '{unique_key}': {exc}")
        raise

    public_url = f"{R2_PUBLIC_URL}/{unique_key}"
    return public_url


# ── Public API ───────────────────────────────────────────────────────────────
__all__ = [
    "upload_media_to_r2",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_URL",
]
