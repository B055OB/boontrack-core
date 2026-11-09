# COMMISSION WRITER INTEGRITY MATRIX (R3 REMEDIATION — REV 2)

- **Document Ref:** `CTO-P0-PHASE2B-COMMISSION-MATRIX-007C-REV2`
- **Repository:** `B055OB/boontrack-core` (`C:\boontrack-core`)
- **Verified Baseline:** `a82b6fdf76c043c9a3ee87f48c34062f05258437`
- **Scope:** Complete 9-Writer Integrity Matrix, Recipient-to-Eligibility Identity Binding Proof, Legacy/Bypass Path Inventory, Isolated Proposed Patches (`PATCH-R3-A`..`PATCH-R3-F`), Independent Payout Lock Verification
- **Posture:** **STRICT HOLD — DESIGN REVIEW REVISION** (Zero source mutations applied to tracked files; `payout_disbursement_locked()` remains unconditionally active)

---

## 1. COMPLETE 9-WRITER INTEGRITY MATRIX (SOURCE, PAYLOAD, TARGET, ELIGIBILITY, IDEMPOTENCY & FAILURE)

| # | Writer Function & Source Location | Route / Caller Trigger | Target Table & Status | Write Payload Columns | `is_class_1_commission_eligible()` Enforcement | Recipient Identity Binding (`Verified ID == Payload ID`) | Idempotency Key & Mechanism | DB Failure Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `AffiliateService.allocate_upgrade_commission`<br>(`app/services/affiliate_service.py:451–778`) | `process_successful_subscription` (`subscription_service.py:419`) via `/api/v1/shop/subscriptions/webhooks/xendit` | `public.affiliate_commissions` (`status='HOLDING'`) + `_commissions` post-DB cache | `id`, `tenant_id`, `affiliate_id`, `type` (`SUBSCRIPTION_UPGRADE_PRORATED` / `AM_OVERRIDE_UPGRADE`), `amount`, `invoice_id`, `order_id` (`{inv}` / `{inv}_am`), `order_amount`, `status`, `created_at` (`L653–664, 719–730`) | **FULL (Direct `L576` + AM `L711`):**<br>18-col `_AFFILIATE_ELIGIBILITY_COLUMNS` (`L542, 549, 709`); non-Class-1 held (`0` DB writes) | **YES (`PATCH-R3-A` hardened):**<br>Direct writes `valid_aff_id = str(aff_record["id"])` (`L637, 656`); AM writes `valid_am_id = str(am_row["id"])` (`L713, 722`) | Pre-check `.eq("order_id", invoice_id)` (`L608–635`) + `uq_affiliate_commissions_tenant_order` (`tenant_id, order_id`) (`23505` catch at `L670, 734`) | **Fail-Closed:** Raises `RuntimeError` if `supabase is None` (`L530`) or non-`23505` DB error (`L683, 738`); cache written strictly post-DB (`L688, 742`) |
| **2** | `AffiliateService.record_prorated_upgrade_commission`<br>(`app/services/affiliate_service.py:266–431`) | `BillingService.mark_invoice_paid` (`billing_service.py:285`) via `/api/v1/billing/invoices/{id}/pay` & `/api/v1/billing/webhook/payment` | `public.affiliate_commissions` (`status='HOLDING'`) + `_commissions` post-DB cache | `tenant_id`, `affiliate_id`, `order_id`, `order_amount`, `amount`, `status` (`'HOLDING'`), `created_at` (`L400–408`) | **FULL (`L354–377`):**<br>18-col `_AFFILIATE_ELIGIBILITY_COLUMNS` (`L344`); returns `held_manual_review` (`amount=0.0`, `0` DB writes) | **YES (`PATCH-R3-A` hardened):**<br>`resolved_aff_id = str(aff_record["id"])` (`L346`) from the exact `aff_record` checked at `L354`, written to `db_payload["affiliate_id"]` (`L402`) | `.upsert(db_payload, on_conflict="tenant_id, order_id")` (`L409`) + `uq_affiliate_commissions_tenant_order` (`23505` at `L412`) | **Fail-Closed:** Raises `RuntimeError` if `supabase is None` (`L291`) or non-`23505` DB error (`L420`); cache written strictly post-DB (`L426`) |
| **3** | `process_order_paid_growth_event`<br>(`app/services/growth_service.py:92–245`) | `POST /api/v1/growth/simulate/order-paid` (`app/routes/growth_routes.py:118`) | `public.affiliate_commissions` (`status='APPROVED'`) | `tenant_id`, `affiliate_id`, `order_id`, `order_amount`, `amount`, `status` (`'APPROVED'`), `created_at` (`L180–189`) | **FULL (`L154` + `PATCH-R2-B`):**<br>Joins `affiliates a`, hydrates 18-col `_AFFILIATE_ELIGIBILITY_COLUMNS` via `to_jsonb(a)`, enforces `is_class_1_commission_eligible(attribution_info)` | **YES (`PATCH-R2-B`):**<br>Selects `a.id AS verified_affiliate_id` from joined `affiliates a`, binds `aff_id = str(verified_affiliate_id)` written to `affiliate_commissions.affiliate_id` (`L189`) | `uq_affiliate_commissions_tenant_order`: `ON CONFLICT (tenant_id, order_id) DO UPDATE ... WHERE status NOT IN ('APPROVED','PAID','SETTLED')` (`L184–188`) + `rowcount == 0` guard (`L194`) | **Fail-Closed:** `conn.rollback()` (`L209`) and raises `RuntimeError("[GROWTH WORKER FAIL-CLOSED]...")` (`L212`) |
| **4** | `PaymentOrchestrator.process_xendit_webhook`<br>(`app/services/payment_orchestrator.py:82–400`) | `PaymentOrchestrator` (`app/services/payment_orchestrator.py`) | `public.commission_ledger` (`status='PENDING_PAYOUT'`) + `public.affiliate_daily_stats` | `order_id`, `affiliate_id`, `affiliate_code`, `manager_id`, `tenant_slug`, `gross_amount`, `affiliate_commission_rate`, `affiliate_commission_amount`, `manager_override_rate`, `manager_override_amount`, `net_platform_revenue`, `status` (`L289–302`) | **PARTIAL at Baseline (`L249`); FULL in `PATCH-R3-B` (`INT-01`):**<br>Verifies both affiliate and `manager_id` via 18-col `_AFFILIATE_ELIGIBILITY_COLUMNS` & `is_class_1_commission_eligible()` | **REMEDIATED in `PATCH-R3-B`:**<br>Binds `verified_affiliate_id = str(aff_row["id"]) if aff_eligible else None` and `verified_manager_id = str(mgr_row["id"]) if mgr_eligible else None` into `ledger_payload` and `affiliate_daily_stats` | `payment_events` (`event_id`) + `orders` (`status='PAID'`) + `uq_commission_ledger_order_id` (`order_id` UNIQUE, `23505` catch at `L309`) | **Fail-Closed:** Raises `RuntimeError("[Payment FAIL-CLOSED]...")` on `AssertionError` (`net < 70%`) or non-`23505` DB error (`L344–351`) |
| **5** | `create_checkout_order_with_shipping`<br>(`app/services/checkout_shipping_service.py:160–275`) | `POST /api/v1/shipping/checkout-order` (`app/routes/shipping_webhook_routes.py`) | `public.affiliate_commissions` (`status='PENDING'` non-payable reservation) | `tenant_id`, `affiliate_id`, `order_id`, `order_amount` (`int(base_price)`), `amount`, `status` (`'PENDING'`), `created_at` (`L236–243`) | **Hardened in `PATCH-R3-C` (`INT-02`):**<br>Hydrates `_AFFILIATE_ELIGIBILITY_COLUMNS` and enforces `is_class_1_commission_eligible()` on both `referral_code` (`affiliate`) and `manager_id` (`verified_manager`) before inserting `PENDING` row (`0` writes if non-Class-1) | **YES (`PATCH-R3-C`):**<br>Binds `target_aff_id = str(affiliate["id"])` (mitra sale) or `str(verified_manager["id"])` (direct AM sale); raw caller `manager_id` is never written (`L212–229`) | `uq_affiliate_commissions_tenant_order`: `ON CONFLICT (tenant_id, order_id) DO UPDATE SET ... status = 'PENDING'` (`L239–242`) | Atomic transaction `conn.rollback()` (`L272`) and returns `{"success": False, "error": str(e)}` |
| **6** | `reconcile_single_cod_order`<br>(`app/services/cod_settlement_service.py:12–111`) | `POST /api/v1/shipping/cod/reconcile` (`app/routes/shipping_webhook_routes.py`) | `public.affiliate_commissions` (`PENDING` -> `APPROVED` or `HELD_MANUAL_REVIEW`) | `UPDATE affiliate_commissions SET status = 'APPROVED', updated_at = NOW() WHERE order_id = %s AND tenant_id = %s AND affiliate_id = %s` (`L65–70`) | **BYPASS at Baseline (`INT-02`); FULL in `PATCH-R3-C`:**<br>Queries `affiliates` by `pending_comm["affiliate_id"]` and enforces `is_class_1_commission_eligible(aff_rec)` before `APPROVED` promotion | **REMEDIATED in `PATCH-R3-C`:**<br>Verifies `str(aff_rec.get("id")) == str(pending_comm["affiliate_id"])` and scopes `UPDATE ... WHERE order_id = %s AND tenant_id = %s AND affiliate_id = %s` to that verified ID | Keyed by `(tenant_id, order_id, affiliate_id)` inside atomic COD settlement transaction | **Fail-Closed (`PATCH-R3-C`):** `conn.rollback()` (`L107`); ineligible rows quarantined to `HELD_MANUAL_REVIEW` (`amount = 0`) with zero WA dispatch |
| **7a** | `_record_settlement_and_ledger_sync`<br>(`app/routes/xendit.py:404–665`) | `process_xendit_webhook_core` (`xendit.py:1006`) via `/api/v1/payments/xendit/callback`, `/webhook/xendit` | `public.commission_ledger` (`status='PENDING_PAYOUT'`) | `event_type`, `reference_id`, `affiliate_id`, `order_id`, `affiliate_code`, `manager_id`, `tenant_slug`, `gross_amount`, `commission_amount`, `payout_status`, `affiliate_commission_rate`, `affiliate_commission_amount`, `manager_override_rate`, `manager_override_amount`, `net_platform_revenue`, `status`, `created_at` (`L552–583`) | **BYPASS at Baseline (`INT-03a`); FULL in `PATCH-R3-D`:**<br>Queries `public.affiliates` for both affiliate and `mgr_id` and enforces `is_class_1_commission_eligible()` | **REMEDIATED in `PATCH-R3-D`:**<br>Replaces `str(aff_code or "DEFAULT")` in `affiliate_id` with `verified_aff_id = str(aff_rec["id"])` and binds `verified_mgr_id = str(mgr_rec["id"])` | 3-tier webhook idempotency (`payment_events.event_id`, `orders.status`, L1 cache) + `uq_commission_ledger_reference` (`ON CONFLICT (reference_id) DO NOTHING` at `L567`) | **Fail-Closed:** `conn.rollback()` (`L658`), re-raises -> `HTTP 503 DATABASE_UNAVAILABLE` (`L1040–1075`) |
| **7b** | `settle_order_atomic`<br>(`app/services/checkout_service.py:125–366`) | Atomic checkout settlement (`app/services/checkout_service.py`) | `public.commission_ledger` (`status='PENDING_PAYOUT'`) | Same 17 columns as Writer #7a (`L242–274`) | **BYPASS at Baseline (`INT-03b`); FULL in `PATCH-R3-E`:**<br>Queries `public.affiliates` for both affiliate and `mgr_id` and enforces `is_class_1_commission_eligible()` | **REMEDIATED in `PATCH-R3-E`:**<br>Replaces `str(aff_code or "DEFAULT")` in `affiliate_id` with `verified_aff_id = str(aff_rec["id"])` and binds `verified_mgr_id = str(mgr_rec["id"])` | `payment_events.event_id` + `orders.status` guard (`L167–177`) + `uq_commission_ledger_reference` (`ON CONFLICT (reference_id) DO NOTHING` at `L257`) | **Fail-Closed:** `conn.rollback()` (`L351`) and re-raises exception (`L355`) |
| **8** | `process_successful_subscription`<br>(`app/services/subscription_service.py:372–535`) | `POST /api/v1/shop/subscriptions/webhooks/xendit` & `/api/v1/subscription/webhook` | `public.shop_commission_ledger` (`disbursement_status='PENDING'`) | `subscription_id`, `tenant_slug`, `gross_amount`, `affiliate_id`, `affiliate_amount`, `am_id`, `am_amount`, `platform_net_amount`, `disbursement_status` (`L492–502`) | **PARTIAL at Baseline (`INT-04`); FULL in `PATCH-R3-F`:**<br>Delegates `is_upgrade=True` to Writer #1; enforces `is_class_1_commission_eligible()` on `affiliate_id` & `am_id` when `is_upgrade=False` | **REMEDIATED in `PATCH-R3-F`:**<br>Writes `verified_aff_id` (`comm_alloc["direct_affiliate_id"]` or `str(aff_row["id"])`) and `verified_am_id` (`comm_alloc["am_id"]` or `str(am_row["id"])`) instead of raw caller params | Pre-check on `shop_subscriptions` by `xendit_invoice_id` (`status IN ('ACTIVE','PAID')` at `L401–412`) | **Fail-Closed (`PATCH-R3-F`):** Raises `RuntimeError` if `shop_commission_ledger` insert fails (`L503–505`) |
| **9** | `PayoutService.settle_affiliate_batch` (`payout_service.py:17–55`) & `mark_payout_paid` (`partner_routes.py:343–366`) | `POST /payout/settle` (`app/main.py:521–525`) & `PUT/POST /api/v1/manager/payouts/{payout_id}/mark-paid` (`partner_routes.py:343–352`) | `public.commission_ledger` (`PAID_OUT`) & `public.payout_requests` (`PAID`) | **UNREACHABLE (HARD-LOCKED):** `status='PAID_OUT'`, `settled_at`, `settlement_notes` / `status='PAID'`, `proof_attachment_url`, `processed_at` | **HARD-LOCKED (`HTTP 403`):**<br>Unconditionally raises `payout_disbursement_locked()` (`app/routes/affiliate_payout_routes.py:13–21`) before service execution | N/A — Zero payout disbursement execution permitted | N/A — Blocked prior to DB access | Deterministic `HTTP 403 Forbidden` (`{"error": "PAYOUT_DISBURSEMENT_LOCKED"}`) |

