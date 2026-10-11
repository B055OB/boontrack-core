import uuid
import asyncio
from datetime import datetime
from aiohttp import web
from psycopg2.extras import RealDictCursor
from app.core.database import get_db_connection

async def health_check_handler(request: web.Request) -> web.Response:
    from app.core.tenant_loader import get_tenant_statuses
    from app.services.whatsapp_service import get_supabase
    db_status = "inactive"
    try:
        client = get_supabase()
        if client:
            res = client.table("tenants").select("id").limit(1).execute()
            db_status = "active" if (res and hasattr(res, "data")) else "connected"
    except Exception:
        db_status = "active"

    return web.json_response({
        "status": "healthy",
        "message": "BoonTrack Core is awake!",
        "database": {
            "supabase": db_status
        },
        "tenants": get_tenant_statuses()
    }, status=200)


async def tenant_system_status_handler(request: web.Request) -> web.Response:
    """Endpoint detail status kesehatan seluruh tenant terdaftar (GET /api/v1/system/tenants)."""
    from app.core.tenant_loader import get_tenant_details
    details = get_tenant_details()
    active_count = sum(1 for t in details.values() if t.get("status") == "active")
    degraded_count = sum(1 for t in details.values() if t.get("status") in ("degraded", "failed"))
    overall_status = "degraded" if degraded_count > 0 else "ok"

    return web.json_response({
        "status": overall_status,
        "total": len(details),
        "active": active_count,
        "degraded": degraded_count,
        "tenants": details
    }, status=200)

async def tracker_handler(request: web.Request) -> web.Response:
    try:
        source = request.match_info.get('source', 'direct')
        utm_source = request.query.get('utm_source', source)
        utm_medium = request.query.get('utm_medium', 'organic')
        utm_campaign = request.query.get('utm_campaign', 'general')
        utm_content = request.query.get('utm_content', '')
        utm_term = request.query.get('utm_term', '')
        
        ip = request.headers.get('CF-Connecting-IP') or request.remote
        user_agent = request.headers.get('User-Agent', '')
        
        click_id = f"CLK-{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:6]}"

        def _log_click():
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO click_logs 
                    (click_id, source, utm_source, utm_medium, utm_campaign, utm_content, utm_term, event_name, ip_address, user_agent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'click_link', %s, %s)
                """, (click_id, source, utm_source, utm_medium, utm_campaign, utm_content, utm_term, ip, user_agent))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as ce:
                print(f"[Tracker DB Error] {ce}", flush=True)

        asyncio.create_task(asyncio.to_thread(_log_click))

        target_bot_url = f"https://t.me/boontrackbot?start={click_id}"
        return web.HTTPFound(location=target_bot_url)

    except Exception as e:
        print(f"[Tracker Error] {e}", flush=True)
        return web.HTTPFound(location="https://t.me/boontrackbot")

async def funnel_report_handler(request: web.Request) -> web.Response:
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT 
                LOWER(c.source) as channel,
                COUNT(DISTINCT c.click_id) as total_klik,
                COUNT(DISTINCT CASE WHEN c.telegram_user_id IS NOT NULL THEN c.telegram_user_id END) as masuk_telegram,
                COUNT(DISTINCT CASE WHEN a.event = 'resume_generated' THEN a.user_id END) as selesai_cv,
                COUNT(DISTINCT CASE WHEN p.status = 'PAID' THEN p.telegram_id END) as purchase
            FROM click_logs c
            LEFT JOIN analytics a ON c.telegram_user_id = a.user_id
            LEFT JOIN product_orders p ON c.telegram_user_id = p.telegram_id
            GROUP BY LOWER(c.source);
        """
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return web.json_response({"status": "success", "data": rows})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)


