"""
Trusted Proxy Configuration and Client IP Resolution Boundary
==============================================================
Enforces strict client IP resolution according to production ingress topology.
Prevents untrusted client-supplied forwarded headers (e.g. X-Forwarded-For spoofing)
from manipulating rate limiting, geolocation, or audit identities.

Rules:
1. Direct connection IP (`request.client.host`) is the authoritative network peer.
2. If the direct peer IP is NOT in the configured trusted proxy list, ALL forwarded
   headers (X-Forwarded-For, CF-Connecting-IP, etc.) are treated as untrusted payload
   and ignored. The direct peer IP is returned.
3. If the direct peer IP IS in the trusted proxy list, X-Forwarded-For is evaluated
   from right to left (reverse order), skipping trusted intermediate proxies. The first
   untrusted IP encountered is the authentic client IP.
4. If CF-Connecting-IP is present and direct peer is a confirmed trusted Cloudflare proxy,
   CF-Connecting-IP is validated and returned.
"""

import ipaddress
import logging
import os
from typing import Any, List, Optional, Set, Union
from starlette.requests import Request

logger = logging.getLogger("TRUSTED_PROXY")

# Default standard trusted network ranges (Loopback, RFC1918 Private VPCs, RFC4193 ULA)
DEFAULT_TRUSTED_CIDRS: List[str] = [
    # Loopback
    "127.0.0.0/8",
    "::1/128",
    # RFC 1918 private IPv4 networks (Docker, Kubernetes Pods/Nodes, AWS/GCP VPCs)
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    # RFC 4193 unique local IPv6
    "fc00::/7",
    # Standard Cloudflare IPv4 CIDRs
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    # Cloudflare IPv6 CIDRs
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]


class TrustedProxyResolver:
    """
    Parses and checks IP addresses against trusted proxy networks.
    """

    def __init__(self, trusted_cidrs: Optional[List[str]] = None):
        self._networks: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
        raw_list = trusted_cidrs if trusted_cidrs is not None else self._load_configured_cidrs()
        for item in raw_list:
            item_clean = item.strip()
            if not item_clean:
                continue
            try:
                if "/" in item_clean:
                    net = ipaddress.ip_network(item_clean, strict=False)
                else:
                    net = ipaddress.ip_network(f"{item_clean}/32" if ":" not in item_clean else f"{item_clean}/128", strict=False)
                self._networks.append(net)
            except ValueError as ve:
                logger.warning(f"[TRUSTED_PROXY] Invalid CIDR or IP '{item_clean}': {ve}")

    @staticmethod
    def _load_configured_cidrs() -> List[str]:
        env_val = os.getenv("TRUSTED_PROXIES", "").strip()
        if env_val.lower() in ("none", "disabled", "false"):
            return []
        if env_val:
            return [cidr.strip() for cidr in env_val.split(",") if cidr.strip()]
        return list(DEFAULT_TRUSTED_CIDRS)

    def is_trusted(self, ip_str: str) -> bool:
        if not ip_str:
            return False
        clean_ip = ip_str.strip()
        try:
            ip_obj = ipaddress.ip_address(clean_ip)
            for net in self._networks:
                if ip_obj in net:
                    return True
            return False
        except ValueError:
            return False

    def resolve_client_ip(self, request: Any) -> str:
        """
        Authoritatively resolves the authentic client IP from a Starlette/FastAPI or aiohttp request.
        """
        if request is None:
            return "127.0.0.1"

        direct_ip = "127.0.0.1"
        if hasattr(request, "client") and request.client and getattr(request.client, "host", None):
            direct_ip = str(request.client.host).strip()
        elif hasattr(request, "remote") and request.remote:
            direct_ip = str(request.remote).strip()

        # If direct network peer is NOT trusted, ALL forwarded headers are untrusted spoofing attempts
        if not self.is_trusted(direct_ip):
            return direct_ip

        # Direct peer is a trusted proxy. Check for CF-Connecting-IP first if from Cloudflare
        cf_connecting_ip = request.headers.get("cf-connecting-ip")
        if cf_connecting_ip:
            clean_cf = cf_connecting_ip.strip()
            try:
                ipaddress.ip_address(clean_cf)
                return clean_cf
            except ValueError:
                pass

        # Parse X-Forwarded-For from right to left
        xff = request.headers.get("x-forwarded-for")
        if not xff:
            return direct_ip

        ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
        if not ips:
            return direct_ip

        # Traverse right to left, skipping trusted proxies
        for ip in reversed(ips):
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                continue

            if not self.is_trusted(ip):
                return ip

        # If all IPs in XFF were trusted proxies, return the leftmost valid IP or direct_ip
        for ip in ips:
            try:
                ipaddress.ip_address(ip)
                return ip
            except ValueError:
                continue

        return direct_ip


# Global default trusted proxy resolver instance
_default_resolver = TrustedProxyResolver()


def get_trusted_client_ip(request: Optional[Request]) -> str:
    """Convenience function to resolve the trusted client IP."""
    return _default_resolver.resolve_client_ip(request)
