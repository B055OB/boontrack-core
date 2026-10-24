import sys
import os

# Setup path aplikasi
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from app.modules.public_services.router import fastapi_public_service_router
import asyncio
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
from supabase import create_client, Client, ClientOptions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MAIN")

# Bounded HTTP socket timeout (2.5s connect, 5.0s read/write) to prevent thread/socket hangs
SUPABASE_HTTP_TIMEOUT = httpx.Timeout(connect=2.5, read=5.0, write=5.0, pool=5.0)

# Inisialisasi Supabase Public / Tenant Client (Principle of Least Privilege: Anon / Standard Key bound by RLS)
supabase_url = os.getenv("SUPABASE_URL", "").strip()
supabase_anon_key = (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY", "")).strip()

if not supabase_url or not supabase_anon_key:
    raise RuntimeError(
        "[SECURITY FAIL-CLOSED] Mandatory Supabase public configuration is missing in app.main. "
        "SUPABASE_URL and SUPABASE_ANON_KEY (or SUPABASE_KEY) must be configured in environment. "
        "SUPABASE_SERVICE_ROLE_KEY is strictly prohibited for standard application client."
    )

try:
    # Standard tenant/merchant/public client (restricted by RLS) with bounded HTTP socket timeout
    supabase_client: Client = create_client(
        supabase_url,
        supabase_anon_key,
        options=ClientOptions(postgrest_client_timeout=SUPABASE_HTTP_TIMEOUT)
    )
except Exception as e:
    raise RuntimeError(f"[SECURITY FAIL-CLOSED] Failed to initialize Supabase client in app.main: {e}") from e


def get_admin_supabase_client() -> Client:
    """Isolated administrative Supabase client using SUPABASE_SERVICE_ROLE_KEY.
    STRICT PRIVILEGE SEPARATION:
    Only accessible by verified administrative execution paths (e.g., signature-verified payment webhooks).
    Never exposed to standard tenant/merchant endpoints or client bundles.
    """
    admin_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not admin_key or not supabase_url:
        raise RuntimeError(
            "[SECURITY FAIL-CLOSED] SUPABASE_SERVICE_ROLE_KEY is required for administrative operations but not configured."
        )
    return create_client(
        supabase_url,
        admin_key,
        options=ClientOptions(postgrest_client_timeout=SUPABASE_HTTP_TIMEOUT)
    )

from app.routes.gym_access_routes import gym_router
from app.routes.gym_admin_routes import router as gym_admin_router
from app.routes.payment import payment_router
from app.routes.webchat import router as webchat_router
from app.routes.internal_routes import internal_router
from app.routes.xendit import xendit_router
from app.routes.onboarding import onboarding_router
from app.routes.tenant_onboard_routes import tenant_intake_router
from app.routes.meta_whatsapp import meta_whatsapp_router
from app.routes.chat import chat_router
from app.routes.tenant_routes import tenant_router, tenant_singular_router, commerce_products_router, legacy_tenant_router, storefront_router

from app.routes.shop_gateway_routes import shop_gateway_fastapi_router
from app.routes.shop_subscription_routes import (
    shop_subscription_fastapi_router,
    subscription_fastapi_router,
)
from app.routes.shop_event_routes import shop_event_fastapi_router
from app.api.webhook_payment import router as webhook_payment_router
from app.services.payout_service import PayoutService

# IMPORT ROUTER ENTITLEMENT, WHATSAPP GATEWAY, PROVISIONING, GROWTH & SHIPPING LOGISTICS
from app.routes.entitlement_routes import router as entitlement_router
from app.routes.whatsapp_gateway_routes import router as whatsapp_gateway_router, tenant_reconnect_router
from app.routes.whatsapp_control import router as whatsapp_control_router
from app.routes.provisioning import router as provisioning_router
from app.routes.growth_routes import router as growth_router
from app.routes.d2c_order_routes import d2c_router
from app.routes.meta_oauth import meta_exchange_router
from app.routes.affiliate_auth import router as affiliate_auth_router, affiliate_payout_router, affiliate_router
from app.routes.meta_waba_routes import waba_router
from app.routes.whatsapp_connect_routes import whatsapp_connect_router
from app.routes.academy_routes import academy_router
from app.routes.shipping_routes import router as shipping_router, logistics_router
from app.routes.partner_routes import partner_router, manager_router
from app.routes.analytics_fastapi_routes import router as analytics_router
from app.routes.boonpilot_routes import router as boonpilot_router, merchant_copilot_router
from app.routes.billing_routes import billing_router
from app.routes.store_chat_routes import router as store_chat_router
from app.routes.media_routes import media_router, general_upload_router
from app.routes.product_routes import product_router, product_singular_router
from app.routes.auth_routes import router as auth_router, auth_general_router
from app.routes.custom_domain_routes import custom_domain_router
from app.api.v1.api import api_v1_router
from app.api.v1.endpoints.whatsapp_webhook import router as whatsapp_webhook_router
from app.api.v1.reader_router import router as reader_router
from app.tenants.career.router import career_fastapi_router
from app.routers.creator_ugc import router as creator_ugc_router
from app.routes.creator_storefront import router as creator_storefront_router
from app.routes.digital_download_routes import router as digital_download_router
from app.routes.inbox_routes import router as inbox_router
from app.routes.telegram_webhook_routes import router as telegram_webhook_router
from app.routes.store_starter_routes import store_starter_router
from fastapi.staticfiles import StaticFiles

# Supabase Client is initialized above at entry point

from app.core.tracing import TracingMiddleware

# ============================================================================
# FastAPI Application Entrypoint (Uvicorn / ASGI compatible)
# ============================================================================

app = FastAPI(
    title="BoonTrack Core API",
    description="Unified Multi-Tenant Core Engine & IoT Access Control Service",
    version="1.0.0",
)

from app.core.logging_sanitizer import install_global_pii_sanitizer, sanitize_pii_recursive
install_global_pii_sanitizer()

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    encoded_detail = jsonable_encoder(exc.detail)
    sanitized_detail = sanitize_pii_recursive(encoded_detail)
    if isinstance(sanitized_detail, dict) and "error" in sanitized_detail:
        return JSONResponse(status_code=exc.status_code, content=sanitized_detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": sanitized_detail})

@app.exception_handler(Exception)
async def global_unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"[UNHANDLED EXCEPTION] Path: {request.url.path} | Error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "INTERNAL_SERVER_ERROR", "message": "An unexpected server error occurred."}
    )

app.add_middleware(TracingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dashboard.boontrack.com",
        "http://dashboard.boontrack.com",
        "https://shop.boontrack.com",
        "http://shop.boontrack.com",
        "https://boontrack.com",
        "http://boontrack.com",
        "https://inbox.boontrack.com",
        "https://affiliate.boontrack.com",
        "https://partner.boontrack.com",
        "https://api.boontrack.com",
        "https://boontrack-inbox.vercel.app",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"^https?://([a-zA-Z0-9-]+\.)?boontrack\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def affiliate_cache_control_middleware(request: Request, call_next):
    """
    Header P0.5 Cache Boundary:
    Set Cache-Control: private, no-store, no-cache, must-revalidate
    untuk response endpoint /api/v1/affiliate/* agar data dashboard privat tidak pernah di-cache.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/affiliate"):
        response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate"
    return response


@app.middleware("http")
async def entitlement_enforcement_middleware(request: Request, call_next):
    """
    Middleware Guard: Memastikan tenant berstatus CHECKOUT_LITE (atau plan yang tidak entitled)
    tidak dapat mengakses fitur terlarang seperti /api/v1/analytics/* dan /api/v1/broadcast/*.
    Mengembalikan HTTP 403 FEATURE_NOT_ENTITLED.
    """
    path = request.url.path
    if path.startswith("/api/v1/analytics") or path.startswith("/api/v1/broadcast"):
        tenant_slug = (
            request.query_params.get("tenant_slug")
            or request.query_params.get("tenant_id")
            or request.headers.get("x-tenant-slug")
            or request.headers.get("x-tenant-id")
        )
        if tenant_slug:
            from app.services.entitlement_service import tenant_context_resolver
            from fastapi.responses import JSONResponse
            ctx = await tenant_context_resolver.resolve(tenant_slug)
            if path.startswith("/api/v1/analytics") and not tenant_context_resolver.can_use(ctx, "analytics.advanced"):
                return JSONResponse(status_code=403, content={"detail": "FEATURE_NOT_ENTITLED"})
            if path.startswith("/api/v1/broadcast") and not tenant_context_resolver.can_use(ctx, "broadcast"):
                return JSONResponse(status_code=403, content={"detail": "FEATURE_NOT_ENTITLED"})

    return await call_next(request)

# Register Routers ke FastAPI
app.include_router(gym_router, prefix="/api/v1/gym")
app.include_router(gym_admin_router)
app.include_router(xendit_router)
app.include_router(payment_router)
app.include_router(webchat_router)
app.include_router(internal_router)
app.include_router(onboarding_router)
app.include_router(tenant_intake_router)
app.include_router(api_v1_router)
app.include_router(whatsapp_webhook_router)
app.include_router(meta_whatsapp_router)
app.include_router(chat_router)
app.include_router(tenant_router)
app.include_router(storefront_router)
app.include_router(tenant_singular_router)
app.include_router(commerce_products_router)
app.include_router(legacy_tenant_router)
app.include_router(shop_gateway_fastapi_router)
app.include_router(shop_subscription_fastapi_router)
app.include_router(subscription_fastapi_router)
app.include_router(shop_event_fastapi_router)
app.include_router(webhook_payment_router)

# DAFTARKAN ENTITLEMENT, WHATSAPP GATEWAY, CONTROL, PROVISIONING & GROWTH ROUTER
app.include_router(entitlement_router)
app.include_router(whatsapp_gateway_router)
app.include_router(tenant_reconnect_router)
app.include_router(whatsapp_control_router)
app.include_router(provisioning_router)
app.include_router(growth_router)
app.include_router(d2c_router)
app.include_router(meta_exchange_router)
app.include_router(affiliate_auth_router)
app.include_router(affiliate_payout_router)
app.include_router(affiliate_router)
app.include_router(waba_router)
app.include_router(whatsapp_connect_router)
app.include_router(academy_router)
app.include_router(shipping_router)
app.include_router(logistics_router)
app.include_router(partner_router)
app.include_router(manager_router)
app.include_router(analytics_router)
app.include_router(boonpilot_router)
app.include_router(merchant_copilot_router)
app.include_router(billing_router)
app.include_router(store_chat_router)
app.include_router(fastapi_public_service_router)
app.include_router(media_router)
app.include_router(general_upload_router)
app.include_router(product_router)
app.include_router(product_singular_router)
app.include_router(auth_router)
app.include_router(auth_general_router)
app.include_router(reader_router)
app.include_router(custom_domain_router)
app.include_router(career_fastapi_router)
app.include_router(creator_ugc_router)
app.include_router(creator_storefront_router)
app.include_router(digital_download_router)
app.include_router(inbox_router)
app.include_router(telegram_webhook_router)
app.include_router(store_starter_router)

# Mount Static Uploads
uploads_dir = os.path.join(project_root, "assets", "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/assets/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# Mount Obfuscated Reader APK Download (FastAPI)
reader_dir = os.path.join(project_root, "static", "dl-reader-x9k2m")
os.makedirs(reader_dir, exist_ok=True)
app.mount("/dl-reader-x9k2m", StaticFiles(directory=reader_dir), name="reader_download")


@app.get("/", summary="Root Liveness Check")
@app.get("/health", summary="Process Liveness Check")
async def root_health_check():
    """Liveness probe: Returns HTTP 200 while the application process is alive and responsive.
    Strictly zero network calls. Does not falsely claim unverified external connectivity.
    """
    return {
        "status": "healthy",
        "service": "boontrack-core",
        "version": "1.0.0",
        "database": {
            "supabase": "configured" if supabase_client else "unconfigured"
        }
    }


@app.get("/ready", summary="Dependency Readiness Check")
async def readiness_check(response: Response):
    """Readiness probe: Validates genuine dependency connectivity to Supabase.
    Returns HTTP 200 when ready to serve requests, or HTTP 503 when dependencies are unreachable.
    Uses bounded HTTP timeouts configured at client initialization without mutating shared state.
    Public responses return sanitized error categories; diagnostics are preserved in server logs.
    """
    db_status = "unconfigured"
    is_ready = False
    error_category: Optional[str] = None

    if not supabase_client:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "service": "boontrack-core",
            "version": "1.0.0",
            "database": {"supabase": "unconfigured"},
            "dependencies": {
                "supabase": {
                    "status": "unconfigured",
                    "category": "DEPENDENCY_NOT_CONFIGURED"
                }
            }
        }

    try:
        # Offload synchronous query to worker thread.
        # ClientOptions(postgrest_client_timeout=SUPABASE_HTTP_TIMEOUT) guarantees socket terminates.
        res = await asyncio.to_thread(lambda: supabase_client.table("tenants").select("id").limit(1).execute())
        if res and hasattr(res, "data") and res.data is not None:
            db_status = "active"
            is_ready = True
        else:
            db_status = "degraded"
            is_ready = False
            error_category = "DEPENDENCY_MALFORMED_RESPONSE"
    except (httpx.TimeoutException, TimeoutError) as e:
        logger.warning(f"[READINESS CHECK] Supabase connection timed out: {e}")
        db_status = "timeout"
        is_ready = False
        error_category = "DEPENDENCY_TIMEOUT"
    except Exception as e:
        logger.warning(f"[READINESS CHECK] Supabase connection error: {e}")
        db_status = "unreachable"
        is_ready = False
        error_category = "DEPENDENCY_UNREACHABLE"

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    dep_info = {"status": db_status}
    if error_category:
        dep_info["category"] = error_category

    return {
        "status": "ready" if is_ready else "unhealthy",
        "service": "boontrack-core",
        "version": "1.0.0",
        "database": {
            "supabase": db_status
        },
        "dependencies": {
            "supabase": dep_info
        }
    }



@app.get("/api/v1/system/cache/refresh", summary="Force Refresh Tenant Resolver Cache")
@app.post("/api/v1/system/cache/refresh", summary="Force Refresh Tenant Resolver Cache")
@app.get("/api/v1/system/tenant-resolver/refresh", summary="Force Refresh Tenant Resolver Cache")
@app.post("/api/v1/system/tenant-resolver/refresh", summary="Force Refresh Tenant Resolver Cache")
async def fastapi_tenant_cache_refresh(
    phone_number_id: str = "541699802061762",
    slug: str = "onlineboost",
    update: bool = False,
):
    import re
    from app.services.tenant_context_resolver import tenant_context_resolver
    from app.services.tenant_resolver import (
        async_clear_tenant_cache,
        resolve_tenant_by_phone_number_id,
    )
    from app.services.whatsapp_service import get_supabase

    tenant_context_resolver.clear_cache()
    await async_clear_tenant_cache()
    try:
        from app.services.circuit_breaker_service import circuit_breaker_service
        circuit_breaker_service.clear()
    except Exception:
        pass

    update_info = None
    if update:
        try:
            sb = get_supabase()
            if sb:
                t_res = sb.table("tenants").select("id, metadata").eq("slug", slug).execute()
                if t_res.data:
                    current_meta = t_res.data[0].get("metadata") or {}
                    current_meta["waba_phone_number_id"] = phone_number_id
                    current_meta["phone_number_id"] = phone_number_id
                    sb.table("tenants").update({
                        "waba_phone_number_id": phone_number_id,
                        "metadata": current_meta,
                        "is_active": True,
                    }).eq("slug", slug).execute()
                try:
                    cfg_chk = sb.table("tenant_waba_configs").select("id").eq("tenant_id", slug).execute()
                    if cfg_chk.data:
                        sb.table("tenant_waba_configs").update({
                            "waba_phone_number_id": phone_number_id,
                            "is_active": True,
                        }).eq("tenant_id", slug).execute()
                    else:
                        sb.table("tenant_waba_configs").insert({
                            "tenant_id": slug,
                            "waba_phone_number_id": phone_number_id,
                            "is_active": True,
                        }).execute()
                except Exception:
                    pass
                update_info = {"status": "success", "message": f"Updated tenant '{slug}' to phone_id '{phone_number_id}'"}
        except Exception as upd_err:
            update_info = {"status": "error", "message": str(upd_err)}

    probe_ctx = await tenant_context_resolver.resolve_by_phone_number_id(phone_number_id, force_refresh=True)
    probe_waba = await resolve_tenant_by_phone_number_id(phone_number_id, force_refresh=True)

    sb_record = None
    sb = get_supabase()
    if sb:
        try:
            res_live = sb.table("tenants").select("id, slug, is_active, waba_phone_number_id, metadata").eq("slug", slug).execute()
            if res_live.data:
                row = res_live.data[0]
                meta = row.get("metadata") or {}
                sb_record = {
                    "id": row.get("id"),
                    "slug": row.get("slug"),
                    "is_active": row.get("is_active"),
                    "waba_phone_number_id": row.get("waba_phone_number_id"),
                    "meta_waba_id": meta.get("waba_phone_number_id"),
                    "meta_phone_id": meta.get("phone_number_id"),
                }
        except Exception as e_sb:
            sb_record = {"error": str(e_sb)}

    supabase_url_val = os.getenv("SUPABASE_URL", "")
    expected_url = "https://mpluzajlzpregmjwpjqr.supabase.co"
    database_url_val = os.getenv("DATABASE_URL", "")
    masked_db = re.sub(r":([^:@]+)@", r":***@", database_url_val) if database_url_val else ""

    res_body = {
        "status": "success",
        "message": "Tenant resolver cache flushed and probes executed.",
        "cache_flushed": {
            "tenant_context_resolver_l1": True,
            "tenant_resolver_l1": True,
            "tenant_resolver_l2_redis": True,
        },
        "env_diagnostics": {
            "supabase_url": supabase_url_val,
            "matches_expected_supabase_url": (supabase_url_val.rstrip("/") == expected_url.rstrip("/")),
            "postgres_host": os.getenv("POSTGRES_HOST", ""),
            "database_url_masked": masked_db,
            "railway_environment": os.getenv("RAILWAY_ENVIRONMENT", "production"),
            "waba_env_ids": {
                "META_WABA_PHONE_NUMBER_ID": os.getenv("META_WABA_PHONE_NUMBER_ID"),
                "WABA_PHONE_NUMBER_ID": os.getenv("WABA_PHONE_NUMBER_ID"),
                "WHATSAPP_PHONE_NUMBER_ID": os.getenv("WHATSAPP_PHONE_NUMBER_ID"),
                "PHONE_NUMBER_ID": os.getenv("PHONE_NUMBER_ID"),
            }
        },
        "target_probed": {
            "phone_number_id": phone_number_id,
            "slug": slug,
            "tenant_context_resolver": {
                "resolved": probe_ctx is not None,
                "tenant_id": probe_ctx.tenant_id if probe_ctx else None,
                "slug": probe_ctx.slug if probe_ctx else None,
                "name": probe_ctx.name if probe_ctx else None,
            },
            "tenant_resolver": probe_waba,
            "supabase_database_row": sb_record,
        }
    }
    if update_info:
        res_body["db_update_result"] = update_info
    return res_body


@app.get("/api/ads-config", summary="Tenant Ads Pixel Config Root")
@app.get("/api/v1/store/ads-config", summary="Tenant Ads Pixel Config v1 Store")
@app.get("/api/v1/shop/{tenant_slug}/ads-config", summary="Tenant Shop Ads Pixel Config")
async def get_store_ads_config(tenant_slug: str = "kurastorenkrw"):
    return {
        "status": "success",
        "tenant_slug": tenant_slug,
        "meta_pixel_id": None,
        "tiktok_pixel_id": None,
        "google_tag_id": None,
    }


@app.post("/payout/settle", summary="Batch Settle Affiliate Commission")
async def settle_payout(payload: Dict[str, Any]):
    code = payload.get("affiliate_code")
    notes = payload.get("notes", "Disbursement Manual Transfer")
    if not code:
        raise HTTPException(status_code=400, detail="Missing affiliate_code")
    
    service = PayoutService(supabase_client)
    result = await service.settle_affiliate_batch(code, notes)
    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
