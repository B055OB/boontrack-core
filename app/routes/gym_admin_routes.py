"""app/routes/gym_admin_routes.py
Admin Dashboard REST Endpoints for Atmosfitnes Gym & IoT Access Control.
Mounted under: /api/v1/gym/admin/

Provides real-time operational feeds for dashboard (bossob.boontrack.com):
- Member list & NFC pairing statuses
- NFC Card Pairing action
- Audit access events log feed
- Controller device heartbeats and online indicators
"""

import logging
from typing import Optional
from fastapi import APIRouter, Query, Path, HTTPException, status
from pydantic import BaseModel, Field

from app.services.gym_access_service import gym_access_service
from app.schemas.gym_schema import PairCardRequest

logger = logging.getLogger("GYM_ADMIN_ROUTES")

router = APIRouter(
    prefix="/api/v1/gym/admin",
    tags=["Gym Admin Dashboard"],
)


@router.get("/members", summary="List members with NFC pairing status and filters")
async def list_admin_members(
    tenant_id: str = Query("atmosfitnes", description="Tenant ID"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status: ACTIVE, EXPIRED, SUSPENDED"),
    package: Optional[str] = Query(None, description="Filter by membership package code"),
):
    """Returns paginated member list including NFC card pairing status."""
    try:
        data = await gym_access_service.get_admin_members(
            tenant_id=tenant_id,
            page=page,
            limit=limit,
            status=status,
            package=package,
        )
        return {
            "status": "success",
            "data": data,
        }
    except Exception as e:
        logger.error(f"[GymAdminAPI] Error listing members: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve members: {str(e)}",
        )


@router.post("/members/{member_id}/pair-card", summary="Pair an NFC Card UID to a gym member")
async def pair_member_card(
    member_id: str = Path(..., description="Target Member UUID / ID"),
    payload: PairCardRequest = ...,
):
    """Pairs or updates an NFC card UID hash to a gym member."""
    try:
        res = await gym_access_service.pair_card(
            tenant_id=payload.tenant_id,
            member_id=member_id,
            uid_hash=payload.uid_hash,
        )
        if res.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=res.get("message"),
            )
        return {
            "status": "success",
            "data": res,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[GymAdminAPI] Error pairing card: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pair card: {str(e)}",
        )


@router.get("/access-logs", summary="Query audit access events log feed")
async def list_admin_access_logs(
    tenant_id: str = Query("atmosfitnes", description="Tenant ID"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
):
    """Returns access log events sorted by timestamp DESC."""
    try:
        data = await gym_access_service.get_admin_access_logs(
            tenant_id=tenant_id,
            limit=limit,
        )
        return {
            "status": "success",
            "data": data,
        }
    except Exception as e:
        logger.error(f"[GymAdminAPI] Error retrieving access logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve access logs: {str(e)}",
        )


@router.get("/controllers", summary="List IoT turnstile controllers with online status")
async def list_admin_controllers(
    tenant_id: str = Query("atmosfitnes", description="Tenant ID"),
):
    """Returns list of turnstile controllers with real-time online indicator (last_seen_at <= 60s)."""
    try:
        data = await gym_access_service.get_admin_controllers(
            tenant_id=tenant_id,
        )
        return {
            "status": "success",
            "data": data,
        }
    except Exception as e:
        logger.error(f"[GymAdminAPI] Error listing controllers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list controllers: {str(e)}",
        )
