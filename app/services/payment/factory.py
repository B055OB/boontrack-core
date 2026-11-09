"""app/services/payment/factory.py
Payment Adapter Factory.
Resolves and instantiates appropriate PaymentAdapter based on TenantRuntimeContext metadata (payment_config).
Fails closed with PaymentConfigurationError on missing config, unknown provider, dummy accounts, or disabled Direct Tenant Rail.
"""

from typing import Optional, Dict, Any, Union
from app.schemas.context import TenantRuntimeContext
from app.services.payment.base import PaymentAdapter, PaymentConfigurationError
from app.services.payment.manual_adapter import ManualTransferAdapter
from app.services.payment.gateway_duitku import DuitkuAdapter
from app.services.payment.gateway_xendit import XenditAdapter


class PaymentAdapterFactory:
    """
    Factory resolver untuk membuat instance PaymentAdapter sesuai konfigurasi tenant.
    Phase 1 Stage 2 (P0-B & P0-C):
      - Zero silent fallback to ManualTransferAdapter.
      - Direct Tenant Rail (MANUAL_TRANSFER / manual / static_qris) is disabled (EXPERIMENTAL / PENDING_REVIEW).
      - Missing config, missing credentials, or unknown provider fails closed with PaymentConfigurationError.
    """

    @classmethod
    def resolve(
        cls,
        context_or_config: Union[TenantRuntimeContext, Dict[str, Any], None] = None,
        provider_override: Optional[str] = None,
    ) -> PaymentAdapter:
        """
        Menentukan adapter pembayaran:
        1. Membaca context.metadata.payment_config jika context_or_config adalah TenantRuntimeContext.
        2. Membaca dict config langsung jika context_or_config adalah dict.
        3. Menolak (fail-closed) konfigurasi kosong, Direct Tenant Rail (manual/static QRIS),
           provider tidak dikenal, atau kredensial Native PG yang tidak lengkap.
        """
        config: Dict[str, Any] = {}

        if isinstance(context_or_config, TenantRuntimeContext):
            meta = getattr(context_or_config, "metadata", {}) or {}
            config = meta.get("payment_config") if isinstance(meta.get("payment_config"), dict) else {}
        elif isinstance(context_or_config, dict):
            nested = context_or_config.get("payment_config")
            config = nested if isinstance(nested, dict) else context_or_config

        mode = str(config.get("mode") or "").strip().upper()
        provider = str(provider_override or config.get("provider") or config.get("gateway") or "").strip().lower()

        # P0-C: Hard-block Direct Tenant Rail (MANUAL_TRANSFER / manual / static_qris)
        if mode in ("MANUAL_TRANSFER", "DIRECT_TENANT", "STATIC_QRIS") or provider in (
            "manual",
            "manual_transfer",
            "bank_transfer",
            "static_qris",
            "direct_tenant",
            "personal_qris",
        ):
            raise PaymentConfigurationError(
                "DIRECT_TENANT_RAIL_DISABLED: Direct Tenant Rail (manual bank transfer / static QRIS) "
                "is EXPERIMENTAL / PENDING_REVIEW and disabled for active checkout and adapter resolution."
            )

        if not config and not provider_override:
            raise PaymentConfigurationError(
                "MISSING_PAYMENT_CONFIG: Tenant does not have a valid payment gateway configuration. "
                "Silent fallback to manual transfer adapter is prohibited."
            )

        if not provider:
            raise PaymentConfigurationError(
                "MISSING_PAYMENT_PROVIDER: Payment configuration must specify a valid Native Payment Gateway "
                "provider ('xendit' or 'duitku'). Silent fallback is prohibited."
            )

        if mode and mode not in ("NATIVE_PG", "GATEWAY", "XENDIT", "DUITKU"):
            raise PaymentConfigurationError(
                f"UNSUPPORTED_PAYMENT_MODE: Payment mode '{mode}' is not supported on active checkout."
            )

        if provider in ("xendit", "qris_xendit", "xendit_qris", "xendit_invoice"):
            secret_key = str(config.get("secret_key") or config.get("api_key") or "").strip()
            callback_token = config.get("callback_token") or config.get("verification_token")
            is_sandbox = config.get("is_sandbox")
            if not secret_key:
                raise PaymentConfigurationError(
                    "MISSING_PROVIDER_CREDENTIALS: Xendit adapter requires a non-empty 'secret_key' or 'api_key' "
                    "in tenant payment_config."
                )
            return XenditAdapter(
                secret_key=secret_key,
                callback_token=callback_token,
                is_sandbox=is_sandbox,
            )

        if provider in ("duitku", "gateway", "dynamic_qris"):
            merchant_code = str(config.get("merchant_code") or "").strip()
            api_key = str(config.get("api_key") or "").strip()
            callback_url = config.get("callback_url")
            return_url = config.get("return_url")
            is_sandbox = config.get("is_sandbox")
            if not (merchant_code and api_key):
                raise PaymentConfigurationError(
                    "MISSING_PROVIDER_CREDENTIALS: Duitku adapter requires non-empty 'merchant_code' and 'api_key' "
                    "in tenant payment_config."
                )
            return DuitkuAdapter(
                merchant_code=merchant_code,
                api_key=api_key,
                callback_url=callback_url,
                return_url=return_url,
                is_sandbox=is_sandbox,
            )

        raise PaymentConfigurationError(
            f"UNSUPPORTED_PAYMENT_PROVIDER: Provider '{provider}' is not a supported Native Payment Gateway "
            "or is disabled. Silent fallback to ManualTransferAdapter is prohibited."
        )

    @classmethod
    def _resolve_manual_adapter(cls, config: Dict[str, Any]) -> ManualTransferAdapter:
        """
        Phase 1 Stage 2 (P0-B & P0-C):
        Direct Tenant Rail is disabled and default dummy bank accounts are prohibited.
        """
        raise PaymentConfigurationError(
            "DIRECT_TENANT_RAIL_DISABLED: Direct Tenant Rail (ManualTransferAdapter) is "
            "EXPERIMENTAL / PENDING_REVIEW and disabled."
        )

