import os
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, status
from pydantic import BaseModel, Field
from app.services.biteship_service import (
    get_instant_rates,
    get_all_shipping_rates,
    map_biteship_event_status,
    ORIGIN_WAREHOUSE,
    STATUS_EVENT_MAPPING,
)

def resolve_tenant_origin(tenant_id: Optional[str]) -> Dict[str, Any]:
    """
    Mengambil data alamat asal pengiriman toko (Single Source of Truth: metadata.shipping_config & tenant_settings.biteship_config).
    Mendukung Biteship Area ID (origin_area_id), koordinat presisi (latitude, longitude),
    serta integrasi akun logistik kemitraan (referral vs custom API key).
    """
    origin = dict(ORIGIN_WAREHOUSE)
    if not tenant_id:
        return origin
    try:
        from app.services.whatsapp_service import get_supabase
        supabase = get_supabase()
        if supabase:
            # 1. tenant_settings
            st_res = supabase.table("tenant_settings").select("biteship_config").eq("tenant_slug", tenant_id).execute()
            biteship_cfg = st_res.data[0].get("biteship_config") if st_res.data and isinstance(st_res.data[0], dict) else {}
            shipping_origin = (biteship_cfg.get("origin") if isinstance(biteship_cfg, dict) else {})

            # 2. tenants.metadata
            t_res = supabase.table("tenants").select("metadata").eq("slug", tenant_id).execute()
            meta = t_res.data[0].get("metadata") if t_res.data and isinstance(t_res.data[0], dict) else {}
            meta_shipping = meta.get("shipping_config") if isinstance(meta.get("shipping_config"), dict) else {}
            meta_origin = meta_shipping.get("origin") if isinstance(meta_shipping.get("origin"), dict) else meta_shipping

            origin_obj = shipping_origin or meta_origin or {}
            
            postal = origin_obj.get("postal_code") or meta_origin.get("origin_postal_code") or meta.get("origin_postal_code")
            if postal:
                origin["postal_code"] = int(postal) if str(postal).isdigit() else postal
            
            city = origin_obj.get("city") or meta_origin.get("origin_city") or meta.get("origin_city")
            if city:
                origin["city"] = city

            district = origin_obj.get("district") or meta_origin.get("origin_district") or meta.get("origin_district")
            if district:
                origin["district"] = district

            subdistrict = origin_obj.get("subdistrict_id") or meta_origin.get("origin_subdistrict_id") or meta.get("origin_subdistrict_id")
            if subdistrict:
                origin["origin_subdistrict_id"] = str(subdistrict)

            addr = origin_obj.get("address") or meta_origin.get("origin_address") or meta.get("origin_address") or meta.get("warehouse_address")
            if addr and isinstance(addr, str):
                origin["address"] = addr

            # Standardized origin_area_id (Biteship Area ID)
            origin_area_id = origin_obj.get("origin_area_id") or origin_obj.get("area_id") or meta_origin.get("origin_area_id")
            if origin_area_id:
                origin["origin_area_id"] = str(origin_area_id)

            # Standardized Pinpoint Coordinates (latitude & longitude)
            lat = origin_obj.get("latitude") if origin_obj.get("latitude") is not None else meta_origin.get("latitude")
            lng = origin_obj.get("longitude") if origin_obj.get("longitude") is not None else meta_origin.get("longitude")
            if lat is not None:
                try:
                    origin["latitude"] = float(lat)
                except (ValueError, TypeError):
                    pass
            if lng is not None:
                try:
                    origin["longitude"] = float(lng)
                except (ValueError, TypeError):
                    pass

            # Contact info
            sender_name = origin_obj.get("sender_name") or meta_origin.get("sender_name")
            if sender_name:
                origin["sender_name"] = str(sender_name)
            sender_phone = origin_obj.get("sender_phone") or meta_origin.get("sender_phone")
            if sender_phone:
                origin["sender_phone"] = str(sender_phone)

            # Partnership logistics account support
            logistics_acc = (
                biteship_cfg.get("logistics_account")
                or meta_shipping.get("logistics_account")
                or biteship_cfg.get("partnership")
                or meta_shipping.get("partnership")
            )
            if logistics_acc and isinstance(logistics_acc, dict):
                origin["logistics_account"] = logistics_acc

    except Exception as err:
        logger.warning(f"[Origin Resolver] Fallback to default: {err}")
    return origin

