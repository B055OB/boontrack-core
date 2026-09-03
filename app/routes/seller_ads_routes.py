from aiohttp import web
from app.services.seller_ads_pro_service import (
    verify_seller_addon_entitlement,
    upsert_seller_pixel_settings,
    get_seller_pixel_settings,
    get_seller_attribution_analytics
)

async def update_pixel_config_handler(request: web.Request):
    """Menyimpan konfigurasi Pixel ID & CAPI seller (hanya bisa diakses seller berhak)."""
    tenant_id = request.match_info.get("tenant_id")
    entitlement = await verify_seller_addon_entitlement(tenant_id)
    if not entitlement["allowed"]:
        return web.json_response({
            "success": False, 
            "error_code": "ADDON_REQUIRED",
            "message": entitlement["message"]
        }, status=403)

    body = await request.json()
    res = await upsert_seller_pixel_settings(tenant_id, body)
    return web.json_response(res)

async def get_pixel_config_handler(request: web.Request):
    """Mengambil config Pixel untuk di-inject ke landing page toko seller."""
    tenant_id = request.match_info.get("tenant_id")
    entitlement = await verify_seller_addon_entitlement(tenant_id)

    # Jika seller tidak berhak, jangan berikan script Pixel ke browser
    if not entitlement["allowed"]:
        return web.json_response({
            "success": False,
            "is_enabled": False,
            "pixel_config": None
        })

    cfg = await get_seller_pixel_settings(tenant_id)
    return web.json_response({
        "success": True, 
        "is_enabled": True,
        "tenant_id": tenant_id, 
        "entitlement_source": entitlement["reason"],
        "pixel_config": cfg
    })

async def get_analytics_handler(request: web.Request):
    """Laporan dashboard performa campaign iklan berbayar milik toko seller."""
    tenant_id = request.match_info.get("tenant_id")
    entitlement = await verify_seller_addon_entitlement(tenant_id)
    if not entitlement["allowed"]:
        return web.json_response({
            "success": False, 
            "error_code": "ADDON_REQUIRED",
            "message": entitlement["message"]
        }, status=403)

    data = await get_seller_attribution_analytics(tenant_id)
    return web.json_response(data)

def register_seller_ads_routes(app: web.Application):
    # Endpoint pengaturan dashboard toko seller (/admin atau /bossob)
    app.router.add_post('/api/v1/seller/ads-pro/config/{tenant_id}', update_pixel_config_handler)
    app.router.add_get('/api/v1/seller/ads-pro/config/{tenant_id}', get_pixel_config_handler)
    app.router.add_get('/api/v1/seller/ads-pro/analytics/{tenant_id}', get_analytics_handler)