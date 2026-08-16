import logging
from aiohttp import web
from app.modules.public_services.whatsapp import whatsapp_webhook_get, whatsapp_webhook_post

logger = logging.getLogger(__name__)

def register_public_service_routes(app: web.Application):
    """Mendaftarkan route WhatsApp webhook yang cocok dengan Meta Dashboard."""
    try:
        # Endpoint sesuai yang didaftarkan di Meta Dashboard
        app.router.add_get('/webhook/whatsapp', whatsapp_webhook_get)
        app.router.add_post('/webhook/whatsapp', whatsapp_webhook_post)
        
        # Endpoint alternatif / fallback
        app.router.add_get('/api/public_services/webhook/whatsapp', whatsapp_webhook_get)
        app.router.add_post('/api/public_services/webhook/whatsapp', whatsapp_webhook_post)
        
        print("=== PUBLIC SERVICES WHATSAPP ROUTES REGISTERED SUCCESSFULLY ===", flush=True)
    except Exception as e:
        print(f"=== ERROR REGISTERING ROUTES: {e} ===", flush=True)