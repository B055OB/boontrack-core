"""app/api/v1/reader.py
Webhook Controller untuk Android Reader Notifications (Contained in Phase 1 Stage 2).

Endpoint: POST /api/v1/reader/notification
Status  : DISABLED (EXPERIMENTAL / PENDING_REVIEW — HTTP 403 DIRECT_TENANT_RAIL_DISABLED)
"""

import logging
import os
from aiohttp import web

from app.services.hybrid_reader_service import HybridReaderProcessor, parse_gopay_notification

logger = logging.getLogger("READER_WEBHOOK")

READER_SECRET_ENV = "READER_WEBHOOK_SECRET"


def get_reader_secret() -> str:
    """Returns configured secret without any static fallback default."""
    return (os.getenv(READER_SECRET_ENV) or "").strip()


async def handle_reader_notification(request: web.Request) -> web.Response:
    """POST /api/v1/reader/notification

    Phase 1 Stage 2 (P0-C):
    Direct Tenant Rail (Android Notification Reader & personal mutation matcher)
    is EXPERIMENTAL / PENDING_REVIEW and disabled for auto-settlement.
    Always fails closed with HTTP 403 DIRECT_TENANT_RAIL_DISABLED without
    default secret fallback, notification parsing, order matching, or CAPI.
    """
    logger.warning(
        "[PaymentPerimeterLockdown] Blocked aiohttp Direct Tenant Rail reader notification webhook on /api/v1/reader/notification."
    )
    return web.json_response(
        {
            "status": "rejected",
            "error_code": "DIRECT_TENANT_RAIL_DISABLED",
            "detail": (
                "DIRECT_TENANT_RAIL_DISABLED: Direct Tenant Rail (Android Reader / bank mutation auto-settlement) "
                "is EXPERIMENTAL / PENDING_REVIEW and disabled."
            ),
        },
        status=403,
    )


def register_reader_routes(app: web.Application) -> None:
    """Daftarkan endpoint Reader ke aplikasi aiohttp."""
    existing_posts = {
        getattr(getattr(r, "resource", None), "canonical", None)
        for r in app.router.routes()
        if getattr(r, "method", None) == "POST"
    }
    if "/api/v1/reader/notification" not in existing_posts:
        app.router.add_post("/api/v1/reader/notification", handle_reader_notification)
    logger.info("[BOOT] Reader webhook route registered (contained) at POST /api/v1/reader/notification")

