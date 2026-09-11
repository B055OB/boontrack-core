"""app/services/cloudflare.py
Cloudflare for SaaS (Custom Hostnames API v4) Service.

Manages tenant custom domains:
- Registration of custom hostnames with SSL (HTTP or TXT validation)
- Status verification for SSL & DNS activation
- Deletion of custom hostnames
"""

import os
import re
import logging
from typing import Optional, Dict, Any, Tuple
import httpx

logger = logging.getLogger("CLOUDFLARE_SAAS")

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_CNAME_TARGET = "shop.boontrack.com"

DOMAIN_REGEX = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)

RESERVED_DOMAINS = {
    "boontrack.com",
    "shop.boontrack.com",
    "api.boontrack.com",
    "admin.boontrack.com",
    "inbox.boontrack.com",
    "localhost",
}


def clean_domain(raw_domain: str) -> str:
    """Sanitizes raw domain input, stripping protocols, ports, and trailing paths."""
    domain = (raw_domain or "").strip().lower()
    if domain.startswith("https://"):
        domain = domain[8:]
    elif domain.startswith("http://"):
        domain = domain[7:]
    domain = domain.split("/")[0].split(":")[0].strip()
    return domain


def validate_domain_name(raw_domain: str) -> Tuple[bool, str, Optional[str]]:
    """Validates domain syntax and ensures it is not reserved."""
    domain = clean_domain(raw_domain)
    if not domain:
        return False, "", "Nama domain tidak boleh kosong."
    if domain in RESERVED_DOMAINS or domain.endswith(".boontrack.com"):
        return False, domain, f"Domain '{domain}' adalah domain internal sistem dan tidak dapat digunakan sebagai custom domain."
    if len(domain) > 253:
        return False, domain, "Domain melebihi batas panjang maksimum 253 karakter."
    if not DOMAIN_REGEX.match(domain):
        return False, domain, f"Format domain '{domain}' tidak valid. Contoh yang benar: 'toko.brandanda.com' atau 'shop.domain.id'."
    return True, domain, None


