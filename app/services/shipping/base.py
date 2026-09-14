"""app/services/shipping/base.py
Abstract Base Class & Standardized Data Contracts for Shipping Adapters.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class RateRequest(BaseModel):
    origin_postal_code: str = Field(..., description="Sender/Warehouse 5-digit postal code")
    destination_postal_code: str = Field(..., description="Buyer/Destination 5-digit postal code")
    origin_latitude: Optional[float] = Field(None, description="Sender latitude for instant delivery")
    origin_longitude: Optional[float] = Field(None, description="Sender longitude for instant delivery")
    destination_latitude: Optional[float] = Field(None, description="Recipient latitude for instant delivery")
    destination_longitude: Optional[float] = Field(None, description="Recipient longitude for instant delivery")
    items: List[Dict[str, Any]] = Field(default_factory=list, description="List of items with name, value, weight (grams), quantity")
    couriers: Optional[List[str]] = Field(None, description="Filter for specific courier codes (e.g. ['gosend', 'grab', 'jne'])")


class RateOption(BaseModel):
    courier_name: str = Field(..., description="Display name of courier (e.g. GoSend, JNE)")
    courier_code: str = Field(..., description="System courier code (e.g. gosend, grab, jne, sicepat)")
    service_name: str = Field(..., description="Service tier (e.g. Instant, Same Day, Regular)")
    service_type: str = Field(..., description="Standardized type: instant, same_day, standard, express")
    rate: int = Field(..., description="Shipping cost in IDR (integer)")
    etd: str = Field(..., description="Estimated delivery time range (e.g. '1 - 2 Jam', '2 - 3 Hari')")
    description: Optional[str] = Field(None, description="Service description")
    is_cod: bool = Field(False, description="Whether Cash on Delivery is supported")


class ShipmentRequest(BaseModel):
    order_id: str = Field(..., description="Unique merchant order ID")
    courier_code: str = Field(..., description="Courier code (e.g. gosend, jne)")
    service_type: str = Field(..., description="Service code (e.g. instant, reg)")
    origin_name: str = Field(..., description="Sender contact name")
    origin_phone: str = Field(..., description="Sender contact phone")
    origin_address: str = Field(..., description="Sender full address")
    origin_postal_code: str = Field(..., description="Sender postal code")
    destination_name: str = Field(..., description="Recipient contact name")
    destination_phone: str = Field(..., description="Recipient contact phone")
    destination_address: str = Field(..., description="Recipient full address")
    destination_postal_code: str = Field(..., description="Recipient postal code")
    items: List[Dict[str, Any]] = Field(default_factory=list, description="Items shipped")
    is_cod: bool = Field(False, description="Whether this is a COD order")
    cod_amount: Optional[int] = Field(None, description="COD collection amount if COD")
    notes: Optional[str] = Field(None, description="Driver pickup notes")


class ShipmentResponse(BaseModel):
    shipment_id: str = Field(..., description="Provider internal shipment/order ID")
    tracking_number: Optional[str] = Field(None, description="Airwaybill or Waybill tracking number")
    courier_code: str = Field(..., description="Courier code assigned")
    service_name: str = Field(..., description="Service level")
    status: str = Field(..., description="Current status: ALLOCATING, PICKED_UP, IN_TRANSIT, DELIVERED, CONFIRMED")
    shipping_cost: int = Field(..., description="Final shipping fee charged")
    raw_response: Optional[Dict[str, Any]] = Field(default=None, description="Raw provider payload")


class TrackingResponse(BaseModel):
    tracking_number: str = Field(..., description="Airwaybill tracking number")
    courier_code: str = Field(..., description="Courier code")
    status: str = Field(..., description="Status: ALLOCATING, PICKED_UP, IN_TRANSIT, DELIVERED, RETURNED, CANCELLED")
    status_description: str = Field(..., description="Human-readable status summary")
    history: List[Dict[str, Any]] = Field(default_factory=list, description="Timeline of tracking events")
    raw_response: Optional[Dict[str, Any]] = Field(default=None, description="Raw tracking response")


class ShippingAdapter(ABC):
    """Abstract interface for all Shipping & Logistics Adapters in BoonTrack Core."""

    @abstractmethod
    async def calculate_rates(self, request: RateRequest) -> List[RateOption]:
        """Calculates available courier rates (instant and regular/standard)."""
        pass

    @abstractmethod
    async def create_shipment(self, request: ShipmentRequest) -> ShipmentResponse:
        """Books a shipment and retrieves the airwaybill / booking confirmation."""
        pass

    @abstractmethod
    async def track_airwaybill(
        self,
        airwaybill_number: str,
        courier_code: Optional[str] = None
    ) -> TrackingResponse:
        """Tracks the current location and delivery status of an airwaybill."""
        pass
