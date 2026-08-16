import logging
from aiohttp import web
from app.modules.public_services.whatsapp import whatsapp_webhook_get, whatsapp_webhook_post

logger = logging.getLogger(__name__)


def register_public_service_routes(app: web.Application):
    """
    Mendaftarkan seluruh endpoint publik & webhook WhatsApp untuk modul Public Services.
    """
    # 1. WhatsApp Webhook Endpoints
    app.router.add_get('/webhook/whatsapp', whatsapp_webhook_get)
    app.router.add_post('/webhook/whatsapp', whatsapp_webhook_post)
    app.router.add_get('/api/public_services/webhook/whatsapp', whatsapp_webhook_get)
    app.router.add_post('/api/public_services/webhook/whatsapp', whatsapp_webhook_post)

    logger.info("[ROUTER] Public Services & WhatsApp Webhook routes registered successfully.")