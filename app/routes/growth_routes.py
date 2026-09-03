from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from aiohttp import web
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import os
from app.services.growth_service import bind_attribution_session, process_order_paid_growth_event

router = APIRouter(prefix="/api/v1/growth", tags=["Growth & Affiliate Engine"])

# Model Payload Lengkap Sesuai P3-A.1
class TrackSessionRequest(BaseModel):
    tenant_id: str
    session_id: Optional[str] = None
    referral_code: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    fbclid: Optional[str] = None
    ttclid: Optional[str] = None
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

def fetch_portal_data(tenant_id: str, referral_code: str):
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id, name, phone_number, referral_code, commission_rate, status 
            FROM affiliates 
            WHERE tenant_id = %s AND referral_code = %s;
        """, (tenant_id, referral_code))
        affiliate = cur.fetchone()

        if not affiliate:
            return None

        aff_id = affiliate["id"]

        # Hitung klik dari tabel attributions baru (dengan fallback ke attribution_sessions)
        try:
            cur.execute("SELECT COUNT(*) as total_clicks FROM attributions WHERE affiliate_id = %s;", (aff_id,))
            click_row = cur.fetchone()
            total_clicks = click_row["total_clicks"] if click_row else 0
        except Exception:
            conn.rollback()
            cur.execute("SELECT COUNT(*) as total_clicks FROM attribution_sessions WHERE affiliate_id = %s;", (aff_id,))
            total_clicks = cur.fetchone()["total_clicks"]

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

        aff_dict = dict(affiliate)
        aff_dict["id"] = str(aff_dict["id"])
        aff_dict["commission_rate"] = float(aff_dict["commission_rate"])

        return {
            "affiliate": aff_dict,
            "referral_url": f"https://shop.boontrack.com/{tenant_id}?ref={referral_code}",
            "metrics": {
                "total_clicks": int(total_clicks),
                "total_orders": int(stats["total_orders"]),
                "ready_to_withdraw": float(stats["approved_balance"]),
                "already_paid": float(stats["paid_balance"])
            }
        }
    finally:
        conn.close()

# --- FASTAPI HANDLERS ---
@router.post("/track")
def track_session_fastapi(req: TrackSessionRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    ua = req.user_agent or request.headers.get("user-agent", "")
    return bind_attribution_session(
        tenant_id=req.tenant_id,
        referral_code=req.referral_code,
        fbclid=req.fbclid,
        user_agent=ua,
        client_ip=client_ip,
        order_id=req.order_id,
        session_id=req.session_id,
        utm_source=req.utm_source,
        utm_medium=req.utm_medium,
        utm_campaign=req.utm_campaign,
        utm_content=req.utm_content,
        utm_term=req.utm_term,
        ttclid=req.ttclid
    )

@router.get("/portal/{tenant_id}/{referral_code}")
def get_affiliate_portal_fastapi(tenant_id: str, referral_code: str):
    data = fetch_portal_data(tenant_id, referral_code)
    if not data:
        raise HTTPException(status_code=404, detail="Affiliate tidak ditemukan!")
    return {"success": True, "data": data}

@router.post("/simulate/order-paid")
async def simulate_order_paid_fastapi(req: SimulatePaidRequest, request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    await process_order_paid_growth_event(
        tenant_id=req.tenant_id,
        order_id=req.order_id,
        order_amount=req.amount,
        customer_phone=req.customer_phone,
        customer_email=req.customer_email,
        client_ip=client_ip
    )
    return {"success": True, "message": f"Event order PAID #{req.order_id} berhasil diproses oleh Growth Worker."}

# --- AIOHTTP HANDLERS ---
async def aiohttp_track_handler(request: web.Request):
    try:
        body = await request.json()
        client_ip = request.remote or "127.0.0.1"
        ua = body.get("user_agent") or request.headers.get("User-Agent", "")
        res = bind_attribution_session(
            tenant_id=body.get("tenant_id", ""),
            referral_code=body.get("referral_code"),
            fbclid=body.get("fbclid"),
            user_agent=ua,
            client_ip=client_ip,
            order_id=body.get("order_id"),
            session_id=body.get("session_id"),
            utm_source=body.get("utm_source"),
            utm_medium=body.get("utm_medium"),
            utm_campaign=body.get("utm_campaign"),
            utm_content=body.get("utm_content"),
            utm_term=body.get("utm_term"),
            ttclid=body.get("ttclid")
        )
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def aiohttp_portal_handler(request: web.Request):
    try:
        tenant_id = request.match_info.get("tenant_id")
        referral_code = request.match_info.get("referral_code")
        data = fetch_portal_data(tenant_id, referral_code)
        if not data:
            return web.json_response({"success": False, "detail": "Affiliate tidak ditemukan!"}, status=404)
        return web.json_response({"success": True, "data": data})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def aiohttp_simulate_paid_handler(request: web.Request):
    try:
        body = await request.json()
        client_ip = request.remote or "127.0.0.1"
        await process_order_paid_growth_event(
            tenant_id=body.get("tenant_id", ""),
            order_id=body.get("order_id", ""),
            order_amount=float(body.get("amount", 0)),
            customer_phone=body.get("customer_phone", "08123456789"),
            customer_email=body.get("customer_email", "buyer@gmail.com"),
            client_ip=client_ip
        )
        return web.json_response({
            "success": True,
            "message": f"Event order PAID #{body.get('order_id')} berhasil diproses oleh Growth Worker."
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

def register_growth_routes(app: web.Application):
    app.router.add_post('/api/v1/growth/track', aiohttp_track_handler)
    app.router.add_get('/api/v1/growth/portal/{tenant_id}/{referral_code}', aiohttp_portal_handler)
    app.router.add_post('/api/v1/growth/simulate/order-paid', aiohttp_simulate_paid_handler)