import logging
from aiohttp import web
from app.modules.public_services.whatsapp import whatsapp_webhook_get, whatsapp_webhook_post

logger = logging.getLogger(__name__)

def register_public_service_routes(app: web.Application):
    """Mendaftarkan route WhatsApp webhook dengan aman tanpa konflik."""
    endpoints = ['/webhook/whatsapp', '/api/public_services/webhook/whatsapp']
    
    # Ambil daftar resource path yang sudah ada
    existing_paths = [r.canonical for r in app.router.resources()]

    for path in endpoints:
        if path not in existing_paths:
            app.router.add_get(path, whatsapp_webhook_get)
            app.router.add_post(path, whatsapp_webhook_post)
            print(f"=== REGISTERED ROUTE: {path} ===", flush=True)
        else:
            print(f"=== ROUTE ALREADY REGISTERED: {path} ===", flush=True)