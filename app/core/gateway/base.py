from abc import ABC, abstractmethod
from typing import Dict, Any

class WhatsAppGatewayInterface(ABC):
    
    # --- Session Management Capability ---
    @abstractmethod
    async def create_session(self, tenant_id: str, webhook_url: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def get_session_status(self, tenant_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def restart_session(self, tenant_id: str) -> bool:
        pass

    @abstractmethod
    async def delete_session(self, tenant_id: str) -> bool:
        pass

    # --- Messaging Capability ---
    @abstractmethod
    async def send_text_message(self, tenant_id: str, recipient: str, message: str, idempotency_key: str) -> Dict[str, Any]:
        pass