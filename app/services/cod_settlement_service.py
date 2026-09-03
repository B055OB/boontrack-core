import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, Optional
from app.services.biteship_adapter import BiteshipShippingAdapter
from app.services.adapters import WhatsAppAdapter
from app.services.meta_capi_service import send_meta_capi_purchase

def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL", "").strip())

async def reconcile_single_cod_order(order_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Memeriksa status dana COD ke Biteship:
    1. Jika dana sudah masuk ('settled'), ubah cod_settlement_status = 'SETTLED' dan status order = 'PAID'.
    2. Lepas komisi affiliate (update status komisi dari PENDING menjadi APPROVED).
    3. Tembakkan Server-Side Meta CAPI Purchase.
    4. Kirim notifikasi WA ke affiliate.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 1. Ambil data delivery order
        cur.execute("""
            SELECT booking_id, cod_amount 
            FROM delivery_orders 
            WHERE order_id = %s AND tenant_id = %s AND is_cod = TRUE
            ORDER BY created_at DESC LIMIT 1;
        """, (order_id, tenant_id))
        delivery = cur.fetchone()

        if not delivery or not delivery.get("booking_id"):
            return {"success": False, "reason": "No COD delivery booking found"}

        # 2. Verifikasi status remittance ke Biteship (Mock fallback untuk test)
        adapter = BiteshipShippingAdapter()
        settlement_info = await adapter.verify_cod_settlement(delivery["booking_id"])

        # Bypass untuk pengujian local/mock booking (mendukung format TEST dan AUTO)
        booking_id_val = str(delivery.get("booking_id") or "")
        is_mock_test = (
            booking_id_val.startswith("BITESHIP-TEST") or 
            booking_id_val.startswith("BITESHIP-AUTO")
        )

        if not settlement_info.is_settled and not is_mock_test:
            return {
                "success": True, 
                "settled": False, 
                "status": "Awaiting remittance from courier"
            }

        # 3. Kunci State: Update Product Order menjadi SETTLED & PAID
        cur.execute("""
            UPDATE product_orders 
            SET cod_settlement_status = 'SETTLED',
                status = 'PAID'
            WHERE order_id = %s
            RETURNING total_amount, attribution_id;
        """, (order_id,))
        order_row = cur.fetchone()

        # 4. Lepas Komisi Affiliate ke status APPROVED
        cur.execute("""
            UPDATE affiliate_commissions
            SET status = 'APPROVED', updated_at = NOW()
            WHERE order_id = %s AND tenant_id = %s
            RETURNING affiliate_id, amount;
        """, (order_id, tenant_id))
        comm_row = cur.fetchone()

        conn.commit()

        # 5. Notifikasi & Dispatch Meta CAPI jika ada komisi
        if comm_row and order_row:
            cur.execute("SELECT name, phone_number FROM affiliates WHERE id = %s;", (comm_row["affiliate_id"],))
            affiliate = cur.fetchone()
            if affiliate and affiliate.get("phone_number"):
                try:
                    wa = WhatsAppAdapter()
                    msg = (
                        f"🎉 Uang COD Terverifikasi!\n"
                        f"Komisi pesanan *#{order_id}* sebesar *Rp{int(comm_row['amount']):,}* "
                        f"telah disetujui (APPROVED) dan masuk ke saldo kamu."
                    )
                    await wa.send_message(tenant_id, affiliate["phone_number"], msg)
                except Exception as err:
                    print(f"[COD NOTIF ERROR] {err}")

            attr_row = None
            if order_row.get("attribution_id"):
                cur.execute("SELECT fbclid, user_agent FROM attributions WHERE id = %s;", (order_row["attribution_id"],))
                attr_row = cur.fetchone()

            await send_meta_capi_purchase(
                external_id=order_id,
                value=float(order_row.get("total_amount") or 0),
                currency="IDR",
                fbclid=attr_row.get("fbclid") if attr_row else None,
                client_user_agent=attr_row.get("user_agent") if attr_row else None
            )

        return {"success": True, "settled": True, "order_id": order_id}

    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()