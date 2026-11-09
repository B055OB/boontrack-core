import logging
from aiohttp import web

from app.core.bot import bot
from app.core.database import match_and_complete_order, match_and_complete_donation
from app.services.cloudflare_service import generate_unique_slug

logger = logging.getLogger("DANA_WEBHOOK")


async def dana_webhook_handler(request: web.Request) -> web.Response:
    """Phase 1 Stage 2 (P0-C):
    Direct Tenant Rail (DANA mutation auto-settlement webhook at POST /webhook/dana)
    is EXPERIMENTAL / PENDING_REVIEW and strictly disabled.

    Always fails closed with HTTP 403 DIRECT_TENANT_RAIL_DISABLED without invoking
    order/donation matching, status mutation, or Telegram/WhatsApp delivery.
    """
    logger.warning(
        "[PaymentPerimeterLockdown] Blocked aiohttp Direct Tenant Rail DANA mutation webhook on /webhook/dana."
    )
    return web.json_response(
        {
            "status": "rejected",
            "error_code": "DIRECT_TENANT_RAIL_DISABLED",
            "detail": (
                "DIRECT_TENANT_RAIL_DISABLED: Direct Tenant Rail (DANA / Android Reader auto-settlement) "
                "is EXPERIMENTAL / PENDING_REVIEW and disabled."
            ),
        },
        status=403,
    )



