"""Sandbox-only Xendit status reconciliation for Core SaaS billing purchases."""
from __future__ import annotations

from typing import Any, Callable

from app.core.database import get_db_connection
from app.services.saas_billing_settlement import (
    SaaSBillingSettlementRepository,
    SaaSSettlementError,
)
from app.services.saas_billing_xendit import SaaSXenditProvider


class SaaSBillingReconciliationService:
    def __init__(
        self,
        connection_factory: Callable[[], Any] | None = None,
        provider_factory: Callable[[], Any] | None = None,
        settlement_repository: SaaSBillingSettlementRepository | None = None,
    ) -> None:
        self._connection_factory = connection_factory or get_db_connection
        self._provider_factory = provider_factory or SaaSXenditProvider
        self._settlement = settlement_repository or SaaSBillingSettlementRepository(
            connection_factory=self._connection_factory
        )

    async def reconcile_purchase(self, purchase_id: str) -> dict[str, Any]:
        clean_id = str(purchase_id or "").strip()
        if not clean_id:
            raise ValueError("BILLING_PURCHASE_ID_REQUIRED")
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, payment_status, provider_invoice_id, total_idr,
                           credential_profile_id, provider_environment
                    FROM public.saas_billing_purchases
                    WHERE id = %s;
                    """,
                    (clean_id,),
                )
                row = cur.fetchone()
        finally:
            if not getattr(conn, "closed", True):
                conn.close()
        if not row:
            raise ValueError("BILLING_PURCHASE_NOT_FOUND")
        _, current_status, invoice_id, total_idr, profile_id, environment = row
        if str(environment) != "sandbox":
            raise ValueError("BILLING_RECONCILIATION_PRODUCTION_FORBIDDEN")
        if str(current_status) == "PAID":
            return {"purchase_id": clean_id, "status": "PAID", "already_settled": True}
        if not invoice_id:
            return {
                "purchase_id": clean_id, "status": str(current_status),
                "reconcilable": False, "reason": "BILLING_PROVIDER_INVOICE_NOT_CREATED",
            }

        provider = self._provider_factory()
        status_result = await provider.adapter.check_status(str(invoice_id))
        observed_status = str(getattr(status_result, "status", "") or "").strip().upper()
        observed_amount = getattr(status_result, "amount", None)
        raw = getattr(status_result, "raw_response", None) or {}
        if observed_status == "SUCCESS":
            if int(observed_amount or 0) != int(total_idr):
                raise SaaSSettlementError("BILLING_RECONCILIATION_AMOUNT_MISMATCH", 409)
            reconciliation_payload = dict(raw)
            reconciliation_payload.setdefault("business_id", str(provider.profile.business_id))
            settlement = self._settlement.settle_xendit_paid_event(
                reconciliation_payload,
                credential_profile_id=str(profile_id),
                business_id=str(provider.profile.business_id),
            )
            return {
                "purchase_id": clean_id, "status": "PAID",
                "reconciled": True, "settlement": settlement,
            }
        if observed_status == "EXPIRED":
            conn = self._connection_factory()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.saas_billing_purchases
                        SET payment_status = 'EXPIRED', updated_at = NOW()
                        WHERE id = %s AND payment_status <> 'PAID';
                        """,
                        (clean_id,),
                    )
                    cur.execute(
                        """
                        UPDATE public.payment_intents pi
                        SET status = 'EXPIRED', initiation_state = 'EXPIRED', updated_at = NOW()
                        FROM public.saas_billing_purchases p
                        WHERE p.id = %s AND pi.id = p.payment_intent_id
                          AND p.payment_status = 'EXPIRED';
                        """,
                        (clean_id,),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if not getattr(conn, "closed", True):
                    conn.close()
            return {"purchase_id": clean_id, "status": "EXPIRED", "reconciled": True}
        return {
            "purchase_id": clean_id,
            "status": observed_status or "UNKNOWN",
            "reconciled": False,
        }
