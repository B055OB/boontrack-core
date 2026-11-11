"""
Trusted Proxy Configuration and Client IP Resolution Boundary
==============================================================
Enforces strict client IP resolution according to production ingress topology.
Prevents untrusted client-supplied forwarded headers (e.g. X-Forwarded-For spoofing)
from manipulating rate limiting, geolocation, or audit identities.

Rules:
1. Direct connection IP (`request.client.host` or `request.remote`) is the authoritative network peer.
2. If the direct peer IP is NOT in the configured trusted proxy list, ALL forwarded
   headers (X-Forwarded-For, CF-Connecting-IP, etc.) are treated as untrusted payload
   and ignored. The direct peer IP is returned.
3. A private network proxy (e.g. RFC1918 / ULA) must NOT be permitted to inject
   a CF-Connecting-IP header. `CF-Connecting-IP` is ONLY trusted when the direct network
   peer is cryptographically/network-verified to reside within Cloudflare's official IP ranges.
4. If direct peer IS a trusted proxy:
   - If direct peer is a verified Cloudflare proxy and CF-Connecting-IP is present: validate and return CF-Connecting-IP.
   - Otherwise, traverse X-Forwarded-For from right to left (reverse order), skipping trusted
     intermediate proxies. The first untrusted IP encountered is the authentic client IP.
5. Production Ingress Configuration:
   In production environments (`APP_ENV=production`), `TRUSTED_PROXIES` must be explicitly
   configured with the CIDRs of the edge load balancers, Kubernetes ingress controllers,
   or Cloudflare edge ranges. Unrestricted trust across all RFC1918 subnets is disabled by default
   in production unless `ALLOW_RFC1918_TRUSTED_PROXIES=1` is explicitly set.
"""

import ipaddress
import logging
import os
from typing import Any, List, Optional, Set, Union
from starlette.requests import Request

logger = logging.getLogger("TRUSTED_PROXY")

# Standard Cloudflare IPv4 and IPv6 CIDRs (https://www.cloudflare.com/ips/)
CLOUDFLARE_TRUSTED_CIDRS: List[str] = [
    # Cloudflare IPv4
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
    # Cloudflare IPv6
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]

# Standard Loopback CIDRs
LOOPBACK_CIDRS: List[str] = [
    "127.0.0.0/8",
    "::1/128",
]

# Standard RFC1918 & RFC4193 private network CIDRs
RFC1918_PRIVATE_CIDRS: List[str] = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
]


class TrustedProxyResolver:
    """
    Parses and checks IP addresses against trusted proxy networks with distinct
    Cloudflare edge boundary enforcement.
    """

    def __init__(
        self,
        trusted_cidrs: Optional[List[str]] = None,
        cloudflare_cidrs: Optional[List[str]] = None,
    ):
        self._networks: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []
        self._cloudflare_networks: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]] = []

        # 1. Parse Cloudflare networks
        cf_list = cloudflare_cidrs if cloudflare_cidrs is not None else CLOUDFLARE_TRUSTED_CIDRS
        for item in cf_list:
            item_clean = item.strip()
            if not item_clean:
                continue
            try:
                self._cloudflare_networks.append(ipaddress.ip_network(item_clean, strict=False))
            except ValueError as ve:
                logger.warning(f"[TRUSTED_PROXY] Invalid Cloudflare CIDR '{item_clean}': {ve}")

        # 2. Parse general trusted proxy networks
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
        """Loads trusted proxy CIDRs from TRUSTED_PROXIES or defaults based on environment."""
        env_val = os.getenv("TRUSTED_PROXIES", "").strip()
        if env_val.lower() in ("none", "disabled", "false"):
            return []
        if env_val:
            return [cidr.strip() for cidr in env_val.split(",") if cidr.strip()]

        app_env = os.getenv("APP_ENV", "development").lower()
        allow_private = os.getenv("ALLOW_RFC1918_TRUSTED_PROXIES", "0").lower() in ("1", "true")

        cidrs = list(LOOPBACK_CIDRS) + list(CLOUDFLARE_TRUSTED_CIDRS)

        if app_env != "production" or allow_private:
            cidrs.extend(RFC1918_PRIVATE_CIDRS)
        else:
            logger.warning(
                "[TRUSTED_PROXY] In production without explicit TRUSTED_PROXIES. "
                "Defaulting to loopback and Cloudflare edge ranges only. "
                "Configure TRUSTED_PROXIES=<load_balancer_cidrs> to trust private VPC proxies."
            )

        return cidrs

    def is_trusted(self, ip_str: str) -> bool:
        """Returns True if the IP belongs to any configured trusted proxy network."""
        if not ip_str:
            return False
        clean_ip = ip_str.strip()
        try:
            ip_obj = ipaddress.ip_address(clean_ip)
            for net in self._networks:
                if ip_obj in net:
                    return True
            for cf_net in self._cloudflare_networks:
                if ip_obj in cf_net:
                    return True
            return False
        except ValueError:
            return False

    def is_cloudflare_proxy(self, ip_str: str) -> bool:
        """Returns True if and only if the direct network peer is in Cloudflare IP ranges."""
        if not ip_str:
            return False
        clean_ip = ip_str.strip()
        try:
            ip_obj = ipaddress.ip_address(clean_ip)
            for cf_net in self._cloudflare_networks:
                if ip_obj in cf_net:
                    return True
            return False
        except ValueError:
            return False

    def resolve_client_ip(self, request: Any) -> str:
        """
        Authoritatively resolves the authentic client IP from a Starlette/FastAPI or aiohttp request.

        Enforces:
        - Direct untrusted peer => all forwarded headers discarded.
        - CF-Connecting-IP => honored ONLY if direct peer is a verified Cloudflare proxy.
        - X-Forwarded-For => evaluated right-to-left, stripping trusted proxies.
        """
        if request is None:
            return "127.0.0.1"

        direct_ip = "127.0.0.1"
        if hasattr(request, "client") and request.client and getattr(request.client, "host", None):
            direct_ip = str(request.client.host).strip()
        elif hasattr(request, "remote") and request.remote:
            direct_ip = str(request.remote).strip()

        # 1. If direct network peer is NOT trusted, ALL forwarded headers are untrusted spoofing attempts
        if not self.is_trusted(direct_ip):
            return direct_ip

        # 2. CF-Connecting-IP is ONLY trusted when direct peer is verified to be a Cloudflare edge proxy.
        # A private network proxy (e.g. RFC1918) CANNOT inject CF-Connecting-IP.
        cf_connecting_ip = request.headers.get("cf-connecting-ip")
        if cf_connecting_ip and self.is_cloudflare_proxy(direct_ip):
            clean_cf = cf_connecting_ip.strip()
            try:
                ipaddress.ip_address(clean_cf)
                return clean_cf
            except ValueError:
                pass

        # 3. Parse X-Forwarded-For from right to left (skipping trusted intermediate proxies)
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
