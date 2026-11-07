import logging
from aiohttp import web

logger = logging.getLogger(__name__)


async def handle_reader_mutation_webhook(request: web.Request) -> web.Response:
    """
    Phase 1 Stage 2 (P0-C):
    Direct Tenant Rail (Android Notification Reader & DANA Bisnis personal mutation matcher)
    is EXPERIMENTAL / PENDING_REVIEW and disabled for auto-settlement.
    """
    logger.warning("[PaymentPerimeterLockdown] Blocked Direct Tenant Rail reader mutation webhook.")
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


def register_payment_webhook_routes(app: web.Application):
    app.router.add_post("/api/webhook/payment-reader", handle_reader_mutation_webhook)
    app.router.add_post("/api/webhook/dana", handle_reader_mutation_webhook)
