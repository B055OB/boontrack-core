"""app/api/v1/endpoints/tenant_onboarding.py
Tenant Onboarding API Endpoints.

Provides:
- POST /api/v1/tenant/onboard:
  1. Checks slug uniqueness in PostgreSQL / registry (returns HTTP 409 Conflict if duplicate).
  2. Creates new Tenant record with default configuration.
  3. Binds TenantWabaConfig if waba_phone_number_id is provided.
  4. Returns TenantResponse.
  5. Backwards-compatible support for legacy intake pilot leads.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select

from app.models.tenant import OnboardingMode, Tenant, TenantTier
from app.schemas.tenant import TenantCreateRequest, TenantResponse

logger = logging.getLogger("TENANT_ONBOARDING_ENDPOINT")

router = APIRouter(tags=["Tenant Onboarding"])

# In-memory store for fast offline testing & state sync
_onboarded_tenants_store: Dict[str, Dict[str, Any]] = {}


def clear_onboarded_tenants_store() -> None:
    """Helper to clear local store between tests."""
    _onboarded_tenants_store.clear()


async def check_tenant_slug_exists(slug: str) -> bool:
    """Checks if a tenant with the given slug already exists in registry or database."""
    clean_slug = slug.strip().lower()

    # 1. In-memory check
    if clean_slug in _onboarded_tenants_store:
        return True

    # 2. Check via SQLAlchemy
    try:
        from app.core.server import async_session
        async with async_session() as session:
            stmt = select(Tenant).where(Tenant.slug == clean_slug)
            result = await session.execute(stmt)
            if result.scalars().first():
                return True
    except Exception as sa_err:
        logger.debug(f"[TENANT_ONBOARDING] SQLAlchemy check note: {sa_err}")

    # 3. Check via direct psycopg2 connection
    def _sync_db_check() -> bool:
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
        except Exception:
            return False

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM tenants WHERE slug = %s LIMIT 1;",
                    (clean_slug,),
                )
                return cur.fetchone() is not None
        except Exception:
            return False
        finally:
            conn.close()

    try:
        if await asyncio.to_thread(_sync_db_check):
            return True
    except Exception:
        pass

    # 4. Check via Supabase Client
    try:
        from app.services.tenant_context_resolver import get_supabase
        supabase = get_supabase()
        if supabase:
            res = (
                supabase.table("tenants")
                .select("id")
                .eq("slug", clean_slug)
                .limit(1)
                .execute()
            )
            if res and res.data and len(res.data) > 0:
                return True
    except Exception:
        pass

    return False


async def save_new_tenant(
    tenant_id: uuid.UUID,
    payload: TenantCreateRequest,
    created_at: datetime,
) -> None:
    """Persists newly onboarded tenant and WABA configuration across stores."""
    clean_slug = payload.slug.strip().lower()
    clean_waba_id = (
        payload.waba_phone_number_id.strip()
        if payload.waba_phone_number_id
        else None
    )

    # 1. Update in-memory stores and dependency caches
    tenant_dict = {
        "id": str(tenant_id),
        "name": payload.name,
        "slug": clean_slug,
        "business_category": payload.business_category,
        "status": "active",
        "is_active": True,
        "waba_phone_number_id": clean_waba_id,
        "created_at": created_at,
        "tier": "STARTER",
    }
    _onboarded_tenants_store[clean_slug] = tenant_dict
    _onboarded_tenants_store[str(tenant_id)] = tenant_dict

    # Register in global dependency cache
    from app.api.deps import register_test_tenant
    register_test_tenant(
        tenant_id=str(tenant_id),
        slug=clean_slug,
        name=payload.name,
        is_active=True,
        business_category=payload.business_category,
        waba_phone_number_id=clean_waba_id,
    )

    # Register WABA mapping if provided
    if clean_waba_id:
        from app.services.tenant_resolver import register_tenant_waba_mapping
        register_tenant_waba_mapping(
            phone_number_id=clean_waba_id,
            tenant_id=str(tenant_id),
            is_active=True,
        )

    # 2. Persist to PostgreSQL via SQLAlchemy
    try:
        from app.core.server import async_session
        from app.models.tenant_waba import TenantWabaConfig

        async with async_session() as session:
            async with session.begin():
                tenant_model = Tenant(
                    id=tenant_id,
                    name=payload.name,
                    slug=clean_slug,
                    tier=TenantTier.STARTER,
                    onboarding_mode=OnboardingMode.SELF_SERVICE,
                    template=payload.business_category or "COMMERCE_TEMPLATE",
                    is_active=True,
                    created_at=created_at,
                )
                session.add(tenant_model)

                if clean_waba_id:
                    waba_config = TenantWabaConfig(
                        id=uuid.uuid4(),
                        tenant_id=str(tenant_id),
                        waba_phone_number_id=clean_waba_id,
                        is_active=True,
                    )
                    session.add(waba_config)
    except Exception as sa_err:
        logger.debug(f"[TENANT_ONBOARDING] SQLAlchemy insert note: {sa_err}")

    # 3. Direct psycopg2 insert fallback
    def _sync_insert() -> None:
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
        except Exception:
            return

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tenants (id, name, slug, tier, onboarding_mode, is_active, created_at)
                    VALUES (%s, %s, %s, 'STARTER', 'SELF_SERVICE', TRUE, %s)
                    ON CONFLICT (slug) DO NOTHING;
                    """,
                    (str(tenant_id), payload.name, clean_slug, created_at),
                )
                if clean_waba_id:
                    cur.execute(
                        """
                        INSERT INTO tenant_waba_configs (id, tenant_id, waba_phone_number_id, is_active, created_at)
                        VALUES (%s, %s, %s, TRUE, %s)
                        ON CONFLICT (waba_phone_number_id) DO NOTHING;
                        """,
                        (str(uuid.uuid4()), str(tenant_id), clean_waba_id, created_at),
                    )
                conn.commit()
        except Exception as q_err:
            logger.debug(f"[TENANT_ONBOARDING] psycopg2 insert note: {q_err}")
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_sync_insert)
    except Exception:
        pass


