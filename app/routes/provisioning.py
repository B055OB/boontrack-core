from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from aiohttp import web
import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor, Json

router = APIRouter(prefix="/api/v1/internal/tenants", tags=["Internal Provisioning & Cockpit"])

class ProvisionRequest(BaseModel):
    tenant_name: str
    slug: str
    vertical: str = Field(default="shop", example="shop")
    plan: str = Field(default="growth", example="growth")
    admin_phone: Optional[str] = None
    config: Optional[Dict[str, Any]] = None

class IncidentResolveRequest(BaseModel):
    incident_id: str

def get_db_connection():
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    return psycopg2.connect(db_url)

def execute_provision_logic(tenant_name: str, slug: str, vertical: str = "shop", plan: str = "growth", admin_phone: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
    slug_sanitized = slug.strip().lower().replace(" ", "-")
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT id, slug FROM tenants WHERE slug = %s", (slug_sanitized,))
        if cur.fetchone():
            raise ValueError(f"Tenant dengan slug '{slug_sanitized}' sudah terdaftar!")

        initial_config = {
            "vertical": vertical,
            "plan": plan,
            "admin_phone": admin_phone or "",
            "onboarding_completed": True,
            "features": {
                "whatsapp_gateway": True,
                "qris_checkout": True,
                "multi_agent_cs": (plan == "pro"),
                "broadcast": (plan == "pro")
            }
        }
        if config:
            initial_config.update(config)

        cur.execute("""
            INSERT INTO tenants (
                name, slug, country_code, currency, timezone, 
                region_config, status
            ) VALUES (
                %s, %s, 'ID', 'IDR', 'Asia/Jakarta', 
                %s, 'HEALTHY'
            ) RETURNING id, name, slug, status, country_code, currency, region_config;
        """, (tenant_name, slug_sanitized, Json(initial_config)))
        
        new_tenant = cur.fetchone()
        conn.commit()
        cur.close()
        return new_tenant
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def fetch_all_tenants():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT 
            id, name, slug, status, country_code, currency, 
            region_config->>'vertical' as vertical,
            region_config->>'plan' as plan,
            region_config->>'admin_phone' as admin_phone,
            region_config
        FROM tenants 
        ORDER BY name ASC;
    """)
    tenants = cur.fetchall()
    cur.close()
    conn.close()
    return tenants

def fetch_incidents(limit: int = 50):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, tenant_id, service, severity, status, error_code, error_message, metadata, first_seen_at 
        FROM tenant_incidents 
        ORDER BY first_seen_at DESC 
        LIMIT %s;
    """, (limit,))
    incidents = cur.fetchall()
    cur.close()
    conn.close()
    return incidents

def resolve_incident_db(incident_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE tenant_incidents 
        SET status = 'RESOLVED', resolved_at = NOW() 
        WHERE id = %s;
    """, (incident_id,))
    conn.commit()
    cur.close()
    conn.close()
    return True

# --- FASTAPI HANDLERS ---

@router.post("/provision")
def provision_fastapi(req: ProvisionRequest):
    try:
        tenant = execute_provision_logic(req.tenant_name, req.slug, req.vertical, req.plan, req.admin_phone, req.config)
        return {"success": True, "message": "Tenant berhasil diprovisi.", "data": tenant}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list")
def list_tenants_fastapi():
    try:
        return {"success": True, "data": fetch_all_tenants()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/incidents")
def list_incidents_fastapi():
    try:
        return {"success": True, "data": fetch_incidents()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/incidents/resolve")
def resolve_incident_fastapi(req: IncidentResolveRequest):
    try:
        resolve_incident_db(req.incident_id)
        return {"success": True, "message": "Insiden ditandai resolved."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- AIOHTTP HANDLERS ---

async def aiohttp_provision_handler(request: web.Request):
    try:
        body = await request.json()
        tenant_name = body.get("tenant_name")
        slug = body.get("slug")
        vertical = body.get("vertical", "shop")
        plan = body.get("plan", "growth")
        admin_phone = body.get("admin_phone")
        config = body.get("config")

        if not tenant_name or not slug:
            return web.json_response({"success": False, "detail": "tenant_name dan slug wajib diisi!"}, status=400)

        tenant = execute_provision_logic(tenant_name, slug, vertical, plan, admin_phone, config)
        return web.json_response({"success": True, "data": dict(tenant)})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)

async def aiohttp_list_tenants_handler(request: web.Request):
    try:
        tenants = fetch_all_tenants()
        return web.json_response({"success": True, "data": [dict(t) for t in tenants]})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)

async def aiohttp_list_incidents_handler(request: web.Request):
    try:
        incidents = fetch_incidents()
        for inc in incidents:
            inc['id'] = str(inc['id'])
            if inc.get('first_seen_at'):
                inc['first_seen_at'] = inc['first_seen_at'].isoformat()
        return web.json_response({"success": True, "data": [dict(i) for i in incidents]})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)

async def aiohttp_resolve_incident_handler(request: web.Request):
    try:
        body = await request.json()
        inc_id = body.get("incident_id")
        if not inc_id:
            return web.json_response({"success": False, "detail": "incident_id required"}, status=400)
        resolve_incident_db(inc_id)
        return web.json_response({"success": True, "message": "Insiden berhasil diselesaikan."})
    except Exception as e:
        return web.json_response({"success": False, "detail": str(e)}, status=500)

def register_provisioning_routes(app: web.Application):
    app.router.add_post('/api/v1/internal/tenants/provision', aiohttp_provision_handler)
    app.router.add_get('/api/v1/internal/tenants/list', aiohttp_list_tenants_handler)
    app.router.add_get('/api/v1/internal/tenants/incidents', aiohttp_list_incidents_handler)
    app.router.add_post('/api/v1/internal/tenants/incidents/resolve', aiohttp_resolve_incident_handler)