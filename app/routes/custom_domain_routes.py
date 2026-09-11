"""app/routes/custom_domain_routes.py
Tenant Custom Domain Management Endpoints for Cloudflare for SaaS.

Endpoints:
- POST /api/v1/store/custom-domain: Registers a custom domain with Cloudflare and updates tenant DB.
- GET /api/v1/store/custom-domain/status: Fetches live SSL/DNS activation status from Cloudflare.
- DELETE /api/v1/store/custom-domain: Removes custom domain from Cloudflare and clears tenant DB.

Aliases supported:
- POST/GET/DELETE /api/v1/tenants/{slug}/custom-domain
- POST/GET/DELETE /api/v1/tenants/{slug}/custom-domain/status
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, HTTPException, status, Request, Body, Query
from pydantic import BaseModel, Field
from aiohttp import web

from app.services.cloudflare import (
    cloudflare_service,
    clean_domain,
    validate_domain_name,
    CloudflareAPIError,
    DEFAULT_CNAME_TARGET,
)
from app.services.whatsapp_service import get_supabase
from app.services.onboarding_service import onboarding_service, slugify

logger = logging.getLogger("CUSTOM_DOMAIN_ROUTES")

custom_domain_router = APIRouter(tags=["Tenant Custom Domain"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Tenant-Slug, X-Tenant-Id",
}


class CustomDomainRegisterRequest(BaseModel):
    model_config = {"extra": "allow"}

    domain: str = Field(..., description="Custom domain or subdomain (e.g., 'toko.brandanda.com')")
    tenant_slug: Optional[str] = Field(None, description="Slug of the tenant store")
    ssl_method: Optional[str] = Field("http", description="SSL verification method: 'http' or 'txt'")


class CustomDomainResponse(BaseModel):
    status: str
    message: str
    tenant_slug: str
    custom_domain: Optional[str] = None
    cloudflare_hostname_id: Optional[str] = None
    custom_domain_status: Optional[str] = None
    ssl_status: Optional[str] = None
    is_active: bool = False
    cname_target: str = DEFAULT_CNAME_TARGET
    dns_instructions: Optional[Dict[str, Any]] = None
    verification_records: Optional[List[Dict[str, Any]]] = None


def _resolve_tenant_slug(
    path_slug: Optional[str] = None,
    body_slug: Optional[str] = None,
    query_slug: Optional[str] = None,
    header_slug: Optional[str] = None,
) -> str:
    """Extracts and normalizes tenant slug from available request sources."""
    candidate = path_slug or query_slug or body_slug or header_slug
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Identifier tenant (tenant_slug atau slug) wajib disertakan.",
        )
    return slugify(candidate)


def _get_tenant_record_from_db(slug: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Fetches tenant row and metadata from Supabase."""
    supabase = get_supabase()
    if not supabase:
        return None, None
    try:
        res = supabase.table("tenants").select("*").eq("slug", slug).execute()
        if res.data:
            tenant_row = res.data[0]
            metadata = tenant_row.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            return tenant_row, metadata
    except Exception as e:
        logger.error(f"[CustomDomain] Error querying Supabase for tenant '{slug}': {e}")
    return None, None


def _update_tenant_metadata(slug: str, meta_updates: Dict[str, Any]) -> bool:
    """Persists updated custom domain metadata to Supabase tenants table."""
    supabase = get_supabase()
    if not supabase:
        return False
    try:
        tenant_row, existing_meta = _get_tenant_record_from_db(slug)
        merged_meta = {**(existing_meta or {}), **meta_updates}

        update_payload = {
            "metadata": merged_meta,
        }
        supabase.table("tenants").update(update_payload).eq("slug", slug).execute()

        # Update in-memory registry if present
        if slug in onboarding_service.TENANT_REGISTRY:
            if "metadata" not in onboarding_service.TENANT_REGISTRY[slug]:
                onboarding_service.TENANT_REGISTRY[slug]["metadata"] = {}
            onboarding_service.TENANT_REGISTRY[slug]["metadata"].update(meta_updates)

        return True
    except Exception as e:
        logger.error(f"[CustomDomain] Error updating metadata in Supabase for tenant '{slug}': {e}")
        return False


