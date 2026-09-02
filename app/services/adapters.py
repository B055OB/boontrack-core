import os
import httpx
from typing import Dict, Any
from app.services.interfaces import NotificationService, PaymentService, ShippingService

class WhatsAppAdapter(NotificationService):
    def __init__(self):
        self.evolution_url = os.getenv("EVOLUTION_API_URL", "http://localhost:8080").strip()
        self.api_key = os.getenv("EVOLUTION_API_KEY", "").strip()

    async def send_message(self, tenant_id: str, to_phone: str, message: str) -> Dict[str, Any]:
        url = f"{self.evolution_url}/message/sendText/{tenant_id}"
        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        payload = {
            "number": to_phone,
            "options": {"delay": 1200, "presence": "composing"},
            "textMessage": {"text": message}
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(url, headers=headers, json=payload)
                return res.json()
            except Exception as e:
                return {"success": False, "error": str(e)}

class XenditAdapter(PaymentService):
    def __init__(self):
        self.secret_key = os.getenv("XENDIT_SECRET_KEY", "").strip()

    async def create_qris_invoice(self, tenant_id: str, amount: int, order_id: str, customer_info: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "provider": "XENDIT",
            "invoice_url": f"https://checkout.xendit.co/web/{order_id}",
            "amount": amount,
            "tenant_id": tenant_id
        }

class KiriminAjaAdapter(ShippingService):
    def __init__(self):
        self.api_key = os.getenv("KIRIMINAJA_API_KEY", "").strip()

    async def get_rates(self, origin: str, destination: str, weight: int) -> Dict[str, Any]:
        return {
            "success": True,
            "provider": "KIRIMINAJA",
            "origin": origin,
            "destination": destination,
            "rates": []
        }