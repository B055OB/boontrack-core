"""app/services/shipping package.
Standardized shipping & logistics adapter engine and multi-courier aggregator for BoonTrack Core.
"""

from app.services.shipping.base import (
    ShippingAdapter,
    RateRequest,
    RateOption,
    ShipmentRequest,
    ShipmentResponse,
    TrackingResponse,
)
from app.services.shipping.biteship import BiteshipAdapter
from app.services.shipping.factory import ShippingAdapterFactory

__all__ = [
    "ShippingAdapter",
    "RateRequest",
    "RateOption",
    "ShipmentRequest",
    "ShipmentResponse",
    "TrackingResponse",
    "BiteshipAdapter",
    "ShippingAdapterFactory",
]
