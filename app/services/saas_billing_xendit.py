"""SaaS-only thin wrapper around Core's existing XenditAdapter.

This module reuses provider connectivity but isolates credentials and callback
verification from OnlineBoost/merchant payment profiles. It does not settle,
write ledger entries, activate entitlements, or fulfill products.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.payment.base import TransactionRequest
from app.services.payment.gateway_xendit import XenditAdapter


class SaaSXenditProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class SaaSXenditSandboxProfile:
    profile_id: str
    secret_key: str
    callback_token: str
    business_id: str
    api_url: str
    environment: str = "sandbox"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "SaaSXenditSandboxProfile":
        env = environ if environ is not None else os.environ
        environment = str(env.get("SAAS_XENDIT_ENV", "")).strip().lower()
        if environment != "sandbox":
            raise SaaSXenditProfileError("BILLING_XENDIT_SANDBOX_ONLY")
        if any(
            str(env.get(key, "")).strip().lower() in {"production", "prod", "live"}
            for key in ("APP_ENV", "ENVIRONMENT", "RAILWAY_ENVIRONMENT")
        ):
            raise SaaSXenditProfileError("BILLING_XENDIT_PRODUCTION_CONTEXT_FORBIDDEN")

        profile_id = str(env.get("SAAS_XENDIT_SANDBOX_PROFILE_ID", "")).strip()
        secret_key = str(env.get("SAAS_XENDIT_SANDBOX_SECRET_KEY", "")).strip()
        callback_token = str(env.get("SAAS_XENDIT_SANDBOX_CALLBACK_TOKEN", "")).strip()
        business_id = str(env.get("SAAS_XENDIT_SANDBOX_BUSINESS_ID", "")).strip()
        api_url = str(env.get("SAAS_XENDIT_SANDBOX_API_URL", "https://api.xendit.co")).strip().rstrip("/")
        if not all((profile_id, secret_key, callback_token, business_id)):
            raise SaaSXenditProfileError("BILLING_PROVIDER_PROFILE_UNAVAILABLE")
        if len(secret_key) < 16 or len(callback_token) < 16:
            raise SaaSXenditProfileError("BILLING_PROVIDER_PROFILE_INVALID")
        if secret_key == str(env.get("XENDIT_SECRET_KEY", "")).strip():
            raise SaaSXenditProfileError("BILLING_ONLINEBOOST_CREDENTIAL_REUSE_FORBIDDEN")
        if callback_token == str(env.get("XENDIT_CALLBACK_TOKEN", "")).strip():
            raise SaaSXenditProfileError("BILLING_ONLINEBOOST_CALLBACK_REUSE_FORBIDDEN")
        if not (
            api_url.startswith("https://")
            or (api_url.startswith("http://127.0.0.1") and str(env.get("APP_ENV", "")).lower() == "test")
        ):
            raise SaaSXenditProfileError("BILLING_PROVIDER_API_URL_INVALID")
        return cls(
            profile_id=profile_id,
            secret_key=secret_key,
            callback_token=callback_token,
            business_id=business_id,
            api_url=api_url,
        )


class SaaSXenditProvider:
    """Creates Xendit sandbox checkout using the existing Core adapter."""

    def __init__(
        self,
        profile: SaaSXenditSandboxProfile | None = None,
        adapter_factory: Any = XenditAdapter,
    ) -> None:
        self.profile = profile or SaaSXenditSandboxProfile.from_env()
        self.adapter = adapter_factory(
            secret_key=self.profile.secret_key,
            callback_token=self.profile.callback_token,
            env="sandbox",
        )
        # The Core adapter reads this from process environment by default. Override
        # the instance only with the explicitly selected SaaS sandbox profile URL.
        self.adapter.api_url = self.profile.api_url

    async def create_invoice(
        self,
        *,
        purchase_reference: str,
        amount_idr: int,
        description: str,
    ) -> dict[str, Any]:
        if not purchase_reference.strip() or isinstance(amount_idr, bool) or amount_idr <= 0:
            raise ValueError("BILLING_PROVIDER_REQUEST_INVALID")
        result = await self.adapter.create_transaction(
            TransactionRequest(
                order_id=purchase_reference,
                amount=amount_idr,
                customer_name="BoonTrack SaaS",
                customer_phone="",
                customer_email=None,
                description=description,
                payment_method="INVOICE",
                metadata={
                    "billing_domain": "BOONTRACK_SAAS",
                    "credential_profile_id": self.profile.profile_id,
                    "provider_business_id": self.profile.business_id,
                },
            )
        )
        if result.amount != amount_idr or not result.transaction_id or not result.payment_url:
            raise SaaSXenditProfileError("BILLING_PROVIDER_RESPONSE_MISMATCH")
        return {
            "provider": "XENDIT",
            "environment": "sandbox",
            "profile_id": self.profile.profile_id,
            "provider_invoice_id": result.transaction_id,
            "checkout_url": result.payment_url,
            "amount_idr": result.amount,
            "status": result.status,
        }

    def verify_callback_token(self, supplied_token: str) -> bool:
        token = str(supplied_token or "").strip()
        return bool(token) and hmac.compare_digest(token, self.profile.callback_token)
