from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from aiohttp import web
import json
import os
import psycopg2
from psycopg2.extras import RealDictCursor, Json

router = APIRouter(prefix="/api/v1/internal/tenants", tags=["Internal Provisioning"])

class ProvisionRequest(BaseModel):
    tenant_name: str
    slug: str
    vertical: str = Field(default="shop", example="shop")
    plan: str = Field(default="growth", example="growth")
    config: Optional[Dict[str, Any]] = None

def get_db_connection():
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    return psycopg2.connect(db_url)

def execute_provision_logic(tenant_name: str, slug: str, vertical: str = "shop", plan: str = "growth", config: Optional[Dict[str, Any]] = None):
    slug_sanitized = slug.strip().lower().replace(" ", "-")
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Cek duplikasi slug
        cur.execute("SELECT id, slug FROM tenants WHERE slug = %s", (slug_sanitized,))
        existing = cur.fetchone()
        if existing:
            raise ValueError(f"Tenant dengan slug '{slug_sanitized}' sudah terdaftar!")

        # 2. Template seeding vertikal otomatis
        initial_config = {
            "vertical": vertical,
            "plan": plan,
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

        # 3. Insert tenant ke database dengan status HEALTHY
        cur.execute("""
            INSERT INTO tenants (
                name, slug, country_code, currency, timezone, 
                region_config, status, created_at, updated_at
            ) VALUES (
                %s, %s, 'ID', 'IDR', 'Asia/Jakarta', 
                %s, 'HEALTHY', NOW(), NOW()
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

# Handler FastAPI
@router.post("/provision")
def provision_fastapi(req: ProvisionRequest):
    try:
        tenant = execute_provision_logic(req.tenant_name, req.slug, req.vertical, req.plan, req.config)
        return {
            "success": True,
            "message": f"Tenant '{req.tenant_name}' berhasil diprovisi secara otomatis.",
            "data": tenant
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Provisioning Error: {str(e)}")

# Handler aiohttp
async def aiohttp_provision_handler(request: web.Request):
    try:
        body = await request.json()
        tenant_name = body.get("tenant_name")
        slug = body.get("slug")
        vertical = body.get("vertical", "shop")
        plan = body.get("plan", "growth")
        config = body.get("config")

        if not tenant_name or not slug:
            return web.json_response({"success": False, "detail": "tenant_name dan slug wajib diisi!"}, status=400)

        tenant = execute_provision_logic(tenant_name, slug, vertical, plan, config)
        return web.json_response({
            "success": True,
            "message": f"Tenant '{tenant_name}' berhasil diprovisi secara otomatis.",
            "data": dict(tenant)
        })
    except ValueError as e:
        return web.json_response({"success": False, "detail": str(e)}, status=400)
    except Exception as e:
        return web.json_response({"success": False, "detail": f"Database Provisioning Error: {str(e)}"}, status=500)

def register_provisioning_routes(app: web.Application):
    app.router.add_post('/api/v1/internal/tenants/provision', aiohttp_provision_handler)