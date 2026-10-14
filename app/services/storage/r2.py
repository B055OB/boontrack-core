"""app/services/storage/r2.py
Cloudflare R2 Object Storage Client for BoonTrack Ecosystem.
Implements S3-compatible client for binary asset storage, zero egress fees,
canonical CDN public URL resolution (assets.boontrack.com), and strict Fail-Closed security.
"""

import io
import os
import uuid
import hmac
import logging
import asyncio
import posixpath
import urllib.parse
from pathlib import PurePosixPath
from typing import Union, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("R2_STORAGE")


class R2Client:
    """Cloudflare R2 S3-Compatible Client with canonical CDN distribution and Fail-Closed security."""

    def __init__(
        self,
        account_id: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        public_domain: Optional[str] = None,
    ):
        self._explicit_config = (access_key_id is not None or secret_access_key is not None)
        self.account_id = (account_id if account_id is not None else os.getenv("R2_ACCOUNT_ID", "")).strip()
        self.access_key_id = (access_key_id if access_key_id is not None else os.getenv("R2_ACCESS_KEY_ID", "")).strip()
        self.secret_access_key = (secret_access_key if secret_access_key is not None else os.getenv("R2_SECRET_ACCESS_KEY", "")).strip()
        self.bucket_name = (bucket_name if bucket_name is not None else os.getenv("R2_BUCKET_NAME", "boontrack-media")).strip()
        
        pub_domain = (public_domain or os.getenv("R2_PUBLIC_DOMAIN") or os.getenv("R2_PUBLIC_URL") or "assets.boontrack.com").strip()
        pub_domain = pub_domain.replace("https://", "").replace("http://", "").rstrip("/")
        self.public_domain = pub_domain
        self._s3_client = None

    def _refresh_credentials_if_needed(self):
        """Ensures credentials from environment are refreshed if initially empty."""
        if not self._explicit_config:
            if not self.access_key_id:
                self.access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
            if not self.secret_access_key:
                self.secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
            if not self.account_id:
                self.account_id = os.getenv("R2_ACCOUNT_ID", "").strip()

    @property
    def endpoint_url(self) -> str:
        self._refresh_credentials_if_needed()
        pure_default = f"https://{self.account_id}.r2.cloudflarestorage.com" if self.account_id else "https://r2.cloudflarestorage.com"
        override = os.getenv("R2_ENDPOINT") or os.getenv("R2_ENDPOINT_URL") or os.getenv("S3_ENDPOINT")
        if override:
            raw = override.strip().rstrip("/")
            if not raw.startswith("http://") and not raw.startswith("https://"):
                raw = f"https://{raw}"
            try:
                from urllib.parse import urlparse
                parsed = urlparse(raw)
                host = parsed.netloc.lower()
                # Guard against custom CDN domain (assets.boontrack.com / r2.dev)
                if "boontrack.com" in host or "r2.dev" in host or "r2.cloudflarestorage.com" not in host:
                    logger.warning(f"[R2] Custom domain detected in endpoint ('{host}'). Re-routing to pure R2 S3 endpoint.")
                    return pure_default
                # Guard against bucket prefix on hostname
                parts = host.split(".")
                if len(parts) >= 4 and parts[-2] == "cloudflarestorage" and parts[-1] == "com" and parts[-3] == "r2":
                    acc_part = parts[-4]
                    if acc_part and acc_part != "r2" and acc_part != self.bucket_name.lower():
                        return f"https://{acc_part}.r2.cloudflarestorage.com"
                    return pure_default
                return f"https://{host}"
            except Exception:
                return pure_default
        return pure_default

    def _get_boto_client(self):
        """Initializes and caches boto3 client for Cloudflare R2 (Strict Fail-Closed)."""
        if self._s3_client is not None:
            return self._s3_client

        self._refresh_credentials_if_needed()

        if not self.access_key_id or not self.secret_access_key:
            err_msg = "[R2 FAIL-CLOSED] Credentials missing (R2_ACCESS_KEY_ID or R2_SECRET_ACCESS_KEY not set). Fail-Closed active."
            logger.critical(err_msg)
            raise RuntimeError(err_msg)

        try:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=Config(s3={"addressing_style": "path"}),
            )
            self._s3_client = client
            return self._s3_client
        except Exception as e:
            err_msg = f"[R2 FAIL-CLOSED] Failed to initialize S3 client: {e}"
            logger.critical(err_msg)
            raise RuntimeError(err_msg)

    def upload_bytes(
        self,
        file_buffer: Union[bytes, io.BytesIO],
        destination_key: str,
        content_type: str = "application/pdf",
    ) -> str:
        """
        Uploads binary buffer directly to Cloudflare R2 and returns canonical CDN URL.
        Accepts raw bytes or in-memory io.BytesIO buffer (zero disk I/O).
        Strict Fail-Closed: Raises RuntimeError on any failure.
        """
        if isinstance(file_buffer, io.BytesIO):
            file_bytes = file_buffer.getvalue()
        elif isinstance(file_buffer, bytes):
            file_bytes = file_buffer
        elif hasattr(file_buffer, "read"):
            file_bytes = file_buffer.read()
            if isinstance(file_bytes, str):
                file_bytes = file_bytes.encode("utf-8")
        else:
            raise TypeError(f"Unsupported buffer type: {type(file_buffer)}")

        clean_key = destination_key.strip().lstrip("/")
        canonical_url = f"https://{self.public_domain}/{clean_key}"

        client = self._get_boto_client()
        try:
            client.put_object(
                Bucket=self.bucket_name,
                Key=clean_key,
                Body=file_bytes,
                ContentType=content_type,
            )
            logger.info(f"[R2] Uploaded {len(file_bytes)} bytes to '{clean_key}' -> {canonical_url}")
            return canonical_url
        except Exception as e:
            err_msg = f"[R2 FAIL-CLOSED] Failed uploading object to '{clean_key}': {e}"
            logger.error(err_msg)
            raise RuntimeError(err_msg)

    def generate_presigned_download_url(
        self,
        object_key: str,
        current_tenant_id: str,
        expires_in: int = 900,
        allow_system_namespace: bool = False,
        tenant_id: Optional[str] = None,
    ) -> str:
        """
        Generates a Presigned Download URL for a private object in Cloudflare R2.
        
        Strict Runtime Gates (CTO Directive 08 P1-H3 Mandate):
        1. Mandatory Verified Tenant Identity: current_tenant_id is strictly required.
           ZERO fallback to caller-supplied tenant_id is permitted. Missing/empty current_tenant_id
           raises ValueError immediately.
        2. Parameter Tamper Check: If tenant_id is also supplied, it MUST match current_tenant_id
           cryptographically. Any mismatch raises PermissionError.
        3. System Namespace Protection: Direct or prefixed access to 'system/' or 'tenants/system/'
           is strictly blocked for standard tenant callers. Only authorized callers with
           explicit allow_system_namespace=True can access the system namespace.
        4. Robust Path Sanitization:
           - Multi-pass URL decoding (%2e%2e, %2f, %5c, nested encodings)
           - Path separator standardization (\\ -> /)
           - Dot segment rejection (., ..)
           - Empty/whitespace path rejection
           - Posixpath normalization and root traversal rejection
        5. Cryptographic Tenant Namespace Gate: The tenant namespace extracted from the path
           MUST match current_tenant_id using constant-time comparison (hmac.compare_digest).
        6. TTL Enforcement: expires_in must be between 1 and 900 seconds (15 minutes).
        7. Fail-Closed: Zero mock fallback; raises RuntimeError on storage client failure.
        """
        # 1. Mandatory current_tenant_id validation (Fail-Secure, Zero Fallback)
        if not current_tenant_id or not str(current_tenant_id).strip():
            raise ValueError(
                "current_tenant_id is mandatory and must be provided from verified authentication context."
            )
        clean_current_tenant = str(current_tenant_id).strip().lower()

        # Parameter tamper check
        if tenant_id is not None:
            clean_param_tenant = str(tenant_id).strip().lower()
            if not hmac.compare_digest(clean_current_tenant, clean_param_tenant):
                logger.warning(
                    f"[R2_SECURITY_AUTH] Tenant parameter manipulation detected: "
                    f"current_tenant_id='{current_tenant_id}' does not match tenant_id='{tenant_id}'."
                )
                raise PermissionError(
                    f"Tenant parameter manipulation detected: caller '{current_tenant_id}' cannot request for '{tenant_id}'."
                )

        # 2. TTL Gate
        if expires_in > 900:
            raise ValueError(
                f"Presigned URL TTL cannot exceed 900 seconds (15 minutes). Requested: {expires_in}s"
            )
        if expires_in <= 0:
            raise ValueError(
                f"Presigned URL TTL must be greater than 0 seconds. Requested: {expires_in}s"
            )

        # 3. Object key sanitization & path-traversal rejection
        if object_key is None:
            raise ValueError("object_key cannot be empty.")

        raw_key = str(object_key).strip()
        if not raw_key:
            raise ValueError("object_key cannot be empty.")

        # Multi-pass URL decoding (handles %2e%2e, %2f, %5c, double encoding)
        decoded_key = raw_key
        for _ in range(3):
            prev = decoded_key
            decoded_key = urllib.parse.unquote(decoded_key)
            if decoded_key == prev:
                break

        # Standardize path separators
        norm_separators = decoded_key.replace("\\", "/")

        # Empty path check after stripping separators
        clean_stripped = norm_separators.strip("/ ")
        if not clean_stripped:
            raise ValueError("object_key cannot be empty.")

        # Reject any standalone dot segments ('.' or '..')
        raw_segments = norm_separators.split("/")
        for seg in raw_segments:
            if seg in (".", ".."):
                raise PermissionError(
                    f"Path traversal or dot segment detected in storage object key: '{object_key}'"
                )

        # Normalize with posixpath
        norm_key = posixpath.normpath(clean_stripped)
        if norm_key.startswith("..") or norm_key.startswith("/"):
            raise PermissionError(
                f"Path traversal detected in storage object key: '{object_key}'"
            )

        # Structural path decomposition
        segments = [p for p in norm_key.split("/") if p]
        if not segments:
            raise ValueError("object_key cannot be empty.")

        root_namespace = segments[0].lower()
        is_authorized = False

        if root_namespace == "system":
            if not allow_system_namespace:
                logger.warning(
                    f"[R2_SECURITY_AUTH] Access to system namespace '{norm_key}' rejected for tenant '{clean_current_tenant}' "
                    f"without explicit allow_system_namespace flag."
                )
                raise PermissionError(
                    f"Access to system namespace '{norm_key}' is restricted to internal system/admin context."
                )
            if clean_current_tenant not in ("admin_system", "system", "internal_system"):
                logger.warning(
                    f"[R2_SECURITY_AUTH] Unauthorized tenant '{clean_current_tenant}' attempted to access system namespace via allow_system_namespace."
                )
                raise PermissionError(
                    f"Tenant '{clean_current_tenant}' is not permitted to access system namespace."
                )
            is_authorized = True
        elif root_namespace in ("tenants", "videos"):
            if len(segments) < 2:
                raise PermissionError(f"Invalid private object path structure: '{norm_key}'")
            namespace_tenant = segments[1].lower()
            if root_namespace == "tenants" and namespace_tenant == "system":
                if not allow_system_namespace:
                    logger.warning(
                        f"[R2_SECURITY_AUTH] Access to tenants/system namespace '{norm_key}' rejected for tenant '{clean_current_tenant}' "
                        f"without explicit allow_system_namespace flag."
                    )
                    raise PermissionError(
                        f"Access to system namespace '{norm_key}' is restricted to internal system/admin context."
                    )
                if clean_current_tenant not in ("admin_system", "system", "internal_system"):
                    logger.warning(
                        f"[R2_SECURITY_AUTH] Unauthorized tenant '{clean_current_tenant}' attempted to access tenants/system via allow_system_namespace."
                    )
                    raise PermissionError(
                        f"Tenant '{clean_current_tenant}' is not permitted to access system namespace."
                    )
                is_authorized = True
            else:
                # Cryptographic comparison: current_tenant_id MUST match namespace tenant
                is_authorized = hmac.compare_digest(namespace_tenant, clean_current_tenant)
        else:
            raise PermissionError(
                f"Unauthorized root storage namespace '{root_namespace}'. "
                f"Only 'tenants', 'videos', or 'system' namespaces are accessible."
            )

        if not is_authorized:
            logger.warning(
                f"[R2_SECURITY_AUTH] Cross-tenant object access denied: tenant '{clean_current_tenant}' "
                f"is not authorized for object '{norm_key}' (path belongs to namespace '{segments[1] if len(segments) > 1 else 'unknown'}')."
            )
            raise PermissionError(
                f"Cross-tenant storage access forbidden: tenant '{clean_current_tenant}' "
                f"is not authorized to access private object '{norm_key}'."
            )

        client = self._get_boto_client()
        try:
            url = client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": norm_key,
                },
                ExpiresIn=expires_in,
            )
            logger.info(
                f"[R2] Generated presigned URL for '{norm_key}' (tenant '{clean_current_tenant}', TTL: {expires_in}s)"
            )
            return url
        except Exception as e:
            err_msg = f"[R2 FAIL-CLOSED] Presigned URL generation failed for '{norm_key}': {e}"
            logger.error(err_msg)
            raise RuntimeError(err_msg)

    async def upload_bytes_async(
        self,
        file_buffer: Union[bytes, io.BytesIO],
        destination_key: str,
        content_type: str = "application/pdf",
    ) -> str:
        """Asynchronous non-blocking wrapper for upload_bytes."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self.upload_bytes,
            file_buffer,
            destination_key,
            content_type,
        )

    def generate_internal_system_presigned_url(
        self,
        object_key: str,
        expires_in: int = 900,
    ) -> str:
        """
        Internal-only system helper to generate presigned download URL for system-scoped assets.
        Guaranteed to run in internal system context ('admin_system').
        Strictly isolated from tenant route callers.
        """
        return self.generate_presigned_download_url(
            object_key=object_key,
            current_tenant_id="admin_system",
            expires_in=expires_in,
            allow_system_namespace=True,
        )


# Singleton instance
r2_client = R2Client()


def upload_bytes(
    file_buffer: Union[bytes, io.BytesIO],
    destination_key: str,
    content_type: str = "application/pdf",
) -> str:
    """Global convenience helper to upload buffer to Cloudflare R2."""
    return r2_client.upload_bytes(file_buffer, destination_key, content_type)


async def upload_bytes_async(
    file_buffer: Union[bytes, io.BytesIO],
    destination_key: str,
    content_type: str = "application/pdf",
) -> str:
    """Global async convenience helper to upload buffer to Cloudflare R2."""
    return await r2_client.upload_bytes_async(file_buffer, destination_key, content_type)


def generate_presigned_download_url(
    object_key: str,
    current_tenant_id: str,
    expires_in: int = 900,
    allow_system_namespace: bool = False,
    tenant_id: Optional[str] = None,
) -> str:
    """Global convenience helper to generate presigned download URL with structural & cryptographic tenant bounds."""
    return r2_client.generate_presigned_download_url(
        object_key=object_key,
        current_tenant_id=current_tenant_id,
        expires_in=expires_in,
        allow_system_namespace=allow_system_namespace,
        tenant_id=tenant_id,
    )


def generate_internal_system_presigned_url(
    object_key: str,
    expires_in: int = 900,
) -> str:
    """Global convenience helper to generate presigned download URL for system-scoped assets."""
    return r2_client.generate_internal_system_presigned_url(
        object_key=object_key,
        expires_in=expires_in,
    )


# Backward Compatibility helpers
def upload_media_to_r2(
    file_bytes: bytes,
    file_name: str,
    content_type: str = "image/jpeg",
    folder: str = "media",
) -> str:
    clean_folder = (folder or "media").strip("/ ")
    suffix = PurePosixPath(file_name).suffix or ".bin"
    key = f"{clean_folder}/{uuid.uuid4().hex}{suffix}"
    return r2_client.upload_bytes(file_bytes, key, content_type)


def upload_qris_to_r2(
    file_bytes: bytes,
    file_name: str = "qris.png",
    content_type: str = "image/png",
) -> str:
    return upload_media_to_r2(file_bytes, file_name, content_type, folder="qris")


__all__ = [
    "R2Client",
    "r2_client",
    "upload_bytes",
    "upload_bytes_async",
    "generate_presigned_download_url",
    "generate_internal_system_presigned_url",
    "upload_media_to_r2",
    "upload_qris_to_r2",
]