---

## 2. PROOF OF RECIPIENT IDENTITY BINDING (`VERIFIED ELIGIBLE ID == PERSISTED RECIPIENT ID`) & BYPASS INVENTORY

### 2.1 Code-Level Proof That Commission Recipient Identity Equals Eligibility-Verified Identity

In `app/services/affiliate_service.py:88–231`, `is_class_1_commission_eligible(aff_record)` evaluates a normalized `aff_record` dictionary and returns `(True, "CLASS_1_EXACT_LINKED_HEALTHY")` **if and only if**:
1. `status` is `'ACTIVE'` or `'APPROVED'` (`L99–101`).
2. `identity_class` / `classification` / `taxonomy_class` is explicitly `'CLASS_1_EXACT_LINKED_HEALTHY'` (`L105–162`), with zero `CLASS_2` / `NON_ELIGIBLE_IDENTITY_CLASSES` tokens.
3. `manual_review`, `requires_manual_review`, `has_discrepancy`, `discrepancies`, and `reconciliation_action` / `reconciliation_status` contain zero hold/review/discrepancy flags (`L122–156`).
4. `auth_user_id` is a non-empty valid UUID/token not in `_INVALID_AUTH_UID_TOKENS`, and if `auth_user` or `linked_auth_user_id` / `verified_auth_user_id` is present, `au["id"] == auth_user_id` and `aff_email == au_email` (`L164–218`).
5. Positive authoritative link proof exists (`is_linked is True`, `relationship_valid is True`, `identity_verified is True`, or `link_status in _ELIGIBLE_LINK_STATUSES` at `L220–229`).

