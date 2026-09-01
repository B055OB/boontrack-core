from fastapi import APIRouter, Depends, HTTPException, Header, status, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import hmac
import hashlib
import os

router = APIRouter(prefix="/api/v1", tags=["Entitlement Policy Engine"])

# =====================================================================
# 1. SQL Schema Migration Definition (PostgreSQL / Supabase)
# =====================================================================
ENTITLEMENT_SCHEMA_SQL = """
-- Plans Master Table
CREATE TABLE IF NOT EXISTS plans (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    max_seats INT NOT NULL DEFAULT 1,
    ai_closing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Subscriptions Table (Synced via Xendit Webhooks)
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

-- Tenant Entitlements Cache / Configuration
CREATE TABLE IF NOT EXISTS tenant_entitlements (
    tenant_slug VARCHAR(100) PRIMARY KEY,
    plan_id VARCHAR(50) REFERENCES plans(id),
    max_seats INT NOT NULL DEFAULT 1,
    ai_closing_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tenant Members (Staff & Seats Engine)
CREATE TABLE IF NOT EXISTS tenant_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_slug VARCHAR(100) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'AGENT', 
    status VARCHAR(50) NOT NULL DEFAULT 'INVITED', -- ACTIVE, INVITED, SUSPENDED, SUSPENDED_BY_PLAN, REMOVED
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_tenant_member UNIQUE (tenant_slug, user_email)
);

-- Webhook Idempotency Table
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
    """Fetch active entitlements and features for a tenant from cache/db."""
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
    """Centralized feature gating checker abstraction."""
    entitlement = get_tenant_entitlement(db, tenant_slug)
    if feature_key == "AI_CLOSING":
        return bool(entitlement.get("ai_closing_enabled", False))
    return False

def get_limit(db: Session, tenant_slug: str, limit_key: str) -> int:
    """Centralized limit checker abstraction."""
    entitlement = get_tenant_entitlement(db, tenant_slug)
    if limit_key == "SEATS":
        return int(entitlement.get("max_seats", 1))
    return 0

def count_occupied_seats(db: Session, tenant_slug: str) -> int:
    """Calculate occupied seats (ACTIVE + INVITED members)."""
    query = text("""
        SELECT COUNT(*) FROM tenant_members 
        WHERE tenant_slug = :slug 
          AND status IN ('ACTIVE', 'INVITED')
    """)
    return db.execute(query, {"slug": tenant_slug}).scalar() or 0

# =====================================================================
# 4. Race-Condition Safe Seat Enforcement Endpoint
# =====================================================================
@router.post("/tenants/{tenant_slug}/members/invite", status_code=status.HTTP_201_CREATED)
def invite_staff_member(
    tenant_slug: str,
    payload: InviteStaffRequest,
    db: Session = Depends()
):
    """
    Race-Condition Safe Staff Invite with Row Locking & Seat Enforcement.
    Prevents double-click bypass of max_seats limit (Growth: 1, Pro Scale: 10).
    """
    try:
        db.begin_nested() if db.in_transaction() else db.begin()

        # 1. Fetch Entitlements & Limits
        max_allowed_seats = get_limit(db, tenant_slug, "SEATS")

        # 2. Lock member rows for this tenant to block concurrent requests
        lock_query = text("""
            SELECT id, status FROM tenant_members 
            WHERE tenant_slug = :slug 
            FOR UPDATE
        """)
        db.execute(lock_query, {"slug": tenant_slug})

        # 3. Calculate currently occupied seats
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

        # 4. Check existing member status
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

        # 5. Insert new member invitation
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
# 5. Backend Feature Gating Dependency (AI Closing)
# =====================================================================
def verify_ai_closing_entitlement(tenant_slug: str, db: Session = Depends()):
    """Dependency guard for AI Closing endpoints rejecting Growth tier with 403."""
    if not can_use(db, tenant_slug, "AI_CLOSING"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "success": False,
                "code": "FEATURE_NOT_ENTITLED",
                "message": "Fitur AI Closing Assistant tidak tersedia pada Plan Growth Anda. Silakan upgrade ke Pro Scale."
            }
        )
    return True

@router.post("/tenants/{tenant_slug}/ai/closing")
def trigger_ai_closing(
    tenant_slug: str,
    payload: AICloseRequest,
    authorized: bool = Depends(verify_ai_closing_entitlement),
    db: Session = Depends()
):
    """Protected AI Closing endpoint with hard backend feature gating."""
    return {
        "success": True,
        "message": "AI Closing executed successfully.",
        "tenant_slug": tenant_slug
    }

# =====================================================================
# 6. Xendit Webhook Handler with Idempotency & Graceful Downgrade
# =====================================================================
@router.post("/webhooks/xendit/payments")
async def xendit_payment_webhook(
    request: Request,
    x_callback_token: Optional[str] = Header(None),
    db: Session = Depends()
):
    """
    Verified Xendit Webhook Handler:
    - Verifies event signature / callback token.
    - Idempotency check to prevent duplicate processing.
    - Synchronizes plan, entitlements, and handles graceful downgrade/expiry.
    """
    body_bytes = await request.body()
    
    # 1. Validate Xendit Signature / Token (Configured in env)
    expected_token = os.getenv("XENDIT_WEBHOOK_TOKEN", "verify-token")
    if x_callback_token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid Xendit Callback Signature")

    payload = await request.json()
    event_id = payload.get("id") or payload.get("event_id")
    
    # 2. Idempotency Check
    if event_id:
        idempotency_check = text("SELECT event_id FROM webhook_idempotency WHERE event_id = :eid")
        existing_event = db.execute(idempotency_check, {"eid": event_id}).fetchone()
        if existing_event:
            return {"status": "ignored", "reason": "event_already_processed"}
        
        db.execute(text("INSERT INTO webhook_idempotency (event_id) VALUES (:eid)"), {"eid": event_id})

    # 3. Parse Payment Status & Tenant Mapping
    status_val = payload.get("status") # e.g., PAID, EXPIRED, COMPLETED
    tenant_slug = payload.get("metadata", {}).get("tenant_slug") or payload.get("external_id", "").split("_")[-1]
    raw_plan_id = payload.get("metadata", {}).get("plan_id", "growth")

    if not tenant_slug:
        raise HTTPException(status_code=400, detail="Tenant slug not found in webhook payload metadata")

    # Determine target plan configuration
    if status_val in ["PAID", "COMPLETED"]:
        plan_id = raw_plan_id if raw_plan_id in ["growth", "pro_scale"] else "growth"
    else:
        # Graceful Downgrade / Expiry fallback to Growth tier
        plan_id = "growth"

    # Fetch plan specifications from database
    plan_query = text("SELECT max_seats, ai_closing_enabled FROM plans WHERE id = :pid")
    plan = db.execute(plan_query, {"pid": plan_id}).mappings().first()
    
    if not plan:
        plan = {"max_seats": 1, "ai_closing_enabled": False} # Safe fallback

    max_seats = plan["max_seats"]
    ai_enabled = plan["ai_closing_enabled"]

    # 4. Update Subscriptions Table
    sub_upsert = text("""
        INSERT INTO subscriptions (tenant_slug, plan_id, status, xendit_invoice_id, updated_at)
        VALUES (:slug, :pid, :status, :inv, NOW())
        ON CONFLICT (tenant_slug) 
        DO UPDATE SET plan_id = :pid, status = :status, xendit_invoice_id = :inv, updated_at = NOW()
    """)
    db.execute(sub_upsert, {
        "slug": tenant_slug,
        "pid": plan_id,
        "status": status_val or "ACTIVE",
        "inv": payload.get("id")
    })

    # 5. Update Tenant Entitlements Cache
    ent_upsert = text("""
        INSERT INTO tenant_entitlements (tenant_slug, plan_id, max_seats, ai_closing_enabled, updated_at)
        VALUES (:slug, :pid, :max_seats, :ai_enabled, NOW())
        ON CONFLICT (tenant_slug) 
        DO UPDATE SET plan_id = :pid, max_seats = :max_seats, ai_closing_enabled = :ai_enabled, updated_at = NOW()
    """)
    db.execute(ent_upsert, {
        "slug": tenant_slug,
        "pid": plan_id,
        "max_seats": max_seats,
        "ai_enabled": ai_enabled
    })

    # 6. Execute Graceful Downgrade Seat Suspension if capacity reduced
    members_query = text("""
        SELECT id FROM tenant_members 
        WHERE tenant_slug = :slug AND status IN ('ACTIVE', 'INVITED')
        ORDER BY created_at ASC
    """)
    active_members = list(db.execute(members_query, {"slug": tenant_slug}))

    if len(active_members) > max_seats:
        excess_members = active_members[max_seats:]
        excess_ids = [m["id"] for m in excess_members]
        
        suspend_query = text("""
            UPDATE tenant_members 
            SET status = 'SUSPENDED_BY_PLAN' 
            WHERE id = ANY(:ids)
        """)
        db.execute(suspend_query, {"ids": excess_ids})

    db.commit()
    return {"success": True, "tenant_slug": tenant_slug, "assigned_plan": plan_id, "max_seats": max_seats}