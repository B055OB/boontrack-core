import os
import logging
from aiohttp import web
from app.core.tenant_loader import LOADED_CONFIG_TENANTS, TENANT_REGISTRY
from app.routes.auth_routes import generate_session_jwt
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger('MAGIC_LOGIN_AIOHTTP')

async def magic_login_handler(request: web.Request) -> web.Response:
    """Internal impersonation endpoint for aiohttp server.
    Expects query parameters `slug` and `secret`.
    Returns a 302 redirect to `/{slug}/dashboard` with a JWT cookie.
    """
    slug = request.query.get('slug')
    secret = request.query.get('secret')
    if not slug or not secret:
        raise web.HTTPBadRequest(reason='Missing slug or secret')
    expected_secret = os.getenv('INTERNAL_MAGIC_SECRET', 'boontrack-super-secret-2026')
    if secret != expected_secret:
        raise web.HTTPForbidden(reason='Forbidden')
    # Lookup tenant config locally first
    tenant_config = LOADED_CONFIG_TENANTS.get(slug) or TENANT_REGISTRY.get(slug)
    # Fallback to Supabase if not found locally
    if not tenant_config:
        supabase = get_supabase()
        if supabase:
            try:
                res = supabase.table('tenants').select('slug').eq('slug', slug).execute()
                if res and res.data:
                    row = res.data[0]
                    tenant_config = {
                        'slug': row.get('slug'),
                        # No specific dashboard_path stored; fallback to default path
                        'dashboard_path': f"/{row.get('slug')}/dashboard",
                        # domain not used; optional
                        'domain': None,
                    }
                else:
                    raise web.HTTPNotFound(reason='Tenant not found')
            except Exception as e:
                logger.error(f"Error querying tenant: {e}")
                raise web.HTTPNotFound(reason='Tenant not found')
        else:
            raise web.HTTPNotFound(reason='Tenant not found')
    logger.warning(f"INTERNAL_MAGIC_LOGIN triggered for slug: {slug}")
    # Generate a placeholder admin email and JWT token
    admin_email = f"admin@{slug}.com"
    token = generate_session_jwt(email=admin_email, tenant_slug=slug)
    # Build redirect response with cookie
    # Build absolute redirect to shop frontend
    redirect_location = f"https://shop.boontrack.com/{slug}/dashboard"
    # Cookie will persist for 7 days (same as JWT expiration)
    max_age = 7 * 24 * 60 * 60
    response = web.HTTPFound(location=redirect_location)
    response.set_cookie('access_token', token, httponly=True, secure=True, samesite='Lax',
                        domain=".boontrack.com", path="/", max_age=max_age)
    return response
