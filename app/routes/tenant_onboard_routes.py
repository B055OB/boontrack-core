"""app/routes/tenant_onboard_routes.py
End-to-end data intake routes for tenant onboarding pilot requests and superadmin leads review.

Endpoints:
- POST /api/v1/tenant/onboard: Validates intake payload, stores in control_plane.tenant_prospects,
                               and schedules asynchronous Meta CAPI Lead dispatch.
- GET /api/v1/superadmin/leads: Returns list of onboarding prospects sorted by created_at DESC.
- PATCH /api/v1/superadmin/leads/{id}/status: Updates a lead's status.
"""

import logging
from typing import Optional
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
