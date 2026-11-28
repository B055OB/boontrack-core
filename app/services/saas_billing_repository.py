"""Durable Core-owned SaaS purchase and effective entitlement repository.

PostgreSQL-only; no process-memory fallback and no migration execution.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from app.core.database import get_db_connection
from app.schemas.saas_billing import SaaSProduct
from app.services.saas_billing_catalog import SaaSQuote


class SaaSBillingRepositoryError(RuntimeError):
    pass


class SaaSBillingIdempotencyConflict(SaaSBillingRepositoryError):
    pass


class SaaSBillingRepository:
    _LEGACY_FEATURE_TO_ENTITLEMENT = {
        "multi_cs": "SHOP_SMARTCHATBOX_MULTI_CS",
        "qris": "SHOP_DYNAMIC_QRIS",
    }

    def __init__(self, connection_factory: Callable[[], Any] | None = None) -> None:
        self._connection_factory = connection_factory or get_db_connection

    @staticmethod
    def _fingerprint(*, product: SaaSProduct, quote: SaaSQuote,
                     request_reference: str, tax_policy_id: str) -> str:
        payload = {
            "product": product.value,
            "request_reference": request_reference,
            "catalog_version": quote.catalog_version,
            "tax_policy_id": tax_policy_id,
            "currency": quote.currency,
            "subtotal_idr": quote.subtotal_idr,
            "tax_amount_idr": quote.tax_amount_idr,
            "total_idr": quote.total_idr,
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_amount_idr": line.unit_amount_idr,
                    "line_amount_idr": line.line_amount_idr,
                    "entitlement_key": line.entitlement_key,
                    "credit_units": line.credit_units,
                    "validity_days": line.entitlement_validity_days,
                }
                for line in quote.lines
            ],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _row_dict(row: Any, columns: tuple[str, ...]) -> dict[str, Any] | None:
        if row is None:
            return None
        if isinstance(row, Mapping):
            return {key: row.get(key) for key in columns}
        return {key: row[index] for index, key in enumerate(columns)}

    def create_purchase(
        self, *, canonical_tenant_id: str, product: SaaSProduct,
        request_reference: str, idempotency_key: str, quote: SaaSQuote,
        tax_policy_id: str, credential_profile_id: str,
    ) -> dict[str, Any]:
        """Atomically reserve Core payment_intents and the SaaS purchase row.

        Provider calls happen only after this transaction commits.
        """
        tenant_id = str(canonical_tenant_id or "").strip()
        reference = str(request_reference or "").strip()
        idem = str(idempotency_key or "").strip()
        policy_id = str(tax_policy_id or "").strip()
        profile_id = str(credential_profile_id or "").strip()
        if not all((tenant_id, reference, idem, policy_id, profile_id)):
            raise ValueError("BILLING_PURCHASE_CONTEXT_REQUIRED")
        if quote.product != product or quote.tax_status != "APPROVED":
            raise ValueError("BILLING_QUOTE_NOT_SETTLEMENT_READY")
        if not quote.payment_intent_allowed or quote.total_idr is None or quote.total_idr <= 0:
            raise ValueError("BILLING_TAX_POLICY_PENDING")

        fingerprint = self._fingerprint(
            product=product, quote=quote, request_reference=reference,
            tax_policy_id=policy_id,
        )
        line_items = [
            {
                "sku": line.sku,
                "item_kind": line.item_kind.value,
                "cadence": line.cadence.value,
                "quantity": line.quantity,
                "unit_amount_idr": line.unit_amount_idr,
                "line_amount_idr": line.line_amount_idr,
                "entitlement_key": line.entitlement_key,
                "credit_units": line.credit_units,
                "entitlement_validity_days": line.entitlement_validity_days,
                "dependency_keys": (
                    ["META_FEES_PASS_THROUGH"]
                    if line.entitlement_key == "SHOP_WABA_OFFICIAL" else []
                ),
            }
            for line in quote.lines
        ]

        conn = None
        try:
            conn = self._connection_factory()
            if conn is None or getattr(conn, "closed", False):
                raise SaaSBillingRepositoryError("BILLING_DATABASE_UNAVAILABLE")
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s));", (idem,))
                cur.execute(
                    """
                    SELECT id, canonical_tenant_id, product, request_reference,
                           request_fingerprint, payment_intent_id, payment_status,
                           provider_invoice_id, checkout_url, expires_at
                    FROM public.saas_billing_purchases
                    WHERE idempotency_key = %s
                    FOR UPDATE;
                    """, (idem,),
                )
                existing = self._row_dict(cur.fetchone(), (
                    "id", "canonical_tenant_id", "product", "request_reference",
                    "request_fingerprint", "payment_intent_id", "payment_status",
                    "provider_invoice_id", "checkout_url", "expires_at",
                ))
                if existing:
                    if (
                        str(existing["canonical_tenant_id"]) != tenant_id
                        or existing["product"] != product.value
                        or existing["request_reference"] != reference
                        or existing["request_fingerprint"] != fingerprint
                    ):
                        raise SaaSBillingIdempotencyConflict("BILLING_IDEMPOTENCY_CONFLICT")
                    conn.commit()
                    return {**existing, "reused": True}

                cur.execute(
                    "SELECT id FROM public.tenants WHERE id = %s FOR SHARE;",
                    (tenant_id,),
                )
                if not cur.fetchone():
                    raise SaaSBillingRepositoryError("BILLING_CANONICAL_TENANT_NOT_FOUND")

                cur.execute(
                    """
                    INSERT INTO public.payment_intents (
                        tenant_id, order_id, amount, unique_code, total_amount,
                        status, idempotency_key, request_fingerprint, initiation_state
                    ) VALUES (%s, %s, %s, 0, %s, 'PENDING', %s, %s, 'INITIATING')
                    RETURNING id;
                    """,
                    (tenant_id, reference, quote.subtotal_idr, quote.total_idr, idem, fingerprint),
                )
                payment_row = cur.fetchone()
                if not payment_row:
                    raise SaaSBillingRepositoryError("BILLING_PAYMENT_INTENT_CREATE_FAILED")
                payment_intent_id = str(payment_row[0])

                cur.execute(
                    """
                    INSERT INTO public.saas_billing_purchases (
                        canonical_tenant_id, product, request_reference, quote_id,
                        catalog_version, request_fingerprint, idempotency_key,
                        line_items, subtotal_idr, tax_policy_id, tax_amount_idr,
                        total_idr, payment_status, payment_intent_id, provider,
                        provider_environment, credential_profile_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                        %s, 'INITIATING', %s, 'XENDIT', 'sandbox', %s
                    )
                    RETURNING id, payment_status, created_at;
                    """,
                    (
                        tenant_id, product.value, reference, quote.quote_id,
                        quote.catalog_version, fingerprint, idem,
                        json.dumps(line_items, separators=(",", ":")),
                        quote.subtotal_idr, policy_id, int(quote.tax_amount_idr or 0),
                        int(quote.total_idr), payment_intent_id, profile_id,
                    ),
                )
                purchase = cur.fetchone()
                if not purchase:
                    raise SaaSBillingRepositoryError("BILLING_PURCHASE_CREATE_FAILED")
                purchase_id = str(purchase[0])
                outbox_payload = {
                    "purchase_id": purchase_id,
                    "payment_intent_id": payment_intent_id,
                    "product": product.value,
                    "credential_profile_id": profile_id,
                    "provider_environment": "sandbox",
                }
                cur.execute(
                    """
                    INSERT INTO public.payment_outbox_events (
                        event_id, aggregate_id, event_type, payload,
                        canonical_tenant_id, order_id, payment_intent_id,
                        provider, idempotency_key, status, delivery_status
                    ) VALUES (
                        %s, %s, 'SAAS_PAYMENT_INTENT_CREATE_REQUESTED', %s::jsonb,
                        %s, %s, %s, 'XENDIT', %s, 'PENDING', 'PENDING'
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING;
                    """,
                    (
                        "saas-payment-intent:" + purchase_id,
                        purchase_id,
                        json.dumps(outbox_payload, separators=(",", ":")),
                        tenant_id,
                        reference,
                        payment_intent_id,
                        "saas-intent:" + idem,
                    ),
                )
                conn.commit()
                return {
                    "id": purchase_id,
                    "canonical_tenant_id": tenant_id,
                    "product": product.value,
                    "request_reference": reference,
                    "payment_intent_id": payment_intent_id,
                    "payment_status": purchase[1],
                    "created_at": purchase[2],
                    "reused": False,
                }
        except SaaSBillingIdempotencyConflict:
            if conn is not None and not getattr(conn, "closed", True):
                conn.rollback()
            raise
        except Exception as exc:
            if conn is not None and not getattr(conn, "closed", True):
                conn.rollback()
            if isinstance(exc, SaaSBillingRepositoryError):
                raise
            raise SaaSBillingRepositoryError("BILLING_DATABASE_OPERATION_FAILED") from exc
        finally:
            if conn is not None and not getattr(conn, "closed", True):
                conn.close()

    def get_effective_tenant_entitlements(
        self, *, canonical_tenant_id: str, product: SaaSProduct,
    ) -> dict[str, Any]:
        """Read activated Core grants and legacy Shop plan inclusions.

        Team Scale subscription rows are read-only and normalized to ENTERPRISE.
        No legacy customer row is modified by this lookup.
        """
        tenant_id = str(canonical_tenant_id or "").strip()
        if not tenant_id:
            raise ValueError("BILLING_CANONICAL_TENANT_REQUIRED")
        conn = None
        try:
            conn = self._connection_factory()
            if conn is None or getattr(conn, "closed", False):
                raise SaaSBillingRepositoryError("BILLING_DATABASE_UNAVAILABLE")
            result: dict[str, Any] = {
                "canonical_tenant_id": tenant_id,
                "product": product.value,
                "legacy_plan_id": None,
                "legacy_plan_status": None,
                "legacy_period_end": None,
                "legacy_feature_keys": [],
                "active_entitlement_keys": [],
            }
            with conn.cursor() as cur:
                cur.execute("SELECT slug FROM public.tenants WHERE id = %s;", (tenant_id,))
                tenant_row = cur.fetchone()
                if not tenant_row:
                    raise SaaSBillingRepositoryError("BILLING_CANONICAL_TENANT_NOT_FOUND")
                tenant_slug = str(tenant_row[0]).strip().lower()

                if product == SaaSProduct.SHOP:
                    cur.execute(
                        """
                        SELECT plan_tier, status, current_period_end
                        FROM public.shop_subscriptions
                        WHERE lower(tenant_slug) = %s
                          AND status::text = 'ACTIVE'
                          AND (current_period_end IS NULL OR current_period_end > NOW())
                        ORDER BY created_at DESC
                        LIMIT 1;
                        """, (tenant_slug,),
                    )
                    sub = cur.fetchone()
                    if sub:
                        raw_tier = str(sub[0] or "").strip().lower().replace("-", "_").replace(" ", "_")
                        if raw_tier in {"team_scale", "team", "enterprise", "scale"}:
                            result["legacy_plan_id"] = "ENTERPRISE"
                        elif raw_tier in {"ads_performance", "pro_scale", "proscale"}:
                            result["legacy_plan_id"] = "PRO_SCALE"
                        elif raw_tier in {"starter", "solo", "growth"}:
                            result["legacy_plan_id"] = "STARTER"
                        else:
                            result["legacy_plan_id"] = raw_tier.upper() or None
                        result["legacy_plan_status"] = str(sub[1])
                        result["legacy_period_end"] = sub[2]

                    cur.execute(
                        "SELECT to_regclass('public.tenant_entitlements'), to_regclass('public.plan_entitlements');"
                    )
                    entitlement_tables = cur.fetchone()
                    if entitlement_tables and entitlement_tables[0] and entitlement_tables[1]:
                        cur.execute(
                            """
                            SELECT pe.feature_key
                            FROM public.tenant_entitlements te
                            JOIN public.plan_entitlements pe ON pe.plan_id = te.plan_id
                            WHERE lower(te.tenant_slug) = %s
                              AND te.status::text IN ('ACTIVE', 'TRIALING')
                              AND (te.subscription_ends_at IS NULL OR te.subscription_ends_at > NOW())
                              AND pe.is_enabled = TRUE
                            ORDER BY pe.feature_key;
                            """, (tenant_slug,),
                        )
                        result["legacy_feature_keys"] = [str(row[0]) for row in cur.fetchall()]
                    mapped = {
                        self._LEGACY_FEATURE_TO_ENTITLEMENT[key]
                        for key in result["legacy_feature_keys"]
                        if key in self._LEGACY_FEATURE_TO_ENTITLEMENT
                    }
                    if result["legacy_plan_id"] == "ENTERPRISE":
                        # The legacy Tier 4 package itself is an active entitlement;
                        # exact feature aliases below prevent add-on double-billing.
                        mapped.update({
                            "ENTERPRISE",
                            "SHOP_DYNAMIC_QRIS",
                            "SHOP_SMARTCHATBOX_MULTI_CS",
                        })
                    result["active_entitlement_keys"].extend(sorted(mapped))

                cur.execute(
                    """
                    SELECT entitlement_key
                    FROM public.saas_billing_entitlement_events
                    WHERE canonical_tenant_id = %s
                      AND product = %s
                      AND event_status = 'ACTIVATED'
                      AND (valid_from IS NULL OR valid_from <= NOW())
                      AND (valid_until IS NULL OR valid_until > NOW())
                    ORDER BY entitlement_key;
                    """, (tenant_id, product.value),
                )
                result["active_entitlement_keys"].extend(str(row[0]) for row in cur.fetchall())
            conn.commit()
            result["active_entitlement_keys"] = sorted(set(result["active_entitlement_keys"]))
            return result
        except Exception as exc:
            if conn is not None and not getattr(conn, "closed", True):
                conn.rollback()
            if isinstance(exc, SaaSBillingRepositoryError):
                raise
            raise SaaSBillingRepositoryError("BILLING_ENTITLEMENT_LOOKUP_FAILED") from exc
        finally:
            if conn is not None and not getattr(conn, "closed", True):
                conn.close()

    def has_effective_entitlement(
        self, *, canonical_tenant_id: str, product: SaaSProduct,
        entitlement_key: str,
    ) -> bool:
        state = self.get_effective_tenant_entitlements(
            canonical_tenant_id=canonical_tenant_id, product=product,
        )
        return str(entitlement_key).strip() in state["active_entitlement_keys"]
