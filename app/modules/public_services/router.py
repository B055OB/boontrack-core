import logging
from aiohttp import web
from app.modules.public_services.whatsapp import whatsapp_webhook_get, whatsapp_webhook_post

logger = logging.getLogger(__name__)

def register_public_service_routes(app: web.Application):
    """Mendaftarkan route WhatsApp webhook."""
    try:
        # Route utama sesuai konfigurasi Meta
        app.router.add_get('/webhook/whatsapp', whatsapp_webhook_get)
        app.router.add_post('/webhook/whatsapp', whatsapp_webhook_post)
        
        # Route alternatif
        app.router.add_get('/api/public_services/webhook/whatsapp', whatsapp_webhook_get)
        app.router.add_post('/api/public_services/webhook/whatsapp', whatsapp_webhook_post)
        
        logger.info("WhatsApp webhook routes registered successfully.")
    except Exception as e:
        logger.warning(f"Error registering WhatsApp routes: {e}")