import os
import hmac
import hashlib
from typing import Optional, Dict, Any
from aiohttp import web
from fastapi import APIRouter, Depends, HTTPException, Header, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v1", tags=["Entitlement Policy Engine"])

# =====================================================================
# 1. SQL Schema Migration Definition (PostgreSQL / Supabase)
# =====================================================================
ENTITLEMENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plans (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    max_seats INT NOT NULL DEFAULT 1,
    ai_closing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_slug VARCHAR(100) UNIQUE NOT NULL,
    plan_id VARCHAR(50) REFERENCES plans(id),
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING_PAYMENT',
    current_period_start TIMESTAMP WITH TIME ZONE,
    current_period_end TIMESTAMP WITH TIME ZONE,
    xendit_invoice_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_entitlements (
    tenant_slug VARCHAR(100) PRIMARY KEY,
    plan_id VARCHAR(50) REFERENCES plans(id),
    max_seats INT NOT NULL DEFAULT 1,
    ai_closing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tenant_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_slug VARCHAR(100) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'AGENT', 
    status VARCHAR(50) NOT NULL DEFAULT 'INVITED',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_tenant_member UNIQUE (tenant_slug, user_email)
);

CREATE TABLE IF NOT EXISTS webhook_idempotency (
    event_id VARCHAR(255) PRIMARY KEY,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

# =====================================================================
# 2. Pydantic Request Models
# =====================================================================
class InviteStaffRequest(BaseModel):
    email: EmailStr
    role: Optional[str] = "AGENT"

class AICloseRequest(BaseModel):
    customer_phone: str
    message: str

# =====================================================================
# 3. Centralized Entitlement Service Layer
# =====================================================================
def get_tenant_entitlement(db: Session, tenant_slug: str) -> Dict[str, Any]:
    query = text("""
        SELECT tenant_slug, plan_id, max_seats, ai_closing_enabled 
        FROM tenant_entitlements 
        WHERE tenant_slug = :slug
    """)
    result = db.execute(query, {"slug": tenant_slug}).mappings().first()
    
    if not result:
        return {
            "tenant_slug": tenant_slug,
            "plan_id": "growth",
            "max_seats": 1,
            "ai_closing_enabled": False
        }
    return dict(result)

def can_use(db: Session, tenant_slug: str, feature_key: str) -> bool:
    entitlement = get_tenant_entitlement(db, tenant_slug)
    if feature_key == "AI_CLOSING":
        return bool(entitlement.get("ai_closing_enabled", False))
    return False

def get_limit(db: Session, tenant_slug: str, limit_key: str) -> int:
    entitlement = get_tenant_entitlement(db, tenant_slug)
    if limit_key == "SEATS":
        return int(entitlement.get("max_seats", 1))
    return 0

def count_occupied_seats(db: Session, tenant_slug: str) -> int:
    query = text("""
        SELECT COUNT(*) FROM tenant_members 
        WHERE tenant_slug = :slug 
          AND status IN ('ACTIVE', 'INVITED')
    """)
    return db.execute(query, {"slug": tenant_slug}).scalar() or 0

# =====================================================================
# 4. FastAPI Endpoints
# =====================================================================
@router.get("/tenant/entitlements")
@router.get("/tenants/{tenant_slug}/entitlements")
def get_entitlements_endpoint(tenant_slug: str = "default_tenant_growth"):
    return {
        "success": True,
        "tenant_id": tenant_slug,
        "plan_name": "Growth (Solo Starter)",
        "max_seats": 1,
        "occupied_seats": 1,
        "ai_closing_enabled": False,
        "custom_domain_enabled": True,
        "can_add_staff": False
    }

@router.post("/tenants/{tenant_slug}/members/invite", status_code=status.HTTP_201_CREATED)
def invite_staff_member(
    tenant_slug: str,
    payload: InviteStaffRequest,
    db: Session = Depends()
):
    try:
        db.begin_nested() if db.in_transaction() else db.begin()
        max_allowed_seats = get_limit(db, tenant_slug, "SEATS")

        lock_query = text("""
            SELECT id, status FROM tenant_members 
            WHERE tenant_slug = :slug 
            FOR UPDATE
        """)
        db.execute(lock_query, {"slug": tenant_slug})

        current_occupied = count_occupied_seats(db, tenant_slug)

        if current_occupied >= max_allowed_seats:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "success": False,
                    "code": "SEAT_LIMIT_REACHED",
                    "message": f"Paket Growth hanya mendukung {max_allowed_seats} user. Upgrade ke Pro Scale untuk menambahkan anggota tim hingga 10 user."
                }
            )

        existing_check = text("""
            SELECT id, status FROM tenant_members 
            WHERE tenant_slug = :slug AND user_email = :email
        """)
        existing = db.execute(existing_check, {"slug": tenant_slug, "email": payload.email}).mappings().first()

        if existing:
            if existing["status"] in ["ACTIVE", "INVITED"]:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Staff dengan email ini sudah terdaftar atau memiliki undangan aktif."
                )
            else:
                update_query = text("""
                    UPDATE tenant_members 
                    SET status = 'INVITED', role = :role, created_at = NOW()
                    WHERE tenant_slug = :slug AND user_email = :email
                    RETURNING id, tenant_slug, user_email, role, status
                """)
                res = db.execute(update_query, {"slug": tenant_slug, "email": payload.email, "role": payload.role}).mappings().first()
                db.commit()
                return {"success": True, "data": dict(res)}

        insert_query = text("""
            INSERT INTO tenant_members (tenant_slug, user_email, role, status)
            VALUES (:slug, :email, :role, 'INVITED')
            RETURNING id, tenant_slug, user_email, role, status
        """)
        new_member = db.execute(insert_query, {
            "slug": tenant_slug, 
            "email": payload.email, 
            "role": payload.role
        }).mappings().first()

        db.commit()
        return {"success": True, "data": dict(new_member)}

    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error processing staff invite: {str(e)}"
        )

# =====================================================================
# 5. aiohttp Handlers & Registration (Runner Aktif Server Railway)
# =====================================================================
async def aiohttp_get_entitlements(request: web.Request):
    return web.json_response({
        "success": True,
        "tenant_id": "default_tenant_growth",
        "plan_name": "Growth (Solo Starter)",
        "max_seats": 1,
        "occupied_seats": 1,
        "ai_closing_enabled": False,
        "custom_domain_enabled": True,
        "can_add_staff": False
    })

def register_entitlement_routes(app: web.Application):
    app.router.add_get("/tenant/entitlements", aiohttp_get_entitlements)
    app.router.add_get("/api/v1/tenant/entitlements", aiohttp_get_entitlements)