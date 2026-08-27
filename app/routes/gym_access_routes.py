"""app/routes/gym_access_routes.py
API Routes for Gym & IoT Access Control (Vertical Pilot Atmosfitnes).

Endpoints:
- POST /api/v1/gym/access/verify                  : Verify NFC card tap in real-time
- GET  /api/v1/gym/controllers/{controller_id}/whitelist : Retrieve active whitelist for ESP32 offline caching
- POST /api/v1/gym/access/sync-events             : Batch sync offline access events
- POST /api/v1/gym/controllers/{controller_id}/heartbeat : IoT controller heartbeat update
"""

import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Header, Query, Path, Body, HTTPException, status
from pydantic import BaseModel, Field

from app.schemas.gym_schema import (
    TapAccessRequest,
    TapAccessResponse,
    AccessEventType,
)
from app.services.gym_access_service import (
    gym_access_service,
    ControllerAuthenticationError,
)

logger = logging.getLogger("GYM_ACCESS_ROUTES")

gym_router = APIRouter(prefix="", tags=["Gym & IoT Access Control"])


class SyncOfflineEventsRequest(BaseModel):
    tenant_id: str = Field(default="atmosfitnes", description="Tenant ID")
    controller_id: str = Field(..., description="Controller Hardware ID")
    events: List[Dict[str, Any]] = Field(default_factory=list, description="Batch list of offline events")


class HeartbeatRequest(BaseModel):
    tenant_id: str = Field(default="atmosfitnes")
    firmware_version: Optional[str] = None


# ============================================================================
# 1. POST /access/verify
# ============================================================================

@gym_router.post(
    "/access/verify",
    response_model=TapAccessResponse,
    summary="Verify NFC Card Tap in Real-Time",
    status_code=status.HTTP_200_OK,
)
async def verify_access_endpoint(
    payload: TapAccessRequest,
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """Verifies an NFC card tap event from a turnstile / gate controller."""
    # Prioritize header token if provided
    device_token = x_device_token or payload.device_token
    try:
        response = await gym_access_service.verify_access(
            tenant_id=payload.tenant_id,
            controller_id=payload.controller_id,
            uid_hash=payload.uid_hash,
            device_token=device_token,
            event_type=payload.event_type,
            idempotency_key=payload.idempotency_key,
        )
        return response
    except ControllerAuthenticationError as e:
        logger.warning(f"[GymRoute] Controller auth rejected: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized controller: {str(e)}",
            headers={"WWW-Authenticate": "DeviceToken"},
        )
    except Exception as e:
        logger.error(f"[GymRoute] Unexpected verification error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal verification error: {str(e)}",
        )


# ============================================================================
# 2. GET /controllers/{controller_id}/whitelist
# ============================================================================

@gym_router.get(
    "/controllers/{controller_id}/whitelist",
    summary="Get Active Whitelist for ESP32 Offline Caching",
    status_code=status.HTTP_200_OK,
)
async def get_whitelist_endpoint(
    controller_id: str = Path(..., description="Controller Hardware ID"),
    tenant_id: str = Query(default="atmosfitnes", description="Tenant ID"),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """Retrieves all active UID hashes for offline local cache on ESP32 hardware."""
    try:
        whitelist = await gym_access_service.get_active_whitelist(
            tenant_id=tenant_id,
            controller_id=controller_id,
            device_token=x_device_token,
        )
        return {
            "status": "success",
            "tenant_id": tenant_id,
            "controller_id": controller_id,
            "count": len(whitelist),
            "whitelist": whitelist,
        }
    except ControllerAuthenticationError as e:
        logger.warning(f"[GymRoute] Controller auth rejected on whitelist query: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized controller: {str(e)}",
        )
    except Exception as e:
        logger.error(f"[GymRoute] Whitelist generation error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal whitelist error: {str(e)}",
        )


# ============================================================================
# 3. POST /access/sync-events
# ============================================================================

@gym_router.post(
    "/access/sync-events",
    summary="Batch Synchronize Offline Logged Access Events",
    status_code=status.HTTP_200_OK,
)
async def sync_offline_events_endpoint(
    payload: SyncOfflineEventsRequest,
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """Batch-ingests access events recorded while IoT controller was offline."""
    try:
        result = await gym_access_service.sync_offline_events(
            tenant_id=payload.tenant_id,
            controller_id=payload.controller_id,
            events_list=payload.events,
            device_token=x_device_token,
        )
        return result
    except ControllerAuthenticationError as e:
        logger.warning(f"[GymRoute] Controller auth rejected on event sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized controller: {str(e)}",
        )
    except Exception as e:
        logger.error(f"[GymRoute] Sync offline events error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal sync error: {str(e)}",
        )


# ============================================================================
# 4. POST /controllers/{controller_id}/heartbeat
# ============================================================================

@gym_router.post(
    "/controllers/{controller_id}/heartbeat",
    summary="Record IoT Controller Online Heartbeat",
    status_code=status.HTTP_200_OK,
)
async def controller_heartbeat_endpoint(
    controller_id: str = Path(..., description="Controller Hardware ID"),
    payload: Optional[HeartbeatRequest] = Body(default=None),
    tenant_id_query: Optional[str] = Query(None, alias="tenant_id"),
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
):
    """Updates controller connection status to ONLINE and refreshes last_seen_at."""
    tenant_id = (payload.tenant_id if payload else None) or tenant_id_query or "atmosfitnes"
    firmware_version = payload.firmware_version if payload else None

    try:
        result = await gym_access_service.record_heartbeat(
            tenant_id=tenant_id,
            controller_id=controller_id,
            device_token=x_device_token,
            firmware_version=firmware_version,
        )
        return result
    except ControllerAuthenticationError as e:
        logger.warning(f"[GymRoute] Controller auth rejected on heartbeat: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unauthorized controller: {str(e)}",
        )
    except Exception as e:
        logger.error(f"[GymRoute] Heartbeat error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal heartbeat error: {str(e)}",
        )
