"""
app/routing/reserved_routes.py
BoonTrack Apex Domain Reserved Route Manifest Helper & Type Definitions (Python)

Single Source of Truth for Route Governance, Normalization, and Namespace Reservation.
Manifest SHA-256: FCE2E8FCA08FDA336F46B4EA648D2D139E0B8BE6F20DF2BB951EEBF9FFAC6DAD
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

MANIFEST_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "routing" / "reserved-route-manifest.v1.json"

with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
    MANIFEST_DATA = json.load(f)

RESERVED_ROUTE_MANIFEST_VERSION: str = MANIFEST_DATA["version"]
RESERVED_ROUTE_MANIFEST_SHA256: str = "FCE2E8FCA08FDA336F46B4EA648D2D139E0B8BE6F20DF2BB951EEBF9FFAC6DAD"

RESERVED_SLUGS_SET: Set[str] = {s.lower().strip() for s in MANIFEST_DATA["reserved_slugs"]}

SLUG_TO_NAMESPACE_MAP: Dict[str, str] = {}
for ns, slugs in MANIFEST_DATA["namespaces"].items():
    for s in slugs:
        SLUG_TO_NAMESPACE_MAP[s.lower().strip()] = ns


class ReservedRouteConflictError(Exception):
    def __init__(self, slug: str, namespace: str):
        super().__init__(
            f"Tenant slug conflict: '{slug}' is a reserved platform route under namespace '{namespace}'. "
            "It cannot be claimed or onboarded as a tenant storefront."
        )
        self.slug = slug
        self.namespace = namespace


def normalize_route_segment(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    return raw.strip().lower().strip("/")


def is_reserved_route_slug(slug: str) -> bool:
    normalized = normalize_route_segment(slug)
    if not normalized:
        return False
    return normalized in RESERVED_SLUGS_SET


def get_reserved_slug_namespace(slug: str) -> Optional[str]:
    normalized = normalize_route_segment(slug)
    if not normalized:
        return None
    return SLUG_TO_NAMESPACE_MAP.get(normalized)


def assert_not_reserved_tenant_slug(slug: str) -> None:
    normalized = normalize_route_segment(slug)
    if is_reserved_route_slug(normalized):
        ns = get_reserved_slug_namespace(normalized) or "system"
        raise ReservedRouteConflictError(normalized, ns)


def validate_and_extract_route(raw_path: str) -> Tuple[bool, str, str, str, bool, Optional[str], Optional[str]]:
    """
    Returns:
    (is_valid, normalized_path, first_segment, sub_path, is_reserved, namespace, error_message)
    """
    if not isinstance(raw_path, str):
        return False, "", "", "", False, None, "Path must be a string"

    trimmed = raw_path.strip()

    # Reject percent-encoded separators (%2f, %5c)
    lower = trimmed.lower()
    if "%2f" in lower or "%5c" in lower:
        return False, "", "", "", False, None, "Percent-encoded separators (%2f, %5c) are strictly prohibited."

    # Reject path traversal (..)
    if ".." in trimmed or "%2e%2e" in lower:
        return False, "", "", "", False, None, "Path traversal sequences (..) are strictly prohibited."

    # Reject double slashes (//)
    if "//" in trimmed:
        return False, "", "", "", False, None, "Double slashes (//) are strictly prohibited."

    clean_path = trimmed.lower()
    if not clean_path.startswith("/"):
        clean_path = "/" + clean_path
    if len(clean_path) > 1 and clean_path.endswith("/"):
        clean_path = clean_path[:-1]

    segments = [s for s in clean_path.split("/") if s]
    first_segment = segments[0] if segments else ""
    sub_path = "/" + "/".join(segments[1:]) if len(segments) > 1 else ""

    is_reserved = bool(first_segment and first_segment in RESERVED_SLUGS_SET)
    namespace = SLUG_TO_NAMESPACE_MAP.get(first_segment) if is_reserved else None

    return True, clean_path, first_segment, sub_path, is_reserved, namespace, None
