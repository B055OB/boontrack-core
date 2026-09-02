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
    order_id: Optional[str] = None
) -> Dict[str, Any]:
    """Mencatat sesi klik/checkout dengan IP di-hash SHA-256 (Data Minimization)."""
    ip_hash = hashlib.sha256((client_ip or "127.0.0.1").encode("utf-8")).hexdigest()
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

        cur.execute("""
            INSERT INTO attribution_sessions (
                tenant_id, affiliate_id, order_id, referral_code, fbclid, user_agent, ip_hash, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, NOW()
            ) RETURNING id;
        """, (tenant_id, affiliate_id, order_id, referral_code, fbclid, user_agent, ip_hash))

        session_row = cur.fetchone()
        conn.commit()
        cur.close()
        return {"success": True, "session_id": str(session_row["id"]), "affiliate_id": affiliate_id}
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

        # Cek apakah order ini terikat sesi atribusi
        cur.execute("""
            SELECT s.affiliate_id, s.fbclid, s.user_agent, a.name, a.phone_number, a.commission_rate
            FROM attribution_sessions s
            LEFT JOIN affiliates a ON s.affiliate_id = a.id
            WHERE s.tenant_id = %s AND s.order_id = %s
            ORDER BY s.created_at DESC LIMIT 1;
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

    # Dispatch Server-Side Meta CAPI
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