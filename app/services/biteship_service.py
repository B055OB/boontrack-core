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


def _get_mock_instant_rates(destination_postal_code: str) -> List[Dict[str, Any]]:
    """Mock rates fallback for Sandbox testing or when balance is insufficient."""
    logger.info(f"[BITESHIP MOCK] Providing sandbox instant rates for destination {destination_postal_code}")
    return [
        {
            "courier_name": "GoSend",
            "service_type": "instant",
            "service_name": "Instant",
            "price": 20000,
            "etd": "1 - 2 hours",
            "description": "Pengiriman kilat instan GoSend 1-2 jam"
        },
        {
            "courier_name": "GoSend",
            "service_type": "same_day",
            "service_name": "Same Day",
            "price": 14000,
            "etd": "6 - 8 hours",
            "description": "Pengiriman ekonomis hari yang sama GoSend"
        },
        {
            "courier_name": "Grab",
            "service_type": "instant",
            "service_name": "Instant",
            "price": 22000,
            "etd": "1 - 2 hours",
            "description": "Pengiriman kilat instan GrabExpress 1-2 jam"
        },
        {
            "courier_name": "Grab",
            "service_type": "same_day",
            "service_name": "Same Day",
            "price": 15000,
            "etd": "6 - 8 hours",
            "description": "Pengiriman hari yang sama GrabExpress"
        }
    ]


async def get_instant_rates(
    destination_postal_code: str,
    items: list,
    destination_area: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Kalkulasi ongkos kirim kurir instan dan sameday (GoSend & Grab) via Biteship API.
    
    Args:
        destination_postal_code: Kode pos penerima (misal: "40287")
        items: Daftar barang pengiriman [{name, value, weight, quantity, ...}]
        destination_area: Area tujuan (opsional)
        
    Returns:
        List objek: [{courier_name, service_type, service_name, price, etd, description}]
    """
    url = f"{BITESHIP_API_URL}/rates/couriers"
    headers = {
        "Authorization": f"Bearer {BITESHIP_API_KEY}",
        "Content-Type": "application/json"
    }

    # Format items to meet Biteship specification
    formatted_items = []
    if items and isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                formatted_items.append({
                    "name": str(it.get("name", "Produk Pengiriman")),
                    "description": str(it.get("description", "")),
                    "value": int(it.get("value", 50000)),
                    "weight": int(it.get("weight", 1000)),  # in grams
                    "quantity": int(it.get("quantity", 1))
                })
    
    if not formatted_items:
        formatted_items = [{
            "name": "BoonTrack Merchandise",
            "value": 50000,
            "weight": 1000,
            "quantity": 1
        }]

    # Clean destination postal code
    dest_postal_str = str(destination_postal_code).strip()
    dest_postal = int(dest_postal_str) if dest_postal_str.isdigit() else dest_postal_str

    payload: Dict[str, Any] = {
        "origin_postal_code": ORIGIN_WAREHOUSE["postal_code"],
        "destination_postal_code": dest_postal,
        "couriers": "gosend,grab",
        "items": formatted_items
    }

    if destination_area:
        payload["destination_area"] = destination_area

    logger.info(
        f"[BITESHIP RATE REQUEST] Querying rates from {ORIGIN_WAREHOUSE['postal_code']} "
        f"to {dest_postal} for couriers 'gosend,grab'..."
    )

    filtered_rates: List[Dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            
            logger.info(f"[BITESHIP RESPONSE] Status {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                pricing_list = data.get("pricing", [])
                
                for item in pricing_list:
                    company = str(item.get("company") or item.get("courier_code") or "").lower()
                    raw_type = str(item.get("type") or item.get("service_type") or item.get("courier_service_code") or "").lower()
                    
                    # Normalize service_type to standard 'instant' or 'same_day'
                    norm_service_type = None
                    if "instant" in raw_type:
                        norm_service_type = "instant"
                    elif "same" in raw_type:
                        norm_service_type = "same_day"
                        
                    # Filter only GoSend & Grab for instant / same_day
                    if company in ALLOWED_SERVICES and norm_service_type in ["instant", "same_day"]:
                        courier_display = item.get("courier_name") or ("GoSend" if company == "gosend" else "Grab")
                        service_display = item.get("courier_service_name") or ("Instant" if norm_service_type == "instant" else "Same Day")
                        
                        duration = item.get("duration") or item.get("shipment_duration_range") or ("1 - 2 hours" if norm_service_type == "instant" else "6 - 8 hours")
                        if item.get("shipment_duration_unit") and item.get("shipment_duration_range"):
                            duration = f"{item.get('shipment_duration_range')} {item.get('shipment_duration_unit')}"
                            
                        desc = item.get("description") or f"Layanan {service_display} {courier_display}"
                        price_val = int(item.get("price", 0))

                        filtered_rates.append({
                            "courier_name": courier_display,
                            "service_type": norm_service_type,
                            "service_name": service_display,
                            "price": price_val,
                            "etd": str(duration),
                            "description": desc
                        })

                if filtered_rates:
                    logger.info(f"[BITESHIP SUCCESS] Found {len(filtered_rates)} matching instant/sameday rates.")
                    return filtered_rates
            else:
                logger.warning(
                    f"[BITESHIP NON-200] Code: {response.status_code} Body: {response.text}"
                )

    except Exception as exc:
        logger.error(f"[BITESHIP EXCEPTION] Error contacting Biteship API: {exc}")

    # Fallback to sandbox mock rates if API failed, balance was 0, or couriers unavailable
    return _get_mock_instant_rates(dest_postal_str)


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