logger = logging.getLogger("SHIPPING_ROUTES")

router = APIRouter(prefix="/api/v1/shipping", tags=["Shipping Logistics"])
logistics_router = APIRouter(prefix="/api/v1/logistics", tags=["Biteship Logistics"])


class ShippingItemSchema(BaseModel):
    name: Optional[str] = Field("BoonTrack Merchandise", description="Nama produk/barang")
    description: Optional[str] = Field(None, description="Deskripsi singkat produk")
    value: Optional[int] = Field(50000, description="Estimasi nilai barang dalam IDR")
    length: Optional[int] = Field(None, description="Panjang paket (cm)")
    width: Optional[int] = Field(None, description="Lebar paket (cm)")
    height: Optional[int] = Field(None, description="Tinggi paket (cm)")
    weight: Optional[int] = Field(1000, description="Berat paket dalam gram")
    quantity: Optional[int] = Field(1, description="Jumlah item")


class ShippingRatesRequest(BaseModel):
    tenant_id: Optional[str] = Field("onlineboost", description="ID atau slug tenant toko")
    destination_postal_code: str = Field(..., description="Kode pos tujuan pengiriman")
    destination_address: Optional[str] = Field(None, description="Alamat lengkap tujuan pengiriman")
    destination_area: Optional[str] = Field(None, description="Nama kelurahan/kecamatan tujuan (opsional)")
    destination_lat: Optional[float] = Field(None, description="Latitude koordinat tujuan")
    destination_lng: Optional[float] = Field(None, description="Longitude koordinat tujuan")
    is_cod: Optional[bool] = Field(False, description="Apakah menggunakan metode Cash on Delivery")
    category: Optional[str] = Field(None, description="Filter kategori: 'instant', 'sameday', 'reguler', 'kargo', 'cod'")
    items: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Daftar item belanja")


class InstantRatesRequest(BaseModel):
    tenant_id: Optional[str] = Field("onlineboost", description="ID atau slug tenant toko")
    destination_postal_code: str = Field(..., description="Kode pos tujuan pengiriman")
    destination_address: Optional[str] = Field(None, description="Alamat lengkap tujuan pengiriman")
    destination_area: Optional[str] = Field(None, description="Nama kelurahan/kecamatan tujuan (opsional)")
    items: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Daftar item belanja")


class CourierRateSchema(BaseModel):
    courier_name: str
    service_type: str
    service_name: str
    price: int
    etd: str
    description: str


class InstantRatesResponse(BaseModel):
    success: bool
    tenant_id: Optional[str]
    origin: Dict[str, Any]
    destination_postal_code: str
    destination_address: Optional[str]
    rates: List[CourierRateSchema]


@router.post(
    "/rates/instant",
    response_model=InstantRatesResponse,
    summary="Kalkulasi Ongkir Kurir Instan & Sameday (Biteship)",
    description="Menghitung tarif ongkos kirim GoSend & Grab (Instant / Same Day) dari Warehouse Margahayu Bandung."
)
async def calculate_instant_rates(payload: InstantRatesRequest):
    """Menghitung tarif ongkir instan / sameday kurir GoSend dan Grab via Biteship API."""
    if not payload.destination_postal_code or not payload.destination_postal_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter 'destination_postal_code' wajib diisi."
        )

    clean_postal = payload.destination_postal_code.strip()
    logger.info(
        f"[SHIPPING RATES REQ] Tenant: {payload.tenant_id} | Dest Postal: {clean_postal} | "
        f"Address: {payload.destination_address} | Items: {len(payload.items or [])}"
    )

    try:
        origin_info = resolve_tenant_origin(payload.tenant_id)
        rates = await get_instant_rates(
            destination_postal_code=clean_postal,
            items=payload.items or [],
            destination_area=payload.destination_area,
            origin_postal_code=origin_info.get("postal_code")
        )

        return InstantRatesResponse(
            success=True,
            tenant_id=payload.tenant_id,
            origin=origin_info,
            destination_postal_code=clean_postal,
            destination_address=payload.destination_address,
            rates=rates
        )
    except Exception as err:
        logger.error(f"[SHIPPING RATES ERROR] {err}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal menghitung tarif pengiriman: {str(err)}"
        )


