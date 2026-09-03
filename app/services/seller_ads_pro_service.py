import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, List, Optional
import aiohttp
import time
import hashlib

def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL", "").strip())

def hash_data(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    return hashlib.sha256(val.strip().lower().encode("utf-8")).hexdigest()

async def verify_seller_addon_entitlement(tenant_id: str) -> bool:
    """Memverifikasi apakah seller berlangganan add-on Ads Tracking Pro."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT is_active, expires_at 
            FROM tenant_addons 
            WHERE tenant_id = %s AND addon_key = 'ads_tracking_pro';
        """, (tenant_id,))
        row = cur.fetchone()
        if not row or not row["is_active"]:
            return False
        return True
    finally:
        cur.close()
        conn.close()

async def upsert_seller_pixel_settings(tenant_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Menyimpan Pixel ID & CAPI Token milik seller sendiri."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            INSERT INTO seller_pixel_configs (
                tenant_id, meta_pixel_id, meta_capi_token, meta_test_event_code,
                tiktok_pixel_id, tiktok_capi_token, tiktok_test_event_code, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                meta_pixel_id = EXCLUDED.meta_pixel_id,
                meta_capi_token = EXCLUDED.meta_capi_token,
                meta_test_event_code = EXCLUDED.meta_test_event_code,
                tiktok_pixel_id = EXCLUDED.tiktok_pixel_id,
                tiktok_capi_token = EXCLUDED.tiktok_capi_token,
                tiktok_test_event_code = EXCLUDED.tiktok_test_event_code,
                updated_at = NOW();
        """, (
            tenant_id,
            data.get("meta_pixel_id"),
            data.get("meta_capi_token"),
            data.get("meta_test_event_code"),
            data.get("tiktok_pixel_id"),
            data.get("tiktok_capi_token"),
            data.get("tiktok_test_event_code")
        ))
        conn.commit()
        return {"success": True, "message": "Konfigurasi Ads Tracking Pro seller berhasil disimpan"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()

async def get_seller_pixel_settings(tenant_id: str) -> Dict[str, Any]:
    """Mengambil konfigurasi Pixel seller untuk ditanam di form checkout/landing page."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT meta_pixel_id, meta_test_event_code, tiktok_pixel_id, tiktok_test_event_code, is_active
            FROM seller_pixel_configs 
            WHERE tenant_id = %s;
        """, (tenant_id,))
        row = cur.fetchone()
        return dict(row) if row else {}
    finally:
        cur.close()
        conn.close()

async def dispatch_seller_capi_purchase(tenant_id: str, order_id: str, amount: float, tracking_data: Dict[str, Any]):
    """
    Mengirim event Purchase server-side LANGSUNG ke Ads Manager milik SELLER
    (Menggunakan Meta Pixel ID & CAPI Token milik seller, bukan akun Boontrack).
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Catat ke attribution log seller
        cur.execute("""
            INSERT INTO seller_ad_conversions (
                tenant_id, order_id, utm_source, utm_medium, utm_campaign,
                utm_content, utm_term, fbclid, ttclid, client_ip, client_user_agent, gross_revenue
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """, (
            tenant_id, order_id,
            tracking_data.get("utm_source"),
            tracking_data.get("utm_medium"),
            tracking_data.get("utm_campaign"),
            tracking_data.get("utm_content"),
            tracking_data.get("utm_term"),
            tracking_data.get("fbclid"),
            tracking_data.get("ttclid"),
            tracking_data.get("client_ip"),
            tracking_data.get("client_user_agent"),
            amount
        ))
        conn.commit()

        # Ambil kredensial seller
        cur.execute("SELECT * FROM seller_pixel_configs WHERE tenant_id = %s AND is_active = TRUE;", (tenant_id,))
        cfg = cur.fetchone()
        if not cfg:
            return

        # 1. Meta CAPI milik Seller
        if cfg.get("meta_pixel_id") and cfg.get("meta_capi_token"):
            pixel_id = cfg["meta_pixel_id"]
            token = cfg["meta_capi_token"]
            url = f"https://graph.facebook.com/v19.0/{pixel_id}/events?access_token={token}"
            
            user_data = {}
            if tracking_data.get("fbclid"):
                user_data["fbc"] = f"fb.1.{int(time.time())}.{tracking_data['fbclid']}"
            if tracking_data.get("client_ip"):
                user_data["client_ip_address"] = tracking_data["client_ip"]
            if tracking_data.get("client_user_agent"):
                user_data["client_user_agent"] = tracking_data["client_user_agent"]
            if tracking_data.get("phone"):
                user_data["ph"] = [hash_data(tracking_data["phone"])]

            payload = {
                "data": [{
                    "event_name": "Purchase",
                    "event_time": int(time.time()),
                    "event_id": f"PURCHASE_{order_id}",
                    "action_source": "website",
                    "user_data": user_data,
                    "custom_data": {
                        "currency": "IDR",
                        "value": float(amount)
                    }
                }]
            }
            if cfg.get("meta_test_event_code"):
                payload["test_event_code"] = cfg["meta_test_event_code"]

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    print(f"[SELLER CAPI] Meta Purchase Dispatched: status={resp.status}")

    except Exception as e:
        print(f"[SELLER CAPI ERROR] {e}")
    finally:
        cur.close()
        conn.close()

async def get_seller_attribution_analytics(tenant_id: str) -> Dict[str, Any]:
    """Laporan dashboard performa campaign iklan berbayar milik toko seller."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Ringkasan Total
        cur.execute("""
            SELECT 
                COUNT(id) as total_ad_orders,
                COALESCE(SUM(gross_revenue), 0) as total_ad_revenue
            FROM seller_ad_conversions
            WHERE tenant_id = %s;
        """, (tenant_id,))
        summary = cur.fetchone()

        # Rincian Berdasarkan Campaign Iklan
        cur.execute("""
            SELECT 
                COALESCE(utm_campaign, '(Direct / No UTM)') as campaign_name,
                COALESCE(utm_source, 'unknown') as source,
                COUNT(id) as total_orders,
                COALESCE(SUM(gross_revenue), 0) as total_revenue
            FROM seller_ad_conversions
            WHERE tenant_id = %s
            GROUP BY utm_campaign, utm_source
            ORDER BY total_revenue DESC;
        """, (tenant_id,))
        campaigns = cur.fetchall()

        return {
            "success": True,
            "tenant_id": tenant_id,
            "summary": {
                "total_ad_orders": int(summary["total_ad_orders"]),
                "total_ad_revenue": float(summary["total_ad_revenue"])
            },
            "campaign_breakdown": [dict(c) for c in campaigns]
        }
    finally:
        cur.close()
        conn.close()