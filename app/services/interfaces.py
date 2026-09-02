from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class NotificationService(ABC):
    @abstractmethod
    async def send_message(self, tenant_id: str, to_phone: str, message: str) -> Dict[str, Any]:
        """Kirim notifikasi pesan keluar tanpa hardcode vendor."""
        pass

class PaymentService(ABC):
    @abstractmethod
    async def create_qris_invoice(self, tenant_id: str, amount: int, order_id: str, customer_info: Dict[str, Any]) -> Dict[str, Any]:
        """Generate transaksi QRIS terisolasi per tenant."""
        pass

class ShippingService(ABC):
    @abstractmethod
    async def get_rates(self, origin: str, destination: str, weight: int) -> Dict[str, Any]:
        """Contract awal boundary Shipping Orchestrator."""
        pass