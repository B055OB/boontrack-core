import os
import logging
import httpx
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("BITESHIP_SERVICE")

# Default Origin Warehouse (Margahayu Raya, Bandung)
ORIGIN_WAREHOUSE = {
    "address": "Jl Pluto Selatan 2 no 41 Margahayu Raya Margacinta Buahbatu Bandung",
    "postal_code": 40286,
    "contact_name": "Aldi Rinaldiawan",
    "contact_phone": "081237450222",
    "area": "Margasari, Buahbatu, Bandung"
}

BITESHIP_API_URL = os.getenv("BITESHIP_BASE_URL", "https://api.biteship.com/v1").rstrip("/")
BITESHIP_API_KEY = os.getenv(
    "BITESHIP_API_KEY",
    "biteship_test.eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJuYW1lIjoiQm9vblRyYWNrIiwidXNlcklkIjoiNmE5YjA3YTdiNDQ3MTUwZTRmZmI2NmVlIiwiaWF0IjoxNzg4NTQ1NTAzfQ.qS6VLuexwjiG9TqN8dpxOYn4IKVBcGjljMNWjeYnMqE"
)

# Allowed instant & sameday couriers
ALLOWED_SERVICES = {
    "gosend": ["instant", "same_day", "sameday"],
    "grab": ["instant", "same_day", "sameday"]
}

# Standard status event mapping for Biteship Logistics Lifecycle
STATUS_EVENT_MAPPING: Dict[str, str] = {
    # 1. ORDER_CREATED
    "order.created": "ORDER_CREATED",
    "order_created": "ORDER_CREATED",
    "created": "ORDER_CREATED",
    "draft": "ORDER_CREATED",
    "placed": "ORDER_CREATED",

    # 2. ALLOCATED
    "order.allocated": "ALLOCATED",
    "allocated": "ALLOCATED",
    "courier_allocated": "ALLOCATED",
    "confirmed": "ALLOCATED",

    # 3. PICKING_UP
    "order.picking_up": "PICKING_UP",
    "picking_up": "PICKING_UP",
    "order.picked": "PICKING_UP",
    "picked": "PICKING_UP",
    "picked_up": "PICKING_UP",

    # 4. DROPPING_OFF
    "order.dropping_off": "DROPPING_OFF",
    "dropping_off": "DROPPING_OFF",
    "in_transit": "DROPPING_OFF",
    "on_delivery": "DROPPING_OFF",

    # 5. DELIVERED / COD_COLLECTED
    "order.delivered": "DELIVERED",
    "delivered": "DELIVERED",
    "completed": "DELIVERED",
    "cod_collected": "COD_COLLECTED",
    "order.cod_collected": "COD_COLLECTED",
    "cod_settled": "COD_COLLECTED",
    "cash_collected": "COD_COLLECTED",
}


def map_biteship_event_status(
    event_or_status: str,
    is_cod: bool = False,
    raw_data: Optional[Dict[str, Any]] = None
) -> str:
    """Memetakan status event dari Biteship webhook ke standar status order internal:
    ORDER_CREATED -> ALLOCATED -> PICKING_UP -> DROPPING_OFF -> DELIVERED / COD_COLLECTED
    """
    clean = str(event_or_status or "").strip().lower()
    raw_status = (raw_data.get("status") if isinstance(raw_data, dict) else "") or ""
    clean_raw = str(raw_status).strip().lower()

    if clean in ("cod_collected", "cod_settled", "cash_collected", "order.cod_collected") or clean_raw in ("cod_collected", "cod_settled", "cash_collected"):
        return "COD_COLLECTED"

    mapped = STATUS_EVENT_MAPPING.get(clean) or STATUS_EVENT_MAPPING.get(clean_raw)

    if mapped == "DELIVERED":
        if is_cod:
            return "COD_COLLECTED"
        if isinstance(raw_data, dict):
            cod_obj = raw_data.get("cash_on_delivery") or {}
            if isinstance(cod_obj, dict) and cod_obj.get("amount", 0) > 0:
                return "COD_COLLECTED"
        return "DELIVERED"

    return mapped or "ORDER_CREATED"


def _get_mock_instant_rates(destination_postal_code: str) -> List[Dict[str, Any]]:
    """Mock rates fallback for Sandbox testing or when balance is insufficient."""
    logger.info(f"[BITESHIP MOCK] Providing sandbox instant rates for destination {destination_postal_code}")
    return [
        {
            "courier_name": "GoSend",
            "courier_code": "gosend",
            "service_type": "instant",
            "service_name": "Instant",
            "category": "instant",
            "price": 20000,
            "etd": "1 - 2 hours",
            "description": "Pengiriman kilat instan GoSend 1-2 jam",
            "is_cod_supported": False,
        },
        {
            "courier_name": "GoSend",
            "courier_code": "gosend",
            "service_type": "same_day",
            "service_name": "Same Day",
            "category": "sameday",
            "price": 14000,
            "etd": "6 - 8 hours",
            "description": "Pengiriman ekonomis hari yang sama GoSend",
            "is_cod_supported": False,
        },
        {
            "courier_name": "Grab",
            "courier_code": "grab",
            "service_type": "instant",
            "service_name": "Instant",
            "category": "instant",
            "price": 22000,
            "etd": "1 - 2 hours",
            "description": "Pengiriman kilat instan GrabExpress 1-2 jam",
            "is_cod_supported": False,
        },
        {
            "courier_name": "Grab",
            "courier_code": "grab",
            "service_type": "same_day",
            "service_name": "Same Day",
            "category": "sameday",
            "price": 15000,
            "etd": "6 - 8 hours",
            "description": "Pengiriman hari yang sama GrabExpress",
            "is_cod_supported": False,
        }
    ]


