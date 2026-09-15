"""app/routes/tenant_onboard_routes.py
End-to-end data intake routes for tenant onboarding pilot requests and superadmin leads review.

Endpoints:
- POST /api/v1/tenant/onboard: Validates intake payload, stores in control_plane.tenant_prospects,
                               and schedules asynchronous Meta CAPI Lead dispatch.
- GET /api/v1/superadmin/leads: Returns list of onboarding prospects sorted by created_at DESC.
- PATCH /api/v1/superadmin/leads/{id}/status: Updates a lead's status.
"""

import json
import asyncio
import logging
from typing import Optional
from aiohttp import web
from fastapi import APIRouter, HTTPException, status, Body, BackgroundTasks, Request
from pydantic import BaseModel, Field

from app.schemas.tenant_prospect_schema import (
    TenantOnboardIntakeRequest,
    TenantOnboardIntakeResponse,
    TenantProspectItem,
    SuperadminLeadsResponse,
)
from app.services.prospect_service import prospect_service
from app.services.lead_capi_service import dispatch_meta_lead_event

logger = logging.getLogger("TENANT_ONBOARD_ROUTES")

# ============================================================================
# 1. FASTAPI ROUTER DEFINITION
# ============================================================================

tenant_intake_router = APIRouter(tags=["Tenant Onboarding Intake & Superadmin Leads"])


class UpdateLeadStatusRequest(BaseModel):
    status: str = Field(..., min_length=2, max_length=50, description="Status baru prospect")


@tenant_intake_router.post(
    "/api/v1/tenant/onboard",
    response_model=TenantOnboardIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit Tenant Onboarding Pilot Request Intake",
)
async def submit_tenant_onboard_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: TenantOnboardIntakeRequest = Body(..., description="Payload data intake calon tenant"),
):
    """Menerima dan memvalidasi intake calon merchant, mapping feature flags,
    menyimpan ke control_plane.tenant_prospects dengan status 'PROSPECT_PILOT_REQUESTED',
    dan mendispatch event 'Lead' ke Meta Conversions API secara asynchronous di background.
    """
    try:
        # 1. Simpan ke database
        prospect = prospect_service.create_prospect(payload)

        # 2. Extract metadata request untuk Meta CAPI (User-Agent, Client IP)
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or request.headers.get("x-real-ip")
            or (request.client.host if request.client else None)
        )
        client_user_agent = request.headers.get("user-agent")

        # 3. Schedule Asynchronous Meta CAPI Lead Dispatch (Non-blocking)
        background_tasks.add_task(
            dispatch_meta_lead_event,
            prospect_id=str(prospect["id"]),
            brand_name=payload.brand_name,
            industry=payload.industry,
            pic_name=payload.pic_name,
            whatsapp=payload.whatsapp,
            client_ip=client_ip,
            client_user_agent=client_user_agent,
        )

        return TenantOnboardIntakeResponse(
            status="success",
            message=f"Pendaftaran pilot untuk '{payload.brand_name}' berhasil diterima.",
            prospect=TenantProspectItem(**prospect),
        )

    except Exception as e:
        logger.error(f"[Onboard Intake Error] {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal memproses pendaftaran onboarding: {str(e)}",
        )


@tenant_intake_router.get(
    "/api/v1/superadmin/leads",
    response_model=SuperadminLeadsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get All Onboarding Leads for Superadmin",
)
async def get_superadmin_leads_endpoint(
    limit: int = 100,
    offset: int = 0,
):
    """Mengembalikan daftar leads calon tenant terurut dari yang terbaru (created_at DESC)."""
    try:
        leads_raw = prospect_service.list_prospects(limit=limit, offset=offset)
        items = [TenantProspectItem(**item) for item in leads_raw]
        return SuperadminLeadsResponse(
            status="success",
            count=len(items),
            data=items,
        )
    except Exception as e:
        logger.error(f"[Superadmin Leads Error] {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengambil daftar leads: {str(e)}",
        )


@tenant_intake_router.patch(
    "/api/v1/superadmin/leads/{lead_id}/status",
    summary="Update Lead Status by Superadmin",
)
async def update_lead_status_endpoint(
    lead_id: str,
    payload: UpdateLeadStatusRequest = Body(...),
):
    """Memperbarui status prospek tenant (misal: FOLLOWED_UP, ONBOARDED, CLOSED)."""
    try:
        updated = prospect_service.update_status(lead_id, payload.status)
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Lead dengan id '{lead_id}' tidak ditemukan",
            )
        return {
            "status": "success",
            "message": f"Status lead '{lead_id}' berhasil diubah ke '{payload.status}'",
            "data": updated,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Update Lead Status Error] {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal memperbarui status lead: {str(e)}",
        )


