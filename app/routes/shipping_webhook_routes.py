import os
import psycopg2
from psycopg2.extras import RealDictCursor
from aiohttp import web
from app.services.cod_settlement_service import reconcile_single_cod_order
from app.services.checkout_shipping_service import (
    fetch_grouped_shipping_rates,
    create_checkout_order_with_shipping,
    trigger_order_processing_and_awb,
)

def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL", "").strip())

async def biteship_webhook_handler(request: web.Request):
    """
    Menangkap webhook event dari Biteship.
    Prinsip Isolasi State: DELIVERED hanya memperbarui fulfillment_status!
    State COD dan komisi affiliate tetap terkunci sampai dana settlement terverifikasi.
    """
    try:
        data = await request.json()
        event = data.get("event")
        booking_id = data.get("order_id")  # ID booking Biteship

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if event == "order.status":
            biteship_status = data.get("status", "").lower()
            
            fulfillment_map = {
                "picking_up": "ALLOCATING",
                "picked": "PICKED_UP",
                "dropping_off": "IN_TRANSIT",
                "delivered": "DELIVERED",
                "returned": "RETURNED"
            }
            new_fulfillment = fulfillment_map.get(biteship_status)

            if new_fulfillment:
                # 1. Update status shipment di delivery_orders
                cur.execute("""
                    UPDATE delivery_orders
                    SET status = %s, updated_at = NOW()
                    WHERE booking_id = %s
                    RETURNING tenant_id, order_id, is_cod;
                """, (new_fulfillment, booking_id))
                row = cur.fetchone()

                # 2. Update state di product_orders (kunci unik order_id)
                if row:
                    cur.execute("""
                        UPDATE product_orders
                        SET fulfillment_status = %s
                        WHERE order_id = %s;
                    """, (new_fulfillment, row["order_id"]))

                    # Jika COD dan barang sampai, status uang menjadi PENDING_REMITTANCE
                    if new_fulfillment == "DELIVERED" and row["is_cod"]:
                        cur.execute("""
                            UPDATE product_orders
                            SET cod_settlement_status = 'PENDING_REMITTANCE'
                            WHERE order_id = %s AND (cod_settlement_status IS NULL OR cod_settlement_status = 'NONE');
                        """, (row["order_id"],))

                conn.commit()

        cur.close()
        conn.close()
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def reconcile_cod_handler(request: web.Request):
    """Trigger endpoint untuk verifikasi settlement dana COD dan pelepasan komisi."""
    try:
        body = await request.json()
        tenant_id = body.get("tenant_id")
        order_id = body.get("order_id")

        if not tenant_id or not order_id:
            return web.json_response({
                "success": False, 
                "error": "Parameter tenant_id dan order_id wajib diisi"
            }, status=400)

        result = await reconcile_single_cod_order(order_id, tenant_id)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def get_shipping_rates_handler(request: web.Request):
    """Mendapatkan opsi ongkir real-time yang terkelompok (instant vs regular)."""
    try:
        body = await request.json()
        rates = await fetch_grouped_shipping_rates(
            dest_lat=float(body.get("dest_lat", -6.9175)),
            dest_lng=float(body.get("dest_lng", 107.6191)),
            weight_kg=float(body.get("weight_kg", 1.0)),
            is_cod=bool(body.get("is_cod", False))
        )
        return web.json_response({"success": True, "rates": rates})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def checkout_shipping_order_handler(request: web.Request):
    """Submit checkout form dengan ongkir terkunci & komisi murni berbasis subtotal."""
    try:
        body = await request.json()
        res = await create_checkout_order_with_shipping(body)
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def process_order_awb_handler(request: web.Request):
    """Trigger status PROCESSING dan auto-booking AWB resi logistik."""
    try:
        body = await request.json()
        tenant_id = body.get("tenant_id", "onlineboost")
        order_id = body.get("order_id")

        if not order_id:
            return web.json_response({"success": False, "error": "order_id wajib diisi"}, status=400)

        res = await trigger_order_processing_and_awb(order_id, tenant_id)
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

def register_shipping_routes(app: web.Application):
    app.router.add_post('/api/v1/webhooks/biteship', biteship_webhook_handler)
    app.router.add_post('/api/v1/shipping/cod/reconcile', reconcile_cod_handler)
    app.router.add_post('/api/v1/shipping/rates', get_shipping_rates_handler)
    app.router.add_post('/api/v1/shipping/checkout', checkout_shipping_order_handler)
    app.router.add_post('/api/v1/shipping/order/process', process_order_awb_handler)