@router.post(
    "/rates",
    summary="Kalkulasi Ongkir Seluruh Kurir (Instant, Sameday, Reguler, Kargo, COD)",
    description="Pusat kalkulasi ongkos kirim seluruh kurir terintegrasi Biteship."
)
@logistics_router.post(
    "/rates",
    summary="Kalkulasi Ongkir Seluruh Kurir Alias",
)
async def calculate_all_rates(payload: ShippingRatesRequest):
    """Pusat kalkulasi ongkos kirim multi-kurir: Instant, Sameday, Reguler, Kargo, COD via Biteship."""
    clean_postal = (payload.destination_postal_code or "").strip()
    if not clean_postal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parameter 'destination_postal_code' wajib diisi."
        )

    try:
        origin_info = resolve_tenant_origin(payload.tenant_id)
        result = await get_all_shipping_rates(
            destination_postal_code=clean_postal,
            items=payload.items or [],
            destination_area=payload.destination_area,
            destination_lat=payload.destination_lat,
            destination_lng=payload.destination_lng,
            is_cod=bool(payload.is_cod),
            origin_postal_code=origin_info.get("postal_code"),
        )
        result["origin"] = origin_info

        if payload.category:
            cat_clean = payload.category.strip().lower()
            grouped = result.get("grouped", {})
            if cat_clean in grouped:
                result["rates"] = grouped[cat_clean]

        return result
    except Exception as err:
        logger.error(f"[ALL RATES CALCULATION ERROR] {err}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal kalkulasi tarif ongkir Biteship: {str(err)}"
        )


def _sync_biteship_status_to_db(booking_id: str, mapped_status: str, raw_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Menyinkronkan status pengiriman Biteship ke database Supabase dan PostgreSQL."""
    # 1. Supabase Client
    try:
        from app.services.whatsapp_service import get_supabase
        supabase = get_supabase()
        if supabase and booking_id:
            try:
                supabase.table("delivery_orders").update({
                    "status": mapped_status,
                }).eq("booking_id", booking_id).execute()
            except Exception:
                pass

            try:
                supabase.table("product_orders").update({
                    "fulfillment_status": mapped_status,
                }).eq("booking_id", booking_id).execute()
            except Exception:
                pass

            if mapped_status == "COD_COLLECTED":
                try:
                    supabase.table("product_orders").update({
                        "cod_settlement_status": "SETTLED",
                        "status": "PAID",
                    }).eq("booking_id", booking_id).execute()
                except Exception:
                    pass

            try:
                supabase.table("orders").update({
                    "fulfillment_status": mapped_status,
                }).or_(f"id.eq.{booking_id},order_id.eq.{booking_id}").execute()
            except Exception:
                pass
    except Exception as db_err:
        logger.debug(f"[BITESHIP SUPABASE SYNC NOTE] {db_err}")

    # 2. PostgreSQL Connection jika ada
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        db_url = os.getenv("DATABASE_URL", "").strip()
        if db_url:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                UPDATE delivery_orders
                SET status = %s, updated_at = NOW()
                WHERE booking_id = %s
                RETURNING tenant_id, order_id, is_cod;
            """, (mapped_status, booking_id))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE product_orders
                    SET fulfillment_status = %s
                    WHERE order_id = %s;
                """, (mapped_status, row["order_id"]))

                if mapped_status == "COD_COLLECTED" or (mapped_status == "DELIVERED" and row.get("is_cod")):
                    cur.execute("""
                        UPDATE product_orders
                        SET cod_settlement_status = 'SETTLED', status = 'PAID'
                        WHERE order_id = %s;
                    """, (row["order_id"],))
            conn.commit()
            cur.close()
            conn.close()
            return row
    except Exception as pg_err:
        logger.debug(f"[BITESHIP PG SYNC NOTE] {pg_err}")

    return None


@logistics_router.post(
    "/biteship/webhook",
    summary="Biteship Logistics Webhook Receiver",
    description="Menerima webhook event status pengiriman dari Biteship API dan memetakan ke status lifecycle BoonTrack: ORDER_CREATED -> ALLOCATED -> PICKING_UP -> DROPPING_OFF -> DELIVERED / COD_COLLECTED."
)
@router.post(
    "/biteship/webhook",
    summary="Biteship Logistics Webhook Receiver Alias 1",
)
@router.post(
    "/webhook",
    summary="Biteship Logistics Webhook Receiver Alias 2",
)
async def biteship_logistics_webhook(request: Request):
    """Endpoint webhook penerima status pengiriman Biteship dengan pemetaan status lifecycle:
    ORDER_CREATED -> ALLOCATED -> PICKING_UP -> DROPPING_OFF -> DELIVERED / COD_COLLECTED
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Format JSON tidak valid."
        )

    logger.info(f"[BITESHIP WEBHOOK RECEIVED] Payload: {payload}")

    event = payload.get("event") or payload.get("status") or "order.status"
    raw_status = payload.get("status") or payload.get("courier_status") or event
    booking_id = (
        payload.get("order_id")
        or payload.get("id")
        or payload.get("booking_id")
        or ""
    )

    is_cod = bool(payload.get("is_cod") or (payload.get("cash_on_delivery") and payload.get("cash_on_delivery", {}).get("amount", 0) > 0))

    # Pemetaan status event terpusat
    mapped_status = map_biteship_event_status(
        event_or_status=raw_status,
        is_cod=is_cod,
        raw_data=payload,
    )

    logger.info(f"[BITESHIP STATUS MAPPED] Raw: '{raw_status}' -> Mapped: '{mapped_status}' for Booking ID: '{booking_id}'")

    if booking_id:
        _sync_biteship_status_to_db(booking_id, mapped_status, payload)

    return {
        "success": True,
        "status": mapped_status,
        "event": event,
        "booking_id": booking_id,
        "mapped_status": mapped_status,
        "message": f"Shipment status updated to {mapped_status}"
    }