@router.post(
    "/api/v1/tenant/onboard",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard New Tenant with Isolation & Optional WABA Binding",
)
@router.post(
    "/tenant/onboard",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard New Tenant with Isolation & Optional WABA Binding (Alias)",
)
async def onboard_tenant_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(..., description="Payload data pendaftaran tenant"),
):
    """Mendaftarkan tenant baru:
    1. Cek keunikan slug di database PostgreSQL. Jika duplikat, kembalikan HTTP 409 Conflict.
    2. Buat record tenant baru dan inisialisasi default configuration (termasuk binding TenantWabaConfig jika waba_phone_number_id disertakan).
    3. Kembalikan response TenantResponse dengan HTTP 201 Created.
    4. Mendukung fallback integrasi pilot intake lead jika payload berisi 'brand_name'.
    """
    # 0. Check if this is a pilot prospect intake payload (backwards compatibility)
    if "brand_name" in payload and "slug" not in payload:
        try:
            from app.schemas.tenant_prospect_schema import TenantOnboardIntakeRequest
            from app.services.prospect_service import prospect_service
            from app.services.lead_capi_service import dispatch_meta_lead_event

            intake_req = TenantOnboardIntakeRequest.model_validate(payload)
            prospect = prospect_service.create_prospect(intake_req)

            client_user_agent = request.headers.get("user-agent", "FastAPI/BoonTrack")
            client_ip_address = request.client.host if request.client else "127.0.0.1"

            background_tasks.add_task(
                dispatch_meta_lead_event,
                prospect_id=prospect["id"],
                raw_phone=intake_req.whatsapp,
                client_user_agent=client_user_agent,
                client_ip_address=client_ip_address,
            )

            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={
                    "status": "success",
                    "message": "Tenant onboarding intake berhasil disimpan.",
                    "prospect": prospect,
                },
            )
        except Exception as intake_err:
            logger.warning(f"[TENANT_ONBOARDING] Pilot intake fallback note: {intake_err}")
            raise

    # 1. Parse and validate TenantCreateRequest
    try:
        tenant_create = TenantCreateRequest.model_validate(payload)
    except ValidationError as val_err:
        serializable_errors = []
        for err in val_err.errors():
            clean_err = dict(err)
            if "ctx" in clean_err and isinstance(clean_err["ctx"], dict):
                clean_err["ctx"] = {k: str(v) for k, v in clean_err["ctx"].items()}
            serializable_errors.append(clean_err)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=serializable_errors,
        )

    # 2. Check slug uniqueness in PostgreSQL / Cache
    clean_slug = tenant_create.slug.strip().lower()
    slug_exists = await check_tenant_slug_exists(clean_slug)
    if slug_exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant dengan slug '{clean_slug}' sudah terdaftar. Gunakan slug unik lainnya.",
        )

    # 3. Create new tenant entity
    new_tenant_id = uuid.uuid4()
    now_utc = datetime.now(timezone.utc)

    await save_new_tenant(
        tenant_id=new_tenant_id,
        payload=tenant_create,
        created_at=now_utc,
    )

    # 4. Return TenantResponse
    return TenantResponse(
        id=str(new_tenant_id),
        name=tenant_create.name,
        slug=clean_slug,
        business_category=tenant_create.business_category,
        status="active",
        is_active=True,
        waba_phone_number_id=tenant_create.waba_phone_number_id,
        created_at=now_utc,
    )
