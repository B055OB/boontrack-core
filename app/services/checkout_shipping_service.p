import os
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Any, List
from app.services.biteship_adapter import BiteshipShippingAdapter
from app.services.shipping_interface import BookingRequest

def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL", "").strip())

# Default origin warehouse (contoh: Gudang Bandung)
DEFAULT_ORIGIN = {
    "name": "BoonTrack Fulfillment Center",
    "phone": "081237450222",
    "address": "Margahayu Raya, Bandung, Jawa Barat",
    "lat": -6.9535,
    "lng": 107.6710
}

async def fetch_grouped_shipping_rates(dest_lat: float, dest_lng: float, weight_kg: float = 1.0, is_cod: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """Mengambil ongkir real-time dari Biteship dan mengelompokkan ke Instant vs Regular."""
    adapter = BiteshipShippingAdapter()
    raw_rates = await adapter.get_rates(
        origin_lat=DEFAULT_ORIGIN["lat"],
        origin_lng=DEFAULT_ORIGIN["lng"],
        dest_lat=dest_lat,
        dest_lng=dest_lng,
        weight_kg=weight_kg,
        is_cod=is_cod
    )

    grouped = {
        "instant": [],
        "regular": []
    }

    for rate in raw_rates:
        item = {
            "courier_name": rate.courier_name.upper(),
            "service_name": rate.service_name,
            "service_code": f"{rate.courier_name.lower()}_{rate.service_name.lower()}",
            "cost": rate.cost,
            "etd": rate.estimated_delivery,
            "is_cod_supported": rate.is_cod_supported
        }
        if "instant" in rate.service_type.lower() or "same" in rate.service_type.lower():
            grouped["instant"].append(item)
        else:
            grouped["regular"].append(item)

    return grouped

async def create_checkout_order_with_shipping(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    1. Hitung total: subtotal produk + ongkir.
    2. Kunci komisi affiliate murni dari subtotal produk (tanpa ongkir).
    3. Simpan order ke product_orders.
    """
    tenant_id = payload.get("tenant_id", "onlineboost")
    order_id = payload.get("order_id")
    product_name = payload.get("product_name", "Single Product")
    base_price = float(payload.get("base_price", 99000))
    shipping_cost = float(payload.get("shipping_cost", 0))
    total_amount = base_price + shipping_cost
    
    payment_method = payload.get("payment_method", "DIRECT").upper()
    referral_code = payload.get("referral_code")
    
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Simpan order
        cur.execute("""
            INSERT INTO product_orders (
                order_id, product_name, base_price, total_amount, shipping_cost,
                payment_method, status, fulfillment_status, cod_settlement_status,
                courier_code, courier_service_name, shipping_address
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, 'PENDING', 'UNFULFILLED', 
                %s, %s, %s, %s
            ) RETURNING id, order_id;
        """, (
            order_id, product_name, int(base_price), int(total_amount), int(shipping_cost),
            payment_method, 'NONE' if payment_method != 'COD' else 'PENDING_REMITTANCE',
            payload.get("courier_code"), payload.get("courier_service_name"), payload.get("shipping_address")
        ))

        # Komisi Affiliate: Dihitung MURNI dari base_price (tanpa shipping_cost)
        if referral_code:
            cur.execute("""
                SELECT id, commission_rate FROM affiliates 
                WHERE tenant_id = %s AND referral_code = %s AND status = 'ACTIVE';
            """, (tenant_id, referral_code))
            affiliate = cur.fetchone()

            if affiliate:
                rate = float(affiliate.get("commission_rate", 10.0))
                commission_earned = (base_price * rate) / 100.0

                cur.execute("""
                    INSERT INTO affiliate_commissions (
                        tenant_id, affiliate_id, order_id, order_amount, amount, status, created_at
                    ) VALUES (%s, %s, %s, %s, %s, 'PENDING', NOW())
                    ON CONFLICT (tenant_id, order_id) DO NOTHING;
                """, (tenant_id, affiliate["id"], order_id, int(base_price), commission_earned))

        conn.commit()
        return {
            "success": True,
            "order_id": order_id,
            "subtotal": base_price,
            "shipping_cost": shipping_cost,
            "grand_total": total_amount,
            "payment_method": payment_method
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()

async def trigger_order_processing_and_awb(order_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Dipanggil saat order masuk tahap PROCESSING:
    Melakukan booking otomatis ke Biteship dan menerbitkan Waybill / Tracking ID.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT * FROM product_orders WHERE order_id = %s;
        """, (order_id,))
        order = cur.fetchone()

        if not order:
            return {"success": False, "error": "Order tidak ditemukan"}

        is_cod = order["payment_method"] == "COD"
        adapter = BiteshipShippingAdapter()

        # Buat Booking Delivery Order
        req = BookingRequest(
            tenant_id=tenant_id,
            order_id=order_id,
            service_type=order.get("courier_code") or "grab_instant",
            is_cod=is_cod,
            cod_amount=float(order["total_amount"]) if is_cod else 0.0,
            sender_name=DEFAULT_ORIGIN["name"],
            sender_phone=DEFAULT_ORIGIN["phone"],
            sender_address=DEFAULT_ORIGIN["address"],
            sender_lat=DEFAULT_ORIGIN["lat"],
            sender_lng=DEFAULT_ORIGIN["lng"],
            recipient_name=order.get("customer_name") or "Pelanggan",
            recipient_phone=order.get("customer_phone") or "08123456789",
            recipient_address=order.get("shipping_address") or "Alamat Penerima",
            item_description=order.get("product_name", "Produk"),
            item_value=float(order["base_price"]),
            weight_kg=float(order.get("weight_gram", 1000)) / 1000.0
        )

        booking_res = await adapter.create_booking(req)

        # Update product_orders dan delivery_orders
        cur.execute("""
            UPDATE product_orders
            SET status = 'PROCESSING',
                fulfillment_status = 'ALLOCATING',
                courier_tracking_id = %s
            WHERE order_id = %s;
        """, (booking_res.tracking_number, order_id))

        cur.execute("""
            INSERT INTO delivery_orders (
                tenant_id, order_id, provider, booking_id, tracking_number,
                service_type, is_cod, cod_amount, shipping_cost, status
            ) VALUES (%s, %s, 'biteship', %s, %s, %s, %s, %s, %s, 'ALLOCATING')
            ON CONFLICT DO NOTHING;
        """, (
            tenant_id, order_id, booking_res.booking_id, booking_res.tracking_number,
            order.get("courier_code", "instant"), is_cod,
            float(order["total_amount"]) if is_cod else 0.0,
            float(order.get("shipping_cost", 0))
        ))

        conn.commit()
        return {
            "success": True,
            "order_id": order_id,
            "status": "PROCESSING",
            "tracking_number": booking_res.tracking_number,
            "booking_id": booking_res.booking_id
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()