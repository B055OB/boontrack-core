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