"""Phase 1 — Stage 3 / Step 1 Targeted Verification Suite:
`app/core/security/provenance_authority.py`

Covers all 9 CTO Step 1 Test Boundary requirements using local mocks/stubs only
(zero external network calls, zero live/sandbox PG calls, zero production/Supabase/R2 access):
1. Provider and verification method allowlist (`XENDIT`, `MIDTRANS`, `DUITKU` only).
2. Midtrans `capture` / `fraud_status` guard (`capture` accepted ONLY if `fraud_status == "accept"`).
3. Duitku HMAC-SHA256 valid/invalid and S2S `transactionStatus` single-call + pre-S2S idempotency.
4. Capability minting (`VerifiedSettlementCapability`) and Ed25519 provenance verification.
5. Atomic settlement persistence (`commit_verified_settlement_transaction`).
6. Composite duplicate idempotency, conflicting replay (409), and late settlement quarantine (CTO Decision #4).
7. Financial ledger (`fee_amount=NULL`, `net_amount=NULL`, `PENDING_RECONCILIATION`) & outbox (`PENDING_STAGE4_VERIFICATION`).
8. Strictly zero fulfillment, entitlement, Telegram invite, WhatsApp delivery, Meta CAPI, and TikTok CAPI.
9. Database failure at any step triggers full transaction rollback and fail-closed `DATABASE_UNAVAILABLE` (503).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple
import uuid


class _StandaloneRaises:
    def __init__(self, exc_type: Any) -> None:
        self.exc_type = exc_type
        self.value: Any = None

    def __enter__(self) -> "_StandaloneRaises":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_type is None:
            raise AssertionError(f"Expected {self.exc_type} to be raised, but none was raised.")
        if not issubclass(exc_type, self.exc_type):
            return False
        self.value = exc_val
        return True


class _StandalonePytestShim:
    raises = _StandaloneRaises


pytest: Any = sys.modules.get("pytest") or _StandalonePytestShim()

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security.test_isolation_guard import bootstrap_isolated_test_env
bootstrap_isolated_test_env(REPO_ROOT)

from app.core.security.provenance_authority import (
    ALLOWED_PROVIDERS,
    ALLOWED_VERIFICATION_METHODS,
    LOCKED_UNAUTHORIZED_PROVIDERS,
    LOCKED_UNAUTHORIZED_VERIFICATION_METHODS,
    PROVENANCE_CONTRACT_FIELDS,
    STAGE3_NATIVE_PG_ALLOWED_PROVIDERS,
    STAGE3_NATIVE_PG_ALLOWED_VERIFICATION_METHODS,
    STAGE3_NATIVE_PG_PROVIDER_METHOD_MAP,
    ProvenanceSigner,
    ProvenanceSigningKeyring,
    ProvenanceVerifier,
    TrustedSettlementVerificationBoundary,
    VerifiedSettlementCapability,
    commit_verified_settlement_transaction,
    validate_provenance_17_field_contract,
)
from app.services.payment.base import SettlementProvenanceError

TENANT_A_UUID = "7f9c2a10-4b55-4e88-9c11-112233445566"
TENANT_B_UUID = "9a8b7c6d-5e4f-4a3b-8c2d-665544332211"

PROV_KEY_ID = "prv_step1_ed25519_active_v1"
PROV_PRIV_HEX = "11" * 32

XENDIT_SECRET = "xnd_cb_secret_step1_verified_token_2026"
XENDIT_BIZ_ID = "5f4e3d2c1b0a998877665544"

MIDTRANS_SERVER_KEY = "Mid-server-step1_verified_secret_key_2026"
MIDTRANS_MERCHANT_ID = "G987654321"

DUITKU_API_KEY = "duitku_api_key_step1_hmac_sha256_secret_2026"
DUITKU_MERCHANT_CODE = "DS12345"


def _build_signer_and_verifier() -> Tuple[ProvenanceSigner, ProvenanceVerifier]:
    signing_keyring = ProvenanceSigningKeyring(
        keys={PROV_KEY_ID: {"private_key_hex": PROV_PRIV_HEX, "status": "ACTIVE"}}
    )
    verify_keyring = signing_keyring.export_public_verification_keyring()
    return ProvenanceSigner(signing_keyring), ProvenanceVerifier(verify_keyring)
class _Step1TransactionalMockDB:
    """In-memory transactional PostgreSQL mock supporting atomic commit/rollback snapshots
    across `tenants`, `orders`, `payment_events`, and `financial_ledger`.
    """

    def __init__(self) -> None:
        self.tenants: Dict[str, Dict[str, Any]] = {
            TENANT_A_UUID: {"id": TENANT_A_UUID, "slug": "onlineboost"},
            TENANT_B_UUID: {"id": TENANT_B_UUID, "slug": "merchant-b"},
        }
        self.orders: Dict[str, Dict[str, Any]] = {}
        for oid in ("ORD-S1-XEN-01", "ORD-S1-MID-01", "ORD-S1-DK-01"):
            self.orders[oid] = {
                "id": oid,
                "tenant_id": TENANT_A_UUID,
                "gross_amount": 249000,
                "amount": 249000,
                "sku_id": "sku-ctwa-scale",
                "product_id": "sku-ctwa-scale",
                "status": "PENDING",
                "payment_status": "PENDING",
                "order_status": "PENDING",
                "fulfillment_status": "UNFULFILLED",
                "paid_at": None,
                "updated_at": None,
            }
        self.payment_events: List[Dict[str, Any]] = []
        self.financial_ledger: List[Dict[str, Any]] = []
        self.fail_on_step: Optional[str] = None
        self.commit_count: int = 0
        self.rollback_count: int = 0
        self._snapshot: Optional[Tuple[Any, Any, Any]] = None

    def connect(self) -> "_Step1TransactionalMockDB":
        if self.fail_on_step == "connect":
            raise RuntimeError("Simulated PostgreSQL connection failure")
        if self._snapshot is None:
            self._snapshot = (
                copy.deepcopy(self.orders),
                copy.deepcopy(self.payment_events),
                copy.deepcopy(self.financial_ledger),
            )
        return self

    def cursor(self) -> "_Step1MockCursor":
        if self._snapshot is None:
            self._snapshot = (
                copy.deepcopy(self.orders),
                copy.deepcopy(self.payment_events),
                copy.deepcopy(self.financial_ledger),
            )
        return _Step1MockCursor(self)

    def commit(self) -> None:
        if self.fail_on_step == "commit":
            raise RuntimeError("Simulated PostgreSQL commit failure")
        self._snapshot = None
        self.commit_count += 1

    def rollback(self) -> None:
        if self._snapshot is not None:
            self.orders, self.payment_events, self.financial_ledger = self._snapshot
            self._snapshot = None
        self.rollback_count += 1
class _Step1MockCursor:
    def __init__(self, db: _Step1TransactionalMockDB) -> None:
        self.db = db
        self._rows: List[Any] = []
        self.rowcount: int = 0

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        norm = " ".join(sql.split()).upper()
        if "FROM ORDERS O INNER JOIN TENANTS T" in norm:
            if self.db.fail_on_step == "select_order":
                raise RuntimeError("Simulated PostgreSQL error on orders lock")
            oid = params[0]
            order = self.db.orders.get(oid)
            if order and order["tenant_id"] in self.db.tenants:
                self._rows = [
                    (
                        order["id"],
                        order["tenant_id"],
                        order["tenant_id"],
                        order["gross_amount"],
                        order["sku_id"],
                        order["status"],
                        order["payment_status"],
                    )
                ]
            else:
                self._rows = []
            self.rowcount = len(self._rows)
        elif "FROM PAYMENT_EVENTS WHERE PROVIDER =" in norm:
            if self.db.fail_on_step == "select_payment_events":
                raise RuntimeError("Simulated PostgreSQL error on payment_events select")
            prov, ev_id, prov_ev_id = params[0], params[1], params[2]
            matched = [
                r
                for r in self.db.payment_events
                if r["provider"] == prov and (r["event_id"] == ev_id or r["provider_event_id"] == prov_ev_id)
            ]
            if "S2S_LEASE_EXPIRES_AT" in norm:
                self._rows = [
                    (
                        r["event_id"],
                        r["provider_event_id"],
                        r["order_id"],
                        r["tenant_id"],
                        r["amount"],
                        r["status"],
                        r.get("s2s_verification_status"),
                        r.get("s2s_lease_expires_at"),
                        r.get("s2s_claimed_by"),
                        r.get("s2s_attempt_count", 0),
                    )
                    for r in matched
                ]
            else:
                self._rows = [
                    (
                        r["event_id"],
                        r["provider_event_id"],
                        r["order_id"],
                        r["tenant_id"],
                        r["amount"],
                        r["status"],
                        r.get("payload", {}),
                        r.get("s2s_verification_status"),
                    )
                    for r in matched
                ]
            self.rowcount = len(self._rows)
        elif "INSERT INTO PAYMENT_EVENTS" in norm and "'S2S_IN_FLIGHT'" in norm:
            if self.db.fail_on_step == "insert_payment_events":
                raise RuntimeError("Simulated PostgreSQL error on payment_events S2S claim insert")
            ev_id, prov_ev_id, ref_id, ord_id, t_id, amt, c_at, l_exp, w_id, cr_at, up_at = params
            if any(
                r["provider"] == "DUITKU"
                and (r["event_id"] == ev_id or (r["provider_event_id"] is not None and r["provider_event_id"] == prov_ev_id))
                for r in self.db.payment_events
            ):
                self._rows = []
                self.rowcount = 0
                return
            self.db.payment_events.append(
                {
                    "provider": "DUITKU",
                    "event_id": ev_id,
                    "provider_event_id": prov_ev_id,
                    "reference_id": ref_id,
                    "order_id": ord_id,
                    "tenant_id": t_id,
                    "event_type": "PAYMENT_PENDING",
                    "amount": amt,
                    "status": "PROCESSING",
                    "record_classification": "STAGE3_SETTLEMENT",
                    "payload": {},
                    "raw_payload": {},
                    "s2s_verification_status": "S2S_IN_FLIGHT",
                    "s2s_claimed_at": c_at,
                    "s2s_lease_expires_at": l_exp,
                    "s2s_claimed_by": w_id,
                    "s2s_attempt_count": 1,
                    "s2s_last_error": None,
                    "created_at": cr_at,
                    "updated_at": up_at,
                }
            )
            self._rows = [(ev_id, 1)]
            self.rowcount = 1
        elif "INSERT INTO PAYMENT_EVENTS" in norm:
            if self.db.fail_on_step == "insert_payment_events":
                raise RuntimeError("Simulated PostgreSQL error on payment_events insert")
            prov, ev_id, ref_id, payload_json, p_at, c_at, u_at, ord_id, prov_ev_id, amt, raw_json, t_id = params
            ev_type = "PAYMENT_SETTLED_LATE" if "PAYMENT_SETTLED_LATE" in norm else "PAYMENT_SETTLED"
            status = "QUARANTINED_LATE_SETTLEMENT" if "QUARANTINED_LATE_SETTLEMENT" in norm else "PROCESSED"
            if any(r["provider"] == prov and r["event_id"] == ev_id for r in self.db.payment_events):
                self._rows = []
                self.rowcount = 0
                return
            if any(
                r["provider"] == prov and r["provider_event_id"] is not None and r["provider_event_id"] == prov_ev_id
                for r in self.db.payment_events
            ):
                raise RuntimeError("duplicate key value violates unique constraint uq_payment_events_provider_provider_event_id")
            self.db.payment_events.append(
                {
                    "provider": prov,
                    "event_id": ev_id,
                    "reference_id": ref_id,
                    "event_type": ev_type,
                    "payload": json.loads(payload_json),
                    "status": status,
                    "record_classification": "STAGE3_SETTLEMENT",
                    "processed_at": p_at,
                    "created_at": c_at,
                    "updated_at": u_at,
                    "order_id": ord_id,
                    "provider_event_id": prov_ev_id,
                    "amount": amt,
                    "raw_payload": json.loads(raw_json),
                    "tenant_id": t_id,
                }
            )
            self._rows = [(ev_id,)]
            self.rowcount = 1
        elif "UPDATE PAYMENT_EVENTS" in norm and "SET S2S_VERIFICATION_STATUS = 'S2S_IN_FLIGHT'" in norm:
            c_at, l_exp, w_id, up_at, ev_id = params
            self._rows = []
            self.rowcount = 0
            for r in self.db.payment_events:
                if r["provider"] == "DUITKU" and r["event_id"] == ev_id and r["status"] == "PROCESSING":
                    r["s2s_verification_status"] = "S2S_IN_FLIGHT"
                    r["s2s_claimed_at"] = c_at
                    r["s2s_lease_expires_at"] = l_exp
                    r["s2s_claimed_by"] = w_id
                    r["s2s_attempt_count"] = int(r.get("s2s_attempt_count", 0)) + 1
                    r["updated_at"] = up_at
                    self._rows = [(r["s2s_attempt_count"],)]
                    self.rowcount = 1
                    break
        elif "UPDATE PAYMENT_EVENTS" in norm and "SET S2S_VERIFICATION_STATUS = 'S2S_RETRYABLE_FAILURE'" in norm:
            err_msg, up_at, ev_id, w_id, att = params
            self._rows = []
            self.rowcount = 0
            for r in self.db.payment_events:
                if (
                    r["provider"] == "DUITKU"
                    and r["event_id"] == ev_id
                    and r["status"] == "PROCESSING"
                    and r.get("s2s_claimed_by") == w_id
                    and int(r.get("s2s_attempt_count", 0)) == int(att)
                ):
                    r["s2s_verification_status"] = "S2S_RETRYABLE_FAILURE"
                    r["s2s_last_error"] = err_msg
                    r["updated_at"] = up_at
                    self.rowcount = 1
                    break
        elif "UPDATE PAYMENT_EVENTS" in norm and "SET S2S_VERIFICATION_STATUS = 'S2S_VERIFIED'" in norm:
            v_at, s_code, s_ref, s_resp, up_at, ev_id, w_id, att, fin_at = params
            self._rows = []
            self.rowcount = 0
            for r in self.db.payment_events:
                l_exp = r.get("s2s_lease_expires_at")
                if (
                    r["provider"] == "DUITKU"
                    and r["event_id"] == ev_id
                    and r["status"] == "PROCESSING"
                    and r.get("s2s_verification_status") == "S2S_IN_FLIGHT"
                    and r.get("s2s_claimed_by") == w_id
                    and int(r.get("s2s_attempt_count", 0)) == int(att)
                    and l_exp is not None
                    and l_exp >= fin_at
                ):
                    r["s2s_verification_status"] = "S2S_VERIFIED"
                    r["s2s_last_error"] = None
                    r["s2s_verified_at"] = v_at
                    r["s2s_status_code"] = s_code
                    r["s2s_reference"] = s_ref
                    r["s2s_response_payload"] = json.loads(s_resp)
                    r["updated_at"] = up_at
                    self._rows = [(ev_id,)]
                    self.rowcount = 1
                    break
        elif "UPDATE PAYMENT_EVENTS" in norm:
            if self.db.fail_on_step == "update_payment_events":
                raise RuntimeError("Simulated PostgreSQL error on payment_events update")
            payload_json, raw_json, p_at, u_at, prov, ev_id = params
            ev_type = "PAYMENT_SETTLED_LATE" if "PAYMENT_SETTLED_LATE" in norm else "PAYMENT_SETTLED"
            status = "QUARANTINED_LATE_SETTLEMENT" if "QUARANTINED_LATE_SETTLEMENT" in norm else "PROCESSED"
            self._rows = []
            self.rowcount = 0
            for r in self.db.payment_events:
                if r["provider"] == prov and r["event_id"] == ev_id and r["status"] == "PROCESSING":
                    r["event_type"] = ev_type
                    r["payload"] = json.loads(payload_json)
                    r["raw_payload"] = json.loads(raw_json)
                    r["status"] = status
                    r["processed_at"] = p_at
                    r["updated_at"] = u_at
                    if prov == "DUITKU":
                        r["s2s_verification_status"] = "S2S_VERIFIED"
                    self._rows = [(ev_id,)]
                    self.rowcount = 1
                    break
        elif "UPDATE ORDERS SET STATUS = 'PAID'" in norm:
            if self.db.fail_on_step == "update_orders":
                raise RuntimeError("Simulated PostgreSQL error on orders update")
            paid_at, updated_at, ord_id, t_id, amt = params
            order = self.db.orders.get(ord_id)
            if (
                order
                and order["tenant_id"] == t_id
                and order["gross_amount"] == amt
                and order["status"].upper() in ("PENDING", "WAITING_PAYMENT", "UNPAID", "")
            ):
                order["status"] = "PAID"
                order["payment_status"] = "PAID"
                order["order_status"] = "PAID"
                order["fulfillment_status"] = "PENDING_STAGE4_VERIFICATION"
                order["paid_at"] = order["paid_at"] or paid_at
                order["updated_at"] = updated_at
                self.rowcount = 1
            else:
                self.rowcount = 0
        elif "INSERT INTO FINANCIAL_LEDGER" in norm:
            if self.db.fail_on_step == "insert_financial_ledger":
                raise RuntimeError("Simulated PostgreSQL error on financial_ledger insert")
            ord_id, t_id, prov, ev_id, gross, meta_json, c_at, chk_ord_id = params
            if not any(
                l["order_id"] == chk_ord_id and l["transaction_type"] == "PAYMENT_CREDIT"
                for l in self.db.financial_ledger
            ):
                self.db.financial_ledger.append(
                    {
                        "order_id": ord_id,
                        "tenant_id": t_id,
                        "provider": prov,
                        "event_id": ev_id,
                        "gross_amount": gross,
                        "fee_amount": None,
                        "net_amount": None,
                        "currency": "IDR",
                        "transaction_type": "PAYMENT_CREDIT",
                        "status": "SETTLED",
                        "transaction_status": "SETTLED",
                        "reconciliation_status": "PENDING_RECONCILIATION",
                        "metadata": json.loads(meta_json),
                        "created_at": c_at,
                    }
                )
                self.rowcount = 1
            else:
                self.rowcount = 0
        else:
            raise AssertionError(f"Unexpected SQL in _Step1MockCursor: {sql}")

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> List[Any]:
        return list(self._rows)
def test_01_provider_and_verification_method_allowlist() -> None:
    """Test Boundary #1 & Finding A: Stage 3 Native PG policy is separated from global policy,
    Stage 3 permits strictly XENDIT, MIDTRANS, DUITKU; DOKU, STRIPE, MANUAL_BANK_MUTATION,
    DODO/DODO_MOR and legacy MD5 remain locked/rejected; and PaymentEventBase preserves
    LEGACY_HISTORICAL compatibility while enforcing STAGE3_SETTLEMENT allowlist.
    """
    assert STAGE3_NATIVE_PG_ALLOWED_PROVIDERS == frozenset({"XENDIT", "MIDTRANS", "DUITKU"})
    assert STAGE3_NATIVE_PG_ALLOWED_VERIFICATION_METHODS == frozenset(
        {"XENDIT_CALLBACK_TOKEN", "MIDTRANS_SHA512", "DUITKU_CALLBACK_HMAC_SHA256"}
    )
    assert ALLOWED_PROVIDERS == STAGE3_NATIVE_PG_ALLOWED_PROVIDERS
    assert ALLOWED_VERIFICATION_METHODS == STAGE3_NATIVE_PG_ALLOWED_VERIFICATION_METHODS
    assert LOCKED_UNAUTHORIZED_PROVIDERS.isdisjoint(ALLOWED_PROVIDERS)
    assert LOCKED_UNAUTHORIZED_VERIFICATION_METHODS.isdisjoint(ALLOWED_VERIFICATION_METHODS)
    assert STAGE3_NATIVE_PG_PROVIDER_METHOD_MAP["XENDIT"] == frozenset({"XENDIT_CALLBACK_TOKEN"})
    assert STAGE3_NATIVE_PG_PROVIDER_METHOD_MAP["MIDTRANS"] == frozenset({"MIDTRANS_SHA512"})
    assert STAGE3_NATIVE_PG_PROVIDER_METHOD_MAP["DUITKU"] == frozenset({"DUITKU_CALLBACK_HMAC_SHA256"})

    # Verify cross-provider verification_method mismatch is rejected on Native PG boundary
    with pytest.raises(SettlementProvenanceError) as exc_cross_meth:
        TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="XENDIT",
            verification_method="MIDTRANS_SHA512",
            credential_profile_id="cred_1",
            expected_provider_account_id=XENDIT_BIZ_ID,
            provider_verification_secret=XENDIT_SECRET,
            webhook_headers={"x-callback-token": XENDIT_SECRET},
            webhook_payload={"id": "evt_1", "business_id": XENDIT_BIZ_ID, "status": "PAID", "amount": 249000},
            authoritative_order_id="ORD-S1-XEN-01",
            authoritative_canonical_tenant_id=TENANT_A_UUID,
            authoritative_order_amount=249000,
            authoritative_sku_id="sku-ctwa-scale",
            verified_at_utc="2026-11-06T00:00:00Z",
        )
    assert exc_cross_meth.value.error_code == "PROVENANCE_INVALID_VERIFICATION_METHOD"

    # Verify PaymentEventBase schema compatibility for LEGACY_HISTORICAL vs STAGE3_SETTLEMENT
    from app.schemas.payment_event import PaymentEventBase

    legacy_rec = PaymentEventBase(
        tenant_id=TENANT_A_UUID,
        order_id="ORD-HIST-COMPAT-01",
        provider="qris_dynamic",
        event_id="evt_hist_compat_01",
        provider_event_id="rrn_hist_compat_01",
        event_type="PAYMENT_SETTLED",
        record_classification="LEGACY_HISTORICAL",
    )
    assert legacy_rec.record_classification == "LEGACY_HISTORICAL"
    assert legacy_rec.provider == "qris_dynamic"

    for forbidden_provider in ("DODO", "DODO_MOR", "STRIPE", "DOKU", "MANUAL_BANK_MUTATION"):
        with pytest.raises(SettlementProvenanceError) as exc_prov:
            TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
                provider=forbidden_provider,
                verification_method="XENDIT_CALLBACK_TOKEN",
                credential_profile_id="cred_1",
                expected_provider_account_id=XENDIT_BIZ_ID,
                provider_verification_secret=XENDIT_SECRET,
                webhook_headers={"x-callback-token": XENDIT_SECRET},
                webhook_payload={"id": "evt_1", "business_id": XENDIT_BIZ_ID, "status": "PAID", "amount": 249000},
                authoritative_order_id="ORD-S1-XEN-01",
                authoritative_canonical_tenant_id=TENANT_A_UUID,
                authoritative_order_amount=249000,
                authoritative_sku_id="sku-ctwa-scale",
                verified_at_utc="2026-11-06T00:00:00Z",
            )
        assert exc_prov.value.error_code == "PROVENANCE_INVALID_PROVIDER"
        assert exc_prov.value.http_status == 403

    for forbidden_method in (
        "DUITKU_CALLBACK_MD5",
        "DOKU_HMAC_SHA256",
        "MAKER_CHECKER_BANK_MUTATION",
        "XENDIT_WEBHOOK_SIGNATURE",
    ):
        with pytest.raises(SettlementProvenanceError) as exc_meth:
            TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
                provider="DUITKU",
                verification_method=forbidden_method,
                credential_profile_id="cred_1",
                expected_provider_account_id=DUITKU_MERCHANT_CODE,
                provider_verification_secret=DUITKU_API_KEY,
                webhook_headers={},
                webhook_payload={},
                authoritative_order_id="ORD-S1-DK-01",
                authoritative_canonical_tenant_id=TENANT_A_UUID,
                authoritative_order_amount=249000,
                authoritative_sku_id="sku-ctwa-scale",
                verified_at_utc="2026-11-06T00:00:00Z",
            )
        assert exc_meth.value.error_code == "PROVENANCE_INVALID_VERIFICATION_METHOD"
        assert exc_meth.value.http_status == 403
def test_02_midtrans_capture_and_settlement_fraud_status_matrix() -> None:
    """Test Boundary #2: Midtrans `capture` is ONLY accepted if `fraud_status == "accept"`.
    `capture` with `challenge`, `deny`, or `""` is rejected with `PG_WEBHOOK_NOT_SETTLED`.
    """
    sig = hashlib.sha512(
        f"ORD-S1-MID-01200249000.00{MIDTRANS_SERVER_KEY}".encode("utf-8")
    ).hexdigest().lower()

    for bad_fraud in ("challenge", "deny", ""):
        with pytest.raises(SettlementProvenanceError) as exc_cap:
            TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
                provider="MIDTRANS",
                verification_method="MIDTRANS_SHA512",
                credential_profile_id="cred_mid_01",
                expected_provider_account_id=MIDTRANS_MERCHANT_ID,
                provider_verification_secret=MIDTRANS_SERVER_KEY,
                webhook_headers={},
                webhook_payload={
                    "order_id": "ORD-S1-MID-01",
                    "status_code": "200",
                    "gross_amount": "249000.00",
                    "signature_key": sig,
                    "merchant_id": MIDTRANS_MERCHANT_ID,
                    "transaction_status": "capture",
                    "fraud_status": bad_fraud,
                    "transaction_id": "mid_tx_cap_01",
                },
                authoritative_order_id="ORD-S1-MID-01",
                authoritative_canonical_tenant_id=TENANT_A_UUID,
                authoritative_order_amount=249000,
                authoritative_sku_id="sku-ctwa-scale",
                verified_at_utc="2026-11-06T00:00:00Z",
            )
        assert exc_cap.value.error_code == "PG_WEBHOOK_NOT_SETTLED"

    cap_ok = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="MIDTRANS",
        verification_method="MIDTRANS_SHA512",
        credential_profile_id="cred_mid_01",
        expected_provider_account_id=MIDTRANS_MERCHANT_ID,
        provider_verification_secret=MIDTRANS_SERVER_KEY,
        webhook_headers={},
        webhook_payload={
            "order_id": "ORD-S1-MID-01",
            "status_code": "200",
            "gross_amount": "249000.00",
            "signature_key": sig,
            "merchant_id": MIDTRANS_MERCHANT_ID,
            "transaction_status": "capture",
            "fraud_status": "accept",
            "transaction_id": "mid_tx_cap_ok",
        },
        authoritative_order_id="ORD-S1-MID-01",
        authoritative_canonical_tenant_id=TENANT_A_UUID,
        authoritative_order_amount=249000,
        authoritative_sku_id="sku-ctwa-scale",
        verified_at_utc="2026-11-06T00:00:00Z",
    )
    assert cap_ok.provider == "MIDTRANS"
    assert cap_ok.verified_amount == 249000

    # Fractional sen "249000.50" must be rejected as PROVENANCE_INVALID_AMOUNT
    sig_frac = hashlib.sha512(
        f"ORD-S1-MID-01200249000.50{MIDTRANS_SERVER_KEY}".encode("utf-8")
    ).hexdigest().lower()
    with pytest.raises(SettlementProvenanceError) as exc_frac:
        TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="MIDTRANS",
            verification_method="MIDTRANS_SHA512",
            credential_profile_id="cred_mid_01",
            expected_provider_account_id=MIDTRANS_MERCHANT_ID,
            provider_verification_secret=MIDTRANS_SERVER_KEY,
            webhook_headers={},
            webhook_payload={
                "order_id": "ORD-S1-MID-01",
                "status_code": "200",
                "gross_amount": "249000.50",
                "signature_key": sig_frac,
                "merchant_id": MIDTRANS_MERCHANT_ID,
                "transaction_status": "settlement",
                "fraud_status": "accept",
                "transaction_id": "mid_tx_frac",
            },
            authoritative_order_id="ORD-S1-MID-01",
            authoritative_canonical_tenant_id=TENANT_A_UUID,
            authoritative_order_amount=249000,
            authoritative_sku_id="sku-ctwa-scale",
            verified_at_utc="2026-11-06T00:00:00Z",
        )
    assert exc_frac.value.error_code == "PROVENANCE_INVALID_AMOUNT"
def test_03_duitku_hmac_sha256_and_s2s_single_call_pre_s2s_idempotency() -> None:
    """Test Boundary #3 & Finding B: Duitku callback uses HMAC-SHA256(merchantCode + amount + merchantOrderId, apiKey)
    with constant-time compare, durable DB-backed claim/lease (`payment_events`) with zero in-memory dict/Lock,
    single S2S `transactionStatus` call per transaction, active lease contention, expired lease takeover,
    and stale-worker fencing.
    """
    assert not hasattr(TrustedSettlementVerificationBoundary, "_duitku_s2s_lock")
    assert not hasattr(TrustedSettlementVerificationBoundary, "_duitku_s2s_verified_events")

    shared_db = _Step1TransactionalMockDB()
    cb_sig = hmac.new(
        DUITKU_API_KEY.encode("utf-8"),
        f"{DUITKU_MERCHANT_CODE}249000ORD-S1-DK-01".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().lower()
    expected_s2s_sig = hmac.new(
        DUITKU_API_KEY.encode("utf-8"),
        f"{DUITKU_MERCHANT_CODE}ORD-S1-DK-01".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().lower()
    legacy_md5 = hashlib.md5(
        f"{DUITKU_MERCHANT_CODE}249000ORD-S1-DK-01{DUITKU_API_KEY}".encode("utf-8")
    ).hexdigest().lower()

    s2s_calls: List[Dict[str, Any]] = []

    def s2s_stub(req: Mapping[str, Any]) -> Mapping[str, Any]:
        s2s_calls.append(dict(req))
        assert req["merchantCode"] == DUITKU_MERCHANT_CODE
        assert req["merchantOrderId"] == "ORD-S1-DK-01"
        assert req["signature"] == expected_s2s_sig
        assert req["signature"] != cb_sig
        return {
            "merchantOrderId": "ORD-S1-DK-01",
            "reference": "DS1234520260001",
            "amount": "249000",
            "statusCode": "00",
        }

    def _call_duitku(
        payload_overrides: Dict[str, Any],
        order_id: str = "ORD-S1-DK-01",
        amt: int = 249000,
        worker_id: str = "verifier-1",
        lease_sec: int = 15,
        verifier_fn: Any = s2s_stub,
        conn_factory: Any = shared_db.connect,
    ) -> VerifiedSettlementCapability:
        payload = {
            "merchantCode": DUITKU_MERCHANT_CODE,
            "amount": "249000",
            "merchantOrderId": "ORD-S1-DK-01",
            "signature": cb_sig,
            "resultCode": "00",
            "reference": "DS1234520260001",
        }
        payload.update(payload_overrides)
        return TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
            provider="DUITKU",
            verification_method="DUITKU_CALLBACK_HMAC_SHA256",
            credential_profile_id="cred_dk_01",
            expected_provider_account_id=DUITKU_MERCHANT_CODE,
            provider_verification_secret=DUITKU_API_KEY,
            webhook_headers={},
            webhook_payload=payload,
            authoritative_order_id=order_id,
            authoritative_canonical_tenant_id=TENANT_A_UUID,
            authoritative_order_amount=amt,
            authoritative_sku_id="sku-ctwa-scale",
            verified_at_utc="2026-11-06T00:00:00Z",
            duitku_s2s_verifier=verifier_fn,
            db_conn_factory=conn_factory,
            s2s_worker_id=worker_id,
            s2s_lease_seconds=lease_sec,
        )

    with pytest.raises(SettlementProvenanceError) as exc_no_db:
        _call_duitku({}, conn_factory=None)
    assert exc_no_db.value.error_code == "DATABASE_UNAVAILABLE"

    for bad_sig in ("0" * 64, legacy_md5, ""):
        with pytest.raises(SettlementProvenanceError) as exc_sig:
            _call_duitku({"signature": bad_sig})
        assert exc_sig.value.error_code == "PG_WEBHOOK_SIGNATURE_INVALID"
    assert len(s2s_calls) == 0

    def stalled_worker_a(req: Mapping[str, Any]) -> Mapping[str, Any]:
        cap_b = _call_duitku({}, worker_id="verifier-2", lease_sec=15, verifier_fn=s2s_stub)
        assert cap_b.provider_event_id == "DS1234520260001"
        return {"merchantOrderId": "ORD-S1-DK-01", "reference": "DS1234520260001", "amount": "249000", "statusCode": "00"}

    with pytest.raises(SettlementProvenanceError) as exc_stale:
        _call_duitku({}, worker_id="verifier-1-stale", lease_sec=-5, verifier_fn=stalled_worker_a)
    assert exc_stale.value.error_code == "DUITKU_S2S_STALE_WORKER_FENCED"
    assert exc_stale.value.http_status == 409
    assert len(s2s_calls) == 1
    assert shared_db.payment_events[0]["s2s_attempt_count"] == 2
    assert shared_db.payment_events[0]["s2s_claimed_by"] == "verifier-2"

    cap_2 = _call_duitku({}, worker_id="verifier-2")
    assert len(s2s_calls) == 1
    assert cap_2.event_id == f"duitku:{DUITKU_MERCHANT_CODE}:DS1234520260001"

    cb_sig_conflict = hmac.new(
        DUITKU_API_KEY.encode("utf-8"),
        f"{DUITKU_MERCHANT_CODE}150000ORD-S1-DK-02".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().lower()
    with pytest.raises(SettlementProvenanceError) as exc_conf:
        _call_duitku(
            {"amount": "150000", "merchantOrderId": "ORD-S1-DK-02", "signature": cb_sig_conflict},
            order_id="ORD-S1-DK-02",
            amt=150000,
        )
    assert exc_conf.value.error_code == "CONFLICTING_PAYMENT_EVENT_REPLAY"
    assert exc_conf.value.http_status == 409
    assert len(s2s_calls) == 1
def test_04_capability_minting_and_ed25519_provenance_verification() -> None:
    """Test Boundary #4: Direct instantiation of VerifiedSettlementCapability is blocked;
    Ed25519 signing and public-key verification succeed for boundary-minted capabilities
    and reject tampered envelopes.
    """
    with pytest.raises(SettlementProvenanceError) as exc_forge:
        VerifiedSettlementCapability(
            proof_source="VERIFIED_PG_WEBHOOK_ADAPTER",
            actor_principal="pg_webhook:xendit:cred_1",
            canonical_tenant_id=TENANT_A_UUID,
            credential_profile_id="cred_1",
            event_id="evt_forged",
            order_id="ORD-S1-XEN-01",
            provider="XENDIT",
            provider_account_id=XENDIT_BIZ_ID,
            provider_event_id="qrpy_forged",
            rail_type="NATIVE_PG",
            sku_id="sku-ctwa-scale",
            verification_method="XENDIT_CALLBACK_TOKEN",
            verified_amount=249000,
            verified_at_utc="2026-11-06T00:00:00Z",
        )
    assert exc_forge.value.error_code == "UNTRUSTED_PROVENANCE_CALLER"

    signer, verifier = _build_signer_and_verifier()
    cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="XENDIT",
        verification_method="XENDIT_CALLBACK_TOKEN",
        credential_profile_id="cred_xen_01",
        expected_provider_account_id=XENDIT_BIZ_ID,
        provider_verification_secret=XENDIT_SECRET,
        webhook_headers={"x-callback-token": XENDIT_SECRET},
        webhook_payload={
            "id": "evt_xen_01",
            "payment_id": "qrpy_xen_01",
            "business_id": XENDIT_BIZ_ID,
            "external_id": "ORD-S1-XEN-01",
            "status": "SUCCEEDED",
            "amount": 249000,
            "currency": "IDR",
        },
        authoritative_order_id="ORD-S1-XEN-01",
        authoritative_canonical_tenant_id=TENANT_A_UUID,
        authoritative_order_amount=249000,
        authoritative_sku_id="sku-ctwa-scale",
        verified_at_utc="2026-11-06T00:00:00Z",
    )
    envelope = signer.sign_verified_settlement(cap)
    assert len(envelope["fields"]) == 17
    assert set(envelope["fields"].keys()) == set(PROVENANCE_CONTRACT_FIELDS)
    assert len(envelope["signature"]) == 128

    verified = verifier.verify_provenance_envelope(
        envelope,
        expected_order_id="ORD-S1-XEN-01",
        expected_canonical_tenant_id=TENANT_A_UUID,
        expected_amount=249000,
        expected_sku_id="sku-ctwa-scale",
        required_rail_type="NATIVE_PG",
    )
    assert verified["actor_principal"] == "pg_webhook:xendit:cred_xen_01"

    tampered = copy.deepcopy(envelope)
    tampered["fields"]["verified_amount"] = 1500
    with pytest.raises(SettlementProvenanceError) as exc_tamper:
        verifier.verify_provenance_envelope(tampered)
    assert exc_tamper.value.error_code == "PROVENANCE_SIGNATURE_MISMATCH"
def _mint_xendit_cap_for_order(
    order_id: str,
    event_id: str = "evt_xen_100",
    provider_event_id: str = "qrpy_xen_100",
    amount: int = 249000,
    sku_id: str = "sku-ctwa-scale",
) -> Tuple[VerifiedSettlementCapability, Dict[str, Any]]:
    payload = {
        "id": event_id,
        "event_id": event_id,
        "payment_id": provider_event_id,
        "business_id": XENDIT_BIZ_ID,
        "external_id": order_id,
        "status": "PAID",
        "amount": amount,
        "currency": "IDR",
    }
    cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="XENDIT",
        verification_method="XENDIT_CALLBACK_TOKEN",
        credential_profile_id="cred_xen_01",
        expected_provider_account_id=XENDIT_BIZ_ID,
        provider_verification_secret=XENDIT_SECRET,
        webhook_headers={"x-callback-token": XENDIT_SECRET},
        webhook_payload=payload,
        authoritative_order_id=order_id,
        authoritative_canonical_tenant_id=TENANT_A_UUID,
        authoritative_order_amount=amount,
        authoritative_sku_id=sku_id,
        verified_at_utc="2026-11-06T00:00:00Z",
    )
    return cap, payload


def test_05_atomic_settlement_persistence_and_ledger_outbox_invariants() -> None:
    """Test Boundary #5 & #7 & #8: Atomic persistence of order update, payment_events,
    financial_ledger (fee_amount=NULL, net_amount=NULL, PENDING_RECONCILIATION),
    outbox (PENDING_STAGE4_VERIFICATION), and strictly zero fulfillment/CAPI.
    """
    db = _Step1TransactionalMockDB()
    signer, verifier = _build_signer_and_verifier()
    cap, raw_payload = _mint_xendit_cap_for_order("ORD-S1-XEN-01")

    res = commit_verified_settlement_transaction(
        capability=cap,
        signer=signer,
        verifier=verifier,
        raw_webhook_payload=raw_payload,
        db_conn_factory=db.connect,
    )
    assert res["status"] == "PERSISTED"
    assert res["http_status"] == 200
    assert res["idempotent"] is False
    assert res["fulfillment_status"] == "PENDING_STAGE4_VERIFICATION"
    assert res["ledger_reconciliation_status"] == "PENDING_RECONCILIATION"
    assert res["ledger_fee_amount"] is None
    assert res["ledger_net_amount"] is None
    assert res["fulfillment_triggered"] is False
    assert res["capi_triggered"] is False

    assert db.commit_count == 1
    assert db.orders["ORD-S1-XEN-01"]["status"] == "PAID"
    assert db.orders["ORD-S1-XEN-01"]["payment_status"] == "PAID"
    assert db.orders["ORD-S1-XEN-01"]["fulfillment_status"] == "PENDING_STAGE4_VERIFICATION"
    assert len(db.payment_events) == 1
    assert db.payment_events[0]["status"] == "PROCESSED"
    assert db.payment_events[0]["record_classification"] == "STAGE3_SETTLEMENT"
    assert "_provenance" in db.payment_events[0]["payload"]
    assert len(db.financial_ledger) == 1
    ledger = db.financial_ledger[0]
    assert ledger["gross_amount"] == 249000
    assert ledger["fee_amount"] is None
    assert ledger["net_amount"] is None
    assert ledger["transaction_status"] == "SETTLED"
    assert ledger["reconciliation_status"] == "PENDING_RECONCILIATION"

    # Unregistered ghost order -> 404 ORDER_NOT_FOUND with zero auto-insert
    ghost_cap, ghost_payload = _mint_xendit_cap_for_order("ORD-GHOST-404", "evt_ghost", "qrpy_ghost")
    with pytest.raises(SettlementProvenanceError) as exc_ghost:
        commit_verified_settlement_transaction(
            capability=ghost_cap,
            signer=signer,
            verifier=verifier,
            raw_webhook_payload=ghost_payload,
            db_conn_factory=db.connect,
        )
    assert exc_ghost.value.error_code == "ORDER_NOT_FOUND"
    assert exc_ghost.value.http_status == 404
    assert "ORD-GHOST-404" not in db.orders
def test_06_composite_idempotency_conflicting_replay_and_late_settlement_quarantine() -> None:
    """Test Boundary #6: Duplicate idempotency on (provider, event_id) / (provider, provider_event_id),
    cross-provider composite key isolation, conflicting replay (409), and CTO Decision #4
    late settlement quarantine on EXPIRED / CANCELLED / FAILED orders.
    """
    db = _Step1TransactionalMockDB()
    signer, verifier = _build_signer_and_verifier()

    cap1, payload1 = _mint_xendit_cap_for_order("ORD-S1-XEN-01", "evt_shared_01", "qrpy_shared_01")
    res1 = commit_verified_settlement_transaction(cap1, signer, verifier, payload1, db.connect)
    assert res1["status"] == "PERSISTED"

    # 1. Identical replay -> ALREADY_PROCESSED (no extra payment_events or ledger row)
    res_dup = commit_verified_settlement_transaction(cap1, signer, verifier, payload1, db.connect)
    assert res_dup["status"] == "ALREADY_PROCESSED"
    assert res_dup["idempotent"] is True
    assert len(db.payment_events) == 1
    assert len(db.financial_ledger) == 1

    # 2. Same event_id on a DIFFERENT provider (MIDTRANS) succeeds (composite uniqueness)
    mid_sig = hashlib.sha512(f"ORD-S1-MID-01200249000.00{MIDTRANS_SERVER_KEY}".encode("utf-8")).hexdigest().lower()
    mid_payload = {
        "order_id": "ORD-S1-MID-01",
        "status_code": "200",
        "gross_amount": "249000.00",
        "signature_key": mid_sig,
        "merchant_id": MIDTRANS_MERCHANT_ID,
        "transaction_status": "settlement",
        "fraud_status": "accept",
        "transaction_id": "evt_shared_01",
    }
    mid_cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="MIDTRANS",
        verification_method="MIDTRANS_SHA512",
        credential_profile_id="cred_mid_01",
        expected_provider_account_id=MIDTRANS_MERCHANT_ID,
        provider_verification_secret=MIDTRANS_SERVER_KEY,
        webhook_headers={},
        webhook_payload=mid_payload,
        authoritative_order_id="ORD-S1-MID-01",
        authoritative_canonical_tenant_id=TENANT_A_UUID,
        authoritative_order_amount=249000,
        authoritative_sku_id="sku-ctwa-scale",
        verified_at_utc="2026-11-06T00:00:00Z",
    )
    res_mid = commit_verified_settlement_transaction(mid_cap, signer, verifier, mid_payload, db.connect)
    assert res_mid["status"] == "PERSISTED"
    assert len(db.payment_events) == 2

    # 3. Conflicting replay on (provider, event_id) or (provider, provider_event_id) -> 409
    cap_conf, payload_conf = _mint_xendit_cap_for_order("ORD-S1-DK-01", "evt_shared_01", "qrpy_other_99")
    with pytest.raises(SettlementProvenanceError) as exc_conf:
        commit_verified_settlement_transaction(cap_conf, signer, verifier, payload_conf, db.connect)
    assert exc_conf.value.error_code == "CONFLICTING_PAYMENT_EVENT_REPLAY"
    assert exc_conf.value.http_status == 409

    # 4. CTO Decision #4: Late settlement on EXPIRED, CANCELLED, and FAILED orders
    for idx, late_state in enumerate(("EXPIRED", "CANCELLED", "FAILED"), start=1):
        ord_id = f"ORD-LATE-{idx}"
        db.orders[ord_id] = {
            "id": ord_id,
            "tenant_id": TENANT_A_UUID,
            "gross_amount": 249000,
            "amount": 249000,
            "sku_id": "sku-ctwa-scale",
            "product_id": "sku-ctwa-scale",
            "status": late_state,
            "payment_status": late_state,
            "order_status": late_state,
            "fulfillment_status": "UNFULFILLED",
            "paid_at": None,
            "updated_at": None,
        }
        late_cap, late_payload = _mint_xendit_cap_for_order(ord_id, f"evt_late_{idx}", f"qrpy_late_{idx}")
        ledger_before = len(db.financial_ledger)
        res_late = commit_verified_settlement_transaction(late_cap, signer, verifier, late_payload, db.connect)
        assert res_late["status"] == "QUARANTINED_LATE_SETTLEMENT"
        assert res_late["http_status"] == 200
        assert res_late["fulfillment_triggered"] is False
        assert res_late["capi_triggered"] is False
        assert db.orders[ord_id]["status"] == late_state
        assert db.orders[ord_id]["fulfillment_status"] == "UNFULFILLED"
        assert len(db.financial_ledger) == ledger_before
        quarantined_ev = [e for e in db.payment_events if e["event_id"] == f"evt_late_{idx}"][0]
        assert quarantined_ev["status"] == "QUARANTINED_LATE_SETTLEMENT"
        assert "_provenance" in quarantined_ev["payload"]
def test_07_08_zero_fulfillment_capi_and_ledger_outbox_contract() -> None:
    """Test Boundary #7 & #8: Verifies ledger fee/net NULL + PENDING_RECONCILIATION,
    outbox PENDING_STAGE4_VERIFICATION, and strictly zero Stage 4 fulfillment, entitlement,
    Telegram invite, WhatsApp delivery, Meta CAPI, or TikTok CAPI dispatches.
    """
    import app.core.security.provenance_authority as pa_mod

    src = open(pa_mod.__file__, "r", encoding="utf-8").read()
    for forbidden_dispatch in (
        "createChatInviteLink",
        "send_whatsapp",
        "dispatch_meta_capi",
        "dispatch_tiktok_capi",
        "grant_entitlement",
    ):
        assert forbidden_dispatch not in src

    db = _Step1TransactionalMockDB()
    signer, verifier = _build_signer_and_verifier()
    dk_sig = hmac.new(
        DUITKU_API_KEY.encode("utf-8"),
        f"{DUITKU_MERCHANT_CODE}249000ORD-S1-DK-01".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().lower()
    dk_payload = {
        "merchantCode": DUITKU_MERCHANT_CODE,
        "amount": "249000",
        "merchantOrderId": "ORD-S1-DK-01",
        "signature": dk_sig,
        "resultCode": "00",
        "reference": "DS1234520269999",
    }
    dk_cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
        provider="DUITKU",
        verification_method="DUITKU_CALLBACK_HMAC_SHA256",
        credential_profile_id="cred_dk_01",
        expected_provider_account_id=DUITKU_MERCHANT_CODE,
        provider_verification_secret=DUITKU_API_KEY,
        webhook_headers={},
        webhook_payload=dk_payload,
        authoritative_order_id="ORD-S1-DK-01",
        authoritative_canonical_tenant_id=TENANT_A_UUID,
        authoritative_order_amount=249000,
        authoritative_sku_id="sku-ctwa-scale",
        verified_at_utc="2026-11-06T00:00:00Z",
        duitku_s2s_verifier=lambda req: {
            "merchantOrderId": "ORD-S1-DK-01",
            "reference": "DS1234520269999",
            "amount": "249000",
            "statusCode": "00",
        },
        db_conn_factory=db.connect,
    )
    res = commit_verified_settlement_transaction(dk_cap, signer, verifier, dk_payload, db.connect)
    assert res["status"] == "PERSISTED"
    assert res["fulfillment_status"] == "PENDING_STAGE4_VERIFICATION"
    assert res["ledger_reconciliation_status"] == "PENDING_RECONCILIATION"
    assert res["ledger_fee_amount"] is None
    assert res["ledger_net_amount"] is None
    assert res["fulfillment_triggered"] is False
    assert res["capi_triggered"] is False


def test_09_database_failure_triggers_atomic_rollback_and_fail_closed_503() -> None:
    """Test Boundary #9: Database failure at any step (connect, select_order,
    insert_payment_events, update_orders, insert_financial_ledger, commit)
    triggers full atomic rollback and raises SettlementProvenanceError(DATABASE_UNAVAILABLE, 503).
    """
    signer, verifier = _build_signer_and_verifier()

    for fail_step in (
        "connect",
        "select_order",
        "insert_payment_events",
        "update_orders",
        "insert_financial_ledger",
        "commit",
    ):
        db = _Step1TransactionalMockDB()
        db.fail_on_step = fail_step
        cap, payload = _mint_xendit_cap_for_order(
            "ORD-S1-XEN-01",
            event_id=f"evt_fail_{fail_step}",
            provider_event_id=f"qrpy_fail_{fail_step}",
        )
        with pytest.raises(SettlementProvenanceError) as exc_db:
            commit_verified_settlement_transaction(cap, signer, verifier, payload, db.connect)
        assert exc_db.value.error_code == "DATABASE_UNAVAILABLE"
        assert exc_db.value.http_status == 503
        # Prove atomic rollback: zero partial mutations remain
        assert db.orders["ORD-S1-XEN-01"]["status"] == "PENDING"
        assert db.orders["ORD-S1-XEN-01"]["fulfillment_status"] == "UNFULFILLED"
        assert len(db.payment_events) == 0
        assert len(db.financial_ledger) == 0
        if fail_step != "connect":
            assert db.rollback_count >= 1


EXACT_DISPOSABLE_STEP1_DB_NAME = "bt_stage1_disposable_test_step1"
CURRENT_PROCESS_RUN_ID: str = f"pid{os.getpid()}_{uuid.uuid4().hex[:12]}"
CURRENT_RUN_MARKER: str = f"DISPOSABLE_STEP1_RUN_{CURRENT_PROCESS_RUN_ID}"
# Active in-process ownership guard: maps (effective_dsn, db_name) -> run_marker
_DISPOSABLE_DBS_CREATED_THIS_RUN: Dict[Tuple[str, str], str] = {}


def _get_effective_disposable_pg_dsn() -> Tuple[str, str]:
    """Resolves and validates the effective disposable PostgreSQL DSN and db_name.
    Strictly enforced loopback-only and exact disposable database naming.
    Shared identically across --pg-run, --pg-cleanup, and test_10.
    """
    from urllib.parse import urlparse

    dsn = os.environ.get(
        "STAGE3_STEP1_DISPOSABLE_PG_DSN",
        "postgresql://test_user:test_password@127.0.0.1:5432/bt_stage1_disposable_test_step1",
    ).strip()
    parsed = urlparse(dsn)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise RuntimeError(f"FORBIDDEN_DB_SCHEME: {parsed.scheme}")
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    if os.getenv("TEST_IN_DOCKER_INTERNAL_NET", "").strip() == "1":
        allowed_hosts.add("test-postgres")
    if parsed.hostname not in allowed_hosts:
        raise RuntimeError(f"FORBIDDEN_NON_LOCAL_HOST: {parsed.hostname}")
    db_name = (parsed.path or "").lstrip("/")
    if db_name != EXACT_DISPOSABLE_STEP1_DB_NAME:
        raise RuntimeError(
            f"FORBIDDEN_TARGET_DB_NAME: '{db_name}'. "
            f"Must match exact disposable target '{EXACT_DISPOSABLE_STEP1_DB_NAME}'."
        )
    return dsn, db_name


def _prepare_disposable_pg_step1_db() -> Tuple[str, str]:
    """Creates disposable database `bt_stage1_disposable_test_step1` strictly on local loopback.
    Fails closed if target already exists (orphaned disposable database detected).
    Automatic service startup is strictly disabled.
    Records ownership in _DISPOSABLE_DBS_CREATED_THIS_RUN only upon successful creation and marker stamping.
    """
    import psycopg2
    from urllib.parse import urlparse

    dsn, db_name = _get_effective_disposable_pg_dsn()
    parsed = urlparse(dsn)
    admin_dsn = dsn.rsplit("/", 1)[0] + "/test_boontrack"

    try:
        adm = psycopg2.connect(admin_dsn)
    except psycopg2.OperationalError as conn_err:
        raise RuntimeError(
            f"LOCAL_POSTGRES_UNAVAILABLE: Could not connect to local PostgreSQL at {parsed.hostname}:{parsed.port or 5432}. "
            "Automatic service startup is strictly disabled. Please ensure local PostgreSQL service is running before executing tests. "
            f"Detail: {conn_err}"
        ) from conn_err

    adm.autocommit = True
    try:
        with adm.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (db_name,))
            if cur.fetchone() is not None:
                cur.execute(
                    "SELECT shobj_description(d.oid, 'pg_database') FROM pg_database d WHERE d.datname = %s;",
                    (db_name,),
                )
                m_row = cur.fetchone()
                existing_marker = m_row[0] if m_row else None
                raise RuntimeError(
                    f"DISPOSABLE_DB_ALREADY_EXISTS: Target database '{db_name}' already exists "
                    f"(marker: '{existing_marker}'). An earlier test run may have terminated abruptly, leaving an "
                    "orphaned disposable database. Automatic reuse, reset, or overwrite is strictly prohibited to prevent data loss. "
                    "Manual administrator inspection and removal required before new runs can proceed."
                )
            cur.execute(f'CREATE DATABASE "{db_name}" TEMPLATE template0;')
            cur.execute(f"COMMENT ON DATABASE \"{db_name}\" IS '{CURRENT_RUN_MARKER}';")
            _DISPOSABLE_DBS_CREATED_THIS_RUN[(dsn, db_name)] = CURRENT_RUN_MARKER
    finally:
        adm.close()
    return dsn, db_name


def _drop_disposable_pg_step1_db(dsn: Optional[str] = None, db_name: Optional[str] = None) -> int:
    """Drops the disposable database only if verified to be the exact Step 1 target,
    owned by the currently running process in _DISPOSABLE_DBS_CREATED_THIS_RUN,
    and bearing the matching per-run marker created by this process instance.
    Fails closed if target is not owned by this process or if an orphaned database is detected.
    """
    import psycopg2
    from urllib.parse import urlparse

    eff_dsn, eff_db_name = _get_effective_disposable_pg_dsn()
    target_dsn = dsn or eff_dsn
    target_db_name = db_name or eff_db_name

    # 1. Validate target_db_name against exact target
    if target_db_name != EXACT_DISPOSABLE_STEP1_DB_NAME:
        raise RuntimeError(
            f"FORBIDDEN_DROP_DATABASE_NAME: '{target_db_name}'. "
            f"Cleanup strictly restricted to exact '{EXACT_DISPOSABLE_STEP1_DB_NAME}'."
        )

    # 2. Validate target_dsn host is strictly loopback (or internal docker network)
    parsed = urlparse(target_dsn)
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    if os.getenv("TEST_IN_DOCKER_INTERNAL_NET", "").strip() == "1":
        allowed_hosts.add("test-postgres")
    if parsed.hostname not in allowed_hosts:
        raise RuntimeError(f"FORBIDDEN_NON_LOCAL_HOST: {parsed.hostname}")

    # 3. Ownership Guard: target must have been created by the currently executing process
    if (target_dsn, target_db_name) not in _DISPOSABLE_DBS_CREATED_THIS_RUN:
        # Check if an unowned or orphaned database exists in PostgreSQL
        admin_dsn = target_dsn.rsplit("/", 1)[0] + "/test_boontrack"
        try:
            adm_check = psycopg2.connect(admin_dsn)
            adm_check.autocommit = True
            try:
                with adm_check.cursor() as cur_check:
                    cur_check.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db_name,))
                    if cur_check.fetchone() is not None:
                        cur_check.execute(
                            "SELECT shobj_description(d.oid, 'pg_database') FROM pg_database d WHERE d.datname = %s;",
                            (target_db_name,),
                        )
                        m_row = cur_check.fetchone()
                        orphaned_marker = m_row[0] if m_row else None
                        raise RuntimeError(
                            f"ORPHANED_DISPOSABLE_DB_DETECTED: Target database '{target_db_name}' exists "
                            f"(marker: '{orphaned_marker}'), but was not created by the currently executing process "
                            f"(PID {os.getpid()}). Standalone or cross-process cleanup is forbidden to prevent accidental "
                            "deletion. Manual inspection and removal required."
                        )
            finally:
                adm_check.close()
        except psycopg2.OperationalError:
            pass

        raise RuntimeError(
            f"UNOWNED_DISPOSABLE_DB_DROP_REJECTED: Database '{target_db_name}' is not registered in the current "
            f"process ownership state (_DISPOSABLE_DBS_CREATED_THIS_RUN). Refusing cleanup."
        )

    expected_marker = _DISPOSABLE_DBS_CREATED_THIS_RUN[(target_dsn, target_db_name)]

    admin_dsn = target_dsn.rsplit("/", 1)[0] + "/test_boontrack"
    try:
        adm = psycopg2.connect(admin_dsn)
    except psycopg2.OperationalError as conn_err:
        raise RuntimeError(
            f"LOCAL_POSTGRES_UNAVAILABLE: Could not connect to local PostgreSQL for cleanup. Detail: {conn_err}"
        ) from conn_err

    adm.autocommit = True
    try:
        with adm.cursor() as cur:
            # Check if database exists
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db_name,))
            if cur.fetchone() is None:
                _DISPOSABLE_DBS_CREATED_THIS_RUN.pop((target_dsn, target_db_name), None)
                return 0

            # Guard: check disposable run marker on database matches the expected per-run marker
            cur.execute(
                "SELECT shobj_description(d.oid, 'pg_database') FROM pg_database d WHERE d.datname = %s;",
                (target_db_name,),
            )
            marker_row = cur.fetchone()
            marker = marker_row[0] if marker_row else None
            if marker != expected_marker:
                raise RuntimeError(
                    f"FORBIDDEN_DROP_DATABASE: Target database '{target_db_name}' possesses marker '{marker}', "
                    f"which does not match this process's active run marker '{expected_marker}'. "
                    "Refusing to drop database with mismatched run marker."
                )

            # Terminate active backend connections
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid != pg_backend_pid();",
                (target_db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{target_db_name}";')
            cur.execute("SELECT COUNT(*) FROM pg_database WHERE datname = %s;", (target_db_name,))
            remaining = int(cur.fetchone()[0])
            _DISPOSABLE_DBS_CREATED_THIS_RUN.pop((target_dsn, target_db_name), None)
            return remaining
    finally:
        adm.close()
def test_10_live_disposable_postgres_step1_settlement_and_s2s_concurrency_integration(
    skip_drop: bool = False,
) -> None:
    """Findings B & C: Live local disposable PostgreSQL integration test (`bt_stage1_disposable_test_step1`)
    using Step 0 schema (`033a` + `033b` + `033c`):
    1. Two-instance Duitku S2S concurrency (active lease contention + expired lease takeover + stale worker fencing).
    2. Atomic settlement persistence (`commit_verified_settlement_transaction`) for Xendit, Midtrans, and Duitku.
    3. Composite duplicate idempotency & conflicting replay (HTTP 409).
    4. Late settlement quarantine on EXPIRED/CANCELLED orders (CTO Decision #4).
    5. Financial ledger (`fee_amount IS NULL`, `net_amount IS NULL`, `PENDING_RECONCILIATION`) & outbox (`PENDING_STAGE4_VERIFICATION`).
    6. Mid-transaction PostgreSQL failure rollback (`503 DATABASE_UNAVAILABLE` with 0 partial rows).
    7. Disposable database `DROP DATABASE` cleanup verified (`remaining_db_count == 0`).
    """
    from decimal import Decimal
    import psycopg2

    dsn, db_name = _prepare_disposable_pg_step1_db()
    try:
        setup_conn = psycopg2.connect(dsn)
        setup_conn.autocommit = True
        try:
            with setup_conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE public.tenants (
                        id UUID PRIMARY KEY,
                        slug VARCHAR(128) NOT NULL UNIQUE
                    );
                    CREATE TABLE public.orders (
                        id VARCHAR(128) PRIMARY KEY,
                        tenant_id VARCHAR(64) NOT NULL,
                        tenant_slug VARCHAR(128),
                        product_id VARCHAR(128),
                        gross_amount NUMERIC(14, 2) NOT NULL,
                        status VARCHAR(64) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE public.payment_events (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        provider VARCHAR(64) NOT NULL,
                        event_id VARCHAR(128) UNIQUE NOT NULL,
                        provider_event_id VARCHAR(128),
                        reference_id VARCHAR(128),
                        order_id VARCHAR(128),
                        tenant_id VARCHAR(64) NOT NULL,
                        event_type VARCHAR(64) NOT NULL,
                        amount NUMERIC(14, 2),
                        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                        status VARCHAR(64) NOT NULL DEFAULT 'PROCESSING'
                    );
                    CREATE TABLE public.financial_ledger (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        order_id VARCHAR(128) NOT NULL,
                        tenant_id VARCHAR(64) NOT NULL,
                        provider VARCHAR(64) NOT NULL,
                        event_id VARCHAR(128),
                        gross_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
                        fee_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
                        net_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
                        currency VARCHAR(16) NOT NULL DEFAULT 'IDR',
                        transaction_type VARCHAR(64) NOT NULL DEFAULT 'PAYMENT_CREDIT',
                        status VARCHAR(32) NOT NULL DEFAULT 'SETTLED',
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                for mig_name in (
                    "033a_stage3_payment_settlement_expand_phase.sql",
                    "033b_stage3_payment_settlement_migrate_validate_phase.sql",
                    "033c_stage3_payment_settlement_contract_phase.sql",
                ):
                    cur.execute((REPO_ROOT / "migrations" / mig_name).read_text(encoding="utf-8"))

                cur.execute(
                    "INSERT INTO public.tenants (id, slug) VALUES (%s::uuid, 'onlineboost');",
                    (TENANT_A_UUID,),
                )
                for oid, st in (
                    ("ORD-PG-XEN-01", "PENDING"),
                    ("ORD-PG-MID-01", "PENDING"),
                    ("ORD-PG-DK-01", "PENDING"),
                    ("ORD-PG-DK-STALE", "PENDING"),
                    ("ORD-PG-LATE-EXP", "EXPIRED"),
                    ("ORD-PG-LATE-CAN", "CANCELLED"),
                    ("ORD-PG-ROLLBACK", "PENDING"),
                ):
                    cur.execute(
                        """
                        INSERT INTO public.orders (
                            id, tenant_id, tenant_slug, sku_id, product_id, gross_amount, amount,
                            status, payment_status, order_status, fulfillment_status
                        ) VALUES (%s, %s, 'onlineboost', 'sku-ctwa-scale', 'sku-ctwa-scale', 249000, 249000, %s, %s, %s, 'UNFULFILLED');
                        """,
                        (oid, TENANT_A_UUID, st, st, st),
                    )
        finally:
            setup_conn.close()
        signer, verifier = _build_signer_and_verifier()

        class _KeepOpenPGConnection(psycopg2.extensions.connection):
            """Subclass of psycopg2.extensions.connection providing dynamic __dict__
            slot so `_keep_open = True` can be set without C-extension AttributeError.
            """
            pass

        conn_w1 = psycopg2.connect(dsn, connection_factory=_KeepOpenPGConnection)
        conn_w2 = psycopg2.connect(dsn, connection_factory=_KeepOpenPGConnection)
        setattr(conn_w1, "_keep_open", True)
        setattr(conn_w2, "_keep_open", True)
        pg_factory = lambda: conn_w1
        pg_factory_w2 = lambda: conn_w2
        try:
            def _issue_dk_pg(
                order_id: str,
                reference: str,
                worker_id: str,
                lease_sec: int,
                s2s_fn: Any,
                factory_fn: Any = pg_factory,
            ) -> Tuple[VerifiedSettlementCapability, Dict[str, Any]]:
                sig = hmac.new(
                    DUITKU_API_KEY.encode("utf-8"),
                    f"{DUITKU_MERCHANT_CODE}249000{order_id}".encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest().lower()
                payload = {
                    "merchantCode": DUITKU_MERCHANT_CODE,
                    "amount": "249000",
                    "merchantOrderId": order_id,
                    "signature": sig,
                    "resultCode": "00",
                    "reference": reference,
                }
                cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
                    provider="DUITKU",
                    verification_method="DUITKU_CALLBACK_HMAC_SHA256",
                    credential_profile_id="cred_dk_pg",
                    expected_provider_account_id=DUITKU_MERCHANT_CODE,
                    provider_verification_secret=DUITKU_API_KEY,
                    webhook_headers={},
                    webhook_payload=payload,
                    authoritative_order_id=order_id,
                    authoritative_canonical_tenant_id=TENANT_A_UUID,
                    authoritative_order_amount=249000,
                    authoritative_sku_id="sku-ctwa-scale",
                    verified_at_utc="2026-11-06T00:00:00Z",
                    duitku_s2s_verifier=s2s_fn,
                    db_conn_factory=factory_fn,
                    s2s_worker_id=worker_id,
                    s2s_lease_seconds=lease_sec,
                )
                return cap, payload

            # 1a. Active lease contention between two verifier instances (separate PG sessions conn_w1 & conn_w2)
            dk_s2s_calls: List[str] = []

            def active_lease_s2s_worker_1(req: Mapping[str, Any]) -> Mapping[str, Any]:
                dk_s2s_calls.append("worker-1-active")
                with pytest.raises(SettlementProvenanceError) as exc_in_flight:
                    _issue_dk_pg(
                        "ORD-PG-DK-01",
                        "DS12345PG0001",
                        "pg-worker-2-concurrent",
                        15,
                        lambda r: (_ for _ in ()).throw(AssertionError("Worker 2 must not call S2S")),
                        factory_fn=pg_factory_w2,
                    )
                assert exc_in_flight.value.error_code == "DUITKU_S2S_VERIFICATION_IN_FLIGHT"
                assert exc_in_flight.value.http_status == 409
                return {
                    "merchantOrderId": "ORD-PG-DK-01",
                    "reference": "DS12345PG0001",
                    "amount": "249000",
                    "statusCode": "00",
                }

            dk_cap_1, dk_payload_1 = _issue_dk_pg(
                "ORD-PG-DK-01", "DS12345PG0001", "pg-worker-1-active", 15, active_lease_s2s_worker_1, pg_factory
            )
            assert dk_s2s_calls == ["worker-1-active"]

            # 1b. Stale worker lease expiry takeover & fencing on shared PostgreSQL (conn_w1 vs conn_w2)
            def stale_worker_1_s2s(req: Mapping[str, Any]) -> Mapping[str, Any]:
                _issue_dk_pg(
                    "ORD-PG-DK-STALE",
                    "DS12345PGSTALE",
                    "pg-worker-2-takeover",
                    15,
                    lambda r: {
                        "merchantOrderId": "ORD-PG-DK-STALE",
                        "reference": "DS12345PGSTALE",
                        "amount": "249000",
                        "statusCode": "00",
                    },
                    factory_fn=pg_factory_w2,
                )
                return {
                    "merchantOrderId": "ORD-PG-DK-STALE",
                    "reference": "DS12345PGSTALE",
                    "amount": "249000",
                    "statusCode": "00",
                }

            with pytest.raises(SettlementProvenanceError) as exc_pg_stale:
                _issue_dk_pg(
                    "ORD-PG-DK-STALE", "DS12345PGSTALE", "pg-worker-1-stale", -5, stale_worker_1_s2s, pg_factory
                )
            assert exc_pg_stale.value.error_code == "DUITKU_S2S_STALE_WORKER_FENCED"
            assert exc_pg_stale.value.http_status == 409
            # 2. Commit verified settlements across Xendit, Midtrans, and Duitku on live PostgreSQL
            xen_cap, xen_payload = _mint_xendit_cap_for_order("ORD-PG-XEN-01", "evt_pg_xen_01", "qrpy_pg_xen_01")
            res_xen = commit_verified_settlement_transaction(xen_cap, signer, verifier, xen_payload, pg_factory)
            assert res_xen["status"] == "PERSISTED"

            mid_sig = hashlib.sha512(f"ORD-PG-MID-01200249000.00{MIDTRANS_SERVER_KEY}".encode("utf-8")).hexdigest().lower()
            mid_payload = {
                "order_id": "ORD-PG-MID-01",
                "status_code": "200",
                "gross_amount": "249000.00",
                "signature_key": mid_sig,
                "merchant_id": MIDTRANS_MERCHANT_ID,
                "transaction_status": "capture",
                "fraud_status": "accept",
                "transaction_id": "mid_pg_tx_01",
            }
            mid_cap = TrustedSettlementVerificationBoundary.verify_pg_webhook_and_issue_capability(
                provider="MIDTRANS",
                verification_method="MIDTRANS_SHA512",
                credential_profile_id="cred_mid_pg",
                expected_provider_account_id=MIDTRANS_MERCHANT_ID,
                provider_verification_secret=MIDTRANS_SERVER_KEY,
                webhook_headers={},
                webhook_payload=mid_payload,
                authoritative_order_id="ORD-PG-MID-01",
                authoritative_canonical_tenant_id=TENANT_A_UUID,
                authoritative_order_amount=249000,
                authoritative_sku_id="sku-ctwa-scale",
                verified_at_utc="2026-11-06T00:00:00Z",
            )
            res_mid = commit_verified_settlement_transaction(mid_cap, signer, verifier, mid_payload, pg_factory)
            assert res_mid["status"] == "PERSISTED"

            res_dk = commit_verified_settlement_transaction(dk_cap_1, signer, verifier, dk_payload_1, pg_factory)
            assert res_dk["status"] == "PERSISTED"

            # 3. Duplicate & conflicting replay on live PostgreSQL
            res_xen_dup = commit_verified_settlement_transaction(xen_cap, signer, verifier, xen_payload, pg_factory)
            assert res_xen_dup["status"] == "ALREADY_PROCESSED"
            assert res_xen_dup["idempotent"] is True

            xen_conf_cap, xen_conf_payload = _mint_xendit_cap_for_order("ORD-PG-ROLLBACK", "evt_pg_xen_01", "qrpy_pg_other")
            with pytest.raises(SettlementProvenanceError) as exc_pg_conf:
                commit_verified_settlement_transaction(xen_conf_cap, signer, verifier, xen_conf_payload, pg_factory)
            assert exc_pg_conf.value.error_code == "CONFLICTING_PAYMENT_EVENT_REPLAY"
            assert exc_pg_conf.value.http_status == 409

            # 4. Late settlement quarantine on EXPIRED & CANCELLED orders in live PostgreSQL (CTO Decision #4)
            for late_oid, ev_sfx in (("ORD-PG-LATE-EXP", "exp"), ("ORD-PG-LATE-CAN", "can")):
                l_cap, l_payload = _mint_xendit_cap_for_order(late_oid, f"evt_pg_late_{ev_sfx}", f"qrpy_pg_late_{ev_sfx}")
                l_res = commit_verified_settlement_transaction(l_cap, signer, verifier, l_payload, pg_factory)
                assert l_res["status"] == "QUARANTINED_LATE_SETTLEMENT"
                assert l_res["http_status"] == 200
            # 5. Mid-transaction PostgreSQL failure rollback (503 DATABASE_UNAVAILABLE)
            class _FailOnCommitProxy:
                def __init__(self, real_conn: Any) -> None:
                    self._real = real_conn
                    self.autocommit = False
                    self._keep_open = True

                def cursor(self) -> Any:
                    return self._real.cursor()

                def commit(self) -> None:
                    raise RuntimeError("Simulated PostgreSQL commit failure after SQL writes")

                def rollback(self) -> None:
                    self._real.rollback()

            rb_cap, rb_payload = _mint_xendit_cap_for_order("ORD-PG-ROLLBACK", "evt_pg_rb_01", "qrpy_pg_rb_01")
            with pytest.raises(SettlementProvenanceError) as exc_pg_rb:
                commit_verified_settlement_transaction(
                    rb_cap,
                    signer,
                    verifier,
                    rb_payload,
                    lambda: _FailOnCommitProxy(conn_w2),
                )
            assert exc_pg_rb.value.error_code == "DATABASE_UNAVAILABLE"
            assert exc_pg_rb.value.http_status == 503

            # 6. Verify authoritative PostgreSQL table state
            with conn_w1.cursor() as cur:
                cur.execute("SELECT id, status, fulfillment_status FROM public.orders ORDER BY id;")
                orders_map = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
                assert orders_map["ORD-PG-XEN-01"] == ("PAID", "PENDING_STAGE4_VERIFICATION")
                assert orders_map["ORD-PG-MID-01"] == ("PAID", "PENDING_STAGE4_VERIFICATION")
                assert orders_map["ORD-PG-DK-01"] == ("PAID", "PENDING_STAGE4_VERIFICATION")
                assert orders_map["ORD-PG-LATE-EXP"] == ("EXPIRED", "UNFULFILLED")
                assert orders_map["ORD-PG-LATE-CAN"] == ("CANCELLED", "UNFULFILLED")
                assert orders_map["ORD-PG-ROLLBACK"] == ("PENDING", "UNFULFILLED")

                cur.execute(
                    "SELECT order_id, gross_amount, fee_amount, net_amount, transaction_status, reconciliation_status FROM public.financial_ledger ORDER BY order_id;"
                )
                ledger_rows = cur.fetchall()
                assert len(ledger_rows) == 3
                for l_row in ledger_rows:
                    assert l_row[1] == Decimal("249000.00")
                    assert l_row[2] is None
                    assert l_row[3] is None
                    assert l_row[4] == "SETTLED"
                    assert l_row[5] == "PENDING_RECONCILIATION"

                cur.execute(
                    "SELECT event_id, status, s2s_attempt_count, s2s_claimed_by, (payload ? '_provenance') FROM public.payment_events ORDER BY event_id;"
                )
                pe_map = {r[0]: (r[1], r[2], r[3], r[4]) for r in cur.fetchall()}
                assert pe_map["evt_pg_xen_01"][0] == "PROCESSED"
                assert pe_map["evt_pg_xen_01"][3] is True
                assert pe_map[f"duitku:{DUITKU_MERCHANT_CODE}:DS12345PG0001"] == ("PROCESSED", 1, "pg-worker-1-active", True)
                assert pe_map[f"duitku:{DUITKU_MERCHANT_CODE}:DS12345PGSTALE"][1] == 2
                assert pe_map[f"duitku:{DUITKU_MERCHANT_CODE}:DS12345PGSTALE"][2] == "pg-worker-2-takeover"
                assert pe_map["evt_pg_late_exp"][0] == "QUARANTINED_LATE_SETTLEMENT"
                assert pe_map["evt_pg_late_can"][0] == "QUARANTINED_LATE_SETTLEMENT"
                assert "evt_pg_rb_01" not in pe_map
        finally:
            conn_w1.close()
            conn_w2.close()
        print(
            f"[PG_STEP1_INTEGRATION_PROOF] db={db_name} orders_paid=3 late_quarantined=2 "
            f"ledger_rows=3 s2s_fenced=True rollback_verified=True",
            flush=True,
        )
    finally:
        if not skip_drop:
            remaining = _drop_disposable_pg_step1_db(dsn, db_name)
            assert remaining == 0, f"Disposable DB {db_name} was not dropped!"
            print(f"[DISPOSABLE_PG_CLEANUP_PROOF] dropped={db_name} remaining_count={remaining}", flush=True)


if __name__ == "__main__":
    unit_suite = [
        ("1_allowlist", test_01_provider_and_verification_method_allowlist),
        ("2_midtrans_capture_fraud", test_02_midtrans_capture_and_settlement_fraud_status_matrix),
        ("3_duitku_hmac_s2s_single_call", test_03_duitku_hmac_sha256_and_s2s_single_call_pre_s2s_idempotency),
        ("4_capability_minting_ed25519", test_04_capability_minting_and_ed25519_provenance_verification),
        ("5_atomic_settlement_persistence", test_05_atomic_settlement_persistence_and_ledger_outbox_invariants),
        ("6_idempotency_conflict_late_quarantine", test_06_composite_idempotency_conflicting_replay_and_late_settlement_quarantine),
        ("7_8_ledger_outbox_zero_fulfillment_capi", test_07_08_zero_fulfillment_capi_and_ledger_outbox_contract),
        ("9_db_failure_rollback_503", test_09_database_failure_triggers_atomic_rollback_and_fail_closed_503),
    ]
    if "--unit" in sys.argv:
        for label, fn in unit_suite:
            fn()
            print(f"PASSED [{label}] {fn.__name__}", flush=True)
        print(f"ALL {len(unit_suite)} STEP 1 UNIT TESTS PASSED (EXIT_CODE=0)", flush=True)
    elif "--pg-run" in sys.argv:
        test_10_live_disposable_postgres_step1_settlement_and_s2s_concurrency_integration(skip_drop=False)
        print("PASSED [10_live_disposable_pg_integration] (EXIT_CODE=0)", flush=True)
    elif "--pg-cleanup" in sys.argv:
        eff_dsn, eff_db = _get_effective_disposable_pg_dsn()
        rem = _drop_disposable_pg_step1_db(eff_dsn, eff_db)
        assert rem == 0
        print(f"[DISPOSABLE_PG_CLEANUP_PROOF] dropped={eff_db} remaining_count={rem} (EXIT_CODE=0)", flush=True)
    else:
        for label, fn in unit_suite:
            fn()
            print(f"PASSED [{label}] {fn.__name__}", flush=True)
        test_10_live_disposable_postgres_step1_settlement_and_s2s_concurrency_integration(skip_drop=False)
        print("PASSED [10_live_disposable_pg_integration] test_10_live_disposable_postgres_step1_settlement_and_s2s_concurrency_integration", flush=True)
        print("ALL 9 STEP 1 TARGETED + PG INTEGRATION TESTS PASSED (EXIT_CODE=0)", flush=True)