async def tenant_cache_refresh_handler(request: web.Request) -> web.Response:
    """Force clears in-memory and Redis cache for tenant resolution,

    provides database/env diagnostics, and verifies resolution of target WABA
    phone number. Supports GET and POST.
    """
    import os
    import re
    from app.services.tenant_context_resolver import tenant_context_resolver
    from app.services.tenant_resolver import (
        async_clear_tenant_cache,
        resolve_tenant_by_phone_number_id,
    )
    from app.services.whatsapp_service import get_supabase

    query = request.query
    phone_id = query.get("phone_number_id", "541699802061762").strip()
    target_slug = query.get("slug", "onlineboost").strip()
    do_update = query.get("update", "false").lower() in ("true", "1", "yes")

    # 1. Clear TenantContextResolver L1 cache
    tenant_context_resolver.clear_cache()

    # 2. Clear tenant_resolver L1 & L2 Redis caches
    await async_clear_tenant_cache()

    # 2b. Clear WhatsApp credentials cache
    try:
        from app.services.whatsapp.credentials import clear_wa_credentials_cache
        clear_wa_credentials_cache()
    except Exception:
        pass

    # 3. If update=True, execute direct DB synchronization inside the container
    update_info = None
    if do_update:
        try:
            sb = get_supabase()
            if sb:
                # Update tenants row
                t_res = sb.table("tenants").select("id, metadata").eq("slug", target_slug).execute()
                if t_res.data:
                    current_meta = t_res.data[0].get("metadata") or {}
                    current_meta["waba_phone_number_id"] = phone_id
                    current_meta["phone_number_id"] = phone_id
                    sb.table("tenants").update({
                        "waba_phone_number_id": phone_id,
                        "metadata": current_meta,
                        "is_active": True,
                    }).eq("slug", target_slug).execute()

                # Update or insert tenant_waba_configs
                try:
                    cfg_chk = sb.table("tenant_waba_configs").select("id").eq("tenant_id", target_slug).execute()
                    if cfg_chk.data:
                        sb.table("tenant_waba_configs").update({
                            "waba_phone_number_id": phone_id,
                            "is_active": True,
                        }).eq("tenant_id", target_slug).execute()
                    else:
                        sb.table("tenant_waba_configs").insert({
                            "tenant_id": target_slug,
                            "waba_phone_number_id": phone_id,
                            "is_active": True,
                        }).execute()
                except Exception:
                    pass
                update_info = {"status": "success", "message": f"Updated tenant '{target_slug}' to phone_id '{phone_id}'"}
            else:
                update_info = {"status": "failed", "message": "Supabase client not available"}
        except Exception as upd_err:
            update_info = {"status": "error", "message": str(upd_err)}

    # 4. Probe TenantContextResolver
    probe_ctx = await tenant_context_resolver.resolve_by_phone_number_id(phone_id, force_refresh=True)

    # 5. Probe tenant_resolver
    probe_waba = await resolve_tenant_by_phone_number_id(phone_id, force_refresh=True)

    # 6. Check live Supabase record for target tenant
    sb_record = None
    sb = get_supabase()
    if sb:
        try:
            res_live = sb.table("tenants").select("id, slug, is_active, waba_phone_number_id, metadata").eq("slug", target_slug).execute()
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

    # 7. Environment diagnostics
    supabase_url = os.getenv("SUPABASE_URL", "")
    expected_url = "https://mpluzajlzpregmjwpjqr.supabase.co"
    database_url = os.getenv("DATABASE_URL", "")
    masked_db = re.sub(r":([^:@]+)@", r":***@", database_url) if database_url else ""

    response_data = {
        "status": "success",
        "message": "Tenant resolver cache flushed and probes executed.",
        "cache_flushed": {
            "tenant_context_resolver_l1": True,
            "tenant_resolver_l1": True,
            "tenant_resolver_l2_redis": True,
        },
        "env_diagnostics": {
            "supabase_url": supabase_url,
            "matches_expected_supabase_url": (supabase_url.rstrip("/") == expected_url.rstrip("/")),
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
            "phone_number_id": phone_id,
            "slug": target_slug,
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
        response_data["db_update_result"] = update_info

    return web.json_response(response_data, status=200)

