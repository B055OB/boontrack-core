import logging
import os
from aiohttp import web
from app.modules.public_services.service import public_service_service

logger = logging.getLogger(__name__)

public_service_routes = web.RouteTableDef()

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
}

# -----------------------------------------------------------------------------
# 1. API WEBCHAT ENDPOINTS
# -----------------------------------------------------------------------------
@public_service_routes.post("/api/v1/public-service/{tenant_id}/chat")
@public_service_routes.post("/api/public-service/chat")
@public_service_routes.post("/api/public_service/chat")
@public_service_routes.post("/api/public_services/chat")
@public_service_routes.post("/api/public_services/webchat")
async def handle_public_service_webchat_http(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=CORS_HEADERS)

    try:
        tenant_id = request.match_info.get("tenant_id", "bale-pananggeuhan")
        data = await request.json()
        session_id = str(data.get("session_id", "webchat_anon")).strip()
        user_msg = str(data.get("message", "")).strip()

        if not user_msg:
            return web.json_response(
                {"status": "error", "message": "Pesan tidak boleh kosong"},
                status=400,
                headers=CORS_HEADERS
            )

        result = await public_service_service.handle_query(
            user_text=user_msg,
            user_id=session_id,
            session_id=f"webchat:{session_id}",
            channel="webchat",
            tenant_id=tenant_id
        )

        return web.json_response({
            "status": "success",
            "tenant_id": tenant_id,
            "response": result.get("reply"),
            "reply": result.get("reply"),
            "message": result.get("reply"),
            "type": result.get("type", "information"),
            "ticket": result.get("ticket")
        }, headers=CORS_HEADERS)

    except Exception as e:
        logger.error(f"[PUBLIC_SERVICE_WEBCHAT ERROR] {e}", exc_info=True)
        return web.json_response(
            {"status": "error", "message": f"Gagal memproses pesan: {str(e)}"},
            status=500,
            headers=CORS_HEADERS
        )

# -----------------------------------------------------------------------------
# 2. TICKET & DASHBOARD API ENDPOINTS (FULL CORS ENABLED)
# -----------------------------------------------------------------------------
@public_service_routes.options("/api/v1/public-service/{tenant_id}/tickets")
@public_service_routes.options("/api/v1/public-service/tickets")
async def tickets_options_handler(request: web.Request) -> web.Response:
    return web.Response(status=200, headers=CORS_HEADERS)

@public_service_routes.get("/api/v1/public-service/{tenant_id}/tickets")
@public_service_routes.get("/api/v1/public-service/tickets")
async def get_tickets_api(request: web.Request) -> web.Response:
    tenant_id = request.match_info.get("tenant_id", "bale-pananggeuhan")
    tickets = public_service_service.get_tickets(tenant_id)
    return web.json_response(
        {"status": "success", "tenant_id": tenant_id, "data": tickets},
        headers=CORS_HEADERS
    )

@public_service_routes.options("/api/v1/public-service/{tenant_id}/tickets/update-status")
@public_service_routes.options("/api/v1/public-service/tickets/update-status")
async def ticket_update_options_handler(request: web.Request) -> web.Response:
    return web.Response(status=200, headers=CORS_HEADERS)

@public_service_routes.post("/api/v1/public-service/{tenant_id}/tickets/update-status")
@public_service_routes.post("/api/v1/public-service/tickets/update-status")
async def update_ticket_status_api(request: web.Request) -> web.Response:
    try:
        tenant_id = request.match_info.get("tenant_id", "bale-pananggeuhan")
        payload = await request.json()
        ticket_id = payload.get("ticket_id")
        status = payload.get("status")
        public_service_service.update_ticket_status(tenant_id, ticket_id, status)
        return web.json_response({"status": "success"}, headers=CORS_HEADERS)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, headers=CORS_HEADERS)

@public_service_routes.get("/public-service/dashboard")
async def render_dashboard(request: web.Request) -> web.Response:
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")
    return web.Response(text="<h1>Dashboard File Not Found</h1>", content_type="text/html", status=404)

def register_public_service_routes(app: web.Application):
    app.add_routes(public_service_routes)
    logger.info("[ROUTER] Public Services unified routes registered.")