def _get_mock_all_rates(destination_postal_code: str) -> List[Dict[str, Any]]:
    """Mock rates lengkap untuk seluruh kategori kurir (Instant, Sameday, Reguler, Kargo, COD)."""
    return [
        # Instant
        {
            "courier_name": "GoSend",
            "courier_code": "gosend",
            "service_type": "instant",
            "service_name": "Instant",
            "category": "instant",
            "price": 20000,
            "etd": "1 - 2 hours",
            "description": "Pengiriman kilat instan GoSend 1-2 jam",
            "is_cod_supported": False,
        },
        {
            "courier_name": "Grab",
            "courier_code": "grab",
            "service_type": "instant",
            "service_name": "Instant",
            "category": "instant",
            "price": 22000,
            "etd": "1 - 2 hours",
            "description": "Pengiriman kilat instan GrabExpress 1-2 jam",
            "is_cod_supported": False,
        },
        # Sameday
        {
            "courier_name": "GoSend",
            "courier_code": "gosend",
            "service_type": "same_day",
            "service_name": "Same Day",
            "category": "sameday",
            "price": 14000,
            "etd": "6 - 8 hours",
            "description": "Pengiriman ekonomis hari yang sama GoSend",
            "is_cod_supported": False,
        },
        {
            "courier_name": "Grab",
            "courier_code": "grab",
            "service_type": "same_day",
            "service_name": "Same Day",
            "category": "sameday",
            "price": 15000,
            "etd": "6 - 8 hours",
            "description": "Pengiriman hari yang sama GrabExpress",
            "is_cod_supported": False,
        },
        # Reguler
        {
            "courier_name": "JNE",
            "courier_code": "jne",
            "service_type": "reguler",
            "service_name": "REG",
            "category": "reguler",
            "price": 11000,
            "etd": "1 - 2 days",
            "description": "Layanan JNE Reguler 1-2 hari kerja",
            "is_cod_supported": True,
        },
        {
            "courier_name": "SiCepat",
            "courier_code": "sicepat",
            "service_type": "reguler",
            "service_name": "REG",
            "category": "reguler",
            "price": 10000,
            "etd": "1 - 2 days",
            "description": "SiCepat Regular Kilat",
            "is_cod_supported": True,
        },
        {
            "courier_name": "J&T",
            "courier_code": "jnt",
            "service_type": "reguler",
            "service_name": "EZ",
            "category": "reguler",
            "price": 12000,
            "etd": "1 - 2 days",
            "description": "J&T Express Reguler",
            "is_cod_supported": True,
        },
        # Kargo
        {
            "courier_name": "JNE",
            "courier_code": "jne",
            "service_type": "kargo",
            "service_name": "JTR (Trucking)",
            "category": "kargo",
            "price": 25000,
            "etd": "3 - 5 days",
            "description": "JNE Trucking Kargo paket besar/berat",
            "is_cod_supported": False,
        },
        {
            "courier_name": "SiCepat",
            "courier_code": "sicepat",
            "service_type": "kargo",
            "service_name": "GOKIL (Kargo)",
            "category": "kargo",
            "price": 24000,
            "etd": "3 - 4 days",
            "description": "SiCepat Cargo Kilat ekonomis",
            "is_cod_supported": False,
        },
    ]


