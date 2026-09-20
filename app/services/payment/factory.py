"""app/services/payment/factory.py
Payment Adapter Factory.
Resolves and instantiates appropriate PaymentAdapter based on TenantRuntimeContext metadata (payment_config).
"""

from typing import Optional, Dict, Any, Union
from app.schemas.context import TenantRuntimeContext
from app.services.payment.base import PaymentAdapter
from app.services.payment.manual_adapter import ManualTransferAdapter
from app.services.payment.gateway_duitku import DuitkuAdapter
from app.services.payment.gateway_xendit import XenditAdapter


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
        1. Menggunakan provider_override jika disediakan ('xendit' / 'duitku' / 'manual').
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

        mode = str(config.get("mode") or "").strip().upper()
        provider = str(provider_override or config.get("provider") or config.get("gateway") or "").strip().lower()

        # If explicitly set to MANUAL_TRANSFER or manual provider, route to ManualTransferAdapter
        if mode == "MANUAL_TRANSFER" or provider in ("manual", "manual_transfer", "bank_transfer"):
            return cls._resolve_manual_adapter(config)

        if provider in ("xendit", "qris_xendit", "xendit_qris", "xendit_invoice"):
            secret_key = config.get("secret_key") or config.get("api_key")
            callback_token = config.get("callback_token") or config.get("verification_token")
            is_sandbox = config.get("is_sandbox")
            if secret_key:
                return XenditAdapter(
                    secret_key=secret_key,
                    callback_token=callback_token,
                    is_sandbox=is_sandbox,
                )

        if provider in ("duitku", "gateway", "dynamic_qris"):
            merchant_code = (config.get("merchant_code") or "").strip()
            api_key = (config.get("api_key") or "").strip()
            callback_url = config.get("callback_url")
            return_url = config.get("return_url")
            is_sandbox = config.get("is_sandbox")
            # Only instantiate DuitkuAdapter if valid credentials exist
            if merchant_code and api_key:
                return DuitkuAdapter(
                    merchant_code=merchant_code,
                    api_key=api_key,
                    callback_url=callback_url,
                    return_url=return_url,
                    is_sandbox=is_sandbox,
                )

        # Fallback to manual transfer adapter
        return cls._resolve_manual_adapter(config)

    @classmethod
    def _resolve_manual_adapter(cls, config: Dict[str, Any]) -> ManualTransferAdapter:
        """Helper to construct ManualTransferAdapter from config or nested manual_config / bank_accounts."""
        manual_cfg = config.get("manual_config") if isinstance(config.get("manual_config"), dict) else {}
        bank_accounts = (
            config.get("bank_accounts")
            or manual_cfg.get("bank_accounts")
            or []
        )

        bank_name = config.get("bank_name") or manual_cfg.get("bank_name")
        account_number = config.get("account_number") or manual_cfg.get("account_number")
        account_holder = config.get("account_holder") or config.get("account_name") or manual_cfg.get("account_name") or manual_cfg.get("account_holder")
        qris_image_url = config.get("qris_image_url") or manual_cfg.get("qris_image_url")
        instructions = config.get("instructions") or manual_cfg.get("instructions")

        if bank_accounts and isinstance(bank_accounts, list) and len(bank_accounts) > 0:
            primary_acc = bank_accounts[0]
            if isinstance(primary_acc, dict):
                bank_name = bank_name or primary_acc.get("bank_name")
                account_number = account_number or primary_acc.get("account_number")
                account_holder = account_holder or primary_acc.get("account_holder") or primary_acc.get("account_name")

        return ManualTransferAdapter(
            bank_name=bank_name or "BCA",
            account_number=account_number or "1234567890",
            account_holder=account_holder or "Merchant Store",
            qris_image_url=qris_image_url,
            instructions=instructions,
        )
