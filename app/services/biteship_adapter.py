import os
import aiohttp
from typing import List, Dict, Any, Optional
from app.services.shipping_interface import (
    BaseShippingProvider,
    ShippingRateItem,
    BookingRequest,
    BookingResponse,
    TrackingStatusResponse,
    CODSettlementCheckResponse
)

BITESHIP_API_URL = os.getenv("BITESHIP_BASE_URL", "https://api.biteship.com/v1")
BITESHIP_API_KEY = os.getenv("BITESHIP_API_KEY", "")

class BiteshipShippingAdapter(BaseShippingProvider):
    """Adapter resmi integrasi logistik via Biteship API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or BITESHIP_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_rates(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        weight_kg: float,
        is_cod: bool = False
    ) -> List[ShippingRateItem]:
        """Kalkulasi ongkir instan, sameday, dan kurir aktif lainnya."""
        url = f"{BITESHIP_API_URL}/rates/couriers"
        payload = {
            "origin_latitude": origin_lat,
            "origin_longitude": origin_lng,
            "destination_latitude": dest_lat,
            "destination_longitude": dest_lng,
            "items": [
                {
                    "name": "Barang Pengiriman",
                    "value": 100000,
                    "weight": int(weight_kg * 1000),  # Biteship membaca dalam gram
                    "quantity": 1
                }
            ]
        }

        if is_cod:
            payload["cash_on_delivery"] = True

        rates: List[ShippingRateItem] = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self.headers) as resp:
                    if resp.status != 200:
                        return rates
                    data = await resp.json()
                    
                    for item in data.get("pricing", []):
                        rates.append(
                            ShippingRateItem(
                                courier_name=item.get("courier_name", ""),
                                service_name=item.get("courier_service_name", ""),
                                service_type=item.get("type", "standard"),
                                cost=float(item.get("price", 0)),
                                estimated_delivery=item.get("shipment_duration_range", ""),
                                is_cod_supported=bool(item.get("available_for_cash_on_delivery", False))
                            )
                        )
            return rates
        except Exception as e:
            print(f"[BITESHIP ERROR] Gagal kalkulasi ongkir: {e}")
            return []

    async def create_booking(self, request: BookingRequest) -> BookingResponse:
        """Booking kurir instan/sameday/reguler dan terbitkan Order Delivery."""
        url = f"{BITESHIP_API_URL}/orders"

        payload: Dict[str, Any] = {
            "origin_contact_name": request.sender_name,
            "origin_contact_phone": request.sender_phone,
            "origin_address": request.sender_address,
            "destination_contact_name": request.recipient_name,
            "destination_contact_phone": request.recipient_phone,
            "destination_address": request.recipient_address,
            "courier_company": request.service_type.split("_")[0] if "_" in request.service_type else "grab",
            "courier_type": "instant",
            "delivery_type": "now",
            "items": [
                {
                    "name": request.item_description,
                    "value": int(request.item_value),
                    "weight": int(request.weight_kg * 1000),
                    "quantity": 1
                }
            ]
        }

        if request.sender_lat and request.sender_lng:
            payload["origin_coordinate"] = {
                "latitude": request.sender_lat,
                "longitude": request.sender_lng
            }

        if request.recipient_lat and request.recipient_lng:
            payload["destination_coordinate"] = {
                "latitude": request.recipient_lat,
                "longitude": request.recipient_lng
            }

        # Konfigurasi COD eksplisit
        if request.is_cod:
            payload["cash_on_delivery"] = {
                "amount": int(request.cod_amount),
                "fee": 0
            }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=self.headers) as resp:
                data = await resp.json()
                if resp.status in (200, 201) and data.get("success", True):
                    return BookingResponse(
                        success=True,
                        booking_id=data.get("id", ""),
                        tracking_number=data.get("courier", {}).get("tracking_id"),
                        provider="biteship",
                        shipping_cost=float(data.get("price", 0)),
                        raw_response=data
                    )
                else:
                    return BookingResponse(
                        success=False,
                        booking_id="",
                        tracking_number=None,
                        provider="biteship",
                        shipping_cost=0.0,
                        raw_response=data
                    )

    async def track_shipment(self, booking_id: str) -> TrackingStatusResponse:
        """Cek pergerakan kurir dan bukti serah terima (POD)."""
        url = f"{BITESHIP_API_URL}/orders/{booking_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                data = await resp.json()
                status_raw = data.get("status", "draft").lower()

                # Pemetaan status Biteship ke domain model internal
                status_map = {
                    "allocated": "ALLOCATING",
                    "picking_up": "ALLOCATING",
                    "picked": "PICKED_UP",
                    "dropping_off": "IN_TRANSIT",
                    "delivered": "DELIVERED",
                    "returned": "RETURNED",
                    "rejected": "FAILED",
                    "cancelled": "FAILED"
                }

                current_status = status_map.get(status_raw, "IN_TRANSIT")
                pod = data.get("proof_of_delivery", {})

                return TrackingStatusResponse(
                    tracking_number=data.get("courier", {}).get("tracking_id") or booking_id,
                    current_status=current_status,
                    pod_receiver_name=pod.get("received_by"),
                    pod_url=pod.get("link"),
                    updated_at=data.get("updated_at", "")
                )

    async def verify_cod_settlement(self, booking_id: str) -> CODSettlementCheckResponse:
        """
        Validasi settlement dana COD.
        Menjaga agar uang fisik benar-benar masuk ke saldo/rekening sebelum komisi dilepas.
        """
        url = f"{BITESHIP_API_URL}/orders/{booking_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as resp:
                data = await resp.json()
                cod_info = data.get("cash_on_delivery", {})
                
                # Biteship menandai uang disetor pada flag cash_on_delivery.status atau status settlement
                cod_status = cod_info.get("status", "").lower()
                is_settled = cod_status in ("settled", "transferred", "paid_to_merchant")

                return CODSettlementCheckResponse(
                    booking_id=booking_id,
                    is_settled=is_settled,
                    settled_amount=float(cod_info.get("amount", 0)),
                    settlement_date=cod_info.get("settlement_date"),
                    remittance_proof_id=cod_info.get("remittance_id")
                )