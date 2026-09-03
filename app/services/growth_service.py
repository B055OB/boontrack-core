import hashlib
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, Optional
from app.services.adapters import WhatsAppAdapter
from app.services.meta_capi_service import send_meta_capi_purchase

def get_db_connection():
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    return psycopg2.connect(db_url)

def bind_attribution_session(
    tenant_id: str,
    referral_code: Optional[str],
    fbclid: Optional[str],
    user_agent: Optional[str],
    client_ip: str,
    order_id: Optional[str] = None,
    session_id: Optional[str] = None,
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    utm_content: Optional[str] = None,
    utm_term: Optional[str] = None,
    ttclid: Optional[str] = None
) -> Dict[str, Any]:
    """Mencatat sesi klik/checkout dengan parameter UTM lengkap dan IP hash SHA-256."""
    ip_hash = hashlib.sha256((client_ip or "127.0.0.1").encode("utf-8")).hexdigest()
    sid = session_id or f"sid_{os.urandom(8).hex()}"
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        affiliate_id = None
        if referral_code:
            cur.execute("""
                SELECT id FROM affiliates 
                WHERE tenant_id = %s AND referral_code = %s AND status = 'ACTIVE'
            """, (tenant_id, referral_code))
            aff = cur.fetchone()
            if aff:
                affiliate_id = aff["id"]

        # 1. Simpan ke tabel attributions (P3-A)
        cur.execute("""
            INSERT INTO attributions (
                tenant_id, session_id, affiliate_id, utm_source, utm_medium,
                utm_campaign, utm_content, utm_term, fbclid, ttclid,
                ip_hash, user_agent, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            ) RETURNING id;
        """, (
            tenant_id, sid, affiliate_id, utm_source, utm_medium,
            utm_campaign, utm_content, utm_term, fbclid, ttclid,
            ip_hash, user_agent
        ))
        attribution_row = cur.fetchone()
        attribution_id = str(attribution_row["id"])

        # 2. Jika ada order_id, bind langsung ke product_orders
        if order_id:
            cur.execute("""
                UPDATE product_orders 
                SET attribution_id = %s 
                WHERE order_id = %s AND tenant_id = %s;
            """, (attribution_id, order_id, tenant_id))

        conn.commit()
        cur.close()
        return {
            "success": True, 
            "attribution_id": attribution_id, 
            "session_id": sid, 
            "affiliate_id": affiliate_id
        }
    except Exception as e:
        if conn:
            conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if conn:
            conn.close()

async def process_order_paid_growth_event(
    tenant_id: str,
    order_id: str,
    order_amount: float,
    customer_phone: Optional[str] = None,
    customer_email: Optional[str] = None,
    client_ip: Optional[str] = None
):
    """
    Eksekusi otomatis saat pesanan status PAID:
    1. Hitung & catat komisi ke tabel affiliate_commissions (APPROVED).
    2. Kirim notifikasi WhatsApp ke affiliate.
    3. Tembakkan Server-Side Meta CAPI Purchase.
    """
    conn = None
    affiliate_info = None
    attribution_info = None

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Cek apakah order ini terikat ke attributions atau legacy attribution_sessions
        cur.execute("""
            SELECT 
                po.attribution_id,
                COALESCE(att.affiliate_id, s.affiliate_id) as affiliate_id,
                COALESCE(att.fbclid, s.fbclid) as fbclid,
                COALESCE(att.user_agent, s.user_agent) as user_agent,
                a.name, 
                a.phone_number, 
                a.commission_rate
            FROM product_orders po
            LEFT JOIN attributions att ON po.attribution_id = att.id
            LEFT JOIN attribution_sessions s ON (po.order_id = s.order_id OR po.tenant_id = s.tenant_id)
            LEFT JOIN affiliates a ON a.id = COALESCE(att.affiliate_id, s.affiliate_id)
            WHERE po.tenant_id = %s AND po.order_id = %s
            ORDER BY po.created_at DESC LIMIT 1;
        """, (tenant_id, order_id))
        attribution_info = cur.fetchone()

        if attribution_info and attribution_info.get("affiliate_id"):
            aff_id = attribution_info["affiliate_id"]
            comm_rate = float(attribution_info.get("commission_rate") or 10.0)
            comm_amount = (order_amount * comm_rate) / 100.0

            # Catat ke Ledger Komisi
            cur.execute("""
                INSERT INTO affiliate_commissions (
                    tenant_id, affiliate_id, order_id, order_amount, amount, status, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, 'APPROVED', NOW()
                ) ON CONFLICT (tenant_id, order_id) DO NOTHING;
            """, (tenant_id, aff_id, order_id, order_amount, comm_amount))
            conn.commit()

            affiliate_info = {
                "name": attribution_info["name"],
                "phone": attribution_info["phone_number"],
                "commission": comm_amount
            }

        cur.close()
    except Exception as e:
        print(f"[GROWTH WORKER ERROR] Ledger step error: {e}", flush=True)
    finally:
        if conn:
            conn.close()

    # Kirim Notifikasi WhatsApp Asynchronous
    if affiliate_info and affiliate_info.get("phone"):
        try:
            wa = WhatsAppAdapter()
            msg = (
                f"🎉 Halo {affiliate_info['name']}!\n"
                f"Komisi sebesar *Rp{int(affiliate_info['commission']):,}* berhasil masuk dari pesanan *#{order_id}*.\n"
                f"Status: APPROVED. Pantau saldo di portal affiliate kamu."
            )
            await wa.send_message(tenant_id, affiliate_info["phone"], msg)
        except Exception as e:
            print(f"[WA NOTIF WARNING] Gagal kirim WA affiliate: {e}", flush=True)

    # Dispatch Server-Side Meta CAPI Purchase
    fbclid = attribution_info.get("fbclid") if attribution_info else None
    user_agent = attribution_info.get("user_agent") if attribution_info else None

    await send_meta_capi_purchase(
        external_id=order_id,
        value=order_amount,
        currency="IDR",
        phone=customer_phone,
        email=customer_email,
        fbclid=fbclid,
        client_ip=client_ip,
        client_user_agent=user_agent
    )