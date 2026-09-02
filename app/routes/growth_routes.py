from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from aiohttp import web
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from app.services.growth_service import bind_attribution_session, process_order_paid_growth_event

router = APIRouter(prefix="/api/v1/growth", tags=["Growth & Affiliate Engine"])

class TrackSessionRequest(BaseModel):
    tenant_id: str
    referral_code: Optional[str] = None
    fbclid: Optional[str] = None
    user_agent: Optional[str] = None
    order_id: Optional[str] = None

class SimulatePaidRequest(BaseModel):
    tenant_id: str
    order_id: str
    amount: float
    customer_phone: Optional[str] = "08123456789"
    customer_email: Optional[str] = "buyer@gmail.com"

def get_db():
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    return psycopg2.connect(db_url)

# 1. Endpoint Storefront Session Binding (P2.2)
@router.post("/track")
def track_session_endpoint(req: TrackSessionRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    ua = req.user_agent or request.headers.get("user-agent", "")
    result = bind_attribution_session(req.tenant_id, req.referral_code, req.fbclid, ua, client_ip, req.order_id)
    return result

# 2. Endpoint Portal Affiliate Performance MVP (P2.5)
@router.get("/portal/{tenant_id}/{referral_code}")
def get_affiliate_portal(tenant_id: str, referral_code: str):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT id, name, phone_number, referral_code, commission_rate, status 
            FROM affiliates 
            WHERE tenant_id = %s AND referral_code = %s;
        """, (tenant_id, referral_code))
        affiliate = cur.fetchone()

        if not affiliate:
            raise HTTPException(status_code=404, detail="Affiliate tidak ditemukan!")

        aff_id = affiliate["id"]

        # Hitung Total Sesi Klik
        cur.execute("SELECT COUNT(*) as total_clicks FROM attribution_sessions WHERE affiliate_id = %s;", (aff_id,))
        total_clicks = cur.fetchone()["total_clicks"]

        # Hitung Saldo Komisi
        cur.execute("""
            SELECT 
                COUNT(*) as total_orders,
                COALESCE(SUM(CASE WHEN status = 'APPROVED' THEN amount ELSE 0 END), 0) as approved_balance,
                COALESCE(SUM(CASE WHEN status = 'PAID' THEN amount ELSE 0 END), 0) as paid_balance
            FROM affiliate_commissions
            WHERE affiliate_id = %s;
        """, (aff_id,))
        stats = cur.fetchone()

        cur.close()
        return {
            "success": True,
            "data": {
                "affiliate": dict(affiliate),
                "referral_url": f"https://shop.boontrack.com/{tenant_id}?ref={referral_code}",
                "metrics": {
                    "total_clicks": total_clicks,
                    "total_orders": stats["total_orders"],
                    "ready_to_withdraw": float(stats["approved_balance"]),
                    "already_paid": float(stats["paid_balance"])
                }
            }
        }
    finally:
        if conn:
            conn.close()

# 3. Endpoint Simulasi Order PAID (DoD P2 Verification)
@router.post("/simulate/order-paid")
async def simulate_order_paid(req: SimulatePaidRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    await process_order_paid_growth_event(
        tenant_id=req.tenant_id,
        order_id=req.order_id,
        order_amount=req.amount,
        customer_phone=req.customer_phone,
        customer_email=req.customer_email,
        client_ip=client_ip
    )
    return {
        "success": True,
        "message": f"Event order PAID #{req.order_id} berhasil diproses oleh Growth Worker."
    }

# Aiohttp Registrar untuk kompatibilitas runner
def register_growth_routes(app: web.Application):
    pass