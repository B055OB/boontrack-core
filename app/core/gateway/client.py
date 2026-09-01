import httpx
from typing import Dict, Any
from .base import WhatsAppGatewayInterface
# Asumsi konfigurasi Pydantic BaseSettings atau os.getenv
from core.config import settings 

class HttpWhatsAppGatewayClient(WhatsAppGatewayInterface):
    def __init__(self):
        self.gateway_base_url = settings.WA_GATEWAY_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.WA_GATEWAY_INTERNAL_API_KEY}",
            "Content-Type": "application/json"
        }

    async def create_session(self, tenant_id: str, webhook_url: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.gateway_base_url}/api/v1/sessions",
                json={"tenant_id": tenant_id, "webhook_url": webhook_url},
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def get_session_status(self, tenant_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.gateway_base_url}/api/v1/sessions/{tenant_id}/status",
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()

    async def restart_session(self, tenant_id: str) -> bool:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.gateway_base_url}/api/v1/sessions/{tenant_id}/restart",
                headers=self.headers
            )
            return response.status_code == 200

    async def delete_session(self, tenant_id: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.delete(
                f"{self.gateway_base_url}/api/v1/sessions/{tenant_id}",
                headers=self.headers
            )
            return response.status_code == 200

    async def send_text_message(self, tenant_id: str, recipient: str, message: str, idempotency_key: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self.gateway_base_url}/api/v1/messages/send",
                json={
                    "tenant_id": tenant_id,
                    "recipient": recipient,
                    "message": message,
                    "idempotency_key": idempotency_key
                },
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()