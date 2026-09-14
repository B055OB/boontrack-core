"""app/services/payment/factory.py
Payment Adapter Factory.
Resolves and instantiates appropriate PaymentAdapter based on TenantRuntimeContext metadata (payment_config).
"""

from typing import Optional, Dict, Any, Union
from app.schemas.context import TenantRuntimeContext
from app.services.payment.base import PaymentAdapter
from app.services.payment.manual_adapter import ManualTransferAdapter
from app.services.payment.gateway_duitku import DuitkuAdapter


class PaymentAdapterFactory:
    """Factory resolver untuk membuat instance PaymentAdapter sesuai konfigurasi tenant."""

    @classmethod
    def resolve(
        cls,
        context_or_config: Union[TenantRuntimeContext, Dict[str, Any], None] = None,
        provider_override: Optional[str] = None,
    ) -> PaymentAdapter:
        """
        Menentukan adapter pembayaran:
        1. Menggunakan provider_override jika disediakan ('duitku' / 'manual').
        2. Membaca context.metadata.payment_config jika context_or_config adalah TenantRuntimeContext.
        3. Membaca dict config langsung jika context_or_config adalah dict.
        4. Fallback ke ManualTransferAdapter jika tidak ada konfigurasi payment gateway khusus.
        """
        config: Dict[str, Any] = {}

        if isinstance(context_or_config, TenantRuntimeContext):
            meta = getattr(context_or_config, "metadata", {}) or {}
            config = meta.get("payment_config") or {}
        elif isinstance(context_or_config, dict):
            config = context_or_config.get("payment_config") or context_or_config

        provider = str(provider_override or config.get("provider") or config.get("gateway") or "").strip().lower()

        if provider in ("duitku", "gateway", "dynamic_qris"):
            merchant_code = config.get("merchant_code")
            api_key = config.get("api_key")
            callback_url = config.get("callback_url")
            return_url = config.get("return_url")
            is_sandbox = config.get("is_sandbox")
            return DuitkuAdapter(
                merchant_code=merchant_code,
                api_key=api_key,
                callback_url=callback_url,
                return_url=return_url,
                is_sandbox=is_sandbox,
            )

        # Default / manual transfer adapter
        bank_name = config.get("bank_name") or "BCA"
        account_number = config.get("account_number") or "1234567890"
        account_holder = config.get("account_holder") or "Merchant Store"
        qris_image_url = config.get("qris_image_url")
        instructions = config.get("instructions")

        return ManualTransferAdapter(
            bank_name=bank_name,
            account_number=account_number,
            account_holder=account_holder,
            qris_image_url=qris_image_url,
            instructions=instructions,
        )