# ============================================================================
# 2. AIOHTTP RUNNER ADAPTERS & CORS HANDLERS
# ============================================================================

def _aiohttp_cors_json_response(data: dict, status_code: int = 200) -> web.Response:
    return web.json_response(
        data,
        status=status_code,
        dumps=lambda obj: json.dumps(obj, default=str),
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
        },
    )


async def aiohttp_options_onboard(request: web.Request) -> web.Response:
    return web.Response(
        status=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
        },
    )


async def aiohttp_submit_tenant_onboard(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        payload = TenantOnboardIntakeRequest(**data)
        prospect = prospect_service.create_prospect(payload)

        # Ekstraksi client metadata untuk Meta CAPI
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or request.headers.get("x-real-ip")
            or request.remote
        )
        client_user_agent = request.headers.get("user-agent")

        # Non-blocking CAPI background task
        asyncio.create_task(
            asyncio.to_thread(
                dispatch_meta_lead_event,
                prospect_id=str(prospect["id"]),
                brand_name=payload.brand_name,
                industry=payload.industry,
                pic_name=payload.pic_name,
                whatsapp=payload.whatsapp,
                client_ip=client_ip,
                client_user_agent=client_user_agent,
            )
        )

        return _aiohttp_cors_json_response(
            {
                "status": "success",
                "message": f"Pendaftaran pilot untuk '{payload.brand_name}' berhasil diterima.",
                "prospect": prospect,
            },
            status_code=201,
        )
    except Exception as e:
        logger.error(f"[aiohttp Onboard Intake Error] {e}", exc_info=True)
        return _aiohttp_cors_json_response({"detail": str(e)}, status_code=400)


async def aiohttp_get_superadmin_leads(request: web.Request) -> web.Response:
    try:
        limit = int(request.query.get("limit", 100))
        offset = int(request.query.get("offset", 0))
        leads_raw = prospect_service.list_prospects(limit=limit, offset=offset)
        return _aiohttp_cors_json_response(
            {
                "status": "success",
                "count": len(leads_raw),
                "data": leads_raw,
            },
            status_code=200,
        )
    except Exception as e:
        logger.error(f"[aiohttp Superadmin Leads Error] {e}", exc_info=True)
        return _aiohttp_cors_json_response({"detail": str(e)}, status_code=500)


async def aiohttp_update_lead_status(request: web.Request) -> web.Response:
    try:
        lead_id = request.match_info.get("lead_id")
        data = await request.json()
        new_status = data.get("status")
        if not new_status:
            return _aiohttp_cors_json_response({"detail": "Field 'status' wajib diisi"}, status_code=400)

        updated = prospect_service.update_status(lead_id, new_status)
        if not updated:
            return _aiohttp_cors_json_response({"detail": f"Lead '{lead_id}' tidak ditemukan"}, status_code=404)

        return _aiohttp_cors_json_response(
            {
                "status": "success",
                "message": f"Status lead '{lead_id}' berhasil diubah ke '{new_status}'",
                "data": updated,
            },
            status_code=200,
        )
    except Exception as e:
        logger.error(f"[aiohttp Update Lead Status Error] {e}", exc_info=True)
        return _aiohttp_cors_json_response({"detail": str(e)}, status_code=500)


def register_tenant_onboard_routes(app: web.Application):
    """Mendaftarkan endpoint Onboarding Intake dan Superadmin Leads ke aiohttp web.Application."""
    routes_to_add = [
        ("POST", "/api/v1/tenant/onboard", aiohttp_submit_tenant_onboard),
        ("OPTIONS", "/api/v1/tenant/onboard", aiohttp_options_onboard),
        ("GET", "/api/v1/superadmin/leads", aiohttp_get_superadmin_leads),
        ("OPTIONS", "/api/v1/superadmin/leads", aiohttp_options_onboard),
        ("PATCH", "/api/v1/superadmin/leads/{lead_id}/status", aiohttp_update_lead_status),
        ("OPTIONS", "/api/v1/superadmin/leads/{lead_id}/status", aiohttp_options_onboard),
    ]

    existing_routes = set()
    for r in app.router.routes():
        try:
            canonical = getattr(getattr(r, "resource", None), "canonical", None)
            method = getattr(r, "method", None)
            if canonical and method:
                existing_routes.add((method.upper(), canonical.rstrip("/")))
        except Exception:
            pass

    for method, path, handler in routes_to_add:
        norm_path = path.rstrip("/")
        if (method, norm_path) not in existing_routes:
            if method == "POST":
                app.router.add_post(path, handler)
            elif method == "GET":
                app.router.add_get(path, handler)
            elif method == "PATCH":
                app.router.add_patch(path, handler)
            elif method == "OPTIONS":
                app.router.add_options(path, handler)