async def get_all_shipping_rates(
    destination_postal_code: str,
    items: list,
    destination_area: Optional[str] = None,
    destination_lat: Optional[float] = None,
    destination_lng: Optional[float] = None,
    is_cod: bool = False,
    couriers: Optional[str] = None,
) -> Dict[str, Any]:
    """Kalkulasi tarif kurir lengkap (Instant, Sameday, Reguler, Kargo, COD) via Biteship API.
    
    Returns:
        Dict dengan key:
        - rates: List seluruh opsi kurir terfilter
        - grouped: Dict kurir dikelompokkan per kategori ('instant', 'sameday', 'reguler', 'kargo', 'cod')
        - origin: Data warehouse pengirim
        - destination_postal_code: Kode pos tujuan
    """
    url = f"{BITESHIP_API_URL}/rates/couriers"
    headers = {
        "Authorization": f"Bearer {BITESHIP_API_KEY}",
        "Content-Type": "application/json"
    }

    formatted_items = []
    if items and isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                formatted_items.append({
                    "name": str(it.get("name", "Produk Pengiriman")),
                    "description": str(it.get("description", "")),
                    "value": int(it.get("value", 50000)),
                    "weight": int(it.get("weight", 1000)),
                    "quantity": int(it.get("quantity", 1))
                })

    if not formatted_items:
        formatted_items = [{
            "name": "BoonTrack Merchandise",
            "value": 50000,
            "weight": 1000,
            "quantity": 1
        }]

    dest_postal_str = str(destination_postal_code).strip()
    dest_postal = int(dest_postal_str) if dest_postal_str.isdigit() else dest_postal_str

    payload: Dict[str, Any] = {
        "origin_postal_code": ORIGIN_WAREHOUSE["postal_code"],
        "destination_postal_code": dest_postal,
        "items": formatted_items
    }

    if couriers:
        payload["couriers"] = couriers

    if destination_area:
        payload["destination_area"] = destination_area
    if destination_lat and destination_lng:
        payload["destination_latitude"] = destination_lat
        payload["destination_longitude"] = destination_lng

    if is_cod:
        payload["cash_on_delivery"] = True

    all_rates: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                data = response.json()
                pricing_list = data.get("pricing", [])

                for item in pricing_list:
                    company = str(item.get("company") or item.get("courier_code") or "").lower()
                    raw_type = str(item.get("type") or item.get("service_type") or item.get("courier_service_code") or "").lower()
                    courier_display = item.get("courier_name") or company.upper()
                    service_display = item.get("courier_service_name") or raw_type.title()

                    # Kategorisasi tier kurir
                    category = "reguler"
                    if "instant" in raw_type:
                        category = "instant"
                    elif "same" in raw_type or "sameday" in raw_type:
                        category = "sameday"
                    elif "cargo" in raw_type or "kargo" in raw_type or "trucking" in raw_type or "gokil" in raw_type:
                        category = "kargo"

                    duration = item.get("duration") or item.get("shipment_duration_range") or "1 - 3 days"
                    if item.get("shipment_duration_unit") and item.get("shipment_duration_range"):
                        duration = f"{item.get('shipment_duration_range')} {item.get('shipment_duration_unit')}"

                    desc = item.get("description") or f"Layanan {service_display} {courier_display}"
                    price_val = int(item.get("price", 0))
                    cod_supported = bool(item.get("available_for_cash_on_delivery", False))

                    all_rates.append({
                        "courier_name": courier_display,
                        "courier_code": company,
                        "service_type": raw_type,
                        "service_name": service_display,
                        "category": category,
                        "price": price_val,
                        "etd": str(duration),
                        "description": desc,
                        "is_cod_supported": cod_supported,
                    })

    except Exception as exc:
        logger.error(f"[BITESHIP ALL RATES EXCEPTION] Error contacting Biteship API: {exc}")

    if not all_rates:
        all_rates = _get_mock_all_rates(dest_postal_str)

    # Kelompokkan rates per kategori
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "instant": [r for r in all_rates if r.get("category") == "instant"],
        "sameday": [r for r in all_rates if r.get("category") == "sameday"],
        "reguler": [r for r in all_rates if r.get("category") == "reguler"],
        "kargo": [r for r in all_rates if r.get("category") == "kargo"],
        "cod": [r for r in all_rates if r.get("is_cod_supported") is True],
    }

    return {
        "success": True,
        "origin": ORIGIN_WAREHOUSE,
        "destination_postal_code": dest_postal_str,
        "rates": all_rates,
        "grouped": grouped,
    }


async def get_instant_rates(
    destination_postal_code: str,
    items: list,
    destination_area: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Kalkulasi ongkos kirim kurir instan dan sameday (GoSend & Grab) via Biteship API."""
    res = await get_all_shipping_rates(
        destination_postal_code=destination_postal_code,
        items=items,
        destination_area=destination_area,
        couriers="gosend,grab"
    )
    grouped = res.get("grouped", {})
    instant_and_sameday = grouped.get("instant", []) + grouped.get("sameday", [])
    if instant_and_sameday:
        return instant_and_sameday
    return _get_mock_instant_rates(str(destination_postal_code))


class BiteshipService:
    """Service wrapper class for Biteship integrations."""
    origin_warehouse = ORIGIN_WAREHOUSE

    @classmethod
    async def get_instant_rates(
        cls,
        destination_postal_code: str,
        items: list,
        destination_area: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        return await get_instant_rates(
            destination_postal_code=destination_postal_code,
            items=items,
            destination_area=destination_area
        )

    @classmethod
    async def get_all_rates(
        cls,
        destination_postal_code: str,
        items: list,
        destination_area: Optional[str] = None,
        is_cod: bool = False,
    ) -> Dict[str, Any]:
        return await get_all_shipping_rates(
            destination_postal_code=destination_postal_code,
            items=items,
            destination_area=destination_area,
            is_cod=is_cod,
        )

    @classmethod
    def map_event_status(cls, event_or_status: str, is_cod: bool = False, raw_data: Optional[Dict[str, Any]] = None) -> str:
        return map_biteship_event_status(event_or_status, is_cod=is_cod, raw_data=raw_data)