def _check_domain_conflict_across_tenants(domain: str, current_slug: str) -> Optional[str]:
    """Checks if any other tenant has already claimed this custom domain."""
    supabase = get_supabase()
    if not supabase:
        return None
    try:
        res = supabase.table("tenants").select("slug, metadata").execute()
        for row in res.data or []:
            other_slug = row.get("slug")
            if other_slug == current_slug:
                continue
            meta = row.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("custom_domain") == domain:
                return other_slug
    except Exception as e:
        logger.debug(f"[CustomDomain] Conflict check note: {e}")
    return None


async def handle_register_custom_domain(
    tenant_slug: str,
    domain: str,
    ssl_method: str = "http",
) -> Dict[str, Any]:
    """Core logic to register custom domain via Cloudflare and update DB."""
    # 1. Format validation
    valid, cleaned_domain, val_err = validate_domain_name(domain)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=val_err or "Format domain tidak valid.",
        )

    # 2. Verify tenant exists
    tenant_row, meta = _get_tenant_record_from_db(tenant_slug)
    if not tenant_row:
        # Fallback check in onboarding service
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
        if not details or not details.get("tenant"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Toko dengan identifier '{tenant_slug}' tidak ditemukan.",
            )

    # 3. Prevent conflict with another tenant
    conflict_slug = _check_domain_conflict_across_tenants(cleaned_domain, tenant_slug)
    if conflict_slug:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Domain '{cleaned_domain}' sudah digunakan oleh toko lain.",
        )

    # 4. Call Cloudflare Custom Hostnames API
    try:
        cf_res = await cloudflare_service.create_custom_hostname(
            hostname=cleaned_domain,
            ssl_method=ssl_method,
        )
    except CloudflareAPIError as cf_err:
        raise HTTPException(status_code=cf_err.status_code, detail=cf_err.message)

    hostname_id = cf_res.get("id")
    cf_status = cf_res.get("status", "pending")
    ssl_status = cf_res.get("ssl_status", "pending_validation")
    cname_target = cf_res.get("cname_target", DEFAULT_CNAME_TARGET)

    # 5. Persist to Supabase metadata
    meta_updates = {
        "custom_domain": cleaned_domain,
        "cloudflare_hostname_id": hostname_id,
        "custom_domain_status": cf_status,
        "custom_domain_ssl_status": ssl_status,
        "custom_domain_cname_target": cname_target,
        "custom_domain_ssl_method": ssl_method,
        "custom_domain_verification": {
            "ownership_verification": cf_res.get("ownership_verification"),
            "ssl_validation_records": cf_res.get("ssl_validation_records"),
        },
        "custom_domain_created_at": datetime.now(timezone.utc).isoformat(),
        "custom_domain_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _update_tenant_metadata(tenant_slug, meta_updates)

    dns_instructions = {
        "type": "CNAME",
        "name": cleaned_domain,
        "target": cname_target,
        "ttl": "Auto / 1 Hour",
        "note": f"Arahkan CNAME '{cleaned_domain}' ke '{cname_target}' pada penyedia DNS domain Anda (Cloudflare, Niagahoster, Domainesia, dsb).",
    }

    return {
        "status": "success",
        "message": f"Custom domain '{cleaned_domain}' berhasil didaftarkan. Silakan konfigurasikan DNS CNAME sesuai petunjuk.",
        "tenant_slug": tenant_slug,
        "custom_domain": cleaned_domain,
        "cloudflare_hostname_id": hostname_id,
        "custom_domain_status": cf_status,
        "ssl_status": ssl_status,
        "is_active": (cf_status == "active") and (ssl_status == "active"),
        "cname_target": cname_target,
        "dns_instructions": dns_instructions,
        "verification_records": cf_res.get("ssl_validation_records") or [],
        "ownership_verification": cf_res.get("ownership_verification"),
    }


async def handle_get_custom_domain_status(tenant_slug: str) -> Dict[str, Any]:
    """Core logic to check custom domain and SSL verification status."""
    tenant_row, meta = _get_tenant_record_from_db(tenant_slug)
    meta = meta or {}

    custom_domain = meta.get("custom_domain")
    hostname_id = meta.get("cloudflare_hostname_id")
    cname_target = meta.get("custom_domain_cname_target", DEFAULT_CNAME_TARGET)

    if not custom_domain or not hostname_id:
        return {
            "status": "not_configured",
            "message": "Belum ada custom domain yang didaftarkan untuk toko ini.",
            "tenant_slug": tenant_slug,
            "custom_domain": None,
            "cloudflare_hostname_id": None,
            "custom_domain_status": None,
            "ssl_status": None,
            "is_active": False,
            "cname_target": cname_target,
        }

    # Query Cloudflare for live status
    try:
        cf_res = await cloudflare_service.get_custom_hostname_status(hostname_id)
        current_status = cf_res.get("status", "pending")
        ssl_status = cf_res.get("ssl_status", "pending_validation")
        is_active = cf_res.get("is_active", False)

        # Update DB if status changed
        if (
            current_status != meta.get("custom_domain_status")
            or ssl_status != meta.get("custom_domain_ssl_status")
        ):
            _update_tenant_metadata(
                tenant_slug,
                {
                    "custom_domain_status": current_status,
                    "custom_domain_ssl_status": ssl_status,
                    "custom_domain_updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        dns_instructions = {
            "type": "CNAME",
            "name": custom_domain,
            "target": cname_target,
            "ttl": "Auto / 1 Hour",
            "note": f"Arahkan CNAME '{custom_domain}' ke '{cname_target}' pada penyedia DNS domain Anda.",
        }

        return {
            "status": "success",
            "message": "Status custom domain berhasil diperbarui.",
            "tenant_slug": tenant_slug,
            "custom_domain": custom_domain,
            "cloudflare_hostname_id": hostname_id,
            "custom_domain_status": current_status,
            "ssl_status": ssl_status,
            "is_active": is_active,
            "cname_target": cname_target,
            "dns_instructions": dns_instructions,
            "verification_records": cf_res.get("ssl_validation_records") or [],
            "ownership_verification": cf_res.get("ownership_verification"),
        }

    except CloudflareAPIError as cf_err:
        raise HTTPException(status_code=cf_err.status_code, detail=cf_err.message)


async def handle_delete_custom_domain(tenant_slug: str) -> Dict[str, Any]:
    """Core logic to delete custom domain mapping from Cloudflare and clear DB."""
    tenant_row, meta = _get_tenant_record_from_db(tenant_slug)
    meta = meta or {}

    hostname_id = meta.get("cloudflare_hostname_id")
    removed_domain = meta.get("custom_domain")

    if hostname_id:
        try:
            await cloudflare_service.delete_custom_hostname(hostname_id)
        except CloudflareAPIError as cf_err:
            logger.warning(f"[CustomDomain] Cloudflare delete note for '{hostname_id}': {cf_err}")

    # Clear custom domain configuration in DB
    meta_cleared = {
        "custom_domain": None,
        "cloudflare_hostname_id": None,
        "custom_domain_status": None,
        "custom_domain_ssl_status": None,
        "custom_domain_cname_target": None,
        "custom_domain_verification": None,
        "custom_domain_deleted_at": datetime.now(timezone.utc).isoformat(),
    }
    _update_tenant_metadata(tenant_slug, meta_cleared)

    return {
        "status": "success",
        "message": f"Custom domain '{removed_domain or 'toko'}' berhasil dihapus.",
        "tenant_slug": tenant_slug,
        "deleted_domain": removed_domain,
    }


# ============================================================================
# FastAPI Route Handlers
# ============================================================================

@custom_domain_router.post("/api/v1/store/custom-domain", summary="Register Custom Domain for Store")
@custom_domain_router.post("/api/v1/tenants/{slug}/custom-domain", summary="Register Custom Domain for Tenant")
async def register_custom_domain_endpoint(
    request: Request,
    slug: Optional[str] = None,
    payload: CustomDomainRegisterRequest = Body(...),
):
    header_slug = request.headers.get("X-Tenant-Slug") or request.headers.get("X-Tenant-Id")
    tenant_slug = _resolve_tenant_slug(
        path_slug=slug,
        body_slug=payload.tenant_slug,
        query_slug=request.query_params.get("tenant_slug") or request.query_params.get("slug"),
        header_slug=header_slug,
    )
    return await handle_register_custom_domain(
        tenant_slug=tenant_slug,
        domain=payload.domain,
        ssl_method=payload.ssl_method or "http",
    )


@custom_domain_router.get("/api/v1/store/custom-domain/status", summary="Check Custom Domain Status")
@custom_domain_router.get("/api/v1/tenants/{slug}/custom-domain/status", summary="Check Custom Domain Status for Tenant")
@custom_domain_router.get("/api/v1/tenants/{slug}/custom-domain", summary="Get Custom Domain for Tenant")
async def get_custom_domain_status_endpoint(
    request: Request,
    slug: Optional[str] = None,
    tenant_slug: Optional[str] = Query(None),
):
    header_slug = request.headers.get("X-Tenant-Slug") or request.headers.get("X-Tenant-Id")
    clean_slug = _resolve_tenant_slug(
        path_slug=slug,
        query_slug=tenant_slug or request.query_params.get("slug"),
        header_slug=header_slug,
    )
    return await handle_get_custom_domain_status(clean_slug)


@custom_domain_router.delete("/api/v1/store/custom-domain", summary="Delete Custom Domain")
@custom_domain_router.delete("/api/v1/tenants/{slug}/custom-domain", summary="Delete Custom Domain for Tenant")
async def delete_custom_domain_endpoint(
    request: Request,
    slug: Optional[str] = None,
    tenant_slug: Optional[str] = Query(None),
):
    header_slug = request.headers.get("X-Tenant-Slug") or request.headers.get("X-Tenant-Id")
    body_slug = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            body_slug = body.get("tenant_slug") or body.get("slug")
    except Exception:
        pass

    clean_slug = _resolve_tenant_slug(
        path_slug=slug,
        body_slug=body_slug,
        query_slug=tenant_slug or request.query_params.get("slug"),
        header_slug=header_slug,
    )
    return await handle_delete_custom_domain(clean_slug)


# ============================================================================
# aiohttp Route Handlers & Registration (Dual-Runner Railway Compliance)
# ============================================================================

async def aiohttp_options_custom_domain(request: web.Request) -> web.Response:
    return web.Response(status=200, headers=CORS_HEADERS)


async def aiohttp_post_custom_domain(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        slug = request.match_info.get("slug")
        header_slug = request.headers.get("X-Tenant-Slug") or request.headers.get("X-Tenant-Id")
        query_slug = request.query.get("tenant_slug") or request.query.get("slug")

        tenant_slug = _resolve_tenant_slug(
            path_slug=slug,
            body_slug=body.get("tenant_slug") or body.get("slug"),
            query_slug=query_slug,
            header_slug=header_slug,
        )

        domain = body.get("domain") or body.get("custom_domain")
        if not domain:
            return web.json_response(
                {"status": "error", "detail": "Field 'domain' wajib diisi."},
                status=400,
                headers=CORS_HEADERS,
            )

        ssl_method = body.get("ssl_method", "http")
        result = await handle_register_custom_domain(tenant_slug, domain, ssl_method)
        return web.json_response(result, status=200, headers=CORS_HEADERS)
    except HTTPException as he:
        return web.json_response({"status": "error", "detail": he.detail}, status=he.status_code, headers=CORS_HEADERS)
    except Exception as e:
        logger.exception("Aiohttp post custom domain error")
        return web.json_response({"status": "error", "detail": str(e)}, status=500, headers=CORS_HEADERS)


async def aiohttp_get_custom_domain_status(request: web.Request) -> web.Response:
    try:
        slug = request.match_info.get("slug")
        header_slug = request.headers.get("X-Tenant-Slug") or request.headers.get("X-Tenant-Id")
        query_slug = request.query.get("tenant_slug") or request.query.get("slug")

        clean_slug = _resolve_tenant_slug(
            path_slug=slug,
            query_slug=query_slug,
            header_slug=header_slug,
        )

        result = await handle_get_custom_domain_status(clean_slug)
        return web.json_response(result, status=200, headers=CORS_HEADERS)
    except HTTPException as he:
        return web.json_response({"status": "error", "detail": he.detail}, status=he.status_code, headers=CORS_HEADERS)
    except Exception as e:
        logger.exception("Aiohttp get custom domain status error")
        return web.json_response({"status": "error", "detail": str(e)}, status=500, headers=CORS_HEADERS)


async def aiohttp_delete_custom_domain(request: web.Request) -> web.Response:
    try:
        slug = request.match_info.get("slug")
        header_slug = request.headers.get("X-Tenant-Slug") or request.headers.get("X-Tenant-Id")
        query_slug = request.query.get("tenant_slug") or request.query.get("slug")
        body_slug = None
        try:
            body = await request.json()
            if isinstance(body, dict):
                body_slug = body.get("tenant_slug") or body.get("slug")
        except Exception:
            pass

        clean_slug = _resolve_tenant_slug(
            path_slug=slug,
            body_slug=body_slug,
            query_slug=query_slug,
            header_slug=header_slug,
        )

        result = await handle_delete_custom_domain(clean_slug)
        return web.json_response(result, status=200, headers=CORS_HEADERS)
    except HTTPException as he:
        return web.json_response({"status": "error", "detail": he.detail}, status=he.status_code, headers=CORS_HEADERS)
    except Exception as e:
        logger.exception("Aiohttp delete custom domain error")
        return web.json_response({"status": "error", "detail": str(e)}, status=500, headers=CORS_HEADERS)


def register_custom_domain_routes(app: web.Application):
    """Maps custom domain routes into aiohttp application with OPTIONS preflight."""
    routes = [
        "/api/v1/store/custom-domain",
        "/api/v1/store/custom-domain/status",
        "/api/v1/tenants/{slug}/custom-domain",
        "/api/v1/tenants/{slug}/custom-domain/status",
    ]

    for route in routes:
        app.router.add_route("OPTIONS", route, aiohttp_options_custom_domain)

    app.router.add_post("/api/v1/store/custom-domain", aiohttp_post_custom_domain)
    app.router.add_post("/api/v1/tenants/{slug}/custom-domain", aiohttp_post_custom_domain)

    app.router.add_get("/api/v1/store/custom-domain/status", aiohttp_get_custom_domain_status)
    app.router.add_get("/api/v1/tenants/{slug}/custom-domain/status", aiohttp_get_custom_domain_status)
    app.router.add_get("/api/v1/tenants/{slug}/custom-domain", aiohttp_get_custom_domain_status)

    app.router.add_delete("/api/v1/store/custom-domain", aiohttp_delete_custom_domain)
    app.router.add_delete("/api/v1/tenants/{slug}/custom-domain", aiohttp_delete_custom_domain)

    logger.info("[SERVER_CORE] Registered Cloudflare Custom Domain routes in aiohttp.")
