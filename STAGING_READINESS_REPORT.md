# STAGING READINESS AUDIT REPORT (POST-MERGE VERIFICATION GATE)

- **Document Reference:** `CTO-P0-PHASE2B-STAGING-READINESS-006`
- **Repository:** `B055OB/boontrack-core` (`C:\boontrack-core`)
- **Branch / Verified HEAD Commit:** `main` @ `a82b6fdf76c043c9a3ee87f48c34062f05258437`
- **Merge Parents:**
  - **Parent 1 (`main` pre-merge base):** `c17cc81a37705cecb482aa7368a1e774a5cb5a45` (`Merge pull request #23`)
  - **Parent 2 (PR #24 branch head):** `4066a3673827a4d8ee9e7e946f14d6a3d5e8c48d` (`fix(security): resolve CTO-PR24-REVIEW-003 blockers`)
- **Audit Date:** 2026-11-01
- **Governance Posture:** **STRICT READ-ONLY INSPECTION** (Zero DB migrations/mutations, zero deployments/canary triggers, zero payout executions, zero raw secret exposure)

---

## EXECUTIVE SUMMARY & STAGING READINESS VERDICT

| Audit Pillar | Scope Area | Status | Summary Finding |
| :--- | :--- | :--- | :--- |
| **1. Test Breakdown Parity** | `tests/test_affiliate_commission_guardrail.py` + Companion Suites | **PASS (22/22)** | `test_affiliate_commission_guardrail.py` contains **9** physical test functions (8 numbered `test_scenario_1..8` + 1 unnumbered `test_e2e_webhook_organic_upgrade_zero_commission`), `test_billing_proration.py` contains **5** functions (5th docstring labeled "Test 6"), and `test_commission_split.py` contains **8** functions: **`9 + 5 + 8 = 22/22 PASSED`**. |
| **2. Environment & Dependency Parity** | Env Vars, Workers, Webhooks, Docker/Procfile | **CONDITIONAL (ACTION REQ)** | Boot-time and runtime fail-closed guards are active in code, but `docker-compose.prod.yml` and `.env.example` omit new PR #24 mandatory variables (`JWT_SECRET`, `SUPABASE_JWT_SECRET`, `INTERNAL_MAGIC_SECRET`, `CORE_JWT_*`, `SUPABASE_JWT_*`). |
| **3. Database Readiness Audit** | Migrations, Unique Constraints, Indexes, RLS Policies | **HOLD FOR DDL PARITY** | RLS policies (`027`, `028`, `030`), views (`security_invoker=true`), and unique constraints (`uq_affiliate_commissions_tenant_order`) are defined, but **4 schema drift items (DB-01..DB-04)** exist between runtime SQL queries/payloads and numbered SQL files in `migrations/`. |
| **4. Identity & Commission Integrity** | Class 1 / Class 2 / Manual Review Boundary Across Writers | **PASS WITH RESIDUAL NOTES** | All 4 primary payable writers enforce `is_class_1_commission_eligible()` (including positive identity link proof) and fail-closed DB persistence. Secondary legacy SQL writers (`xendit.py`, `checkout_service.py`, `cod_settlement_service.py`) bypass `is_class_1_commission_eligible()`, though actual fund outflow is contained by `payout_disbursement_locked()` (HTTP 403). |
| **5. Staging Test & Rollback Plan** | Positive, Negative, Idempotency, Fail-Closed & Rollback | **READY** | Deterministic 14-scenario staging test matrix, Hardened-Build-Only rollback protocol, and 6 CTO Stop Conditions defined. |

---

## 1. CLARIFICATION OF TEST BREAKDOWN DISCREPANCY (22/22 TOTAL PASS COUNT)

### 1.1 Root Cause of Prior Count Discrepancy (`8 + 6 + 8` vs Actual `9 + 5 + 8 = 22`)
During PR #24 review cycles (`CTO-PR24-REVIEW-001` through `CTO-PR24-REVIEW-003`), two naming artifacts caused manual docstring/name tallies to read `8 + 6 + 8 = 22` while `pytest` physically collects and executes **`9 + 5 + 8 = 22`**:
1. **`tests/test_affiliate_commission_guardrail.py` has 9 tests (not 8):**
   - Functions are named `test_scenario_1_...` through `test_scenario_8_...` (8 numbered scenarios), **plus** `test_e2e_webhook_organic_upgrade_zero_commission` at line `273` (inserted between `test_scenario_3` and `test_scenario_4` without a `scenario_N` prefix).
2. **`tests/test_billing_proration.py` has 5 tests (not 6):**
   - Docstrings in `tests/test_billing_proration.py` are labeled `Test 1` (line `62`), `Test 2` (line `93`), `Test 3` (line `114`), `Test 5` (line `158` — skipping `Test 4`), and `Test 6 (CTO-PR24-REVIEW-003 Blocker B)` (line `188`). Physically, the file contains **5** `async def test_*` functions.
3. **`tests/test_commission_split.py` has 8 tests:**
   - Physically contains **8** `def test_*` functions.

### 1.2 Verification Commands on `main` (`a82b6fd`)

```powershell
# 1. AST Verification of Physical Test Function Count per File (9 + 5 + 8 = 22)
python -c "import ast; [print(f, len([n.name for n in ast.walk(ast.parse(open('C:/boontrack-core/'+f, encoding='utf-8').read())) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')])) for f in ['tests/test_affiliate_commission_guardrail.py', 'tests/test_billing_proration.py', 'tests/test_commission_split.py']]"

# 2. Execute Full 22-Test Commission Guardrail, Proration & Split Regression Suite
cd C:\boontrack-core
python -m pytest -p no:anyio -p no:faker -p no:locust -p no:cov -v `
  tests/test_affiliate_commission_guardrail.py `
  tests/test_billing_proration.py `

### 1.3 Complete 22/22 Test Case Matrix

#### Suite A: `tests/test_affiliate_commission_guardrail.py` (9/9 PASSED)
| # | Test Function Name | Line Range | Verified Invariant | Status |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `test_scenario_1_organic_guardrail_kurastoren` | `L17–L74` | Organic tenant (`affiliate_id=None`, `referral_code=None`) -> `status="skipped"`, `reason="ORGANIC_NO_AFFILIATE"`, 0 DB writes, 100% platform revenue, logs `ORGANIC_SUBSCRIPTION_PROCESSED`. | `PASSED` |
| 2 | `test_scenario_2_direct_affiliate_only_independent` | `L77–L152` | Independent Class 1 affiliate (`is_linked=True`, no AM) -> 1 direct `HOLDING` row (`Rp 13.340` on `Rp 66.700`), 0 AM override rows (Anti-Ghost AM). | `PASSED` |
| 3 | `test_scenario_3_multi_tier_full_affiliate_and_am` | `L155–L270` | Class 1 direct affiliate (`20%` = `Rp 13.340`) + Class 1 active AM (`5%` = `Rp 3.335`) -> 2 `HOLDING` rows, platform net `Rp 50.025`. | `PASSED` |
| 4 | `test_e2e_webhook_organic_upgrade_zero_commission` | `L273–L317` | E2E Xendit subscription webhook (`handle_xendit_subscription_webhook_logic`) for organic upgrade -> `affiliate_share=0`, `am_share=0`, 0 `affiliate_commissions` rows. | `PASSED` |
| 5 | `test_scenario_4_class_2_unlinked_candidate_manual_review_only_zero_commission` | `L320–L374` | Class 2 (`CLASS_2_UNLINKED_CANDIDATE` / `FLAG_FOR_MANUAL_REVIEW`) -> `status="held_manual_review"`, `reason="CLASS_2_MANUAL_REVIEW_ONLY"`, `payout_commission=0`, 0 DB writes, 0 in-memory entries. | `PASSED` |
| 6 | `test_scenario_5_fail_closed_commission_persistence_raises_on_db_error` | `L377–L424` | Non-unique DB insert failure on `affiliate_commissions` raises explicit `RuntimeError("Failed to persist direct affiliate commission")`; in-memory cache remains `[]`. | `PASSED` |
| 7 | `test_scenario_6_identity_eligibility_fail_closed_six_cases` | `L427–L600` | Verifies `is_class_1_commission_eligible()` across 7 structured cases (`case_1`..`case_7`) + mismatched `auth_user.id` and `has_discrepancy=True`. **Only `case_5` (explicit Class 1 + valid UID + positive link proof) returns `True`**. | `PASSED` |
| 8 | `test_scenario_7_payable_commission_writers_fail_closed_no_in_memory_fallback` | `L603–L727` | Verifies `record_prorated_upgrade_commission`, `process_order_paid_growth_event` (with `conn.rollback()`), and `PaymentOrchestrator.process_xendit_webhook` all raise `RuntimeError` on DB write failure with 0 in-memory fallback. | `PASSED` |
| 9 | `test_scenario_8_prorated_upgrade_writer_blocks_non_class_1_and_missing_link_proof` | `L730–L810` | Verifies `billing_service.mark_invoice_paid` -> `record_prorated_upgrade_commission` blocks `CLASS_2_UNLINKED_CANDIDATE` (`CLASS_2_MANUAL_REVIEW_ONLY`) and Class 1 missing positive link proof (`MISSING_POSITIVE_IDENTITY_LINK`) with 0 DB writes. | `PASSED` |

#### Suite B: `tests/test_billing_proration.py` (5/5 PASSED)
| # | Test Function Name | Line Range | Docstring Label | Status |
| :--- | :--- | :--- | :--- | :--- |
| 10 | `test_prorata_formula_exact_calculation` | `L60–L88` | `Test 1` | `PASSED` |
| 11 | `test_billing_cycle_renewal_date_preserved` | `L91–L109` | `Test 2` | `PASSED` |
| 12 | `test_invoice_creation_and_payment_webhook_lifecycle` | `L112–L153` | `Test 3` | `PASSED` |
| 13 | `test_affiliate_commission_strict_cash_collected` | `L156–L183` | `Test 5` | `PASSED` |
| 14 | `test_prorated_upgrade_blocks_non_class_1_affiliate_zero_commission` | `L186–L248` | `Test 6 (CTO-PR24-REVIEW-003 Blocker B)` | `PASSED` |

#### Suite C: `tests/test_commission_split.py` (8/8 PASSED)
| # | Test Function Name | Line Range | Verified Invariant | Status |
| :--- | :--- | :--- | :--- | :--- |
| 15 | `test_payment_orchestrator_commission_mitra_default` | `L6–L83` | 25% Class 1 affiliate + 5% AM override + 70% net platform in `commission_ledger` (`PENDING_PAYOUT`). | `PASSED` |
| 16 | `test_payment_orchestrator_commission_direct_am` | `L85–L141` | 0% affiliate + 30% direct AM + 70% net platform in `commission_ledger`. | `PASSED` |
| 17 | `test_payment_orchestrator_commission_clamp` | `L143–L211` | Clamps custom 30% affiliate + 5% AM (35% total) to <= 30.0% total (`25.7143%` + `4.2857%`), preserving >= 70% platform net. | `PASSED` |
| 18 | `test_checkout_shipping_service_commission_mitra_default` | `L214–L246` | Shipping checkout calculates 25% commission strictly on `base_price` (excluding `shipping_cost`). | `PASSED` |
| 19 | `test_checkout_shipping_service_commission_direct_am` | `L248–L279` | Shipping checkout direct AM 30% on `base_price` (excluding `shipping_cost`). | `PASSED` |
| 20 | `test_growth_service_commission_mitra_default_approved` | `L281–L324` | `process_order_paid_growth_event` inserts `APPROVED` commission for Class 1 linked affiliate and dispatches WA + Meta CAPI. | `PASSED` |
| 21 | `test_commission_db_row_normalization_dict_realdictrow_and_tuple` | `L327–L443` | `normalize_db_row` handles `dict`, `RealDictRow`, and positional `tuple` across `PaymentOrchestrator`, `allocate_upgrade_commission`, and `process_order_paid_growth_event`. | `PASSED` |
| 22 | `test_commission_concurrent_callbacks_idempotency_at_db_constraint_level` | `L446–L570` | 5-thread concurrent `allocate_upgrade_commission` (`23505` unique constraint -> 1 row, 4 idempotent hits) + 4-thread `process_order_paid_growth_event` (`rowcount == 0` -> 1 WA sent). | `PASSED` |

---

## 2. ENVIRONMENT & DEPENDENCY PARITY AUDIT

### 2.1 Environment Variable Matrix (`main` Codebase vs `.env.example` vs `docker-compose.prod.yml`)

| Variable Name | Enforcement Tier | Codebase Enforcement Reference | In `.env.example`? | In `docker-compose.prod.yml`? | Staging Parity Requirement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | **Boot Fail-Closed** | `app/core/server.py:23–28`, `app/core/database.py:95–97` | Yes (`L7`) | Yes (`L18`) | Mandatory PostgreSQL connection URI. |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | **Runtime Fail-Closed** | `app/core/config.py:18–55`, `app/core/database.py:99–125` | Yes (`L2–L6`) | Via `DATABASE_URL` | Required when `DATABASE_URL` is unset (`init_test_postgres_schema.py:14–32`). |
| `SUPABASE_URL` | **Boot Fail-Closed** | `app/main.py:30–38`, `app/api/webhook_payment.py:13–20` | Yes (`L10`) | Yes (`L19`) | Mandatory Supabase project URL (`2.5s` connect / `5.0s` read timeout in `app/main.py:27`). |
| `SUPABASE_ANON_KEY` / `SUPABASE_KEY` | **Boot Fail-Closed** | `app/main.py:31–38`, `app/api/webhook_payment.py:14–20` | Yes (`L11–L12`) | Yes (`L20–L21`) | Least-privilege key bound by RLS. **Must NOT equal `SUPABASE_SERVICE_ROLE_KEY`**. |
| `SUPABASE_SERVICE_ROLE_KEY` | **Admin Fail-Closed** | `app/main.py:51–66`, `app/api/webhook_payment.py:29–39` | **NO (Missing)** | Yes (`L22`) | Isolated admin key for signature-verified webhooks (`get_verified_webhook_supabase_client`). |
| `JWT_SECRET` | **Runtime Fail-Closed** | `app/core/jwt_secret.py:58–70` (`get_jwt_secret()`) | **NO (Missing)** | **NO (Missing)** | **CRITICAL GAP (`ENV-01`):** Required in non-dev/test environments for Core JWT realm. Compromised static secrets (`_COMPROMISED_SECRETS` at `L38–L41`) raise `RuntimeError`. |
| `SUPABASE_JWT_SECRET` | **Runtime Fail-Closed** | `app/core/jwt_secret.py:73–85` (`get_supabase_jwt_secret()`) | **NO (Missing)** | **NO (Missing)** | **CRITICAL GAP (`ENV-02`):** Required in non-dev/test environments for Supabase JWT realm; strictly isolated from `JWT_SECRET`. |
| `CORE_JWT_ISSUER` / `CORE_JWT_AUDIENCE` | **Runtime Trust Profile** | `app/core/jwt_secret.py:88–94` | **NO (Missing)** | **NO (Missing)** | Defaults to `"boontrack-core"` / `"boontrack-core"`. |
| `SUPABASE_JWT_ISSUER` / `SUPABASE_JWT_AUDIENCE` | **Runtime Trust Profile** | `app/core/jwt_secret.py:96–112` | **NO (Missing)** | **NO (Missing)** | Defaults to `"<SUPABASE_URL>/auth/v1"` / `"authenticated"`. |
| `INTERNAL_MAGIC_SECRET` | **Runtime Fail-Closed** | `app/core/jwt_secret.py:305–310`, `app/routes/auth_routes.py:282–288`, `app/api/endpoints/magic_login.py:20–23` | **NO (Missing)** | **NO (Missing)** | Returns `None` -> `HTTP 403 Forbidden` if unset or in `_COMPROMISED_SECRETS`. |
| `BOONTRACK_HMAC_SECRET` | **Runtime Fail-Closed** | `app/core/security/inter_service_auth.py`, `verify_cto_full_signoff.py:98–103` | **NO (Missing)** | Yes (`L27`) | Mandatory for Core <-> Inbox inter-service HMAC signing; zero fallback aliases. |
| `XENDIT_SECRET_KEY` | **Boot Fail-Closed** | `app/services/xendit_service.py:33–36` | Yes (`L69`) | Yes (`L24`) | Raises `ValueError` at import time if missing. Staging must use Xendit Sandbox key. |
| `XENDIT_CALLBACK_TOKEN` | **Boot Fail-Closed** | `app/services/xendit_service.py:41–49`, `app/routes/xendit.py:706–730`, `app/api/webhook_payment.py:46–51` | Yes (`L72`) | Yes (`L25`) | Verified via `hmac.compare_digest` on `x-callback-token` header. |
| `EVOLUTION_API_KEY` | **Boot Fail-Closed** | `app/services/whatsapp/evolution.py:34–41` | Yes (`L83`) | Yes (`L23`) | Raises `RuntimeError` at module import time if unset. |
| `REDIS_URL` | **Resilient Fallback** | `app/core/redis.py:18–46`, `app/routes/auth_routes.py:40`, `app/workers/whatsapp_inbound_worker.py:31` | **NO (Missing)** | Yes (`L31`) | Distributed lock `lock:payment:webhook:{external_id}` (`NX EX 300`) & `stream:whatsapp:inbound`. |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` | **Feature Fail-Closed** | `app/services/storage/r2.py`, `generate_cto_p1_evidence_bundle.py:41–42` | **NO (Missing)** | Yes (`L36–L38`) | Required for Cloudflare R2 tenant-scoped storage and presigned URLs. |
| `ONLINEBOOST_ALUMNI_BROADCAST_HOLD`, `ONLINEBOOST_PAYMENT_STRICT_HOLD` | **Governance Gate** | `PHASE_2A_CLOSURE_AND_PHASE_2B_READINESS.md:287`, `P0_GATE_A_FINAL_EVIDENCE_AND_GOVERNANCE_REVIEW.md:20` | **NO (Missing)** | **NO (Missing)** | Must remain locked (`true`) in staging/production until explicit written release. |

---
### 2.2 Queue Workers, Webhooks & Service Dependencies

1. **Primary Web Runtime (`boontrack-core`):**
   - Entrypoint: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}` (`Procfile:1`, `Dockerfile:18`, `docker-compose.prod.yml:8`).
   - **Python Version Discrepancy (`ENV-03`):** `.env.example:16` specifies `PYTHON_VERSION="3.10.13"`, `Dockerfile:1` uses `python:3.11-slim`, and `.github/workflows/cto-security-audit.yml:62` + local host run `Python 3.12` (with conditional `aiogram==2.25.2; python_version < '3.12'` in `requirements.txt:20`). Staging should standardize on `Python 3.11` or `Python 3.12`.
2. **Background & Queue Workers:**
   - **Payment Reconciler Worker (`app/workers/payment_reconciler_worker.py:103–273`):** Scans `payment_orders` where `payment_status == 'PENDING'` and `expired_at < NOW()`, marks `EXPIRED`, restores reserved inventory, and enforces `current_tenant_id` isolation (`reconcile_single_order`, `L242–L273`).
   - **WhatsApp Inbound Stream Worker (`app/workers/whatsapp_inbound_worker.py:144–209`):** Async Redis consumer on `stream:whatsapp:inbound` via `REDIS_URL`.
   - **Subscription Reminder Worker (`subscription_reminder_worker.py:1–789`):** Daemon/cron scanner (`--dry-run` supported) for H-3/H-1/Expired trials on `public.tenants` via Meta WABA (`META_WABA_PHONE_NUMBER_ID`, `WHATSAPP_TOKEN`) and Resend (`RESEND_API_KEY`).
   - **Video Metadata Worker (`app/services/video_metadata_worker.py`):** R2 object storage worker (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`).
   - **In-Process Webhook Tasks (`app/routes/xendit.py:53–260`, `app/api/webhook_payment.py:60–70`):** Non-blocking `asyncio.create_task` / `BackgroundTasks` for WhatsApp e-receipt delivery and Meta/TikTok CAPI `Purchase` dispatch (`app/services/meta_capi_service.py:24–80`).
3. **Webhook Ingress Endpoints Required in Staging:**
   - **Xendit QRIS / Invoice Callback:** `POST /api/v1/payments/xendit/callback` (aliases: `/api/v1/payment/xendit/callback`, `/webhook/payment/xendit`, `/webhook/xendit` in `app/routes/xendit.py:1178–1239`, `app/api/webhook_payment.py:76–138`) — authenticated via constant-time `hmac.compare_digest` on `x-callback-token` (`app/routes/xendit.py:706–730`).
   - **Shop Subscription Xendit Webhook:** `POST /api/v1/shop/subscriptions/webhooks/xendit` & `POST /api/v1/subscription/webhook` (`app/routes/shop_subscription_routes.py:17–18`).
   - **Billing Proration Payment Webhook:** `POST /api/v1/billing/webhook/payment` & `POST /api/v1/billing/invoices/{invoice_id}/pay` (`app/routes/billing_routes.py:84–115`).
   - **Meta WABA Webhook:** `GET/POST /api/v1/webhook/waba` (`app/routes/meta_waba_routes.py:1–120`) & `/webhook/whatsapp` (`app/routes/meta_whatsapp.py`).
   - **Evolution API Webhook:** `POST /api/v1/whatsapp/webhook/evolution/{tenant_slug}` (`app/routes/whatsapp_gateway_routes.py:1–120`).
   - **Biteship Logistics & COD Reconciliation:** `POST /api/v1/logistics/biteship/webhook`, `/api/v1/shipping/biteship/webhook`, `/api/v1/shipping/cod/reconcile` (`app/routes/shipping_webhook_routes.py:157–164`).

---

## 3. DATABASE READINESS AUDIT

### 3.1 Unique Idempotency Constraints & Indexes Relevant to Commission Tracking

| Table Name | Constraint / Index Name | Columns / Predicate | Source Reference | Enforcement Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `public.affiliate_commissions` | `uq_affiliate_commissions_tenant_order` (`UNIQUE`) + `idx_uq_affiliate_commissions_tenant_order` (`UNIQUE INDEX`) | `(tenant_id, order_id)` | `app/core/database.py:595–597`, `scripts/init_test_postgres_schema.py:544–546` | Prevents duplicate direct/prorated/growth commission rows per `(tenant_id, order_id)`. Caught via SQLSTATE `23505` in `affiliate_service.py:234–239` and `ON CONFLICT (tenant_id, order_id)` in `growth_service.py:184`. |
| `public.commission_ledger` | `uq_commission_ledger_reference` & `uq_commission_ledger_order_id` (`UNIQUE INDEX`) | `(reference_id)`, `(order_id)` | `app/core/database.py:566, 568, 583–584` | Enforces 1:1 order settlement idempotency (`ON CONFLICT (reference_id) DO NOTHING` in `xendit.py:567`, `checkout_service.py:257`, and `23505` catch in `payment_orchestrator.py:309`). |
| `public.financial_ledger` | `uq_financial_ledger_order_credit` (Partial `UNIQUE INDEX`) + `idx_financial_ledger_order`, `idx_financial_ledger_tenant`, `idx_financial_ledger_event` | `(order_id) WHERE (transaction_type = 'PAYMENT_CREDIT')` | `app/core/database.py:558–561` | Prevents double-crediting platform revenue for any `order_id`. |
| `public.payment_events` | `payment_events_event_id_key` (`UNIQUE`) + `idx_payment_events_event_id`, `idx_payment_events_ref_id`, `idx_payment_events_status` | `(event_id)` | `app/core/database.py:523, 536–538` | Tier-2 database webhook idempotency ledger (`ON CONFLICT (event_id) DO NOTHING` in `xendit.py:302, 432`). |
| `public.payment_intents` & `public.payment_settlements` | `uq_payment_intent_tenant_order`, `uq_payment_settlement_ref` | `(tenant_id, order_id)`, `(provider_ref)` | `migrations/005_create_core_payment_tables.sql:17, 30, 34–38` | Intent & settlement deduplication. |
| `public.partners` | `idx_partners_ref_code_upper` (`UNIQUE INDEX`), `partners_phone_key` (`UNIQUE`) | `(UPPER(ref_code))`, `(phone)` | `migrations/008_whitelist_partners_bank_and_payouts.sql:27, 30, 39–41` | Case-insensitive referral slug uniqueness. |
| `public.affiliates` | `idx_affiliates_screening_status`, `idx_affiliates_bank_account`, `idx_affiliates_experience_level` | `(screening_status)`, `(bank_name, bank_account_number)`, `(experience_level)` | `migrations/013_add_screening_and_bank_details_to_affiliates.sql:23–25` | Affiliate bank and screening lookup indexes. |
| `public.payment_orders` | `payment_orders_order_id_key` (`UNIQUE`), `idx_payment_orders_reconcile`, `idx_payment_orders_tenant_order` | `(order_id)`, `(payment_status, expired_at)`, `(tenant_id, order_id)` | `migrations/024_create_payment_orders.sql:7, 19–20` | Reconciler worker expiry scan & order lookup. |

### 3.2 RLS Policies, Helper Functions, Roles & Dynamic Views

1. **Dual-Resolution Tenant Helper Functions (`migrations/027_harden_rls_tenants_commerce_products_carts_attributions.sql:19–88`):**
   - `public.try_cast_uuid(p_val text)` (`L19–L36`): Safe UUID casting without raising `22P02 invalid input syntax for type uuid`.
   - `public.current_app_tenant_uuid()` (`L41–L63`) & `public.current_app_tenant_slug()` (`L68–L88`): Resolve `current_setting('app.current_tenant_id', true)` across both UUID and text slug representations against `public.tenants`.
2. **Commission & Attribution RLS Policies:**
   - **`public.attributions` (`migrations/027_...sql:424–528`):** `ENABLE` + `FORCE ROW LEVEL SECURITY`; policies `public_insert_attributions`, `auth_tenant_attributions`, `service_role_all_attributions`.
   - **`public.affiliates` (`migrations/028_harden_rls_affiliates_commissions_cart_items.sql:17–133`):** `ENABLE` + `FORCE ROW LEVEL SECURITY`; drops wildcard `allow_all_ops_affiliates`; enforces `public_select_active_affiliates` (`status = 'ACTIVE'` + tenant match), `auth_tenant_affiliates`, and `service_role_all_affiliates`.
   - **`public.affiliate_commissions` (`migrations/028_...sql:139–245`):** `ENABLE` + `FORCE ROW LEVEL SECURITY`; drops permissive policies; enforces `auth_tenant_affiliate_commissions` (`TO authenticated`) and `service_role_all_affiliate_commissions` (`TO service_role`).
   - **`public.commission_ledger` (`migrations/030_harden_rls_all_remaining_tenant_tables.sql:54–114`):** `ENABLE` + `FORCE ROW LEVEL SECURITY`; enforces `auth_tenant_commission_ledger` and `service_role_all_commission_ledger` on `tenant_slug`.
   - **`public.shop_commission_ledger` (`migrations/030_...sql:596–656`):** `ENABLE` + `FORCE ROW LEVEL SECURITY`; enforces `auth_tenant_shop_commission_ledger` and `service_role_all_shop_commission_ledger` on `tenant_slug`.
3. **Security Invoker Views & Non-Bypass Application Roles (`scripts/init_test_postgres_schema.py:52–65, 606–636`, `docs/audit/production_catalog_rls_report.md:14–42`):**
   - All 4 dynamic views (`public.affiliate_ledger`, `public.v_affiliate_ledger`, `public.v_affiliate_payout_summary`, `public.chat_sessions`) are configured with `WITH (security_invoker = true)`.
   - Roles `anon` and `authenticated` have `rolsuper = False` and `rolbypassrls = False`.

---
### 3.3 Pending Migrations & Schema Drift Findings (`DB-01` .. `DB-04`)

Inspection of `migrations/002_*.sql` through `migrations/030_*.sql`, `app/core/database.py`, and `scripts/init_test_postgres_schema.py` identified **4 schema parity items** that must be reconciled before executing live staging database tests:

1. **`DB-01` — Baseline DDL for `commission_ledger`, `financial_ledger`, `payment_events`, and `affiliate_commissions` Resides in `app/core/database.py` Rather Than `migrations/`:**
   - `CREATE TABLE IF NOT EXISTS` and unique constraint definitions for `payment_events` (`L520–L539`), `financial_ledger` (`L543–L561`), `commission_ledger` (`L563–L584`), and `affiliate_commissions` (`L586–L598`) are executed programmatically in `app/core/database.py` (`init_db()`) and `scripts/init_test_postgres_schema.py:532–546`, whereas `migrations/028_*.sql` and `migrations/030_*.sql` assume those tables already exist when running `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`.
   - **Staging Requirement:** Ensure `init_db()` or baseline DDL has created these 4 tables and their unique indexes prior to applying migrations `028` and `030`.
2. **`DB-02` — Pending Gate B1 Identity Boundary Columns on `public.affiliates` (`auth_user_id`, `identity_class`, `is_linked`, `reconciliation_action`, `reconciliation_status`):**
   - `app/services/growth_service.py:126–128` executes a raw PostgreSQL `SELECT ..., a.auth_user_id, a.identity_class, a.is_linked FROM product_orders po ... LEFT JOIN affiliates a ...`, and `app/routes/affiliate_auth.py:218` queries `.eq("auth_user_id", str(user_id))`.
   - Neither `migrations/` nor `scripts/init_test_postgres_schema.py:460–493` currently includes `auth_user_id`, `identity_class`, `is_linked`, `reconciliation_action`, or `reconciliation_status` on `public.affiliates` (because Gate B1 live identity linking is held per `ONLINEBOOST_PHASE2B_RELEASE_READINESS.md:33`).
   - **Impact in Staging:** If `public.affiliates` in Staging lacks columns `auth_user_id`, `identity_class`, and `is_linked`, calling `process_order_paid_growth_event` (`POST /api/v1/growth/simulate/order-paid`) will fail closed with `psycopg2.errors.UndefinedColumn` (`RuntimeError: [GROWTH WORKER FAIL-CLOSED]`).
3. **`DB-03` — Extra Payload Keys (`type`, `invoice_id`) in `allocate_upgrade_commission` vs `public.affiliate_commissions` DDL:**
   - `AffiliateService.record_prorated_upgrade_commission` (`app/services/affiliate_service.py:400–408`) constructs a clean `db_payload` containing strictly the 7 DDL columns `(tenant_id, affiliate_id, order_id, order_amount, amount, status, created_at)`.
   - By contrast, `AffiliateService.allocate_upgrade_commission` (`app/services/affiliate_service.py:653–668, 719–732`) passes `direct_comm_record` / `am_comm_record` directly to `supabase.table("affiliate_commissions").insert(...)`, which includes extra keys `"type"` (`"SUBSCRIPTION_UPGRADE_PRORATED"` / `"AM_OVERRIDE_UPGRADE"`) and `"invoice_id"`.
   - **Impact in Staging:** Unless `public.affiliate_commissions` in Staging has `type VARCHAR` and `invoice_id VARCHAR` columns (or `allocate_upgrade_commission` strips `db_payload` like `record_prorated_upgrade_commission`), Supabase PostgREST will reject the insert with `PGRST204` (`column not found in schema cache`), triggering the fail-closed `RuntimeError`.
4. **`DB-04` — Pending Gate A Snapshot Columns on `public.payout_requests`:**
   - `PartnerService.request_payout` (`app/services/partner_service.py:417–439`) inserts `snapshot_bank_name`, `snapshot_account_number`, `snapshot_account_holder`, `bank_name`, `account_number`, `account_holder_name`, `partner_name`, `partner_phone` into `public.payout_requests`, whereas `migrations/008_whitelist_partners_bank_and_payouts.sql:58–67` only defines `(id, partner_id, bank_account_id, amount, status, proof_attachment_url, created_at, processed_at)` and the Gate A `ALTER TABLE` (`P0_GATE_A_FINAL_EVIDENCE_AND_GOVERNANCE_REVIEW.md:531–539`) is not yet in `migrations/`.

---

## 4. IDENTITY & COMMISSION INTEGRITY CHECK

### 4.1 Class 1, Class 2, and Manual Review Boundary Mapping (`is_class_1_commission_eligible`)

The authoritative eligibility gate `is_class_1_commission_eligible(aff_record)` in `app/services/affiliate_service.py:88–231` (aligned with the offline taxonomy engine `classify_records` in `scripts/audit_affiliate_identities.py:251–520`) enforces a **strict positive-proof, fail-closed boundary**:

| Identity Class / Condition | Code Reference (`affiliate_service.py`) | Return Tuple `(bool, reason)` | Payable Writer Behavior |
| :--- | :--- | :--- | :--- |
| **`CLASS_1_EXACT_LINKED_HEALTHY`** (with active status, valid `auth_user_id`, zero discrepancy flags, AND positive link proof: `is_linked=True` / `relationship_valid=True` / `identity_verified=True` / `link_status` in `_ELIGIBLE_LINK_STATUSES`) | `L88–L231` (`_ELIGIBLE_LINK_STATUSES` at `L56–L59`) | `(True, "CLASS_1_EXACT_LINKED_HEALTHY")` | **ELIGIBLE:** Automatic payable commission persisted to DB (`HOLDING` / `APPROVED` / `PENDING_PAYOUT`). |
| **`CLASS_2` / `CLASS_2_UNLINKED_CANDIDATE`** | `L28–L29`, `L119–L120` | `(False, "CLASS_2_MANUAL_REVIEW_ONLY")` | **BLOCKED (Manual Review Only):** `status="held_manual_review"`, `payout_commission=0`, **0 DB writes**, **0 auto-link**, logs `AFFILIATE_COMMISSION_HELD_MANUAL_REVIEW`. |
| **Class 1 Label + Valid `auth_user_id` Missing Positive Link Proof** (`CTO-PR24-REVIEW-003` Blocker A) | `L220–L229` | `(False, "MISSING_POSITIVE_IDENTITY_LINK")` | **BLOCKED:** Rejects records that have `CLASS_1_EXACT_LINKED_HEALTHY` and `auth_user_id` but lack explicit positive link proof (`is_linked=True`, etc.). |
| **Missing `identity_class` / `classification` / `taxonomy_class`** | `L105–L117`, `L158–L159` | `(False, "MISSING_IDENTITY_CLASS")` | **BLOCKED:** Never infers Class 1 from absence of a negative flag. |
| **Non-Class 1 Taxonomy (`CLASS_1A`, `CLASS_1B`, `CLASS_3`, `CLASS_4A`, `CLASS_4B`, `CLASS_5`, `CLASS_6`)** | `L23–L40`, `L161–L163` | `(False, "NON_CLASS_1_INELIGIBLE_<CLASS>")` | **BLOCKED:** Discrepancy, stale FK, collision, phone mismatch/missing, or orphan records blocked fail-closed. |
| **Missing, Blank, or Placeholder `auth_user_id`** (`none`, `null`, `unlinked`, `orphan`, `stale`, etc.) | `L61–L64`, `L165–L168` | `(False, "MISSING_OR_INVALID_AUTH_USER_ID")` | **BLOCKED:** Zero fallback to email, phone, or referral code matching. |
| **Stale / Invalid Identity Relationship** (`is_stale_auth_reference=True`, `auth_user_exists=False`, mismatched `auth_user.id`/`email`, or `link_status` not in `_ELIGIBLE_LINK_STATUSES`) | `L170–L218` | `(False, "STALE_OR_INVALID_IDENTITY_RELATIONSHIP")` | **BLOCKED:** Held for investigation; 0 DB writes. |
| **Manual Review / Discrepancy Flags** (`manual_review=True`, `has_discrepancy=True`, `reconciliation_action` in `MANUAL_REVIEW_ACTIONS` or containing `MANUAL\|HOLD\|FLAG\|TRIAGE`) | `L42–L49`, `L122–L156` | `(False, "MANUAL_REVIEW_STATUS_INELIGIBLE")` / `"DISCREPANCY_STATUS_INELIGIBLE"` / `"MANUAL_REVIEW_OR_DISCREPANCY_*"` | **BLOCKED:** Held for manual review; 0 DB writes. |
| **Inactive / Suspended Affiliate** (`status` not in `ACTIVE`, `APPROVED`) | `L99–L101` | `(False, "AFFILIATE_INACTIVE_<STATUS>")` | **BLOCKED:** 0 DB writes. |

---
### 4.2 Exhaustive Audit of All Commission Writers & Residual Observations

| # | Target Ledger / Table | Writer Function & File:Line | Enforces `is_class_1_commission_eligible()`? | Idempotency Mechanism | Fail-Closed DB Error Behavior | Audit Status & Residual Findings |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `affiliate_commissions` (`HOLDING`) + `_commissions` cache | `AffiliateService.allocate_upgrade_commission` (`app/services/affiliate_service.py:451–784`) | **YES** (Direct at `L576`; AM override at `L711` using 18-col `_AFFILIATE_ELIGIBILITY_COLUMNS`) | Pre-insert DB lookup (`L607–L635`) + `_is_unique_constraint_conflict` (`23505`, `L670–L681`, `L734–L735`) | Raises `RuntimeError` if `supabase is None` (`L529–L533`) or on non-unique DB error (`L682–L685`, `L737–L740`). Cache written strictly post-DB (`L688`, `L742`). | **PASS** (Note `DB-03`: payload includes `type` and `invoice_id`). |
| 2 | `affiliate_commissions` (`HOLDING`) + `_commissions` cache | `AffiliateService.record_prorated_upgrade_commission` (`app/services/affiliate_service.py:266–431`) via `BillingService.mark_invoice_paid` (`billing_service.py:285`) | **YES** (`L354–L377` using 18-col `_AFFILIATE_ELIGIBILITY_COLUMNS` at `L343`) | `.upsert(db_payload, on_conflict="tenant_id, order_id")` (`L409`) + `_is_unique_constraint_conflict` (`L412`) | Raises `RuntimeError` if `supabase is None` (`L290–L294`) or on non-unique DB error (`L417–L422`). Cache written post-DB (`L425–L426`). | **PASS** |
| 3 | `affiliate_commissions` (`APPROVED`) | `process_order_paid_growth_event` (`app/services/growth_service.py:92–245`) | **YES** (`L154` after joining `affiliates` with `auth_user_id, identity_class, is_linked` at `L126–L128`) | `ON CONFLICT (tenant_id, order_id) DO UPDATE ... WHERE status NOT IN ('APPROVED', 'PAID', 'SETTLED')` (`L180–L189`) + `rowcount == 0` guard (`L193–L196`) | `conn.rollback()` and raises `RuntimeError("[GROWTH WORKER FAIL-CLOSED]...")` (`L206–L214`). | **PASS** (Requires `DB-02` columns on `public.affiliates` in staging DB). |
| 4 | `commission_ledger` (`PENDING_PAYOUT`) | `PaymentOrchestrator.process_xendit_webhook` (`app/services/payment_orchestrator.py:82–400`) | **PARTIAL (`L249`)** — see Residual Notes `INT-01a/b/c` below | Catches `23505` / `duplicate key` / `unique constraint` on `commission_ledger` insert (`L307–L313`) | Raises `RuntimeError("[Payment FAIL-CLOSED]...")` on `AssertionError` or non-unique DB insert error (`L344–L351`). | **CONDITIONAL (`INT-01a/b/c`):** Zeroes rates when `aff_res.data` fails Class 1 check, but see 3 residual paths below. |
| 5 | `affiliate_commissions` (`PENDING` reservation) | `create_checkout_order_with_shipping` (`app/services/checkout_shipping_service.py:160–244`) | **NO** (Non-payable `PENDING` checkout reservation) | `ON CONFLICT (tenant_id, order_id) DO UPDATE SET ... status = 'PENDING'` (`L236–L243`) | `conn.rollback()` and returns `{"success": False, "error": str(e)}` (`L255–L257`). | Non-payable reservation at checkout; see Writer #6 for COD transition. |
| 6 | `affiliate_commissions` (`PENDING` -> `APPROVED`) | `reconcile_single_cod_order` (`app/services/cod_settlement_service.py:12–111`) | **NO (`INT-02`)** | `UPDATE affiliate_commissions SET status = 'APPROVED' WHERE order_id = %s AND tenant_id = %s` (`L65–L70`) | `conn.rollback()` and returns `{"success": False, "error": str(e)}` (`L106–L108`). | **RESIDUAL (`INT-02`):** Promotes `PENDING` shipping commission to `APPROVED` on COD settlement without checking `is_class_1_commission_eligible()`. |
| 7 | `commission_ledger` (`PENDING_PAYOUT`) | `_record_settlement_and_ledger_sync` (`app/routes/xendit.py:404–615`) & `settle_order_atomic` (`app/services/checkout_service.py:165–365`) | **NO (`INT-03`)** | `ON CONFLICT (reference_id) DO NOTHING` (`xendit.py:567`, `checkout_service.py:257`) | `conn.rollback()` and re-raises -> HTTP `503 DATABASE_UNAVAILABLE` (`xendit.py:1016–1031`). | **RESIDUAL (`INT-03`):** If `orders.affiliate_code` or `manager_id` is set, inserts 25%/5% `PENDING_PAYOUT` row into `commission_ledger` without querying `affiliates` for Class 1 eligibility. |
| 8 | `shop_commission_ledger` (`PENDING`) | `process_successful_subscription` (`app/services/subscription_service.py:415–505`) | **YES for upgrades (`L417–L433`); NO for new subs (`L435–L445`, `INT-04`)** | Guarded by `xendit_invoice_id` check prior to `shop_subscriptions` insert | Logs warning on `shop_commission_ledger` error (`L503–L504`); upgrade commission fails closed in `allocate_upgrade_commission`. | **RESIDUAL (`INT-04`):** Initial subscription (`is_upgrade=False`) writes `shop_commission_ledger` without Class 1 check. |
| 9 | `commission_ledger` (`PAID_OUT`) & `payout_requests` (`PAID`) | `PayoutService.settle_affiliate_batch` (`app/services/payout_service.py:17–55`) & `mark_payout_paid` (`app/routes/partner_routes.py:362–379`) | **HARD-LOCKED (`HTTP 403`)** | Locked before execution via `payout_disbursement_locked()` (`app/routes/affiliate_payout_routes.py:13–21`) | Immediate `HTTP 403 Forbidden` (`{"error": "PAYOUT_DISBURSEMENT_LOCKED"}`) at `app/main.py:472–475` and `partner_routes.py:371–378`. | **CONTAINED:** Zero funds can be settled or marked paid across any endpoint. |


#### Detailed Residual Integrity Notes (`INT-01` .. `INT-04`):
- **`INT-01` (`app/services/payment_orchestrator.py:224–305`):**
  - **`INT-01a` (Zero-Amount Row on Non-Class 1):** When `is_class_1_commission_eligible(aff_row)[0]` is `False` (`L249`), `affiliate_rate` and `manager_rate` are zeroed (`0.0`), but `L305` still inserts a `PENDING_PAYOUT` row into `commission_ledger` with `affiliate_commission_amount = 0.0` rather than skipping the insert.
  - **`INT-01b` (Empty `aff_res.data` Fallback):** If `aff_lookup_val` is present on the order (`L229`) but `aff_res.data` returns `[]` (`L234`), the `if aff_res.data:` block is skipped and `affiliate_rate = 25.0` / `manager_rate = 5.0` defaults remain active. Similarly, direct `manager_id` (`L263–L265`) does not query `is_class_1_commission_eligible()`.
  - **`INT-01c` (Positional Tuple Columns at `L237–L247`):** Lists 9 columns (`id`..`metadata`) rather than the 18-column `_AFFILIATE_ELIGIBILITY_COLUMNS` tuple; dict rows from PostgREST retain all keys, but positional tuple rows would omit `is_linked`.
- **`INT-02` / `INT-03` / `INT-04` Containment:** While secondary SQL paths (`cod_settlement_service.py:65–70`, `xendit.py:543–587`, `checkout_service.py:233–275`, `subscription_service.py:435–504`) can write `PENDING_PAYOUT` / `APPROVED` rows without invoking `is_class_1_commission_eligible()`, all actual disbursement endpoints (`POST /payout/settle` and `PUT/POST /api/v1/manager/payouts/{payout_id}/mark-paid`) are hard-locked fail-closed with `HTTP 403 PAYOUT_DISBURSEMENT_LOCKED`.

---

## 5. STAGING TEST PLAN & ROLLBACK PLAN

### 5.1 Staging Verification Test Matrix (Positive, Negative, Idempotency Duplicate & Fail-Closed DB Error)

| Scenario ID | Category | Target Flow / Endpoint | Input / Precondition | Expected Deterministic Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **STG-POS-01** | **Positive** | Prorated Upgrade Direct Affiliate (`allocate_upgrade_commission` / `record_prorated_upgrade_commission`) | Tenant linked to active `CLASS_1_EXACT_LINKED_HEALTHY` affiliate (`auth_user_id` valid, `is_linked=True`, no AM), `amount_paid = 66700`, `rate = 20%` | 1 row inserted in `affiliate_commissions` (`status='HOLDING'`, `amount=13340`); 0 AM override rows (Anti-Ghost AM); net platform revenue `Rp 53.360`. |
| **STG-POS-02** | **Positive** | Multi-Tier Affiliate + Class 1 AM Override (`allocate_upgrade_commission`) | Direct `CLASS_1_EXACT_LINKED_HEALTHY` affiliate (`20%`) + active `CLASS_1_EXACT_LINKED_HEALTHY` AM (`5%`, `is_linked=True`) on `Rp 66.700` | 2 rows in `affiliate_commissions`: direct (`order_id=inv`, `amount=13340`) + AM override (`order_id=inv_am`, `amount=3335`); platform net `Rp 50.025`. |
| **STG-POS-03** | **Positive** | Growth Order Paid (`POST /api/v1/growth/simulate/order-paid`) | Order bound to `attributions` with Class 1 linked affiliate (`25%` rate) on `Rp 100.000` | 1 row in `affiliate_commissions` (`status='APPROVED'`, `amount=25000`); 1 WhatsApp notification; 1 Meta CAPI `Purchase` event. |
| **STG-NEG-01** | **Negative** | Organic Guardrail (`allocate_upgrade_commission` / Subscription Webhook) | Tenant with `affiliate_id=None`, `referral_code=None` pays `Rp 66.700` | Returns `status="skipped"`, `reason="ORGANIC_NO_AFFILIATE"`, `payout_commission=0`; **0 rows** in `affiliate_commissions`; logs `ORGANIC_SUBSCRIPTION_PROCESSED`. |
| **STG-NEG-02** | **Negative** | Class 2 Unlinked Candidate (`allocate_upgrade_commission` & `mark_invoice_paid`) | Affiliate with `identity_class="CLASS_2_UNLINKED_CANDIDATE"` or `reconciliation_action="FLAG_FOR_MANUAL_REVIEW"` | Returns `status="held_manual_review"`, `reason="CLASS_2_MANUAL_REVIEW_ONLY"`, `payout_commission=0`; **0 rows** in `affiliate_commissions` and `_commissions`. |
| **STG-NEG-03** | **Negative** | Missing Positive Identity Link Proof (`CTO-PR24-REVIEW-003` Blocker A) | Affiliate with `identity_class="CLASS_1_EXACT_LINKED_HEALTHY"` + valid `auth_user_id`, but missing `is_linked=True` / `relationship_valid=True` / `link_status` | Returns `status="held_manual_review"`, `reason="MISSING_POSITIVE_IDENTITY_LINK"`, `amount=0.0`; **0 DB writes** and **0 in-memory entries**. |
| **STG-NEG-04** | **Negative** | Stale Auth Reference / Missing Class / Discrepancy (`Case 1, 2, 3, 6`) | Affiliate missing `identity_class`, missing `auth_user_id`, `is_stale_auth_reference=True`, or `has_discrepancy=True` | `is_class_1_commission_eligible()` returns `(False, reason)`; **0 DB writes**. |
| **STG-NEG-05** | **Negative** | Webhook Auth, Cross-Realm JWT, IDOR & Disbursement Lock | Invalid `x-callback-token`; `aud="authenticated"` on Core route; client-supplied `affiliate_id`/`partner_id`; `POST /payout/settle` or `PUT /api/v1/manager/payouts/{id}/mark-paid` | `HTTP 403` on bad callback token; `HTTP 401` on cross-realm/expired JWT; `HTTP 403` on IDOR; `HTTP 403 PAYOUT_DISBURSEMENT_LOCKED` on settlement endpoints. |
| **STG-IDEM-01** | **Idempotency** | Concurrent Upgrade Commission Callbacks (5x parallel workers) | 5 concurrent calls to `allocate_upgrade_commission` for identical `(tenant_id, invoice_id)` | 1 DB insert succeeds; 4 calls hit pre-check or `uq_affiliate_commissions_tenant_order` (`23505`) and return `status="success"`, `idempotent=True`; **1 row total in DB**. |
| **STG-IDEM-02** | **Idempotency** | Concurrent Growth Order Paid Callbacks (4x parallel workers) | 4 concurrent calls to `process_order_paid_growth_event` for identical `(tenant_id, order_id)` | `ON CONFLICT (tenant_id, order_id) DO UPDATE ... WHERE status NOT IN ('APPROVED', 'PAID', 'SETTLED')` yields `rowcount=1` once and `rowcount=0` 3 times; **1 WhatsApp message sent**. |
| **STG-IDEM-03** | **Idempotency** | 3x Duplicate Xendit Webhook Delivery + Replay Audit Failure | 3 identical `POST /api/v1/payments/xendit/callback` payloads (including simulated failure of `PROCESSED_DUPLICATE_ORDER` audit insert on already-`PAID` order) | Call 1 settles order; Calls 2 & 3 return `HTTP 200` (`status="ALREADY_PROCESSED"`, `idempotent=True`); aborted replay audit rolls back cleanly with **zero duplicate ledger/WA/CAPI effects**. |
| **STG-ERR-01** | **Fail-Closed DB** | Non-Unique DB Persistence Error Across All Payable Writers | Simulated DB connection drop / constraint error (non-`23505`) during `allocate_upgrade_commission`, `record_prorated_upgrade_commission`, `process_order_paid_growth_event`, or `PaymentOrchestrator` | Raises explicit `RuntimeError`; `conn.rollback()` executed on SQL transactions; in-memory `AffiliateService._commissions` remains empty (`[]`). |
| **STG-ERR-02** | **Fail-Closed DB** | Database Outage During Xendit Idempotency Check | Simulated PostgreSQL connection failure inside `_check_db_idempotency_sync` (`app/routes/xendit.py:318–322`) | Raises `RuntimeError("[SECURITY FAIL-CLOSED]...")` and returns `HTTP 503 Service Unavailable` (`IDEMPOTENCY_CHECK_UNAVAILABLE`); zero downstream settlement execution. |
| **STG-RLS-01** | **Catalog & RLS** | Read-Only Catalog & Cross-Tenant Isolation Gate | Execute `python scripts/enable_rls_security.py --verify` and `python scripts/audit_production_catalog_rls.py` against staging DB | 100% tenant tables have `relrowsecurity=true` & `relforcerowsecurity=true`; 4/4 views have `security_invoker=true`; `authenticated`/`anon` have `rolbypassrls=false`; 0 `USING (true)` policies. |

---

### 5.2 Rollback Plan, Commit Targets & Abort Criteria

#### A. Git Commit Provenance & Rollback Target Hierarchy
```text
c17cc81a37705cecb482aa7368a1e774a5cb5a45  (Parent 1: Pre-PR #24 main HEAD — Merge PR #23)
70a8c5186437837c846c74a1eabca3d4465286d2  (Phase 2A Hardened Baseline)
  └── ab58b3317efd90cea2c7a21cccd933c51f35c2f1  (PR #24 Base: Phase 2B P0 Remediation)
        └── 917bd651ec997f6701992ba645c7b3904a1a05b3  (CTO-PR24-REVIEW-001 Hardening)
              └── d2d03f685df15ef10a9937c879608027cf995cba  (CTO-PR24-REVIEW-002 Hardening)
                    └── 4066a3673827a4d8ee9e7e946f14d6a3d5e8c48d  (Parent 2: CTO-PR24-REVIEW-003 Head)
                          └── a82b6fdf76c043c9a3ee87f48c34062f05258437  (CURRENT main HEAD — Merge PR #24)
```

1. **Hardened-Build-Only Rollback Invariant (`PHASE_2A_CLOSURE_AND_PHASE_2B_READINESS.md:267–276`):**
   - **Prohibition on Unhardened Rollback Under Live Traffic:** Rolling back live traffic to a build that re-enables compromised fallback secrets (`"boontrack-secret-key-production-3000"`) or removes `payout_disbursement_locked()` / `is_class_1_commission_eligible()` is **strictly prohibited**.
   - **Configuration Failure Recovery:** If staging startup fails due to missing `JWT_SECRET`, `SUPABASE_JWT_SECRET`, or `BOONTRACK_HMAC_SECRET`, remediate by injecting the required high-entropy environment variables rather than reverting security guards.
2. **Exact Rollback Commit Targets (If Authorized Under Infrastructure Hold):**
   - **Intra-PR Step-Back Target (Hardened PR #24 Prior Revision):** `d2d03f685df15ef10a9937c879608027cf995cba` (`fix(security): complete CTO-PR24-REVIEW-002 final targeted hardening`).
   - **Full PR #24 Merge Revert Target (`main` Parent 1):** `c17cc81a37705cecb482aa7368a1e774a5cb5a45` (requires `ONLINEBOOST_PAYMENT_STRICT_HOLD=true` and `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` locked at infrastructure level prior to revert):
     ```powershell
     # Non-destructive merge revert command (DO NOT EXECUTE without written CTO authorization)
     git revert -m 1 a82b6fdf76c043c9a3ee87f48c34062f05258437 --no-edit
     ```

#### B. Mandatory Abort Criteria (Immediate Staging Halt Triggers)
Staging verification must be **aborted immediately** and held if any of the following 6 conditions occur:
1. **Identity Boundary Breach:** Any `CLASS_2_UNLINKED_CANDIDATE`, unlinked, stale-FK, or missing-positive-link-proof affiliate receives a non-zero commission row in `affiliate_commissions` or `commission_ledger`, or is auto-linked to `auth.users`.
2. **Organic Revenue Leakage:** Any organic order or subscription upgrade (`affiliate_id=None`, `referral_code=None`) generates a row in `affiliate_commissions` or reduces platform net revenue below 100%.
3. **Disbursement Lock Bypass:** `POST /payout/settle` or `PUT/POST /api/v1/manager/payouts/{payout_id}/mark-paid` returns any status other than `HTTP 403 Forbidden` (`PAYOUT_DISBURSEMENT_LOCKED`).
4. **Duplicate Financial / Notification Effect:** Replaying a Xendit webhook (`event_id` or `external_id`) produces >1 row in `financial_ledger`, `commission_ledger`, or `affiliate_commissions`, or >1 WhatsApp/CAPI dispatch.
5. **Silent DB Failure / In-Memory Fallback:** A database persistence error during commission allocation returns `status="success"` or populates `AffiliateService._commissions` without raising `RuntimeError`.
6. **PostgreSQL Catalog RLS Violation:** `scripts/enable_rls_security.py --verify` or `scripts/audit_production_catalog_rls.py` reports any table with `relrowsecurity=false`, `relforcerowsecurity=false`, wildcard `USING (true)` policy, or view missing `security_invoker=true`.

---

## 6. PRE-STAGING RELEASE GATE CHECKLIST

- [x] **22/22 Commission Guardrail, Proration & Split Tests Verified on `main` (`a82b6fd`)** (`9 + 5 + 8 = 22 PASSED`).
- [x] **34/34 Offline Identity Taxonomy Audit Tests Verified** (`tests/test_audit_affiliate_identities_offline.py`).
- [x] **Payout Disbursement Endpoints Hard-Locked (`HTTP 403 PAYOUT_DISBURSEMENT_LOCKED`)** (`tests/test_payout_disbursement_lock.py`).
- [ ] **Action Item `ENV-01/02`:** Add `JWT_SECRET`, `SUPABASE_JWT_SECRET`, `INTERNAL_MAGIC_SECRET`, `CORE_JWT_*`, and `SUPABASE_JWT_*` pass-through entries to `docker-compose.prod.yml` and `.env.example` prior to container staging boot.
- [ ] **Action Item `DB-01..DB-04`:** Reconcile staging DDL for `public.affiliates` (`auth_user_id`, `identity_class`, `is_linked`), `public.affiliate_commissions` (`type`, `invoice_id` or payload filter), and `public.payout_requests` snapshot columns under supervised Gate B1 authorization.
- [ ] **Action Item `INT-01..INT-04`:** Enforce `is_class_1_commission_eligible()` on secondary SQL writers (`xendit.py:543`, `checkout_service.py:233`, `cod_settlement_service.py:65`, `subscription_service.py:435`, and empty `aff_res.data` branch in `payment_orchestrator.py:234`) prior to unlocking `payout_disbursement_locked()`.









  tests/test_commission_split.py
```
