import uuid
from aiohttp import web

async def pair_device_handler(request: web.Request, session=None) -> web.Response:
    try:
        data = await request.json()
        activation_code = data.get("activation_code", "").strip()
        device_uuid = data.get("device_uuid", "").strip()
        device_name = data.get("device_name", "Android Reader")
        platform = data.get("platform", "ANDROID")
        app_version = data.get("app_version", "1.0.0")

        if not activation_code or not device_uuid:
            return web.json_response({"error": "Missing activation_code or device_uuid"}, status=400)

        # Generate pairing tokens
        device_id = str(uuid.uuid4())
        access_token = f"bt_at_{uuid.uuid4().hex}"
        refresh_token = f"bt_rt_{uuid.uuid4().hex}"

        return web.json_response({
            "status": "success",
            "message": "Device paired successfully",
            "device_id": device_id,
            "device_name": device_name,
            "platform": platform,
            "app_version": app_version,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer"
        })

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

async def refresh_token_handler(request: web.Request, session=None) -> web.Response:
    return web.json_response({
        "status": "success",
        "access_token": f"bt_at_{uuid.uuid4().hex}",
        "refresh_token": f"bt_rt_{uuid.uuid4().hex}"
    })

async def revoke_device_handler(request: web.Request, session=None) -> web.Response:
    return web.json_response({"status": "success", "message": "Device revoked successfully"})


def register_reader_routes(app: web.Application, session_factory=None):
    """Mendaftarkan route reader device pairing, token management, dan status."""
    async def _wrap_pair(req):
        if session_factory:
            async with session_factory() as session:
                return await pair_device_handler(req, session)
        return await pair_device_handler(req)

    async def _wrap_refresh(req):
        if session_factory:
            async with session_factory() as session:
                return await refresh_token_handler(req, session)
        return await refresh_token_handler(req)

    async def _wrap_revoke(req):
        if session_factory:
            async with session_factory() as session:
                return await revoke_device_handler(req, session)
        return await revoke_device_handler(req)

    app.router.add_post("/api/v1/devices/pair", _wrap_pair)
    app.router.add_post("/api/v1/devices/refresh", _wrap_refresh)
    app.router.add_post("/api/v1/devices/revoke", _wrap_revoke)