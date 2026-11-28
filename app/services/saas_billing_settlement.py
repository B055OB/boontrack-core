"""SaaS-only Xendit settlement transaction and immutable SKU ledger writer."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Callable

from app.core.database import get_db_connection


class SaaSSettlementError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _payload_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, Mapping) else payload


def _required_text(value: Any, code: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise SaaSSettlementError(code)
    return result


def _strict_positive_int(value: Any, code: str) -> int:
    if isinstance(value, bool):
        raise SaaSSettlementError(code)
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value.strip())
    else:
        raise SaaSSettlementError(code)
    if result <= 0:
        raise SaaSSettlementError(code)
    return result


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


class SaaSBillingSettlementRepository:
    """Verifies a SaaS invoice callback and commits payment, ledger, and activation outbox atomically."""

    def __init__(self, connection_factory: Callable[[], Any] | None = None) -> None:
        self._connection_factory = connection_factory or get_db_connection

    def settle_xendit_paid_event(
        self,
        payload: Mapping[str, Any],
        *,
        credential_profile_id: str,
        business_id: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise SaaSSettlementError("BILLING_WEBHOOK_PAYLOAD_INVALID")
        data = _payload_data(payload)
        invoice_id = _required_text(data.get("id") or payload.get("id"), "BILLING_PROVIDER_INVOICE_ID_REQUIRED")
        purchase_ref = _required_text(
            data.get("external_id") or payload.get("external_id"),
            "BILLING_PURCHASE_REFERENCE_REQUIRED",
        )
        business_id_fields = (
            data.get("business_id"),
            payload.get("business_id"),
        )
        # Legacy Invoice callbacks may expose the account identity as user_id;
        # newer webhook families expose business_id. Prefer business_id whenever present.
        selected_business_fields = (
            business_id_fields
            if any(value is not None and str(value).strip() for value in business_id_fields)
            else (data.get("user_id"), payload.get("user_id"))
        )
        business_id_candidates = [
            str(value).strip()
            for value in selected_business_fields
            if value is not None and str(value).strip()
        ]
        if not business_id_candidates:
            raise SaaSSettlementError("BILLING_PROVIDER_BUSINESS_ID_REQUIRED")
        callback_business_id = business_id_candidates[0]
        callback_profile_id = _required_text(credential_profile_id, "BILLING_CREDENTIAL_PROFILE_REQUIRED")
        expected_business_id = _required_text(business_id, "BILLING_PROVIDER_BUSINESS_ID_REQUIRED")
        if callback_business_id != expected_business_id or any(value != expected_business_id for value in business_id_candidates):
            raise SaaSSettlementError("BILLING_PROVIDER_BUSINESS_MISMATCH", 403)
        status = str(data.get("status") or payload.get("status") or "").strip().upper()
        if status not in {"PAID", "SETTLED"}:
            raise SaaSSettlementError("BILLING_PROVIDER_STATUS_NOT_SETTLED", 409)
        currency = str(data.get("currency") or payload.get("currency") or "").strip().upper()
        if currency != "IDR":
            raise SaaSSettlementError("BILLING_PROVIDER_CURRENCY_MISMATCH")
        amount = _strict_positive_int(
            data.get("paid_amount") if data.get("paid_amount") is not None else (payload.get("paid_amount") if payload.get("paid_amount") is not None else (data.get("amount") if data.get("amount") is not None else payload.get("amount"))),
            "BILLING_PROVIDER_AMOUNT_INVALID",
        )
        provider_event_id = f"{invoice_id}:PAID"
        if len(provider_event_id) > 180:
            raise SaaSSettlementError("BILLING_PROVIDER_EVENT_ID_INVALID")
        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

        conn = None
        try:
            conn = self._connection_factory()
            if conn is None or getattr(conn, "closed", False):
                raise SaaSSettlementError("BILLING_DATABASE_UNAVAILABLE", 503)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, canonical_tenant_id, product, request_reference,
                           catalog_version, line_items, subtotal_idr, tax_policy_id,
                           tax_amount_idr, total_idr, currency, payment_status,
                           payment_intent_id, provider_environment, credential_profile_id,
                           provider_invoice_id
                    FROM public.saas_billing_purchases
                    WHERE id::text = %s
                    FOR UPDATE;
                    """,
                    (purchase_ref,),
                )
                row = cur.fetchone()
                if not row:
                    raise SaaSSettlementError("BILLING_PURCHASE_NOT_FOUND", 404)
                (
                    purchase_id, tenant_id, product, request_reference, catalog_version,
                    line_items_raw, subtotal, tax_policy_id, tax_amount, total, purchase_currency,
                    payment_status, payment_intent_id, environment, stored_profile_id, stored_invoice_id,
                ) = row
                if str(environment) != "sandbox":
                    raise SaaSSettlementError("BILLING_PRODUCTION_SETTLEMENT_FORBIDDEN", 403)
                if str(stored_profile_id) != callback_profile_id:
                    raise SaaSSettlementError("BILLING_CREDENTIAL_PROFILE_MISMATCH", 403)
                if str(stored_invoice_id or "") != invoice_id:
                    raise SaaSSettlementError("BILLING_PROVIDER_INVOICE_MISMATCH")
                if str(purchase_currency).upper() != currency or int(total) != amount:
                    raise SaaSSettlementError("BILLING_PROVIDER_AMOUNT_MISMATCH")
                if str(payment_status) == "PAID":
                    cur.execute(
                        """
                        SELECT payload_sha256 FROM public.saas_billing_webhook_events
                        WHERE provider = 'XENDIT' AND provider_event_id = %s;
                        """,
                        (provider_event_id,),
                    )
                    prior = cur.fetchone()
                    if prior:
                        # Critical identifiers, business scope, currency, and amount were
                        # validated above. Optional callback fields may differ on redelivery
                        # or reconciliation, but a paid invoice can never create a second ledger.
                        conn.commit()
                        return {
                            "purchase_id": str(purchase_id), "duplicate": True,
                            "ledger_entries": 0, "entitlement_events": 0,
                            "payment_status": "PAID",
                        }
                    raise SaaSSettlementError("BILLING_PURCHASE_ALREADY_PAID_WITHOUT_EVENT", 409)

                cur.execute(
                    """
                    SELECT payload_sha256, processing_status
                    FROM public.saas_billing_webhook_events
                    WHERE provider = 'XENDIT' AND provider_event_id = %s
                    FOR UPDATE;
                    """,
                    (provider_event_id,),
                )
                prior = cur.fetchone()
                if prior:
                    if str(prior[0]) == payload_hash and str(prior[1]) == "PROCESSED":
                        conn.commit()
                        return {
                            "purchase_id": str(purchase_id), "duplicate": True,
                            "ledger_entries": 0, "entitlement_events": 0,
                            "payment_status": str(payment_status),
                        }
                    cur.execute(
                        """
                        UPDATE public.saas_billing_webhook_events
                        SET processing_status = 'QUARANTINED',
                            rejection_code = 'DUPLICATE_EVENT_PAYLOAD_MISMATCH'
                        WHERE provider = 'XENDIT' AND provider_event_id = %s;
                        """,
                        (provider_event_id,),
                    )
                    conn.commit()
                    raise SaaSSettlementError("BILLING_DUPLICATE_EVENT_PAYLOAD_MISMATCH", 409)

                line_items = _json_value(line_items_raw)
                if not isinstance(line_items, list) or not line_items:
                    raise SaaSSettlementError("BILLING_PURCHASE_LINE_ITEMS_INVALID")
                normalized_lines: list[dict[str, Any]] = []
                line_sum = 0
                for line in line_items:
                    if not isinstance(line, Mapping):
                        raise SaaSSettlementError("BILLING_PURCHASE_LINE_ITEMS_INVALID")
                    sku = _required_text(line.get("sku"), "BILLING_PURCHASE_SKU_INVALID")
                    line_amount = _strict_positive_int(line.get("line_amount_idr"), "BILLING_PURCHASE_LINE_AMOUNT_INVALID")
                    quantity = _strict_positive_int(line.get("quantity"), "BILLING_PURCHASE_QUANTITY_INVALID")
                    entitlement_key = _required_text(line.get("entitlement_key"), "BILLING_ENTITLEMENT_KEY_INVALID")
                    credit_units = line.get("credit_units") or 0
                    if isinstance(credit_units, bool) or not isinstance(credit_units, int) or credit_units < 0:
                        raise SaaSSettlementError("BILLING_CREDIT_UNITS_INVALID")
                    validity_days = line.get("entitlement_validity_days")
                    if validity_days is not None and (
                        isinstance(validity_days, bool) or not isinstance(validity_days, int) or validity_days < 1
                    ):
                        raise SaaSSettlementError("BILLING_ENTITLEMENT_VALIDITY_INVALID")
                    normalized_lines.append({
                        "sku": sku, "line_amount_idr": line_amount, "quantity": quantity,
                        "entitlement_key": entitlement_key, "credit_units": credit_units,
                        "validity_days": validity_days,
                    })
                    line_sum += line_amount
                if line_sum != int(subtotal) or int(total) not in {int(subtotal), int(subtotal) + int(tax_amount)}:
                    raise SaaSSettlementError("BILLING_PURCHASE_SNAPSHOT_TOTAL_MISMATCH")

                cur.execute(
                    """
                    INSERT INTO public.saas_billing_webhook_events (
                        provider, provider_event_id, payload_sha256, purchase_id,
                        payment_intent_id, verification_status, processing_status
                    ) VALUES ('XENDIT', %s, %s, %s, %s, 'VERIFIED', 'RECEIVED')
                    RETURNING id;
                    """,
                    (provider_event_id, payload_hash, purchase_id, payment_intent_id),
                )
                webhook_event_id = cur.fetchone()[0]

                ledger_count = 0
                entitlement_count = 0
                for line in normalized_lines:
                    metadata = {
                        "quantity": line["quantity"],
                        "base_amount_idr": line["line_amount_idr"],
                        "entitlement_key": line["entitlement_key"],
                        "credit_units": line["credit_units"],
                        "validity_days": line["validity_days"],
                        "tax_policy_id": str(tax_policy_id),
                    }
                    cur.execute(
                        """
                        INSERT INTO public.saas_billing_ledger_entries (
                            canonical_tenant_id, purchase_id, payment_intent_id,
                            product, sku, entry_kind, amount_idr, currency, provider,
                            provider_event_id, catalog_version, policy_reference, metadata
                        ) VALUES (%s, %s, %s, %s, %s, 'CHARGE', %s, 'IDR', 'XENDIT',
                                  %s, %s, %s, %s::jsonb)
                        RETURNING id;
                        """,
                        (
                            tenant_id, purchase_id, payment_intent_id, product,
                            line["sku"], line["line_amount_idr"], provider_event_id,
                            catalog_version, str(tax_policy_id),
                            json.dumps(metadata, separators=(",", ":")),
                        ),
                    )
                    ledger_id = cur.fetchone()[0]
                    ledger_count += 1
                    event_seed = f"{purchase_id}:{line['sku']}:{line['entitlement_key']}:{provider_event_id}"
                    entitlement_event_id = hashlib.sha256(event_seed.encode("utf-8")).hexdigest()
                    cur.execute(
                        """
                        INSERT INTO public.saas_billing_entitlement_events (
                            event_id, canonical_tenant_id, product, purchase_id, ledger_entry_id,
                            sku, entitlement_key, quantity, credit_units, valid_from, valid_until,
                            event_status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(),
                            CASE WHEN %s IS NULL THEN NULL ELSE NOW() + (%s * INTERVAL '1 day') END,
                            'REQUESTED'
                        );
                        """,
                        (
                            entitlement_event_id, tenant_id, product, purchase_id, ledger_id,
                            line["sku"], line["entitlement_key"], line["quantity"], line["credit_units"],
                            line["validity_days"], line["validity_days"],
                        ),
                    )
                    entitlement_count += 1

                if int(tax_amount) > 0 and int(total) == int(subtotal) + int(tax_amount):
                    cur.execute(
                        """
                        INSERT INTO public.saas_billing_ledger_entries (
                            canonical_tenant_id, purchase_id, payment_intent_id,
                            product, sku, entry_kind, amount_idr, currency, provider,
                            provider_event_id, catalog_version, policy_reference, metadata
                        ) VALUES (%s, %s, %s, %s, '__TAX__', 'CHARGE', %s, 'IDR', 'XENDIT',
                                  %s, %s, %s, %s::jsonb);
                        """,
                        (
                            tenant_id, purchase_id, payment_intent_id, product, int(tax_amount),
                            provider_event_id, catalog_version, str(tax_policy_id),
                            json.dumps({"tax_amount_idr": int(tax_amount), "tax_policy_id": str(tax_policy_id)}),
                        ),
                    )
                    ledger_count += 1

                outbox_event_id = f"saas-entitlement-activate:{purchase_id}"
                cur.execute(
                    """
                    INSERT INTO public.payment_outbox_events (
                        event_id, aggregate_id, event_type, payload, canonical_tenant_id,
                        order_id, payment_intent_id, provider, provider_event_id,
                        idempotency_key, status, delivery_status
                    ) VALUES (
                        %s, %s, 'SAAS_ENTITLEMENTS_ACTIVATE_REQUESTED', %s::jsonb, %s,
                        %s, %s, 'XENDIT', %s, %s, 'PENDING', 'PENDING'
                    );
                    """,
                    (
                        outbox_event_id, str(purchase_id),
                        json.dumps({
                            "purchase_id": str(purchase_id),
                            "webhook_event_id": str(webhook_event_id),
                            "product": str(product),
                            "canonical_tenant_id": str(tenant_id),
                        }, separators=(",", ":")),
                        str(tenant_id), str(request_reference), str(payment_intent_id),
                        provider_event_id, outbox_event_id,
                    ),
                )
                cur.execute(
                    """
                    UPDATE public.saas_billing_purchases
                    SET payment_status = 'PAID', updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (purchase_id,),
                )
                cur.execute(
                    """
                    UPDATE public.payment_intents
                    SET status = 'SETTLED', initiation_state = 'PAID', updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (payment_intent_id,),
                )
                cur.execute(
                    """
                    UPDATE public.saas_billing_webhook_events
                    SET processing_status = 'PROCESSED', processed_at = NOW()
                    WHERE id = %s;
                    """,
                    (webhook_event_id,),
                )
            conn.commit()
            return {
                "purchase_id": str(purchase_id), "duplicate": False,
                "ledger_entries": ledger_count, "entitlement_events": entitlement_count,
                "payment_status": "PAID",
            }
        except SaaSSettlementError:
            if conn is not None and not getattr(conn, "closed", True):
                conn.rollback()
            raise
        except Exception as exc:
            if conn is not None and not getattr(conn, "closed", True):
                conn.rollback()
            raise SaaSSettlementError("BILLING_SETTLEMENT_TRANSACTION_FAILED", 503) from exc
        finally:
            if conn is not None and not getattr(conn, "closed", True):
                conn.close()