class CloudflareAPIError(Exception):
    """Custom exception for Cloudflare SaaS API errors."""
    def __init__(self, message: str, status_code: int = 400, cf_errors: Optional[list] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.cf_errors = cf_errors or []


class CloudflareCustomHostnameService:
    def __init__(self):
        self.zone_id = os.getenv("CLOUDFLARE_ZONE_ID", "").strip()
        self.api_token = (
            os.getenv("CLOUDFLARE_SAAS_API_TOKEN", "") or os.getenv("CLOUDFLARE_API_TOKEN", "")
        ).strip()
        self.cname_target = os.getenv("CLOUDFLARE_FALLBACK_ORIGIN", DEFAULT_CNAME_TARGET).strip()

    def is_configured(self) -> bool:
        """Returns True if Cloudflare zone ID and API token are provided."""
        return bool(self.zone_id and self.api_token)

    def _get_headers(self) -> Dict[str, str]:
        if not self.api_token:
            raise CloudflareAPIError(
                "CLOUDFLARE_SAAS_API_TOKEN belum dikonfigurasi di environment.",
                status_code=500
            )
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    async def create_custom_hostname(
        self,
        hostname: str,
        ssl_method: str = "http",
    ) -> Dict[str, Any]:
        """
        Registers a new custom hostname in Cloudflare for SaaS.
        Method: POST /zones/{zone_id}/custom_hostnames
        """
        valid, domain, err = validate_domain_name(hostname)
        if not valid:
            raise CloudflareAPIError(err or "Domain tidak valid", status_code=400)

        if not self.zone_id:
            raise CloudflareAPIError(
                "CLOUDFLARE_ZONE_ID belum dikonfigurasi di environment.",
                status_code=500
            )

        # Normalize SSL method ('http' or 'txt')
        method = "http" if ssl_method.lower() == "http" else "txt"

        payload = {
            "hostname": domain,
            "ssl": {
                "method": method,
                "type": "dv",
                "settings": {
                    "min_tls_version": "1.2",
                    "http2": "on"
                }
            }
        }

        url = f"{CLOUDFLARE_API_BASE}/zones/{self.zone_id}/custom_hostnames"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=self._get_headers(), json=payload)
                data = resp.json()
        except httpx.RequestError as req_err:
            logger.error(f"[Cloudflare SaaS] Request error creating hostname '{domain}': {req_err}")
            raise CloudflareAPIError(f"Gagal menghubungi server Cloudflare: {req_err}", status_code=502)

        if not data.get("success"):
            cf_errors = data.get("errors", [])
            err_msg = "Gagal mendaftarkan domain di Cloudflare."
            status_code = 400

            if cf_errors:
                first_err = cf_errors[0]
                code = first_err.get("code")
                msg = first_err.get("message", "")
                if code == 1406 or "already exists" in msg.lower():
                    err_msg = f"Domain '{domain}' sudah terdaftar di Cloudflare. Pastikan domain belum terhubung ke toko atau layanan lain."
                    status_code = 409
                elif "invalid" in msg.lower():
                    err_msg = f"Domain '{domain}' ditolak oleh Cloudflare: {msg}"
                    status_code = 400
                else:
                    err_msg = f"Cloudflare API error ({code}): {msg}"

            logger.warning(f"[Cloudflare SaaS] Failed to create hostname '{domain}': {data}")
            raise CloudflareAPIError(err_msg, status_code=status_code, cf_errors=cf_errors)

        result = data.get("result", {})
        return {
            "id": result.get("id"),
            "hostname": result.get("hostname", domain),
            "status": result.get("status", "pending"),
            "ssl_status": result.get("ssl", {}).get("status", "pending_validation"),
            "ssl_method": method,
            "cname_target": self.cname_target,
            "ownership_verification": result.get("ownership_verification"),
            "ssl_validation_records": result.get("ssl", {}).get("validation_records") or [],
            "raw_result": result,
        }

    async def get_custom_hostname_status(self, hostname_id: str) -> Dict[str, Any]:
        """
        Retrieves status of a custom hostname.
        Method: GET /zones/{zone_id}/custom_hostnames/{hostname_id}
        """
        if not hostname_id:
            raise CloudflareAPIError("Hostname ID tidak boleh kosong.", status_code=400)
        if not self.zone_id:
            raise CloudflareAPIError(
                "CLOUDFLARE_ZONE_ID belum dikonfigurasi di environment.",
                status_code=500
            )

        url = f"{CLOUDFLARE_API_BASE}/zones/{self.zone_id}/custom_hostnames/{hostname_id}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=self._get_headers())
                data = resp.json()
        except httpx.RequestError as req_err:
            logger.error(f"[Cloudflare SaaS] Request error fetching status for '{hostname_id}': {req_err}")
            raise CloudflareAPIError(f"Gagal menghubungi server Cloudflare: {req_err}", status_code=502)

        if not data.get("success"):
            cf_errors = data.get("errors", [])
            status_code = resp.status_code if resp.status_code >= 400 else 400
            err_msg = "Gagal mengambil status domain dari Cloudflare."
            if cf_errors:
                err_msg = f"Cloudflare error: {cf_errors[0].get('message')}"
            raise CloudflareAPIError(err_msg, status_code=status_code, cf_errors=cf_errors)

        result = data.get("result", {})
        status = result.get("status", "pending")
        ssl_status = result.get("ssl", {}).get("status", "pending_validation")
        is_active = (status == "active") and (ssl_status == "active")

        return {
            "id": result.get("id"),
            "hostname": result.get("hostname"),
            "status": status,
            "ssl_status": ssl_status,
            "is_active": is_active,
            "cname_target": self.cname_target,
            "ownership_verification": result.get("ownership_verification"),
            "ssl_validation_records": result.get("ssl", {}).get("validation_records") or [],
            "raw_result": result,
        }

    async def delete_custom_hostname(self, hostname_id: str) -> Dict[str, Any]:
        """
        Deletes a custom hostname from Cloudflare for SaaS.
        Method: DELETE /zones/{zone_id}/custom_hostnames/{hostname_id}
        """
        if not hostname_id:
            raise CloudflareAPIError("Hostname ID tidak boleh kosong.", status_code=400)
        if not self.zone_id:
            raise CloudflareAPIError(
                "CLOUDFLARE_ZONE_ID belum dikonfigurasi di environment.",
                status_code=500
            )

        url = f"{CLOUDFLARE_API_BASE}/zones/{self.zone_id}/custom_hostnames/{hostname_id}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.delete(url, headers=self._get_headers())
                data = resp.json()
        except httpx.RequestError as req_err:
            logger.error(f"[Cloudflare SaaS] Request error deleting hostname '{hostname_id}': {req_err}")
            raise CloudflareAPIError(f"Gagal menghubungi server Cloudflare: {req_err}", status_code=502)

        # If Cloudflare returned 404 / already deleted, treat as success
        if not data.get("success"):
            cf_errors = data.get("errors", [])
            if cf_errors and any(e.get("code") in [1436, 1437, 404] or "not found" in str(e).lower() for e in cf_errors):
                logger.info(f"[Cloudflare SaaS] Hostname '{hostname_id}' already removed from Cloudflare.")
                return {"success": True, "id": hostname_id, "deleted": True}
            err_msg = "Gagal menghapus domain dari Cloudflare."
            if cf_errors:
                err_msg = f"Cloudflare error: {cf_errors[0].get('message')}"
            raise CloudflareAPIError(err_msg, status_code=400, cf_errors=cf_errors)

        return {"success": True, "id": hostname_id, "deleted": True}


cloudflare_service = CloudflareCustomHostnameService()
