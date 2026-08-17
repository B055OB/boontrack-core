import logging
from aiohttp import web
from app.modules.public_services.whatsapp import whatsapp_webhook_get, whatsapp_webhook_post
from app.modules.public_services.service import public_service_service

logger = logging.getLogger(__name__)


async def handle_public_service_webchat_http(request: web.Request) -> web.Response:
    """Handler HTTP POST untuk Webchat Pelayanan Publik (Kelurahan)."""
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
    }

    if request.method == "OPTIONS":
        return web.Response(status=200, headers=cors_headers)

    try:
        data = await request.json()
        session_id = str(data.get("session_id", "webchat_anon")).strip()
        user_msg = str(data.get("message", "")).strip()

        if not user_msg:
            return web.json_response(
                {"status": "error", "message": "Pesan tidak boleh kosong"},
                status=400,
                headers=cors_headers
            )

        # Panggil Engine Public Service Kelurahan
        reply_text = await public_service_service.handle_query(
            user_text=user_msg,
            user_id=session_id,
            session_id=f"webchat:{session_id}",
            channel="webchat"
        )

        return web.json_response({
            "status": "success",
            "response": reply_text,
            "reply": reply_text,
            "message": reply_text
        }, headers=cors_headers)

    except Exception as e:
        logger.error(f"[PUBLIC_SERVICE_WEBCHAT ERROR] {e}", exc_info=True)
        return web.json_response(
            {"status": "error", "message": "Gagal memproses pesan."},
            status=500,
            headers=cors_headers
        )


def register_public_service_routes(app: web.Application):
    """
    Mendaftarkan seluruh endpoint Webchat publik & webhook WhatsApp untuk modul Public Services.
    """
    # 1. Webchat Pelayanan Publik Endpoints (Semua variasi path)
    app.router.add_post('/api/public-service/chat', handle_public_service_webchat_http)
    app.router.add_post('/api/public_service/chat', handle_public_service_webchat_http)
    app.router.add_post('/api/public_services/chat', handle_public_service_webchat_http)
    app.router.add_post('/api/public_services/webchat', handle_public_service_webchat_http)

    # 2. WhatsApp Webhook Endpoints
    app.router.add_get('/webhook/whatsapp', whatsapp_webhook_get)
    app.router.add_post('/webhook/whatsapp', whatsapp_webhook_post)
    app.router.add_get('/api/public_services/webhook/whatsapp', whatsapp_webhook_get)
    app.router.add_post('/api/public_services/webhook/whatsapp', whatsapp_webhook_post)

    logger.info("[ROUTER] Public Services Webchat & WhatsApp routes registered successfully.")