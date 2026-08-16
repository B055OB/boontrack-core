import logging
from aiohttp import web
from app.modules.public_services.whatsapp import whatsapp_webhook_get, whatsapp_webhook_post

logger = logging.getLogger(__name__)

def register_public_service_routes(app: web.Application):
    """Mendaftarkan route public services dan WhatsApp webhook."""
    try:
        app.router.add_get('/api/public_services/webhook/whatsapp', whatsapp_webhook_get)
        app.router.add_post('/api/public_services/webhook/whatsapp', whatsapp_webhook_post)
        logger.info("Public Services WhatsApp routes registered.")
    except Exception as e:
        logger.warning(f"Public service routes note: {e}")