To prevent **TOCTOU / recipient substitution** (where one identity is checked for eligibility or looked up by `referral_code`, while an unverified caller string or a non-eligible second tier's ID is written to the ledger row), every writer enforces **`Persisted_Recipient_ID === str(Verified_Aff_Record["id"])`**:

| Writer # | Tier / Role | Eligibility-Checked Object | Persisted Recipient Column & Value | Identity Binding Proof & Remediation |
| :--- | :--- | :--- | :--- | :--- |
| **Writer #1** (`affiliate_service.py`) | Direct Affiliate | `aff_record` (`L540–550`, checked at `L576`) | `affiliate_commissions.affiliate_id = str(valid_aff_id)` (`L656`) | `PATCH-R3-A` enforces `valid_aff_id = str(aff_record["id"])` (`L637`) with zero fallback to unverified `resolved_aff_id`. |
| **Writer #1** (`affiliate_service.py`) | AM Override | `am_row` (`L707–710`, checked at `L711`) | `affiliate_commissions.affiliate_id = str(valid_am_id)` (`L722`) | `PATCH-R3-A` enforces `valid_am_id = str(am_row["id"])` (`L713`) ONLY when `am_eligible is True` and `am_row.get("id")` is non-empty. |
| **Writer #2** (`affiliate_service.py`) | Direct Affiliate | `aff_record` (`L344`, checked at `L354`) | `affiliate_commissions.affiliate_id = str(resolved_aff_id)` (`L402`) | `PATCH-R3-A` enforces `resolved_aff_id = str(aff_record["id"])` (`L346`) from the exact `aff_record` verified at `L354`. |
| **Writer #3** (`growth_service.py`) | Direct Affiliate | `attribution_info` (`LEFT JOIN affiliates a ON a.id = ...`, checked at `L154`) | `affiliate_commissions.affiliate_id = aff_id` (`L189`) | `PATCH-R2-B` projects `a.id AS verified_affiliate_id` and binds `aff_id = str(verified_affiliate_id)` from the joined `affiliates` row. |
| **Writer #4** (`payment_orchestrator.py`) | Direct Affiliate + AM Override | `aff_row` & `mgr_row` (`PATCH-R3-B`) | `commission_ledger.affiliate_id`, `commission_ledger.manager_id`, `affiliate_daily_stats.affiliate_id` | **Baseline Gap Fixed (`PATCH-R3-B`):** Previously wrote raw `order.get("affiliate_id")` and `order.get("manager_id")` even if one tier failed eligibility. Now binds `verified_affiliate_id = str(aff_row["id"]) if aff_eligible else None` and `verified_manager_id = str(mgr_row["id"]) if mgr_eligible else None`. |
| **Writer #5 & #6** (`checkout_shipping` & `cod_settlement`) | Direct / AM Shipping & COD | `affiliate` & `verified_manager` (Writer #5) and `aff_rec` (Writer #6) in `PATCH-R3-C` | `affiliate_commissions.affiliate_id` (`PENDING` insert & `APPROVED` promotion) | **Baseline Gap Fixed (`PATCH-R3-C`):** Writer #5 verifies both `referral_code` and `manager_id` via `_AFFILIATE_ELIGIBILITY_COLUMNS` & `is_class_1_commission_eligible()`, binding `target_aff_id = str(affiliate["id"])` or `str(verified_manager["id"])` (preventing any `PENDING` row with `amount > 0` for non-Class-1). Writer #6 re-verifies `is_class_1_commission_eligible(aff_rec)[0]` AND `str(aff_rec["id"]) == str(pending_comm["affiliate_id"])`, and scopes `UPDATE ... WHERE order_id=%s AND tenant_id=%s AND affiliate_id=%s`. |
| **Writer #7a & #7b** (`xendit.py` & `checkout_service.py`) | Direct Affiliate + AM Override | `aff_rec` & `mgr_rec` (`PATCH-R3-D` & `PATCH-R3-E`) | `commission_ledger.affiliate_id`, `commission_ledger.manager_id` | **Baseline Gap Fixed (`PATCH-R3-D` / `PATCH-R3-E`):** Previously wrote `str(aff_code or "DEFAULT")` into `affiliate_id` and omitted `manager_id`. Now writes `verified_aff_id = str(aff_rec["id"]) if aff_eligible else None` and `verified_mgr_id = str(mgr_rec["id"]) if mgr_eligible else None`. |
| **Writer #8** (`subscription_service.py`) | Upgrade & New Subscription | `comm_alloc` (`is_upgrade=True`) or `aff_row` & `am_row` (`is_upgrade=False` in `PATCH-R3-F`) | `shop_commission_ledger.affiliate_id`, `shop_commission_ledger.am_id` | **Baseline Gap Fixed (`PATCH-R3-F`):** Previously wrote raw caller `affiliate_id` / `am_id` (`L496, 498`). Now writes `verified_aff_id` and `verified_am_id` returned by `allocate_upgrade_commission` or verified via `is_class_1_commission_eligible()`. |
| **Writer #9** (`payout_service.py` & `partner_routes.py`) | Disbursement | Hard-locked prior to service call | Unreachable (`HTTP 403`) | `payout_disbursement_locked()` aborts before any row can be read or updated. |

### 2.2 Complete Inventory of Bypass Paths & Legacy Writers
1. **Legacy Raw-SQL Settlement Writers (`Writer #7a` in `app/routes/xendit.py:543–588` & `Writer #7b` in `app/services/checkout_service.py:233–275`):** Both legacy settlement paths inserted hardcoded `25%`/`5%` rows into `commission_ledger` whenever `aff_code` or `mgr_id` was present on `orders` without querying `public.affiliates` or calling `is_class_1_commission_eligible()`, and wrote `aff_code` instead of `affiliates.id` into `affiliate_id`. Remediated in `PATCH-R3-D` and `PATCH-R3-E`.
2. **Legacy COD Remittance Promotion (`Writer #6` in `app/services/cod_settlement_service.py:64–72` & `Writer #5` in `app/services/checkout_shipping_service.py:200–244`):** Promoted `PENDING` COD reservations to `APPROVED` upon courier remittance without checking `is_class_1_commission_eligible()`. Remediated in `PATCH-R3-C`.
3. **Initial Subscription Sub-Ledger (`Writer #8` in `app/services/subscription_service.py:435–445, 490–504`):** Bypassed `is_class_1_commission_eligible()` when `is_upgrade=False`, inserted `0`-amount rows into `shop_commission_ledger` when `not is_upgrade`, wrote unverified caller `affiliate_id`/`am_id` parameters, and logged a warning instead of raising `RuntimeError` on DB failure. Remediated in `PATCH-R3-F`.
4. **Orchestrator Partial Guard (`Writer #4` in `app/services/payment_orchestrator.py:224–340`):** Defaulted `affiliate_rate=25.0`/`manager_rate=5.0` when `aff_res.data` was empty, did not check `manager_id` eligibility, normalized only 9 of 18 columns, and wrote raw `order["affiliate_id"]`/`order["manager_id"]` even when a tier was ineligible. Remediated in `PATCH-R3-B`.
5. **Partner Whitelist Payout Request Creation (`PartnerService.request_payout` in `app/services/partner_service.py:390–444`):** Creates `PENDING` rows in `public.payout_requests` with immutable bank snapshots (`snapshot_bank_name`, `snapshot_account_number`, `snapshot_account_holder` via `DB-04`); actual disbursement (`mark_payout_paid` in `app/routes/partner_routes.py:343–352`) is unconditionally blocked by `payout_disbursement_locked()` (`HTTP 403`).

---

## 3. ISOLATED PROPOSED PATCHES FOR CTO REVIEW (`PATCH-R3-A` .. `PATCH-R3-F`)

### 3.1 `PATCH-R3-A` — Strict Recipient Identity Binding in `AffiliateService` (`app/services/affiliate_service.py` — Writers #1 & #2)

```diff
--- a/app/services/affiliate_service.py
+++ b/app/services/affiliate_service.py
@@ -345,2 +345,2 @@
                     if aff_record:
-                        resolved_aff_id = aff_record.get("id") or resolved_aff_id
+                        resolved_aff_id = str(aff_record["id"]) if aff_record.get("id") else None
@@ -637,1 +637,4 @@
-        valid_aff_id = (aff_record.get("id") if aff_record else resolved_aff_id) or str(resolved_aff_id)
+        if not aff_record or not aff_record.get("id"):
+            raise RuntimeError(f"[AffiliateService FAIL-CLOSED] Missing verified affiliate.id for invoice '{invoice_id}'.")
+        valid_aff_id = str(aff_record["id"])
@@ -711,3 +714,3 @@
                 am_eligible, _ = is_class_1_commission_eligible(am_row)
-                if am_eligible:
-                    valid_am_id = am_row.get("id") or str(am_candidate)
+                if am_eligible and am_row.get("id"):
+                    valid_am_id = str(am_row["id"])
```

### 3.2 `PATCH-R3-B` (`INT-01`) — `PaymentOrchestrator` Eligibility & Verified Recipient Binding (`app/services/payment_orchestrator.py` — Writer #4)

```diff
--- a/app/services/payment_orchestrator.py
+++ b/app/services/payment_orchestrator.py
@@ -10,1 +10,4 @@ from app.core.database import normalize_db_row
-from app.services.affiliate_service import is_class_1_commission_eligible
+from app.services.affiliate_service import (
+    _AFFILIATE_ELIGIBILITY_COLUMNS,
+    is_class_1_commission_eligible,
+)
@@ -223,46 +226,48 @@
-                affiliate_rate = 25.0   # default: sale via mitra
-                manager_rate   = 5.0    # default: AM pembina
+                affiliate_rate = 0.0
+                manager_rate   = 0.0
+                verified_affiliate_id = None
+                verified_affiliate_code = None
+                verified_manager_id = None
+                aff_row = {}
                 aff_lookup_key = "id" if affiliate_id else "referral_code"
                 aff_lookup_val = affiliate_id or affiliate_code
                 if aff_lookup_val:
                     aff_res = self.supabase.table("affiliates").select("*").eq(aff_lookup_key, aff_lookup_val).execute()
                     if aff_res.data:
-                        aff_row = normalize_db_row(
-                            aff_res.data[0],
-                            (
-                                "id", "auth_user_id", "identity_class", "classification",
-                                "status", "commission_rate", "reconciliation_action",
-                                "reconciliation_status", "metadata",
-                            ),
-                        ) or {}
-                        if not is_class_1_commission_eligible(aff_row)[0]:
+                        aff_row = normalize_db_row(aff_res.data[0], _AFFILIATE_ELIGIBILITY_COLUMNS) or {}
+                        if is_class_1_commission_eligible(aff_row)[0] and aff_row.get("id"):
+                            verified_affiliate_id = str(aff_row["id"])
+                            verified_affiliate_code = str(aff_row.get("referral_code") or affiliate_code or "DEFAULT")
+                            db_rate = aff_row.get("commission_rate")
+                            affiliate_rate = float(db_rate) if db_rate is not None else 25.0
+                        else:
                             logger.warning(f"[Payment] Affiliate '{aff_lookup_val}' is not Class 1 eligible; skipping commission for order {external_id}.")
-                            affiliate_rate = 0.0
-                            manager_rate = 0.0
-                        else:
-                            db_rate = aff_row.get("commission_rate")
-                            if db_rate is not None:
-                                affiliate_rate = float(db_rate)
-
-                if manager_id and not affiliate_id and not affiliate_code:
-                    affiliate_rate = 0.0
-                    manager_rate   = 30.0
-
-                effective_manager_rate = manager_rate if manager_id else 0.0
+                mgr_candidate = manager_id or aff_row.get("parent_am_id") or aff_row.get("manager_id") or aff_row.get("registered_by_am_id")
+                if mgr_candidate and (verified_affiliate_id or (not affiliate_id and not affiliate_code)):
+                    mgr_res = self.supabase.table("affiliates").select("*").eq("id", str(mgr_candidate)).execute()
+                    if mgr_res and mgr_res.data:
+                        mgr_row = normalize_db_row(mgr_res.data[0], _AFFILIATE_ELIGIBILITY_COLUMNS) or {}
+                        if is_class_1_commission_eligible(mgr_row)[0] and mgr_row.get("id"):
+                            verified_manager_id = str(mgr_row["id"])
+                            manager_rate = 30.0 if (not affiliate_id and not affiliate_code) else 5.0
+                effective_manager_rate = manager_rate if verified_manager_id else 0.0
@@ -280,1 +285,1 @@
-                manager_override     = round((amount * effective_manager_rate) / 100.0, 2) if manager_id else 0.0
+                manager_override     = round((amount * effective_manager_rate) / 100.0, 2) if verified_manager_id else 0.0
@@ -290,4 +295,4 @@
                     "order_id": external_id,
-                    "affiliate_id": affiliate_id,
-                    "affiliate_code": affiliate_code or "DEFAULT",
-                    "manager_id": manager_id,
+                    "affiliate_id": verified_affiliate_id,
+                    "affiliate_code": verified_affiliate_code or "NONE",
+                    "manager_id": verified_manager_id,
                     "tenant_slug": tenant_slug,
@@ -304,2 +309,3 @@
                 try:
-                    self.supabase.table("commission_ledger").insert(ledger_payload).execute()
+                    if affiliate_commission > 0 or manager_override > 0:
+                        self.supabase.table("commission_ledger").insert(ledger_payload).execute()
@@ -318,2 +324,2 @@
-                if affiliate_id:
+                if verified_affiliate_id and affiliate_commission > 0:
```

### 3.3 `PATCH-R3-C` (`INT-02`) — Checkout Shipping & COD Remittance Eligibility + Recipient Identity Binding (`app/services/checkout_shipping_service.py` — Writer #5 & `app/services/cod_settlement_service.py` — Writer #6)

```diff
--- a/app/services/checkout_shipping_service.py
+++ b/app/services/checkout_shipping_service.py
@@ -5,1 +5,5 @@ from typing import Dict, Any, List
 from app.core.database import normalize_db_row
+from app.services.affiliate_service import (
+    _AFFILIATE_ELIGIBILITY_COLUMNS,
+    is_class_1_commission_eligible,
+)
 from app.services.biteship_adapter import BiteshipShippingAdapter
@@ -200,22 +204,35 @@ async def create_checkout_order_with_shipping(payload: Dict[str, Any]) -> Dict[s
         if ENABLE_TENANT_AFFILIATE_COMMISSION and (referral_code or manager_id):
             affiliate = None
             if referral_code:
                 cur.execute("""
-                    SELECT id, commission_rate FROM affiliates
-                    WHERE tenant_id = %s AND referral_code = %s AND status = 'ACTIVE';
+                    SELECT * FROM affiliates
+                    WHERE tenant_id = %s AND referral_code = %s AND status = 'ACTIVE' LIMIT 1;
                 """, (tenant_id, referral_code))
-                affiliate = normalize_db_row(cur.fetchone(), ("id", "commission_rate"))
+                aff_candidate = normalize_db_row(cur.fetchone(), _AFFILIATE_ELIGIBILITY_COLUMNS)
+                if aff_candidate and is_class_1_commission_eligible(aff_candidate)[0] and aff_candidate.get("id"):
+                    affiliate = aff_candidate
+
+            verified_manager = None
+            if manager_id:
+                cur.execute("""
+                    SELECT * FROM affiliates
+                    WHERE tenant_id = %s AND id = %s AND status = 'ACTIVE' LIMIT 1;
+                """, (tenant_id, str(manager_id)))
+                mgr_candidate = normalize_db_row(cur.fetchone(), _AFFILIATE_ELIGIBILITY_COLUMNS)
+                if mgr_candidate and is_class_1_commission_eligible(mgr_candidate)[0] and mgr_candidate.get("id"):
+                    verified_manager = mgr_candidate
 
             # Aturan Split 2-Tier (Maksimal total komisi 30%, Margin Platform minimal 70%):
             # 1. Direct AM (tanpa mitra referral): 30% ke AM
             # 2. Sale via Mitra: Mitra 25% (atau custom rate), AM pembina 5%
-            if manager_id and not affiliate:
+            if verified_manager and not affiliate and not referral_code:
                 affiliate_rate = 0.0
                 am_rate = 30.0
-                target_aff_id = manager_id
-            else:
-                db_rate = affiliate.get("commission_rate") if affiliate else None
+                target_aff_id = str(verified_manager["id"])
+            elif affiliate:
+                db_rate = affiliate.get("commission_rate")
                 affiliate_rate = float(db_rate) if db_rate is not None else 25.0
-                am_rate = 5.0 if manager_id else 0.0
-                target_aff_id = affiliate.get("id") if affiliate else None
+                am_rate = 5.0 if verified_manager else 0.0
+                target_aff_id = str(affiliate["id"])
+            else:
+                affiliate_rate = 0.0
+                am_rate = 0.0
+                target_aff_id = None
--- a/app/services/cod_settlement_service.py
+++ b/app/services/cod_settlement_service.py
@@ -5,1 +5,6 @@ from typing import Dict, Any, Optional
+from app.core.database import normalize_db_row
+from app.services.affiliate_service import (
+    _AFFILIATE_ELIGIBILITY_COLUMNS,
+    is_class_1_commission_eligible,
+)
 from app.services.biteship_adapter import BiteshipShippingAdapter
@@ -64,8 +69,24 @@
-        # 4. Lepas Komisi Affiliate ke status APPROVED
-        cur.execute("""
-            UPDATE affiliate_commissions
-            SET status = 'APPROVED', updated_at = NOW()
-            WHERE order_id = %s AND tenant_id = %s
-            RETURNING affiliate_id, amount;
-        """, (order_id, tenant_id))
-        comm_row = cur.fetchone()
+        # 4. INT-02: Verify Class 1 eligibility & exact recipient identity before promoting PENDING COD commission
+        cur.execute(
+            "SELECT affiliate_id, amount FROM affiliate_commissions WHERE order_id = %s AND tenant_id = %s LIMIT 1;",
+            (order_id, tenant_id),
+        )
+        pending_comm = normalize_db_row(cur.fetchone(), ("affiliate_id", "amount"))
+        comm_row = None
+        if pending_comm and pending_comm.get("affiliate_id"):
+            cur.execute("SELECT * FROM affiliates WHERE id = %s LIMIT 1;", (str(pending_comm["affiliate_id"]),))
+            aff_rec = normalize_db_row(cur.fetchone(), _AFFILIATE_ELIGIBILITY_COLUMNS)
+            if aff_rec and is_class_1_commission_eligible(aff_rec)[0] and str(aff_rec.get("id")) == str(pending_comm["affiliate_id"]):
+                verified_aff_id = str(aff_rec["id"])
+                cur.execute(
+                    "UPDATE affiliate_commissions SET status = 'APPROVED', updated_at = NOW() WHERE order_id = %s AND tenant_id = %s AND affiliate_id = %s RETURNING affiliate_id, amount;",
+                    (order_id, tenant_id, verified_aff_id),
+                )
+                comm_row = cur.fetchone()
+            else:
+                cur.execute(
+                    "UPDATE affiliate_commissions SET status = 'HELD_MANUAL_REVIEW', amount = 0, updated_at = NOW() WHERE order_id = %s AND tenant_id = %s;",
+                    (order_id, tenant_id),
+                )
```

### 3.4 `PATCH-R3-D` (`INT-03a`) — Xendit Settlement Ledger Guard & Identity Binding (`app/routes/xendit.py` — Writer #7a)

```diff
--- a/app/routes/xendit.py
+++ b/app/routes/xendit.py
@@ -30,1 +30,5 @@ from app.core.database import get_db_connection, normalize_db_row
+from app.services.affiliate_service import (
+    _AFFILIATE_ELIGIBILITY_COLUMNS,
+    is_class_1_commission_eligible,
+)
 from app.services.xendit_service import xendit_service
@@ -543,45 +547,50 @@
         if aff_code or mgr_id:
-            aff_rate = 25.0
-            mgr_rate = 5.0
+            aff_rate = 0.0
+            mgr_rate = 0.0
+            verified_aff_id = None
+            verified_aff_code = None
+            verified_mgr_id = None
+            aff_rec = None
+            if aff_code:
+                cur.execute("SELECT * FROM affiliates WHERE id::text = %s OR LOWER(referral_code) = LOWER(%s) LIMIT 1;", (str(aff_code), str(aff_code)))
+                aff_rec = normalize_db_row(cur.fetchone(), _AFFILIATE_ELIGIBILITY_COLUMNS)
+                if aff_rec and is_class_1_commission_eligible(aff_rec)[0] and aff_rec.get("id"):
+                    verified_aff_id = str(aff_rec["id"])
+                    verified_aff_code = str(aff_rec.get("referral_code") or aff_code)
+                    db_rate = aff_rec.get("commission_rate")
+                    aff_rate = float(db_rate) if db_rate is not None else 25.0
+            mgr_candidate = mgr_id or (aff_rec.get("parent_am_id") if aff_rec else None) or (aff_rec.get("manager_id") if aff_rec else None)
+            if mgr_candidate and (verified_aff_id or not aff_code):
+                cur.execute("SELECT * FROM affiliates WHERE id::text = %s OR LOWER(referral_code) = LOWER(%s) LIMIT 1;", (str(mgr_candidate), str(mgr_candidate)))
+                mgr_rec = normalize_db_row(cur.fetchone(), _AFFILIATE_ELIGIBILITY_COLUMNS)
+                if mgr_rec and is_class_1_commission_eligible(mgr_rec)[0] and mgr_rec.get("id"):
+                    verified_mgr_id = str(mgr_rec["id"])
+                    mgr_rate = 30.0 if not aff_code else 5.0
             aff_amount = round((amount * aff_rate) / 100.0, 2)
             mgr_amount = round((amount * mgr_rate) / 100.0, 2)
             net_platform = round(amount - aff_amount - mgr_amount, 2)
-            cur.execute(
+            if aff_amount > 0 or mgr_amount > 0:
+                cur.execute(
+                    """
+                    INSERT INTO commission_ledger (
+                        event_type, reference_id, affiliate_id, order_id, affiliate_code, manager_id, tenant_slug,
+                        gross_amount, commission_amount, payout_status, affiliate_commission_rate, affiliate_commission_amount,
+                        manager_override_rate, manager_override_amount, net_platform_revenue, status, created_at
+                    ) VALUES (
+                        'ORDER_COMMISSION', %s, %s, %s, %s, %s, %s, %s, %s, 'UNPAID', %s, %s, %s, %s, %s, 'PENDING_PAYOUT', %s
+                    ) ON CONFLICT (reference_id) DO NOTHING;
+                    """,
+                    (
+                        str(external_id), verified_aff_id, str(external_id), verified_aff_code or "NONE",
+                        verified_mgr_id, tenant_id, amount, aff_amount, aff_rate, aff_amount,
+                        mgr_rate, mgr_amount, net_platform, now_utc,
+                    ),
+                )
```


### 3.5 `PATCH-R3-E` (`INT-03b`) — Atomic Checkout Settlement Ledger Guard (`app/services/checkout_service.py` — Writer #7b)

```diff
--- a/app/services/checkout_service.py
+++ b/app/services/checkout_service.py
@@ -18,1 +18,5 @@ from typing import Dict, Any, Optional, Tuple
-from app.core.database import get_db_connection
+from app.core.database import get_db_connection, normalize_db_row
+from app.services.affiliate_service import (
+    _AFFILIATE_ELIGIBILITY_COLUMNS,
+    is_class_1_commission_eligible,
+)
@@ -233,42 +237,45 @@
         if aff_code or mgr_id:
-            aff_rate = 25.0
-            mgr_rate = 5.0
+            aff_rate = 0.0
+            mgr_rate = 0.0
+            verified_aff_id = None
+            verified_aff_code = None
+            verified_mgr_id = None
+            aff_rec = None
+            if aff_code:
+                cur.execute("SELECT * FROM affiliates WHERE id::text = %s OR LOWER(referral_code) = LOWER(%s) LIMIT 1;", (str(aff_code), str(aff_code)))
+                aff_rec = normalize_db_row(cur.fetchone(), _AFFILIATE_ELIGIBILITY_COLUMNS)
+                if aff_rec and is_class_1_commission_eligible(aff_rec)[0] and aff_rec.get("id"):
+                    verified_aff_id = str(aff_rec["id"])
+                    verified_aff_code = str(aff_rec.get("referral_code") or aff_code)
+                    db_rate = aff_rec.get("commission_rate")
+                    aff_rate = float(db_rate) if db_rate is not None else 25.0
+            mgr_candidate = mgr_id or (aff_rec.get("parent_am_id") if aff_rec else None) or (aff_rec.get("manager_id") if aff_rec else None)
+            if mgr_candidate and (verified_aff_id or not aff_code):
+                cur.execute("SELECT * FROM affiliates WHERE id::text = %s OR LOWER(referral_code) = LOWER(%s) LIMIT 1;", (str(mgr_candidate), str(mgr_candidate)))
+                mgr_rec = normalize_db_row(cur.fetchone(), _AFFILIATE_ELIGIBILITY_COLUMNS)
+                if mgr_rec and is_class_1_commission_eligible(mgr_rec)[0] and mgr_rec.get("id"):
+                    verified_mgr_id = str(mgr_rec["id"])
+                    mgr_rate = 30.0 if not aff_code else 5.0
             aff_amount = round((amount * aff_rate) / 100.0, 2)
             mgr_amount = round((amount * mgr_rate) / 100.0, 2)
             net_platform = round(amount - aff_amount - mgr_amount, 2)
-            cur.execute(
+            if aff_amount > 0 or mgr_amount > 0:
+                cur.execute(
+                    """
+                    INSERT INTO commission_ledger (
+                        event_type, reference_id, affiliate_id, order_id, affiliate_code, manager_id, tenant_slug,
+                        gross_amount, commission_amount, payout_status, affiliate_commission_rate, affiliate_commission_amount,
+                        manager_override_rate, manager_override_amount, net_platform_revenue, status, created_at
+                    ) VALUES (
+                        'ORDER_COMMISSION', %s, %s, %s, %s, %s, %s, %s, %s, 'UNPAID', %s, %s, %s, %s, %s, 'PENDING_PAYOUT', %s
+                    ) ON CONFLICT (reference_id) DO NOTHING;
+                    """,
+                    (
+                        str(external_id), verified_aff_id, str(external_id), verified_aff_code or "NONE",
+                        verified_mgr_id, tenant_id, amount, aff_amount, aff_rate, aff_amount,
+                        mgr_rate, mgr_amount, net_platform, now_utc,
+                    ),
+                )
```

### 3.6 `PATCH-R3-F` (`INT-04`) — Initial Subscription Eligibility & Verified Recipient Binding (`app/services/subscription_service.py` — Writer #8)

```diff
--- a/app/services/subscription_service.py
+++ b/app/services/subscription_service.py
@@ -417,29 +417,51 @@
+    verified_aff_id = None
+    verified_am_id = None
     if is_upgrade:
         from app.services.affiliate_service import affiliate_service
         comm_alloc = await affiliate_service.allocate_upgrade_commission(
             tenant_id=clean_slug,
             invoice_id=xendit_invoice_id,
             amount_paid=gross_amount,
             affiliate_id=affiliate_id,
             am_id=am_id
         )
         if comm_alloc.get("status") == "success":
             affiliate_share = comm_alloc.get("direct_commission", 0)
             am_share = comm_alloc.get("override_commission", 0)
+            verified_aff_id = comm_alloc.get("direct_affiliate_id") if affiliate_share > 0 else None
+            verified_am_id = comm_alloc.get("am_id") if am_share > 0 else None
         else:
             affiliate_share = 0
             am_share = 0
         platform_net = gross_amount - affiliate_share - am_share
     else:
-        # Aturan Pembagian Komisi Standar untuk Langganan Baru
-        if am_id and not affiliate_id:
-            affiliate_share = 0
-            am_share = int(gross_amount * 0.30)
-        elif affiliate_id:
-            affiliate_share = int(gross_amount * 0.25)
-            am_share = int(gross_amount * 0.05) if am_id else 0
-        else:
-            affiliate_share = 0
-            am_share = 0
+        from app.core.database import normalize_db_row
+        from app.services.affiliate_service import _AFFILIATE_ELIGIBILITY_COLUMNS, is_class_1_commission_eligible
+        affiliate_share = 0
+        am_share = 0
+        if supabase and affiliate_id:
+            aff_q = supabase.table("affiliates").select("*").eq("id", str(affiliate_id)).execute()
+            if aff_q and aff_q.data:
+                aff_row = normalize_db_row(aff_q.data[0], _AFFILIATE_ELIGIBILITY_COLUMNS) or {}
+                if is_class_1_commission_eligible(aff_row)[0] and aff_row.get("id"):
+                    verified_aff_id = str(aff_row["id"])
+                    affiliate_share = int(gross_amount * 0.25)
+        if supabase and am_id and (verified_aff_id or not affiliate_id):
+            am_q = supabase.table("affiliates").select("*").eq("id", str(am_id)).execute()
+            if am_q and am_q.data:
+                am_row = normalize_db_row(am_q.data[0], _AFFILIATE_ELIGIBILITY_COLUMNS) or {}
+                if is_class_1_commission_eligible(am_row)[0] and am_row.get("id"):
+                    verified_am_id = str(am_row["id"])
+                    am_share = int(gross_amount * 0.30) if not affiliate_id else int(gross_amount * 0.05)
         platform_net = gross_amount - affiliate_share - am_share
@@ -490,15 +512,18 @@
-    if sub_id and (not is_upgrade or (affiliate_share > 0 or am_share > 0)):
+    if sub_id and (affiliate_share > 0 or am_share > 0):
         try:
             supabase.table("shop_commission_ledger").insert({
                 "subscription_id": sub_id,
                 "tenant_slug": clean_slug,
                 "gross_amount": gross_amount,
-                "affiliate_id": affiliate_id if affiliate_share > 0 else None,
+                "affiliate_id": verified_aff_id if affiliate_share > 0 else None,
                 "affiliate_amount": affiliate_share,
-                "am_id": am_id if am_share > 0 else None,
+                "am_id": verified_am_id if am_share > 0 else None,
                 "am_amount": am_share,
                 "platform_net_amount": platform_net,
                 "disbursement_status": "PENDING"
             }).execute()
         except Exception as ledger_err:
-            logger.warning(f"[COMMISSION LEDGER ERROR] {ledger_err}")
+            logger.error(f"[SUBSCRIPTION COMMISSION FAIL-CLOSED] {ledger_err}")
+            raise RuntimeError(f"Failed to persist shop_commission_ledger for subscription '{sub_id}': {ledger_err}") from ledger_err
```

---

## 4. INDEPENDENT PAYOUT DISBURSEMENT LOCK VERIFICATION

1. **Physical Enforcement Proof:**
   - `POST /payout/settle` (`app/main.py:521–525`): Line 525 unconditionally executes `raise payout_disbursement_locked()` prior to `PayoutService.settle_affiliate_batch`.
   - `PUT/POST /api/v1/manager/payouts/{payout_id}/mark-paid` (`app/routes/partner_routes.py:343–352`): Line 352 unconditionally executes `raise payout_disbursement_locked()` prior to `partner_service.mark_payout_as_paid`.
   - `app/routes/affiliate_payout_routes.py:1–22`: Contains strictly `PAYOUT_DISBURSEMENT_LOCKED` and `payout_disbursement_locked()` (`HTTP 403 Forbidden`) with zero route handlers.
2. **Control Independence:** `payout_disbursement_locked()` remains **100% active and locked** in Staging and Production regardless of commission writer eligibility state, and cannot be unlocked without separate written CTO & Founder release authorization.