@router.get("/areas", summary="Pencarian dan Validasi Wilayah Autocomplete (Biteship)")
@logistics_router.get("/areas", summary="Pencarian dan Validasi Wilayah Autocomplete Alias")
async def search_biteship_areas(
    query: Optional[str] = None,
    q: Optional[str] = None,
    input: Optional[str] = None,
):
    """
    Meneruskan query pencarian wilayah ke Biteship Maps Areas API.
    GET https://api.biteship.com/v1/maps/areas?countries=ID&input={query}&type=single
    Mengembalikan data area terstandarisasi lengkap dengan Biteship Area ID.
    """
    search_term = (query or q or input or "").strip()
    if not search_term or len(search_term) < 2:
        return {
            "success": True,
            "areas": [],
            "message": "Query pencarian minimal 2 karakter.",
        }

    import httpx
    from app.services.biteship_service import BITESHIP_API_URL, BITESHIP_API_KEY

    url = f"{BITESHIP_API_URL}/maps/areas"
    params = {
        "countries": "ID",
        "input": search_term,
        "type": "single",
    }
    headers = {
        "Authorization": f"Bearer {BITESHIP_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                raw_areas = data.get("areas", [])
                formatted = []
                for a in raw_areas:
                    formatted.append({
                        "id": a.get("id"),
                        "name": a.get("name"),
                        "postal_code": a.get("postal_code"),
                        "country_name": a.get("country_name", "Indonesia"),
                        "country_code": a.get("country_code", "ID"),
                        "administrative_division_level_1_name": a.get("administrative_division_level_1_name"),
                        "administrative_division_level_2_name": a.get("administrative_division_level_2_name"),
                        "administrative_division_level_3_name": a.get("administrative_division_level_3_name"),
                        "latitude": a.get("latitude"),
                        "longitude": a.get("longitude"),
                    })
                return {
                    "success": True,
                    "areas": formatted,
                    "count": len(formatted),
                }
            else:
                logger.warning(f"[Biteship Areas] HTTP {resp.status_code}: {resp.text}")
                return {
                    "success": False,
                    "areas": [],
                    "message": "Gagal menghubungi layanan pencarian area pengiriman.",
                }
    except Exception as exc:
        logger.error(f"[Biteship Areas Exception] {exc}")
        return {
            "success": False,
            "areas": [],
            "message": str(exc),
        }
