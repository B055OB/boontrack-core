"""app/payments/base_provider.py
Abstract Base Class / Interface for Payment Providers in BoonTrack Core.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple

from app.payments.schemas import (
    PaymentIntentCreate,
    WebhookEventPayload,
    PaymentStatus,
)


class BasePaymentProvider(ABC):
    """Abstract interface defining the contract for all payment providers in BoonTrack Core."""

    @abstractmethod
    async def generate_qr(
        self,
        intent: PaymentIntentCreate,
        unique_code: int,
    ) -> Tuple[str, str]:
        """Generates dynamic QR string and image URL for the requested payment intent.
        
        Returns:
            Tuple[str, str]: (qr_payload_string, qr_image_url)
        """
        pass

    @abstractmethod
    async def verify_webhook(
        self,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> WebhookEventPayload:
        """Verifies, authenticates, and normalizes an incoming provider webhook payload.
        
        Returns:
            WebhookEventPayload: Standardized mutation event.
        """
        pass

    @abstractmethod
    async def check_status(self, provider_ref: str) -> PaymentStatus:
        """Queries the provider upstream to check the current payment status."""
        pass

    @abstractmethod
    async def refund(
        self,
        provider_ref: str,
        amount: Optional[int] = None,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Requests a full or partial refund from the provider."""
        pass
