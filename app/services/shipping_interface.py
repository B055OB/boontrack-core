from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

class ShippingRateItem(BaseModel):
    courier_name: str
    service_name: str
    service_type: str  # instant, sameday, standard
    cost: float
    estimated_delivery: str
    is_cod_supported: bool

class BookingRequest(BaseModel):
    tenant_id: str
    order_id: str
    service_type: str
    is_cod: bool
    cod_amount: float
    sender_name: str
    sender_phone: str
    sender_address: str
    sender_lat: Optional[float] = None
    sender_lng: Optional[float] = None
    recipient_name: str
    recipient_phone: str
    recipient_address: str
    recipient_lat: Optional[float] = None
    recipient_lng: Optional[float] = None
    item_description: str
    item_value: float
    weight_kg: float

class BookingResponse(BaseModel):
    success: bool
    booking_id: str
    tracking_number: Optional[str] = None
    provider: str
    shipping_cost: float
    raw_response: Dict[str, Any]

class TrackingStatusResponse(BaseModel):
    tracking_number: str
    current_status: str  # DRAFT, ALLOCATING, PICKED_UP, IN_TRANSIT, DELIVERED, RETURNED
    pod_receiver_name: Optional[str] = None
    pod_url: Optional[str] = None
    updated_at: str

class CODSettlementCheckResponse(BaseModel):
    booking_id: str
    is_settled: bool
    settled_amount: float
    settlement_date: Optional[str] = None
    remittance_proof_id: Optional[str] = None


class BaseShippingProvider(ABC):
    """Abstract Interface generic untuk seluruh provider ekspedisi/kurir instan."""

    @abstractmethod
    async def get_rates(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        weight_kg: float,
        is_cod: bool = False
    ) -> List[ShippingRateItem]:
        """Kalkulasi ongkir ke destinasi."""
        pass

    @abstractmethod
    async def create_booking(self, request: BookingRequest) -> BookingResponse:
        """Booking kurir dan generate delivery order / AWB."""
        pass

    @abstractmethod
    async def track_shipment(self, booking_id: str) -> TrackingStatusResponse:
        """Cek status pengiriman realtime dan bukti serah terima (POD)."""
        pass

    @abstractmethod
    async def verify_cod_settlement(self, booking_id: str) -> CODSettlementCheckResponse:
        """Verifikasi apakah uang cash COD sudah tervalidasi dan disetor oleh ekspedisi."""
        pass