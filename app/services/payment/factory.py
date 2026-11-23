from __future__ import annotations

"""app/services/payment/factory.py
Payment Adapter Factory.
Normalizes server-side payment contract strictly around:
  rail="NATIVE_PG", provider="XENDIT", channel="DYNAMIC_QRIS".

Invariants:
- Normalizes legacy PAYMENT_GATEWAY strictly server-side to rail="NATIVE_PG".
- Rejects/ignores any client-supplied payment routing hints (isGateway, isXendit, provider/rail overrides, or plaintext secrets).
- Wires CredentialProfileMapper / api_credentials.secret_ref resolution inside Core server-side.
- NEVER logs or stores plaintext provider secrets in tenant metadata.
- Instantiates XenditAdapter with its own instance-resolved secret_key (zero global singleton reliance).
- Explicitly EXCLUDES Midtrans, Duitku, Dodo, Direct Tenant rail (manual transfer, static QRIS), and any Production Xendit call.
- Fails closed on tenant identity, credential profile, environment, or channel validation failure.
"""

from typing import Optional, Dict, Any, Union, TYPE_CHECKING
import os
import logging

from app.schemas.context import TenantRuntimeContext
from app.services.payment.base import PaymentAdapter, PaymentConfigurationError, PaymentAuthorizationError
from app.services.payment.manual_adapter import ManualTransferAdapter
from app.services.payment.gateway_xendit import XenditAdapter

if TYPE_CHECKING:
    from app.core.security.payment_auth_guard import CredentialProfileMapper

logger = logging.getLogger("PAYMENT_FACTORY")

EXCLUDED_PROVIDERS = frozenset({
    "midtrans",
    "duitku",
    "dodo",
    "manual",
    "manual_transfer",
    "bank_transfer",
    "static_qris",
    "direct_tenant",
    "personal_qris",
})


