from typing import Dict, Any

class CommercePaymentService:
    @staticmethod
    async def verify_payment(order: Dict[str, Any], received_amount: int) -> bool:
        if received_amount >= order.get("amount", 0):
            order["status"] = "PAID"
            return True
        return False
