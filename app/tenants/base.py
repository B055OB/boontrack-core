"""app/tenants/base.py
Abstract / Base Interface for Multi-Tenant backend modules in BoonTrack Core.
"""

from abc import ABC, abstractmethod
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger("TENANT_BASE")


class BaseTenantService(ABC):
    """Abstract Base Class for Multi-Tenant Services.

    Each tenant module (e.g. Om Budi, Career, Gym, or B2G Pilots)
    inherits from this class and implements the standardized interface
    for message handling and status reporting.
    """

    tenant_id: str = "base"
    tenant_name: str = "Base Tenant"

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        tenant_name: Optional[str] = None
    ) -> None:
        if tenant_id:
            self.tenant_id = tenant_id
        if tenant_name:
            self.tenant_name = tenant_name

    def clean_phone(self, phone: str) -> str:
        """Utility helper to normalize phone numbers to digits only."""
        return re.sub(r"\D", "", str(phone or ""))

    def get_info(self) -> Dict[str, Any]:
        """Return basic metadata regarding the tenant service."""
        return {
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "is_active": True,
        }

    @abstractmethod
    async def handle_incoming_message(
        self,
        phone_number: str,
        message_text: str,
        media_url: Optional[str] = None,
        media_type: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Process incoming chat/webhook messages for this tenant.

        Args:
            phone_number: Sanitized or raw phone number of sender.
            message_text: Text content of incoming user message.
            media_url: Optional media URL or asset identifier.
            media_type: Optional media type (e.g. image, document, audio).
            **kwargs: Tenant-specific extra parameters (e.g. button_id, user_name).

        Returns:
            Dict containing response metadata, such as:
            {"reply": str, "type": "text"|"buttons"|"image", ...}
        """
        raise NotImplementedError("Subclasses must implement handle_incoming_message")