class PaymentAdapterFactory:
    """Factory resolver for payment adapters.
    Phase 1 Stage 2 (P0-B & P0-C) & Packet 3D Step 3:
      - Normalizes server-side payment contract around rail="NATIVE_PG", provider="XENDIT", channel="DYNAMIC_QRIS".
      - Normalizes legacy PAYMENT_GATEWAY strictly server-side.
      - Rejects/ignores client-supplied payment routing hints (isGateway, isXendit, provider/rail overrides, or plaintext secrets).
      - Wires CredentialProfileMapper / api_credentials.secret_ref resolution inside Core server-side.
      - Explicitly excludes Midtrans, Duitku, Dodo, Direct Tenant rail, Static QRIS, and any Production Xendit call.
    """

    @classmethod
    def resolve(
        cls,
        context_or_config: Union[TenantRuntimeContext, Dict[str, Any], None] = None,
        provider_override: Optional[str] = None,
        *,
        credential_mapper: Optional[CredentialProfileMapper] = None,
    ) -> PaymentAdapter:
        """Menentukan dan menginisialisasi PaymentAdapter sesuai kontrak terisolasi Xendit Native PG."""
        # DEF-10: Fail closed on None / empty config (no fallback to ManualTransferAdapter)
        if not context_or_config and not provider_override:
            raise PaymentConfigurationError(
                "MISSING_PAYMENT_CONFIG: Tenant does not have a valid payment gateway configuration. "
                "Silent fallback to manual transfer adapter is prohibited."
            )

        config: Dict[str, Any] = {}
        meta: Dict[str, Any] = {}

        if isinstance(context_or_config, TenantRuntimeContext):
            meta = getattr(context_or_config, "metadata", {}) or {}
            config = meta.get("payment_config") if isinstance(meta.get("payment_config"), dict) else {}
            if not config and not provider_override:
                raise PaymentConfigurationError(
                    "MISSING_PAYMENT_CONFIG: Tenant does not have a valid payment gateway configuration. "
                    "Silent fallback to manual transfer adapter is prohibited."
                )
        elif isinstance(context_or_config, dict):
            meta = dict(context_or_config)
            nested = context_or_config.get("payment_config")
            config = nested if isinstance(nested, dict) else context_or_config
            if not config and not provider_override:
                raise PaymentConfigurationError(
                    "MISSING_PAYMENT_CONFIG: Tenant does not have a valid payment gateway configuration. "
                    "Silent fallback to manual transfer adapter is prohibited."
                )

        # Security Check: Reject plaintext provider secrets in metadata or config
        for forbidden_key in ("secret_key", "api_key", "server_key", "callback_token", "secret_value"):
            raw_val = config.get(forbidden_key) or meta.get(forbidden_key)
            if raw_val and isinstance(raw_val, str) and not raw_val.startswith(("env://", "vault://")):
                # Check if it looks like a client-supplied secret
                if any(k in config for k in ("isGateway", "isXendit", "provider_override")):
                    raise PaymentConfigurationError(
                        "CLIENT_PLAINTEXT_SECRET_REJECTED: Client-supplied plaintext secrets are strictly prohibited."
                    )

        raw_rail = str(config.get("rail") or config.get("mode") or "").strip().upper()
        raw_provider = str(provider_override or config.get("provider") or config.get("gateway") or "").strip().lower()

        # Direct Tenant Rail -> DIRECT_TENANT_RAIL_DISABLED
        if raw_rail in ("MANUAL_TRANSFER", "DIRECT_TENANT", "STATIC_QRIS") or raw_provider in (
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

        # 1. Reject / check explicit exclusions on provider_override or config hints
        if provider_override:
            clean_override = str(provider_override).strip().lower()
            if clean_override in ("midtrans", "dodo"):
                raise PaymentConfigurationError(
                    f"EXCLUDED_PROVIDER: Provider '{provider_override}' is explicitly excluded. "
                    "Only XENDIT Native PG (rail='NATIVE_PG', provider='XENDIT', channel='DYNAMIC_QRIS') is permitted."
                )

        if raw_provider in ("midtrans", "dodo"):
            raise PaymentConfigurationError(
                f"EXCLUDED_PROVIDER: Provider '{raw_provider}' is explicitly excluded. "
                "Only XENDIT Native PG (rail='NATIVE_PG', provider='XENDIT', channel='DYNAMIC_QRIS') is permitted."
            )

        if not raw_provider:
            raise PaymentConfigurationError(
                "MISSING_PAYMENT_PROVIDER: Payment configuration must specify a valid Native Payment Gateway "
                "provider ('xendit' or 'duitku'). Silent fallback is prohibited."
            )

        if raw_provider not in ("xendit", "qris_xendit", "xendit_qris", "xendit_invoice", "duitku", "gateway", "dynamic_qris"):
            raise PaymentConfigurationError(
                f"UNSUPPORTED_PAYMENT_PROVIDER: Provider '{raw_provider}' is not a supported Native Payment Gateway "
                "or is disabled. Silent fallback to ManualTransferAdapter is prohibited."
            )

        # Duitku Native PG adapter resolution
        if raw_provider in ("duitku", "gateway", "dynamic_qris"):
            from app.services.payment.gateway_duitku import DuitkuAdapter
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

        # 2. Server-side Normalization: rail="NATIVE_PG", provider="XENDIT", channel="DYNAMIC_QRIS"
        if raw_rail in ("PAYMENT_GATEWAY", "GATEWAY", "XENDIT"):
            rail = "NATIVE_PG"
        elif raw_rail:
            rail = raw_rail
        else:
            rail = "NATIVE_PG"

        if rail != "NATIVE_PG":
            raise PaymentConfigurationError(
                f"UNSUPPORTED_PAYMENT_MODE: Payment mode / rail '{rail}' is not supported. Must be 'NATIVE_PG'."
            )

        raw_channel = str(config.get("channel") or config.get("payment_method") or "").strip().upper()
        if raw_channel in ("STATIC_QRIS", "STATIC"):
            raise PaymentConfigurationError(
                "STATIC_QRIS_EXCLUDED: Static QRIS is explicitly excluded under current contract guardrails."
            )
        channel = "DYNAMIC_QRIS"

        # 3. Wire CredentialProfileMapper & secret_ref resolution
        from app.core.security.payment_auth_guard import CredentialProfileMapper
        mapper = credential_mapper or CredentialProfileMapper()
        secret_key = ""
        callback_token = ""
        is_sandbox = True

        has_profiles = bool(
            meta.get("credential_profiles")
            or config.get("credential_profiles")
        )
        api_creds = config.get("api_credentials") or meta.get("api_credentials")

        if has_profiles:
            try:
                prof = mapper.resolve_checkout_profile(meta, requested_provider="XENDIT")
                # DEF-15: Keep verification_secrets strictly for inbound webhook callback_token
                active_secs = [s for s in prof.verification_secrets if s.status == "ACTIVE"]
                if active_secs:
                    callback_token = mapper.resolve_secret_ref(active_secs[0].secret_ref)
                is_sandbox = (prof.environment == "sandbox")
            except (PaymentAuthorizationError, PaymentConfigurationError) as err:
                raise PaymentConfigurationError(str(err)) from err

            # DEF-15: Always resolve outbound secret_key from api_credentials.secret_ref (or outbound provider secret ref)
            if isinstance(api_creds, dict) and (api_creds.get("secret_ref") or api_creds.get("secret_key_ref")):
                sec_ref = api_creds.get("secret_ref") or api_creds.get("secret_key_ref")
                secret_key = mapper.resolve_secret_ref(sec_ref)
                if not callback_token:
                    cb_ref = api_creds.get("callback_token_ref")
                    if cb_ref:
                        callback_token = mapper.resolve_secret_ref(cb_ref)
                    else:
                        callback_token = api_creds.get("callback_token") or ""
                if "is_sandbox" in api_creds:
                    is_sandbox = bool(api_creds.get("is_sandbox", True))
            elif config.get("secret_ref"):
                secret_key = mapper.resolve_secret_ref(config["secret_ref"])
                if not callback_token:
                    callback_token = config.get("callback_token") or ""
                if "is_sandbox" in config:
                    is_sandbox = bool(config.get("is_sandbox", True))
            elif config.get("secret_key") or config.get("api_key"):
                raw_sec = config.get("secret_key") or config.get("api_key")
                if str(raw_sec).startswith(("env://", "vault://")):
                    secret_key = mapper.resolve_secret_ref(str(raw_sec))
                else:
                    secret_key = str(raw_sec).strip()
                if not callback_token:
                    callback_token = config.get("callback_token") or ""
            elif os.getenv("XENDIT_SECRET_KEY"):
                secret_key = os.getenv("XENDIT_SECRET_KEY", "").strip()

        elif isinstance(api_creds, dict):
            sec_ref = api_creds.get("secret_ref") or api_creds.get("secret_key_ref")
            if not sec_ref:
                raise PaymentConfigurationError(
                    "MISSING_PROVIDER_CREDENTIALS: api_credentials requires 'secret_ref' pointer URI."
                )
            secret_key = mapper.resolve_secret_ref(sec_ref)
            cb_ref = api_creds.get("callback_token_ref")
            if cb_ref:
                callback_token = mapper.resolve_secret_ref(cb_ref)
            else:
                callback_token = api_creds.get("callback_token") or ""
            is_sandbox = bool(api_creds.get("is_sandbox", True))
        elif config.get("secret_ref"):
            secret_key = mapper.resolve_secret_ref(config["secret_ref"])
            callback_token = config.get("callback_token") or ""
            is_sandbox = bool(config.get("is_sandbox", True))
        elif config.get("secret_key") or config.get("api_key"):
            raw_sec = config.get("secret_key") or config.get("api_key")
            if str(raw_sec).startswith(("env://", "vault://")):
                secret_key = mapper.resolve_secret_ref(str(raw_sec))
            else:
                secret_key = str(raw_sec).strip()

            callback_token = (
                config.get("callback_token")
                or config.get("verification_token")
                or os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
                or os.getenv("XENDIT_CALLBACK_TOKEN")
                or ""
            ).strip()
            is_sandbox = config.get("is_sandbox")
            if is_sandbox is None:
                is_sandbox = (os.getenv("XENDIT_ENV", "sandbox").strip().lower() == "sandbox")
        else:
            # Missing credentials in config
            pass

        if not secret_key:
            raise PaymentConfigurationError(
                "MISSING_PROVIDER_CREDENTIALS: Xendit adapter requires a non-empty 'secret_key' "
                "resolved from secret_ref or tenant configuration."
            )

        # 4. Explicitly EXCLUDE any Production Xendit call (Deliverable 9)
        env_xendit = os.getenv("XENDIT_ENV", "sandbox").strip().lower()
        if not is_sandbox or env_xendit == "production":
            raise PaymentConfigurationError(
                "PRODUCTION_XENDIT_EXCLUDED: Production Xendit calls are explicitly excluded under current contract guardrails."
            )

        # 5. Return XenditAdapter with its own instance-resolved secret_key (zero global singleton)
        return XenditAdapter(
            secret_key=secret_key,
            callback_token=callback_token,
            is_sandbox=is_sandbox,
        )

    @classmethod
    def _resolve_manual_adapter(cls, config: Dict[str, Any]) -> ManualTransferAdapter:
        raise PaymentConfigurationError(
            "DIRECT_TENANT_RAIL_DISABLED: Direct Tenant Rail (ManualTransferAdapter) is "
            "EXPERIMENTAL / PENDING_REVIEW and disabled."
        )
