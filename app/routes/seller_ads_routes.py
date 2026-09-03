from aiohttp import web
from app.services.seller_ads_pro_service import (
    verify_seller_addon_entitlement,
    upsert_seller_pixel_settings,
    get_seller_pixel_settings,
    get_seller_attribution_analytics
)

async def update_pixel_config_handler(request: web.Request):
    tenant_id = request.match_info.get("tenant_id")
    has_access = await verify_seller_addon_entitlement(tenant_id)
    if not has_access:
        return web.json_response({
            "success": False, 
            "error": "Fitur ini memerlukan langganan add-on Ads Tracking Pro (Rp99k/bulan)."
        }, status=403)

    body = await request.json()
    res = await upsert_seller_pixel_settings(tenant_id, body)
    return web.json_response(res)

async def get_pixel_config_handler(request: web.Request):
    tenant_id = request.match_info.get("tenant_id")
    cfg = await get_seller_pixel_settings(tenant_id)
    return web.json_response({"success": True, "tenant_id": tenant_id, "pixel_config": cfg})

async def get_analytics_handler(request: web.Request):
    tenant_id = request.match_info.get("tenant_id")
    has_access = await verify_seller_addon_entitlement(tenant_id)
    if not has_access:
        return web.json_response({
            "success": False, 
            "error": "Akses ditolak. Silakan aktifkan add-on Ads Tracking Pro."
        }, status=403)

    data = await get_seller_attribution_analytics(tenant_id)
    return web.json_response(data)

def register_seller_ads_routes(app: web.Application):
    # Endpoint pengaturan dashboard toko seller
    app.router.add_post('/api/v1/seller/ads-pro/config/{tenant_id}', update_pixel_config_handler)
    app.router.add_get('/api/v1/seller/ads-pro/config/{tenant_id}', get_pixel_config_handler)
    app.router.add_get('/api/v1/seller/ads-pro/analytics/{tenant_id}', get_analytics_handler)