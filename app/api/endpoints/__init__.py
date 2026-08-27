from aiohttp import web
from app.api.endpoints.health import health_check_handler, tracker_handler, funnel_report_handler, tenant_system_status_handler
from app.api.endpoints.webchat import handle_web_chat_http, handle_b2b_webchat_http
from app.api.endpoints.dana import dana_webhook_handler
from app.api.endpoints.gym import (
    handle_gym_verify_access,
    handle_gym_whitelist,
    handle_gym_sync_events,
    handle_gym_heartbeat,
)

def register_api_routes(app: web.Application):
    """Mendaftarkan seluruh endpoint REST API & Webchat base ke aplikasi aiohttp."""
    # Health & Source Tracker & Tenant Status
    app.router.add_get('/', health_check_handler)
    app.router.add_get('/health', health_check_handler)
    app.router.add_get('/api/v1/system/tenants', tenant_system_status_handler)
    app.router.add_get('/source', tracker_handler)
    app.router.add_get('/funnel-report', funnel_report_handler)

    # WebChat Endpoints
    app.router.add_post('/api/webchat', handle_web_chat_http)
    app.router.add_post('/api/web-chat', handle_web_chat_http)
    app.router.add_post('/api/webchat/business', handle_b2b_webchat_http)
    app.router.add_post('/api/b2b-webchat', handle_b2b_webchat_http)

    # DANA Mutation Webhook
    app.router.add_post('/webhook/dana', dana_webhook_handler)

    # Gym & IoT Access Control Endpoints (Atmosfitnes)
    app.router.add_post('/api/v1/gym/access/verify', handle_gym_verify_access)
    app.router.add_get('/api/v1/gym/controllers/{controller_id}/whitelist', handle_gym_whitelist)
    app.router.add_post('/api/v1/gym/access/sync-events', handle_gym_sync_events)
    app.router.add_post('/api/v1/gym/controllers/{controller_id}/heartbeat', handle_gym_heartbeat)

