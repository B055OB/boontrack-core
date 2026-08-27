"""app/api/endpoints/gym.py
aiohttp HTTP Handlers for Gym & IoT Access Control (Atmosfitnes).
"""

import json
import logging
from aiohttp import web

from app.schemas.gym_schema import (
    AccessEventType,
    TapAccessResponse,
)
from app.services.gym_access_service import (
    gym_access_service,
    ControllerAuthenticationError,
)

logger = logging.getLogger("GYM_AIOHTTP_ENDPOINT")


async def handle_gym_verify_access(request: web.Request) -> web.Response:
    """aiohttp handler for POST /api/v1/gym/access/verify."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    tenant_id = data.get("tenant_id", "atmosfitnes")
    controller_id = data.get("controller_id")
    uid_hash = data.get("uid_hash")
    device_token = request.headers.get("X-Device-Token") or data.get("device_token")
    raw_event_type = data.get("event_type", "TAP_IN")
    event_type = AccessEventType.TAP_OUT if str(raw_event_type).upper() == "TAP_OUT" else AccessEventType.TAP_IN
    idempotency_key = data.get("idempotency_key")

    if not controller_id or not uid_hash:
        return web.json_response({"error": "controller_id and uid_hash are required"}, status=400)

    try:
        response: TapAccessResponse = await gym_access_service.verify_access(
            tenant_id=tenant_id,
            controller_id=controller_id,
            uid_hash=uid_hash,
            device_token=device_token,
            event_type=event_type,
            idempotency_key=idempotency_key,
        )
        return web.json_response(response.model_dump(mode="json"), status=200)
    except ControllerAuthenticationError as e:
        return web.json_response({"error": "Unauthorized controller", "detail": str(e)}, status=401)
    except Exception as e:
        logger.error(f"[GymAiohttp] Verification error: {e}", exc_info=True)
        return web.json_response({"error": "Internal server error", "detail": str(e)}, status=500)


async def handle_gym_whitelist(request: web.Request) -> web.Response:
    """aiohttp handler for GET /api/v1/gym/controllers/{controller_id}/whitelist."""
    controller_id = request.match_info.get("controller_id")
    tenant_id = request.query.get("tenant_id", "atmosfitnes")
    device_token = request.headers.get("X-Device-Token")

    if not controller_id:
        return web.json_response({"error": "controller_id is required"}, status=400)

    try:
        whitelist = await gym_access_service.get_active_whitelist(
            tenant_id=tenant_id,
            controller_id=controller_id,
            device_token=device_token,
        )
        return web.json_response({
            "status": "success",
            "tenant_id": tenant_id,
            "controller_id": controller_id,
            "count": len(whitelist),
            "whitelist": whitelist,
        }, status=200)
    except ControllerAuthenticationError as e:
        return web.json_response({"error": "Unauthorized controller", "detail": str(e)}, status=401)
    except Exception as e:
        logger.error(f"[GymAiohttp] Whitelist error: {e}", exc_info=True)
        return web.json_response({"error": "Internal server error", "detail": str(e)}, status=500)


async def handle_gym_sync_events(request: web.Request) -> web.Response:
    """aiohttp handler for POST /api/v1/gym/access/sync-events."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    tenant_id = data.get("tenant_id", "atmosfitnes")
    controller_id = data.get("controller_id")
    events = data.get("events", [])
    device_token = request.headers.get("X-Device-Token")

    if not controller_id:
        return web.json_response({"error": "controller_id is required"}, status=400)

    try:
        result = await gym_access_service.sync_offline_events(
            tenant_id=tenant_id,
            controller_id=controller_id,
            events_list=events,
            device_token=device_token,
        )
        return web.json_response(result, status=200)
    except ControllerAuthenticationError as e:
        return web.json_response({"error": "Unauthorized controller", "detail": str(e)}, status=401)
    except Exception as e:
        logger.error(f"[GymAiohttp] Sync events error: {e}", exc_info=True)
        return web.json_response({"error": "Internal server error", "detail": str(e)}, status=500)


async def handle_gym_heartbeat(request: web.Request) -> web.Response:
    """aiohttp handler for POST /api/v1/gym/controllers/{controller_id}/heartbeat."""
    controller_id = request.match_info.get("controller_id")
    try:
        data = await request.json()
    except Exception:
        data = {}

    tenant_id = data.get("tenant_id") or request.query.get("tenant_id", "atmosfitnes")
    device_token = request.headers.get("X-Device-Token")
    firmware_version = data.get("firmware_version")

    if not controller_id:
        return web.json_response({"error": "controller_id is required"}, status=400)

    try:
        result = await gym_access_service.record_heartbeat(
            tenant_id=tenant_id,
            controller_id=controller_id,
            device_token=device_token,
            firmware_version=firmware_version,
        )
        return web.json_response(result, status=200)
    except ControllerAuthenticationError as e:
        return web.json_response({"error": "Unauthorized controller", "detail": str(e)}, status=401)
    except Exception as e:
        logger.error(f"[GymAiohttp] Heartbeat error: {e}", exc_info=True)
        return web.json_response({"error": "Internal server error", "detail": str(e)}, status=500)
