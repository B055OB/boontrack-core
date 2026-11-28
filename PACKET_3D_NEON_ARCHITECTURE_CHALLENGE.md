# BOONTRACK — PACKET 3D ARCHITECTURE CHALLENGE
## INDEPENDENT READ-ONLY PRINCIPAL DESIGN REVIEW

**Document ID:** `PACKET_3D_NEON_ARCHITECTURE_CHALLENGE.md`  
**Model:** Neon X-tra High  
**Role:** Principal Cross-Repository Payment Architect  
**Repositories Audited:** `boontrack-core` (`C:\boontrack-core-gateb-p2` @ `3e4ffe21c1c53313ac87768043be564085f7c9d3`, `C:\boontrack-core` @ `0e18979ac02488100e28df2becd2751f9a22a802`) + `boontrack-inbox` (`C:\boontrack-inbox-gateb-p2` @ `133f178c4d05c2649a91e1051e2494ddbdd837dd`, `C:\boontrack-inbox-gateb-recut-101` @ `a3301154ab623385fa2cf1d0520fb4cf299f80fc`, `C:\boontrack-inbox-gateb-recut-94` @ `99dd15958f1162ffd5d75146c366b2e4ab3eaede`)  
**Primary Input Challenged:** `C:\boontrack-core\PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md` (and Packet 3C E2E artifacts under `C:\Users\Alldy\.gemini\antigravity\brain\660951a5-1be4-4ffe-9713-9af494ea92b8\`)  
**Evaluation Mode:** STRICT READ-ONLY (Zero source edits, zero git mutations, zero SQL executed, zero remote connections)  
**Timestamp:** 2026-11-22T21:15:00+07:00  

### GLOBAL LOCKS ACKNOWLEDGED
- Production Supabase, Railway Production, and Xendit Production remain on **STRICT HOLD**.
- Zero migrations, merges, pushes, deployments, credential rotations, or Production preflight executed.
- **SSOT v1.1** remains **FROZEN**.
- **BWM Workforce** remains **ISOLATED / OUT OF SCOPE**.

---

## 1. EXECUTIVE VERDICT

**Overall Adjudication Verdict: `MODIFY` (Do NOT execute the Command Center's provisional Packet 3D plan as drafted; execute the smaller, boundary-preserving architecture below.)**

Independent source-level inspection across all five local candidate worktrees confirms that all six Packet 3C blockers (`BLK-P3C-01` through `BLK-P3C-06`) represent real architectural defects—**but the Command Center's provisional adjudication (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md` and `packet3c_cto_delivery_report.md`) contains five material forensic inaccuracies and four unsafe architectural proposals** that would either fail to close the blockers or introduce worse financial/operational hazards if executed directly:

1. **`REJECT` Core Migration `037_add_orders_runtime_schema.sql` (`BLK-P3C-02`):** Putting an 18-column `ALTER TABLE public.orders` migration in `boontrack-core` violates Inbox ownership of commerce orders, materializes columns that Inbox's own `sanitizeOrderPayload()` strips (`unique_code`, `total_amount` are absent from `VALID_ORDER_COLUMNS` in `C:\boontrack-inbox-gateb-p2\lib\order-sanitizer.ts:7-57`), duplicates existing physical columns (`gross_amount`, `amount`), and omits the one physical column actually required for safe checkout retries (`idempotency_key`).
2. **`REJECT` "Timeout + `rollbackOrphanOrder` DELETE" as the fix for `BLK-P3C-03`:** Deleting `public.orders` on an Inbox `AbortSignal.timeout()` (`C:\boontrack-inbox-gateb-p2\lib\checkout-service.ts:29-91`) creates a catastrophic split-brain when Core has already accepted the request and created a live Xendit QRIS charge (and triggers `ON DELETE CASCADE` on `public.checkout_sessions` in `C:\boontrack-core-gateb-p2\migrations\035_durable_checkout_sessions.sql:20`). Timeouts are **unknown outcomes**, not definitive rejections; they require a durable `PAYMENT_INIT_UNKNOWN` state + stable idempotency keys.
3. **`MODIFY` Payment Contract Remediation (`BLK-P3C-01`):** Simply adding `"PAYMENT_GATEWAY"` as an alias in `PaymentAdapterFactory.resolve` (`C:\boontrack-core-gateb-p2\app\services\payment\factory.py:75`) will **not** achieve per-tenant credential isolation. Raw source proves that `create_dynamic_qris_endpoint` (`C:\boontrack-core-gateb-p2\app\routes\payment.py:171-209`) and `quick_qris_checkout_endpoint` (`C:\boontrack-core-gateb-p2\app\routes\d2c_order_routes.py:88-120`) **discard the resolved `adapter` variable** and call the global singleton `xendit_service` (which also makes a second unrequested `POST /v2/invoices` call at `C:\boontrack-core-gateb-p2\app\services\xendit_service.py:284-295`), while `XenditAdapter` (`C:\boontrack-core-gateb-p2\app\services\payment\gateway_xendit.py:36,68,93,120`) ignores `self.secret_key`, and `TenantCredentialProfile` (`C:\boontrack-core-gateb-p2\app\core\security\payment_auth_guard.py:1769-1781`) only models inbound webhook `verification_secrets`, not outbound `api_secret_ref`.
4. **`MODIFY` Settlement Hardening (`BLK-P3C-04`, `BLK-P3C-06`):** Step 1 misdiagnosed `app/routes/xendit.py` by citing unreachable dead code (`_record_settlement_and_ledger_sync` at `C:\boontrack-core-gateb-p2\app\routes\xendit.py:485-738`) while missing that `process_xendit_webhook_core` (`xendit.py:745-1108`) **already** calls `commit_verified_settlement_transaction` and quarantines `EXPIRED` orders (`OB-04` passed!). Simultaneously, Step 1 missed **seven additional Inbox direct-`PAID` mutation paths** and **five live hazards inside Core settlement** (ephemeral Ed25519 key fallback, tautological `provider_verification_secret=candidate_token` boundary call, duplicate global-token route `app/api/webhook_payment.py`, fire-and-forget `asyncio.create_task` side effects, and Core directly executing `UPDATE orders` inside `provenance_authority.py:2172-2187`).
5. **`REJECT` Unconditional Parallel Approval of Sibling Inbox Branches `Recut-101` & `Recut-94`:** Contrary to `packet3c_cto_delivery_report.md:159-160`, `a3301154` (`Recut-101`) and `99dd1595` (`Recut-94`) **collide on 3 Studio files** (`app/studio/desk/page.tsx`, `app/studio/desk/ugc-studio/page.tsx`, `app/studio/page.tsx`), AND `Recut-94` retains a direct Inbox-to-Xendit invoice path (`C:\boontrack-inbox-gateb-recut-94\app\api\studio\billing\create-invoice\route.ts:213-280`) emitting `TOPUP-STUDIO-*` IDs that Core hard-rejects (`HTTP 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD` at `xendit.py:771-781`).
6. **`ACCEPT` Deferral of Shabu Aji Static QRIS (`BLK-P3C-05`):** Phase 1 release MUST ship with **OnlineBoost `NATIVE_PG` Dynamic QRIS (exact `Rp249.000`, `unique_code = 0`)** only, keeping Shabu Aji Static Merchant QRIS (`DIRECT_TENANT` rail) deferred (`BLOCKED` pending Founder/CTO ADR + Phase 2 Direct-Tenant security gate) and disabling Inbox's local static-QRIS bypass path.

---

## 2. ACCEPTED PROVISIONAL DECISIONS

| Item | Decision Source | Status | Forensic Verification & Rationale |
|---|---|---|---|
| **Commit Identity & Ancestry Tree** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:36-46, 100-135` | `ACCEPT` | Verified via `git worktree list`, `git log`, and `git diff --stat`: Inbox candidates `133f178c`, `a3301154`, `99dd1595` are siblings off `b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc`; Core candidate `3e4ffe21` is 5 linear commits ahead of `dde1011b8207e2c2d4db812475c8ebb8debe211e`. Clean trees on `C:\boontrack-core-gateb-p2` and `C:\boontrack-inbox-gateb-p2`; `C:\boontrack-core` (`0e18979`) is dirty and must not be used as release base. |
| **108-Step Migration Manifest Accounting (41+59+8)** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:20-23, 399-409` | `ACCEPT` | Verified directly in `C:\boontrack-core-gateb-p2\migrations\reconciliation\shared_db_migration_manifest.json:25-164`: 41 Core entries (`031` replaced by `R06`), 59 Inbox entries (`20260921_create_payment_events.sql` replaced by `R01`; `20261004_create_credit_ledger_tables.sql` replaced by `R05`), and 8 Reconciliation steps (`R02` executed twice at lines 73 and 75). |
| **Core as Sole Financial / Payment / Ledger / Provenance Authority** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:412-425`; `ARCHITECTURE.md:5363-5371` | `ACCEPT` | Verified across `app/core/security/payment_auth_guard.py`, `app/core/security/provenance_authority.py`, and `lib/payment/xendit-service.ts:1-40`. Inbox must never hold Xendit signing/API authority or directly write authoritative settlement states. |
| **Zero Algorithm Invention on Unique Code (`BLK-P3C-05`)** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:312-326`; `run_e2e_smoke_tests.py:1200-1224` | `ACCEPT` | Verified 4-way contradiction across `ARCHITECTURE.md:1673-1680` (downward), `migrations/035_durable_checkout_sessions.sql:51-58` + `ARCHITECTURE.md:2189-2191` (upward), `lib/unique-code-generator.ts:43-63` (zero for QRIS, upward for manual), and `app/services/payment/factory.py:50-61` (Direct Tenant Rail hard-locked). |
| **Elimination of Direct Inbox Xendit Webhooks (`BLK-P3C-04`)** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:266-309` | `ACCEPT` (with scope expansion in §3 & §7) | Confirmed `app/api/webhooks/xendit/paid/route.ts:155-165` directly mutates `orders` to `PAID` with 0 Core ledger/provenance rows (`packet3c_e2e_evidence.json:222-240`). Must expand decommissioning to all 10 Inbox mutation paths identified in §7. |
| **Rejection of `EXPIRED` Order Resurrection (`BLK-P3C-06`)** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:329-352` | `ACCEPT` | Confirmed `app/api/v1/payments/qris/create/route.ts:652-654, 706-711` checks only `isAlreadyPaid` and resets `EXPIRED` orders back to `PENDING` (verified in `packet3c_e2e_evidence.json:331-352`). |
| **Packet 3C E2E Test Gaming Findings (`OB-02B`..`SA-04` & `503`/`RST` Skips)** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:19, 490-493` | `ACCEPT` | Verified in `run_e2e_smoke_tests.py:666-693, 886-893, 986-996, 1402-1409, 1478-1485`: `OB-01`/`OB-01B` failed, so downstream webhook tests used raw SQL `INSERT INTO public.orders`, and HTTP 503 / TCP drop tests were replaced with `FakeResp` stubs. |
| **Single-Owner Lock on High-Contention Files** | `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:432-454` | `ACCEPT` (with expanded file list in §9) | Single-owner enforcement is essential, but the Step 1 list of 4 files omits 11+ additional shared/conflicting files across Core, Inbox payment routes, and Studio/Routing sibling recuts. |

---

## 3. REJECTED ASSUMPTIONS AND ALTERNATIVES

| # | Provisional Claim / Assumption | Verdict | Ground-Truth Counterexample (Path, Symbol, Line Range) | Safer Minimal Alternative |
|---|---|---|---|---|
| **R-01** | *"Authorize Core additive migration `037_add_orders_runtime_schema.sql` for the 18 missing `orders` columns."* (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:466, 503`) | `REJECT` | `public.orders` is Inbox-owned (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:416`). `lib/order-sanitizer.ts:7-57` (`VALID_ORDER_COLUMNS`) does **not** even contain `unique_code` or `total_amount`; `000_disposable_pg17_base_catalog_bootstrap.sql:153-154` already defines `gross_amount` and `amount`; Core `migrations/005_create_core_payment_tables.sql:5-18` & `035_durable_checkout_sessions.sql:18-65` already own `unique_code`, `total_amount`, `qr_string`; Inbox `20261003_payment_evidence_and_capi_outbox.sql:7-26` already owns `payment_evidence.evidence_url`. | Zero columns added by Core to `public.orders`. Use existing `orders.metadata` / `orders.fulfillment_metadata`, Core `payment_intents`, and Inbox `payment_evidence`/outbox tables. Add ONLY genuinely needed Inbox-owned `idempotency_key` (and conditional `correlation_id` if Quick POS is in Phase 1) via an **Inbox** migration (§5). |
| **R-02** | *"Core `app/routes/xendit.py:539-558` misclassifies `EXPIRED` orders as ghost orders and has not adopted `provenance_authority.py`."* (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:353-364`) | `REJECT` | `C:\boontrack-core-gateb-p2\app\routes\xendit.py:745-1108` (`process_xendit_webhook_core`) **already adopts** `CredentialProfileMapper` (line 967), `TrustedSettlementVerificationBoundary` (line 993), and `commit_verified_settlement_transaction` (line 1023), returning `200 QUARANTINED_LATE_SETTLEMENT` (lines 1056–1066)—confirmed passing in `packet3c_e2e_evidence.json:155-174` (`OB-04`). Lines `315-384` (`_check_db_idempotency_sync`) and `485-738` (`_record_settlement_and_ledger_sync`) are **unreachable dead code** (zero callers anywhere in `app/`). | Delete dead legacy helpers (`xendit.py:315-384, 485-738`) and remediate the **five actual live Core settlement bugs**: ephemeral Ed25519 key fallback (`xendit.py:66-88`), tautological boundary secret (`xendit.py:998`), fire-and-forget tasks (`xendit.py:1076-1098`), duplicate `webhook_payment_router` (`app/main.py:341`, `app/api/webhook_payment.py:51-107`), and Core's direct `UPDATE orders` (`provenance_authority.py:2172-2187`). |
| **R-03** | *"`A-02` passed deceptively on unmodified 108-step schema because `lib/checkout-service.ts:821-856` fell back to `coreOrderData` which omitted missing columns."* (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:19, 222, 488-489`) | `REJECT` | Raw source refutes this mechanism: `coreOrderData` (`C:\boontrack-inbox-gateb-p2\lib\checkout-service.ts:823-853`) **still explicitly includes** 4 absent columns (`affiliate_code:833`, `manager_id:834`, `briefing_url:846`, `customer_briefing:847`), and PostgREST rejects any unknown JSON key even when `null` (`PGRST204`). Further, `checkout-service.ts:1116-1129` unconditionally executes `.update({ qr_code_url: qrCodeUrl })` and throws on error. File timestamps show `pg17_108step_replay.log` ran at `19:44` while `packet3c_e2e_evidence.json` ran at `20:06` (+22 min), consistent with `p3c_postgres` container reuse after an earlier run applied `apply_ephemeral_diagnostic_orders_columns()` (`run_e2e_smoke_tests.py:384-411`). Exact earlier-run stdout is `NOT VERIFIED`. | Enforce `--reset-db` inside a brand-new tmpfs PostgreSQL 17 container before every E2E run, forbid any diagnostic `ALTER TABLE` shim in E2E harnesses, and remove `coreOrderData` schema-guessing fallback entirely after aligning `order-sanitizer.ts` with canonical migrations. |
| **R-04** | *"Fix `BLK-P3C-03` by adding `AbortSignal.timeout(8000)` + `rollbackOrphanOrder` on `AbortError`."* (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:472`; `packet3c_cto_delivery_report.md:107`) | `REJECT` | `rollbackOrphanOrder()` (`C:\boontrack-inbox-gateb-p2\lib\checkout-service.ts:29-91`) executes `DELETE FROM order_items` and `DELETE FROM orders` (or sets `FAILED`/`CANCELLED`). If Core already accepted the request and Xendit takes 9s (`xendit_service.py:212` has `timeout=30.0` + second call `/v2/invoices` at line 166 has another `30.0s`), deleting `orders` at 8s destroys the order (and cascades to `checkout_sessions` via `035_durable_checkout_sessions.sql:20`) while Xendit creates a live payable QRIS! Also misses `qris/create/route.ts:514` which calls Core BEFORE inserting `orders`. | Separate definitive 4xx rejection (`PAYMENT_INIT_FAILED`) from ambiguous timeout/5xx (`PAYMENT_INIT_UNKNOWN`), never `DELETE` orders on timeout, and bind every initiation to a stable `idempotency_key` across Inbox and Core (§6). |
| **R-05** | *"Fix `BLK-P3C-01` by adding `'PAYMENT_GATEWAY'` as an alias in `factory.py` (or emitting `'NATIVE_PG'` from Inbox)."* (`packet3c_cto_delivery_report.md:100`; `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:463`) | `REJECT` (Insufficient) | `C:\boontrack-core-gateb-p2\app\routes\payment.py:171-209` and `app\routes\d2c_order_routes.py:88-120` resolve `adapter = PaymentAdapterFactory.resolve(tenant_ctx)` and then **never call `adapter`**—they call global singleton `xendit_service.create_dynamic_qris()`, which uses `os.getenv("XENDIT_SECRET_KEY")` (`xendit_service.py:62-65`). `XenditAdapter` (`gateway_xendit.py:68,93,120`) also delegates to global `xendit_service`. `CredentialProfileMapper` (`payment_auth_guard.py:1769-1781`) lacks outbound `api_secret_ref`. `payment.py:164` bypasses factory for `"commerce"`/`"default"`. | Introduce canonical `rail` + `provider` + `channel` contract, extend `TenantCredentialProfile` with `api_secret_ref`, resolve credentials strictly server-side in `PaymentAdapterFactory`, and make `payment.py` execute through the per-tenant `adapter` directly (§4). |
| **R-06** | *"Deprecate Inbox webhook routes OR proxy all incoming webhooks through Inbox to Core."* (`packet3c_cto_delivery_report.md:114`) | `REJECT` (Proxy option) | Proxying provider webhooks through Inbox keeps Next.js/Vercel inside the payment-verification perimeter, adds latency/timeout failure modes, preserves legacy `XENDIT_CALLBACK_TOKEN` secrets in Inbox env, and violates `ARCHITECTURE.md:5363-5366` ("Next.js frontend is a pure consumer and MUST NOT ingest production payment gateway webhooks"). Also ignores 7 additional Inbox direct-`PAID` writers (`webhooks/xendit`, `webhooks/payment`, `webhook/payment`, `qris/webhook`, `reader/notification`, `evolution-webhook-handler.ts:1182-1190`, `financial-state-machine.ts:243-252` + `process_payment_match` RPC). | Hard-decommission (`HTTP 410 GONE`) all Inbox provider webhook/reader routes; zero proxying; route Xendit directly to Core; hard-lock `quick-paid`/`approve` for `NATIVE_PG` and Phase 1; disable WhatsApp payment auto-settlement and `process_payment_match` RPC (§7). |
| **R-07** | *"Approve `Recut-101` (`a3301154`) and `Recut-94` (`99dd1595`) directly to `main` — zero overlap with payment logic."* (`packet3c_cto_delivery_report.md:159-160`) | `REJECT` | `git diff --name-only` proves `a3301154` and `99dd1595` **directly conflict on 3 files**: `app/studio/desk/page.tsx`, `app/studio/desk/ugc-studio/page.tsx`, and `app/studio/page.tsx` (`Recut-101` hardens `/studio/register` and `isPreviewOrStagingHost`; `Recut-94` rewrites 2,795+ lines reverting links to `/register`). Furthermore, `Recut-94`'s `app/api/studio/billing/create-invoice/route.ts:213-280` directly calls `POST ${xenditApiUrl}/v2/invoices` with `process.env.XENDIT_SECRET_KEY` and `TOPUP-STUDIO-*` IDs that Core blocks with `403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD` (`xendit.py:771-781`). | Sequence local integration strictly: `b6eec81f` -> `133f178c` (P2) -> `99dd1595` (Studio rewrite, with Studio billing feature-gated OFF for Phase 1 per CTO Decision #2) -> `a3301154` (surgical routing rebase resolving the 3 Studio files under single owner) -> Packet 3D fixes (§10). |
| **R-08** | *"Core Migration `035` constraint is at line 44."* (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:319`) | `MODIFY` (Citation correction) | `C:\boontrack-core-gateb-p2\migrations\035_durable_checkout_sessions.sql:51-55` defines `CONSTRAINT chk_checkout_sessions_amounts CHECK (base_amount >= 0 AND total_amount > 0 AND total_amount = base_amount + unique_code)`. Line 44 is inside `chk_checkout_sessions_non_blank`. | Use verified line range `035_durable_checkout_sessions.sql:51-58` in ADR and test specifications. |
| **R-09** | *"In `OB-06B`, both `/api/webhooks/xendit/paid` and `/quick-paid` returned HTTP 200 and directly settled orders."* (`PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:288-305`; `run_e2e_smoke_tests.py:1192`) | `MODIFY` (Evidence precision) | In `packet3c_e2e_evidence.json:227-238`, `/api/webhooks/xendit/paid` returned `HTTP 200` and wrote `PAID` (0 ledger rows), whereas `/quick-paid` returned **`HTTP 401`** (harness secret mismatch) and left `ob_qp_id` in `PENDING`. However, raw source inspection of `app/api/v1/tenants/[slug]/orders/[id]/quick-paid/route.ts:281-295` and `app/api/orders/[orderId]/approve/route.ts:191-206` confirms that an authenticated merchant session **does** directly write `orders.status='PAID'` bypassing Core ledger/provenance. | Classify `quick-paid` and `approve` as **source-verified P0 dark-settlement paths** (`ACCEPT` blocker, `MODIFY` evidence citation). |

---

## 4. PAYMENT CONTRACT PROPOSAL (DESIGN QUESTION 1)

### 4.1 Complete Root-Cause Chain in Raw Source
1. **Mode Enum Mismatch:** Inbox checks/stores `mode: 'PAYMENT_GATEWAY'` (`C:\boontrack-inbox-gateb-p2\lib\checkout-service.ts:512,514`; `C:\boontrack-inbox-gateb-p2\lib\security\payment-destination-guard.ts:300,302,304`). Core `PaymentAdapterFactory.resolve` (`C:\boontrack-core-gateb-p2\app\services\payment\factory.py:46,75-78`) rejects anything outside `("NATIVE_PG", "GATEWAY", "XENDIT", "DUITKU")` with `422 UNSUPPORTED_PAYMENT_MODE`.
2. **Plaintext vs `secret_ref` Contradiction:** `factory.py:81-88,96-105` requires plaintext `secret_key`/`api_key`/`merchant_code` in `tenant_metadata.payment_config`, whereas `CredentialProfileMapper.parse_profiles_from_metadata` (`C:\boontrack-core-gateb-p2\app\core\security\payment_auth_guard.py:2009-2017`) rejects plaintext secrets in credential profiles (`422 INVALID_CREDENTIAL_PROFILE`).
3. **Missing Outbound Credential Schema:** `TenantCredentialProfile` (`payment_auth_guard.py:1769-1781`) only declares `verification_secrets` (inbound webhook verification); it has no outbound API credential pointer (`api_secret_ref`). In Packet 3C, `run_e2e_smoke_tests.py:286` set `ob_payment_config["secret_key"] = "env://ONLINEBOOST_XENDIT_SECRET_KEY"`, which `factory.py:81` passed literally without resolving.
4. **Dead `adapter` Variable & Global Singleton Leakage:** `app/routes/payment.py:169-209` and `app/routes/d2c_order_routes.py:87-120` validate `adapter = PaymentAdapterFactory.resolve(tenant_ctx)` and then discard `adapter`, invoking global `xendit_service.create_dynamic_qris()` (`app/services/xendit_service.py:62-65, 180-330`). Worse, `XenditAdapter.create_transaction` (`app/services/payment/gateway_xendit.py:68,93`) and `check_status` (`gateway_xendit.py:120`) also ignore `self.secret_key` and call global `xendit_service`.
5. **Dual Xendit API Call & Third-Party QR Leak:** `xendit_service.py:213` calls `POST /qr_codes` (`timeout=30s`) and then lines `284-295` make a second `POST /v2/invoices` call (`timeout=30s`) with the **same `external_id`** (60s worst-case latency + dual Xendit objects per order!), while line `273` constructs an external `https://api.qrserver.com/v1/create-qr-code/?data=...` URL (and Inbox constructs `https://quickchart.io/qr?text=...` at `checkout-service.ts:968,1057,1089`).
6. **Client Payment Hints & Unauthenticated Core Endpoint:**
   - Inbox `lib/checkout-service.ts:510` and `app/api/checkout/create-order/route.ts:148` allow client booleans `payload.isGateway || payload.isXendit` to influence `isGatewayOrQris`.
   - Core `app/routes/payment.py:139-168` lacks `InternalPaymentHMACVerifier` (`payment_auth_guard.py:855`), bypasses factory validation for `target_tenant in ("commerce", "default")` (`payment.py:164`), and trusts request-body `amount` directly.
   - Core `app/services/tenant_context_resolver.py:446-475` has a hardcoded fallback for `"onlineboost"` with non-UUID `id: "onlineboost"` and zero `payment_config`.

### 4.2 Canonical Provider/Channel Contract & Server-Side Credential Resolution (`ACCEPT` Design Target)

Store **one canonical schema** strictly server-side in `public.tenants.metadata.payment_config` (never accepted from client payloads; protected by `FORBIDDEN_CLIENT_PAYMENT_DESTINATION_FIELDS` in `lib/security/payment-destination-guard.ts:10-70`):

```json
{
  "payment_config": {
    "schema_version": 2,
    "rail": "NATIVE_PG",
    "active_provider": "XENDIT",
    "default_channel": "DYNAMIC_QRIS",
    "default_credential_profile_id": "cred_ob_xendit_prod_01",
    "credential_profiles": [
      {
        "credential_profile_id": "cred_ob_xendit_prod_01",
        "canonical_tenant_id": "<lowercase-uuid-matching-tenants.id>",
        "provider": "XENDIT",
        "channels": ["DYNAMIC_QRIS"],
        "environment": "production",
        "profile_status": "ACTIVE",
        "expected_provider_account_id": "<xendit-business-id>",
        "api_credentials": {
          "secret_ref": "env://TENANT_OB_XENDIT_API_KEY",
          "merchant_code": null
        },
        "verification_method": "XENDIT_CALLBACK_TOKEN",
        "verification_secrets": [
          {
            "secret_version_id": "v1",
            "secret_ref": "env://TENANT_OB_XENDIT_CALLBACK_TOKEN",
            "status": "ACTIVE",
            "created_at_utc": "2026-11-22T00:00:00Z"
          }
        ],
        "updated_at_utc": "2026-11-22T00:00:00Z"
      }
    ]
  }
}
```

**Canonical Enums:**
- `rail`: `"NATIVE_PG"` (active in Phase 1) | `"DIRECT_TENANT"` (hard-locked `422 DIRECT_TENANT_RAIL_DISABLED` in Phase 1).
- `provider`: `"XENDIT"` | `"DUITKU"` | `"MIDTRANS"` (strictly matching `ALLOWED_CREDENTIAL_PROVIDERS` in `payment_auth_guard.py:1720`).
- `channel`: `"DYNAMIC_QRIS"` (OnlineBoost Phase 1) | `"VIRTUAL_ACCOUNT"` | `"INVOICE"` (Phase 2).

### 4.3 Legacy Configuration Normalization Without Client Payment Authority
- **Server-Side Pure Normalizer in Core (`app/services/payment/factory.py`):**
  1. Read ONLY from `public.tenants` row loaded by canonical UUID/slug inside Core (remove hardcoded `"onlineboost"`/`"commerce"`/`"default"` bypasses in `payment.py:164` and `tenant_context_resolver.py:446-475`).
  2. Ignore **every** payment routing/mode/provider/rail/secret field in inbound HTTP request bodies (`isGateway`, `isXendit`, `mode`, `provider`, `qris_payload`, `secret_key`). Caller may at most send an optional `requested_channel: "DYNAMIC_QRIS"` validated against the tenant's enabled `channels[]`.
  3. Normalize legacy DB keys strictly on read:
     - `mode in ("PAYMENT_GATEWAY", "NATIVE_PG", "GATEWAY", "XENDIT", "DUITKU")` -> `rail = "NATIVE_PG"`.
     - `mode in ("MANUAL_TRANSFER", "DIRECT_TENANT", "STATIC_QRIS", "SELLER_NATIVE_QRIS")` -> `rail = "DIRECT_TENANT"` -> fail-closed `422 DIRECT_TENANT_RAIL_DISABLED`.
     - If `metadata.payment_config` is absent but legacy `metadata.payment_settings` exists, map `payment_settings.mode` / `payment_settings.provider` through the same table, **still requiring a valid `ACTIVE` `TenantCredentialProfile` with `api_credentials.secret_ref`**.
  4. Resolve outbound API secret **exclusively inside Core** via `CredentialProfileMapper._resolve_secret_ref(profile.api_credentials.secret_ref)` (`payment_auth_guard.py:1899-1957`), enforcing `env://` or `vault://` URI schemes, environment parity (`runtime_environment == "production"` rejects `"sandbox"` profiles at line `2153-2162`), and zero plaintext secret storage in DB or logs.
  5. **Refactor `XenditAdapter` (`gateway_xendit.py`) & `app/routes/payment.py:171-219`:**
     - `XenditAdapter` executes `POST {self.api_url}/qr_codes` using its **own instance `self.secret_key`** (Basic Auth header per adapter instance; zero global `xendit_service` delegation).
     - Remove the duplicate `POST /v2/invoices` call (`xendit_service.py:284-295`) from Dynamic QRIS creation.
     - Authenticate Inbox -> Core payment-intent calls using Core's existing `InternalPaymentHMACVerifier` (`payment_auth_guard.py:855-1070`, `PAYMENT_INTERNAL_HMAC_KEYRING_JSON`, Migration `032` `payment_hmac_replay_nonces`) so no unauthenticated external caller can trigger Xendit API calls or forge amounts.
- **Inbox Normalization (`lib/checkout-service.ts:505-516`, `lib/security/payment-destination-guard.ts:298-308`, `app/api/checkout/create-order/route.ts:143-149`):**
  - Remove `Boolean(payload.isGateway || payload.isXendit)` completely.
  - Treat `rail === 'NATIVE_PG'` and legacy `mode in ('PAYMENT_GATEWAY', 'NATIVE_PG', 'GATEWAY')` identically as Core-delegated `NATIVE_PG`; disable Inbox's local static QRIS generator for Phase 1 (§8).

---

## 5. ORDERS OWNERSHIP AND MINIMAL SCHEMA PROPOSAL (DESIGN QUESTION 2 & 3)

### 5.1 Strict Domain & Table Ownership Boundary

Even while Core and Inbox share one PostgreSQL 17 instance (`migrations/reconciliation/shared_db_migration_manifest.json`), **single-writer table ownership MUST be enforced**:

| Domain | Sole Writer | Owned Tables (Physical) | Read Access by Peer |
|---|---|---|---|
| **Commerce Orders, Line Items & Buyer Projection** | **Inbox** | `public.orders`, `public.order_items`, `public.order_audit_logs`, `public.payment_evidence`, `public.capi_outbox`, `public.message_outbox`, `public.outbox_events`, `public.reseller_commission_ledger` | Core reads `orders` **ONLY** during Phase 1 migration transition if needed for legacy lookup—**target Phase 1 state: Core reads `public.payment_intents` (its own table!) and NEVER writes `public.orders`!** |
| **Payment Intent, Obligation, Provider Events, Ledger, Settlement, Refund, Provenance, Settlement Outbox** | **Core** | `public.payment_intents` (Mig `005`), `public.payment_settlements` (Mig `005`), `public.payment_events` (Mig `033a-c`), `public.financial_ledger` (Mig `033a-b`), `public.payment_hmac_replay_nonces` (Mig `032`), `public.checkout_sessions` (Mig `035`), `public.payment_outbox_events` (**new Core Mig `037`**) | Inbox reads status ONLY via Core authenticated API (`GET /api/v1/payments/intents/{orderId}`) or receives signed Core outbox deliveries to update Inbox's own `orders` projection. |

**Why Core MUST stop mutating `public.orders` (`provenance_authority.py:2172-2187`):**
1. Today, `commit_verified_settlement_transaction` (`C:\boontrack-core-gateb-p2\app\core\security\provenance_authority.py:1872-1888, 2172-2187`) takes `FOR UPDATE OF o` on `public.orders` and executes `UPDATE orders SET status='PAID', payment_status='PAID', order_status='PAID', fulfillment_status='PENDING_STAGE4_VERIFICATION'`.
2. That creates a **dual-writer hazard** with Inbox (`checkout-service.ts`, `qris/create`, `orders/route.ts`, `payment-proof`, `email-service`), forces Core to depend on Inbox's `orders` columns (`sku_id`, `gross_amount`, `amount`, `fulfillment_status`), and overloads `orders.fulfillment_status` as a pseudo-outbox.
3. Moving Core's authoritative settlement lock and state transition onto **Core-owned `public.payment_intents`** (created when Inbox initiates payment via Core!) decouples Core's ACID settlement transaction from `public.orders` completely.

### 5.2 Forensic Disposition of All 18 Missing `orders` Columns (`BLK-P3C-02`)

**Verdict on Proposed Core Migration `037_add_orders_runtime_schema.sql`: `REJECT`**

Forensic audit of every column in `run_e2e_smoke_tests.py:389-407` and `PACKET_3D_STEP1_GROUND_TRUTH_AUDIT.md:372-391` against raw source across both repos:

| # | Column | Step 1 Rating | Actual Raw-Source Consumers (Verified) | Target Home | Physical `orders` Column? | Verdict |
|---|---|---|---|---|---|---|
| 1 | `qr_code_url` | MANDATORY | Inbox writes `checkout-service.ts:1119`, `qris/create:707,828`; UI `app/checkout/[order_id]/page.tsx:599` & `lib/qris-dynamic.ts:353` **already fallback to `metadata.qr_code_url`**; `v1/orders/[id]/route.ts:197` reads `order.qr_code_url`. Core does not write `orders.qr_code_url`. | **Core `payment_intents.qr_string` / `qr_image_url`** (Mig `005:12-13`) + projection in **`orders.metadata.payment_projection`** (render QR locally from `qr_string`; eliminate external `quickchart.io`/`qrserver.com` leak). | **NO** | `REJECT` physical col |
| 2 | `affiliate_code` | OPTIONAL | Inbox writes `checkout-service.ts:782,833`; `quick-paid:364` **already reads `metadata?.affiliate_code`**; `approve:373` reads `order.affiliate_code`. Core only in dead code `xendit.py:584` & legacy `checkout_service.py:228`. (`orders.reseller_code` already exists via `20261008_create_store_reseller_system.sql:86`.) | Existing **`orders.metadata`** (`metadata.affiliate_code`). | **NO** | `ACCEPT` metadata |
| 3 | `manager_id` | OPTIONAL | Inbox has only 4 hits (`checkout-service.ts:627,783,834` write-only; `order-sanitizer.ts:18`) — **zero Inbox readers**. Core only in dead `xendit.py:584` & legacy `checkout_service.py:228`. | Existing **`orders.metadata`** (`metadata.manager_id`). | **NO** | `ACCEPT` metadata |
| 4 | `utm_source` | OPTIONAL | Inbox writes `checkout-service.ts:791`; `analytics/campaigns/route.ts:76` reads `tracking` JSON; `affiliate/me/route.ts:231` queries `attribution_sessions` (not `orders`). Core uses `click_logs`/`attributions`. | Existing **`orders.metadata`** (`metadata.tracking_context.utm_source`). | **NO** | `ACCEPT` metadata |
| 5 | `utm_medium` | OPTIONAL | Same as #4 (`checkout-service.ts:792`; `affiliate/me/route.ts:231` queries `attribution_sessions`). | Existing **`orders.metadata`** (`metadata.tracking_context.utm_medium`). | **NO** | `ACCEPT` metadata |
| 6 | `utm_campaign` | OPTIONAL | Same as #4 (`checkout-service.ts:793`; `analytics/campaigns/route.ts:75` reads `tracking` JSON). | Existing **`orders.metadata`** (`metadata.tracking_context.utm_campaign`). | **NO** | `ACCEPT` metadata |
| 7 | `utm_content` | OPTIONAL | Same as #4 (`checkout-service.ts:794`; Core `webchat.py:65` writes `click_logs`). | Existing **`orders.metadata`** (`metadata.tracking_context.utm_content`). | **NO** | `ACCEPT` metadata |
| 8 | `utm_term` | OPTIONAL | Same as #4 (`checkout-service.ts:795`; Core `growth_service.py:57` writes `attributions`). | Existing **`orders.metadata`** (`metadata.tracking_context.utm_term`). | **NO** | `ACCEPT` metadata |
| 9 | `fbclid` | OPTIONAL | Inbox writes `checkout-service.ts:796`; `qris/create:469-470` folds into `metadata.tracking_context.fbc`; `tracking/capi/route.ts:212` reads `dbOrder.fbclid` (1-line fallback to `metadata.tracking_context.fbclid`). Core `cod_settlement_service.py:97` reads `attributions`. | Existing **`orders.metadata`** (`metadata.tracking_context.fbclid`). | **NO** | `ACCEPT` metadata |
| 10 | `ttclid` | OPTIONAL | Inbox writes `checkout-service.ts:797` — **zero Inbox DB readers on `orders`**. Core `growth_service.py:57` writes `attributions`. | Existing **`orders.metadata`** (`metadata.tracking_context.ttclid`). | **NO** | `ACCEPT` metadata |
| 11 | `briefing_url` | OPTIONAL | Inbox writes `checkout-service.ts:798,846` (and **already writes to `order_items.metadata`** at line `907`!), `orders/route.ts:465`; `CampaignTab.tsx:34` & `OrdersTab.tsx:114` **already fallback to `fulfillment_metadata.briefing_url`**. Core has **0 hits**. | Existing **`orders.fulfillment_metadata`** (`fulfillment_metadata.briefing_url`) / `orders.metadata`. | **NO** | `ACCEPT` metadata |
| 12 | `customer_briefing` | OPTIONAL | Inbox writes `checkout-service.ts:799,847` (and `order_items.metadata` at line `908`!), `orders/route.ts:468`. Core has **0 hits**. | Existing **`orders.fulfillment_metadata`** (`fulfillment_metadata.customer_briefing`) / `orders.metadata`. | **NO** | `ACCEPT` metadata |
| 13 | `payment_proof_url` | MANDATORY (manual) | Inbox writes `lib/payment-evidence-service.ts:355` **after already inserting `public.payment_evidence.evidence_url`** (`20261003_payment_evidence_and_capi_outbox.sql:12`). `orders/[orderId]/status:217` reads it. Core has **0 hits**. | Existing **`public.payment_evidence.evidence_url`** + **`orders.metadata.payment_proof_url`**. | **NO** | `REJECT` physical col |
| 14 | `correlation_id` | MANDATORY | **ONLY** written in `TeamChatTab.tsx:1600,1957` (Quick POS payment token, also written to `metadata.payment_token` at lines `1618-1619`). **NOT written by `checkout-service.ts` or `qris/create`**, and has NO uniqueness constraint (not used for deduplication!). Queried as fallback lookup `.eq('correlation_id', orderId)` in 6 Inbox routes (`status:61`, `v1/orders/[id]:69`, `v1/fulfillment:43`, `archive:58`, `payment-proof:156`, `approve:75`, `quick-paid:127`). | **Conditional Inbox-owned physical column** (`correlation_id VARCHAR(128)` + partial index) **ONLY if Quick POS chat checkout is in Phase 1**; otherwise **`orders.metadata.payment_token`** and remove fallback `.eq('correlation_id', ...)`. | **CONDITIONAL (0 or 1)** | `MODIFY` |
| 15 | `unique_code` | MANDATORY | **Stripped by `lib/order-sanitizer.ts:7-57`** (`unique_code` is NOT in `VALID_ORDER_COLUMNS`!). Already saved in `orders.metadata.unique_code` (`checkout-service.ts:746`, `qris/create:723,832`, `orders/route.ts:778`) and read via fallback (`v1/orders/[id]:199`). Core already has `unique_code INT` on `payment_intents` (`005:10`) and `checkout_sessions` (`035:26`). | **Core `payment_intents.unique_code` / `checkout_sessions.unique_code`** + display copy in **`orders.metadata.unique_code`**. | **NO** | `REJECT` physical col |
| 16 | `email_sent` | OPTIONAL | Written best-effort inside `try/catch` in `lib/email-service.ts:550` & `lib/email/order-event-bus.ts:175`. **Zero readers in Inbox or Core.** | **Notification / outbox table** (`public.message_outbox` / `public.outbox_events`) or `orders.metadata.notifications`. | **NO** | `ACCEPT` outbox |
| 17 | `email_sent_at` | OPTIONAL | Same as #16 (`lib/email-service.ts:551`, `lib/email/order-event-bus.ts:176`). **Zero readers in Inbox or Core.** | **Notification / outbox table** (`public.message_outbox` / `public.outbox_events`) or `orders.metadata.notifications`. | **NO** | `ACCEPT` outbox |
| 18 | `total_amount` | MANDATORY | **Stripped by `lib/order-sanitizer.ts:7-57`** (`total_amount` is NOT in `VALID_ORDER_COLUMNS`!). `orders` **already has `gross_amount` and `amount`** (`000_disposable_pg17_base_catalog_bootstrap.sql:153-154`, `033a:41`). Every active Inbox reader already falls back `gross_amount ?? total_amount ?? amount`. Only broken callers are disabled Direct-Rail `process_payment_match()` (`20261004_create_payment_observations_and_outbox.sql:108,165`) and `lib/financial-state-machine.ts:230,233`. | **Core `payment_intents.total_amount` / `checkout_sessions.total_amount`**; Inbox uses existing **`orders.gross_amount`**. | **NO** | `REJECT` physical col |

### 5.3 Minimal Schema Contract & Migration Ownership Recommendation

Replace the rejected 18-column Core migration with **two tiny, single-owner additive migrations**:

1. **Inbox-Owned Migration** (`boontrack-inbox/supabase/migrations/20261123_orders_idempotency_and_projection.sql`):
   - `ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);`
   - `ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS payment_intent_id UUID;` *(nullable projection reference to Core `payment_intents.id`)*
   - `ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS last_settlement_event_id VARCHAR(128);` *(monotonic projection dedup guard)*
   - *(Conditional, ONLY if Quick POS chat payment tokens ship in Phase 1)*: `ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(128);` + `CREATE INDEX IF NOT EXISTS idx_orders_correlation_id ON public.orders (correlation_id) WHERE correlation_id IS NOT NULL;`
   - `CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_tenant_idempotency_key ON public.orders (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;`
   - **Code cleanup in Inbox:** Align `VALID_ORDER_COLUMNS` (`lib/order-sanitizer.ts:7-57`), `lib/checkout-service.ts:767-861,1116-1129`, `app/api/v1/payments/qris/create/route.ts:706-741,807-854`, `app/api/orders/route.ts:449-470`, `lib/email-service.ts:544-557`, `lib/email/order-event-bus.ts:172-179`, and `lib/payment-evidence-service.ts:349-359` to write non-physical fields solely to `metadata` / `fulfillment_metadata` / outbox—eliminating `PGRST204` permanently without 18 junk columns.

2. **Core-Owned Migration** (`boontrack-core/migrations/037_core_payment_intent_idempotency_and_settlement_outbox.sql`):
   - **Expand existing `public.payment_intents`** (created by Core Migration `005_create_core_payment_tables.sql:5-18`) with:
     - `canonical_tenant_id VARCHAR(100)`, `idempotency_key VARCHAR(128)`, `provider VARCHAR(32)`, `channel VARCHAR(32)`, `credential_profile_id VARCHAR(128)`, `provider_reference_id VARCHAR(255)`, `sku_id VARCHAR(255)`, `currency VARCHAR(16) NOT NULL DEFAULT 'IDR'`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `settled_at TIMESTAMPTZ`, `init_lease_expires_at TIMESTAMPTZ`, `last_error_code VARCHAR(64)`.
     - Allow `qr_string TEXT` nullable while `status IN ('INITIATING', 'PROVIDER_UNKNOWN', 'INIT_FAILED')` (`ALTER COLUMN qr_string DROP NOT NULL`).
     - `UNIQUE (canonical_tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL` (prevents double intent creation!).
     - `CHECK (status IN ('INITIATING', 'ACTIVE', 'PROVIDER_UNKNOWN', 'INIT_FAILED', 'SETTLED', 'EXPIRED', 'CANCELLED', 'REFUNDED'))`.
     - Strict `FORCE ROW LEVEL SECURITY` (matching `035_durable_checkout_sessions.sql:82-123`).
   - **Create `public.payment_outbox_events`** (Core-owned durable settlement outbox):
     - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `event_type VARCHAR(64) NOT NULL CHECK (event_type IN ('PAYMENT_SETTLED', 'PAYMENT_EXPIRED', 'PAYMENT_LATE_QUARANTINED', 'PAYMENT_REFUNDED'))`, `canonical_tenant_id VARCHAR(100) NOT NULL`, `order_id VARCHAR(128) NOT NULL`, `payment_intent_id UUID REFERENCES public.payment_intents(id)`, `provider VARCHAR(32) NOT NULL`, `provider_event_id VARCHAR(128)`, `idempotency_key VARCHAR(255) NOT NULL UNIQUE`, `payload JSONB NOT NULL`, `provenance_envelope JSONB`, `status VARCHAR(32) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DELIVERING', 'DELIVERED', 'DEAD_LETTER'))`, `attempt_count INT NOT NULL DEFAULT 0`, `next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `locked_by VARCHAR(128)`, `locked_at TIMESTAMPTZ`, `delivered_at TIMESTAMPTZ`, `last_error TEXT`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.
     - Partial claim index `ON public.payment_outbox_events (next_attempt_at ASC) WHERE status IN ('PENDING', 'DELIVERING')` + `FORCE ROW LEVEL SECURITY`.
   - Update `migrations/reconciliation/shared_db_migration_manifest.json` to include both candidate migrations in clean-replay order (108 -> 110 steps) before local verification.

---

## 6. IDEMPOTENCY / SAGA PROPOSAL (DESIGN QUESTION 4)

### 6.1 Critique of Current Order-Before-Payment Sequencing
- **Path A (`lib/checkout-service.ts:817, 930, 1019, 1100`):** Inserts `orders` + `order_items` (`PENDING`), calls Core with **no `AbortSignal.timeout()`** and **no `Idempotency-Key`**, and runs `rollbackOrphanOrder` (`DELETE`) on error. Under Core stall (`OB-05`), container termination leaves orphan `PENDING` orders; under a naive 8s timeout + `DELETE`, a slow 9s Xendit response leaves a **live Xendit QRIS with no DB order**!
- **Path B (`app/api/v1/payments/qris/create/route.ts:514, 652, 706, 854`):** Calls Core **first** (no timeout, no idempotency key) even for an already-`PAID` or `EXPIRED` order (checked 140 lines later at line 652!), then inserts/updates `orders`—creating orphan Xendit charges if DB write fails and resurrecting `EXPIRED` orders if order exists.
- **Core (`app/routes/payment.py:139-219`, `app/services/xendit_service.py:180-330`):** Persists **zero** payment-intent row in PostgreSQL (only in-process RAM dict `PAYMENT_INTENTS` at `xendit_service.py:317`!), sends no Xendit idempotency header, and makes two sequential 30s HTTP calls (`/qr_codes` + `/v2/invoices`).

### 6.2 Durable Two-Service Checkout & Payment Initiation Saga (`ACCEPT` Target)

```text
Inbox (Commerce Order)                         Core (Payment Intent / Obligation)
──────────────────────                         ──────────────────────────────────
[POST /api/checkout/create-order]
  (requires stable Idempotency-Key)
          │
          ▼
1. Upsert orders + order_items
   status = 'INITIATING_PAYMENT'
   UNIQUE(tenant_id, idempotency_key)
   - If existing PAYMENT_PENDING & unexpired -> return cached projection (0 Core calls)
   - If existing PAID / EXPIRED / CANCELLED  -> return 409 TERMINAL_ORDER_STATE
          │
          ▼ (Signed InternalPaymentHMAC + AbortSignal.timeout(10000))
   POST /api/v1/payments/intents
   { order_id, tenant_id, amount, sku_id, channel: "DYNAMIC_QRIS",
     idempotency_key: "pi:{tenant_id}:{order_id}:v1" }
                                                        │
                                                        ▼
                                               2. INSERT INTO payment_intents
                                                  (status='INITIATING', init_lease_expires_at=NOW()+15s)
                                                  ON CONFLICT (canonical_tenant_id, idempotency_key) DO NOTHING
                                                  - If existing ACTIVE (same amt/sku/tenant) -> return cached QR (0 Xendit calls)
                                                  - If existing ACTIVE (different amt/sku)   -> 409 IDEMPOTENCY_PAYLOAD_MISMATCH
                                                  - If existing INITIATING & lease valid     -> 409 PAYMENT_INTENT_IN_FLIGHT
                                                  - If existing PROVIDER_UNKNOWN / expired lease -> reconcile GET /qr_codes first!
                                                  - If existing SETTLED/EXPIRED/CANCELLED    -> 409 TERMINAL_INTENT_STATE
                                                        │
                                                        ▼
                                               3. Resolve TenantCredentialProfile (api_secret_ref)
                                                  Call Xendit POST /qr_codes ONLY (connect=3s, read=6s)
                                                  reference_id = order_id, Idempotency-Key = intent.idempotency_key
                                                        │
                            ┌───────────────────────────┼───────────────────────────┐
                            ▼                           ▼                           ▼
                    [Xendit 200/201]         [Definitive 4xx]          [Timeout / 5xx / Reset]
                    UPDATE payment_intents   UPDATE payment_intents    UPDATE payment_intents
                    SET status='ACTIVE',     SET status='INIT_FAILED', SET status='PROVIDER_UNKNOWN',
                        qr_string=...,           last_error_code=...       last_error_code=...
                        provider_ref=...,    Return HTTP 422/400       Return HTTP 503/504
                        expires_at=...       (definitive: true)        (definitive: false)
                    Return HTTP 200
                            │                           │                           │
          ┌─────────────────┘                           │                           │
          ▼                                             ▼                           ▼
4a. Inbox receives 200:                      4b. Inbox receives 4xx:     4c. Inbox times out (10s) OR gets 5xx:
    UPDATE orders                                UPDATE orders               UPDATE orders
    SET status='PAYMENT_PENDING',                SET status='PAYMENT_        SET status='PAYMENT_INIT_UNKNOWN',
        payment_status='PENDING',                    INIT_FAILED',               payment_status='INIT_UNKNOWN'
        payment_intent_id=...,                       payment_status='FAILED' **DO NOT DELETE ORDER!**
        metadata=metadata || {qr_string,...}     Return error to buyer       Return 503/504 with same
    Return 200 to buyer                                                      order_id + retryable=true
```

### 6.3 Exact State Transitions & Double-Creation Prevention

| Scenario | Inbox State | Core `payment_intents` State | Retry / Reconciliation Behavior | Double Intent Prevented? |
|---|---|---|---|---|
| **Normal Happy Path** | `INITIATING_PAYMENT` -> `PAYMENT_PENDING` | `INITIATING` -> `ACTIVE` | Buyer pays QRIS -> Core settles -> outbox projects `PAID`. | Yes (`UNIQUE(tenant_id, idempotency_key)` on both sides). |
| **Core Accepts, Inbox Times Out at 10s** | Transitions to `PAYMENT_INIT_UNKNOWN` (order preserved!) | Finishes Xendit call at 11s -> `ACTIVE` (durable in PG17!) | Client retries with same `Idempotency-Key` (or polls `GET /api/orders/{id}/status`) -> Inbox re-sends same `order_id` + `pi:{tenant}:{order}:v1` -> Core finds existing `ACTIVE` row -> returns exact same `qr_string` & `payment_intent_id` with **0 new Xendit calls**! | **YES — guaranteed by Core `UNIQUE(canonical_tenant_id, idempotency_key)` + `UNIQUE(canonical_tenant_id, order_id)`.** |
| **Core -> Xendit Times Out (`PROVIDER_UNKNOWN`)** | `PAYMENT_INIT_UNKNOWN` | `PROVIDER_UNKNOWN` | Retry or Core reconciliation worker queries Xendit (`GET /qr_codes` by `reference_id = order_id`) before attempting any new create. If Xendit created it, promote `PROVIDER_UNKNOWN` -> `ACTIVE`; if definitively absent (`404`) and within retry window, allow single bounded retry with same `reference_id`, else mark `INIT_FAILED`. | **YES — provider reconciliation precedes any retry.** |
| **Definitive 4xx Rejection (e.g., Tenant Misconfigured)** | `PAYMENT_INIT_FAILED` (terminal, never deleted for audit) | `INIT_FAILED` (or not created) | No provider charge exists. Buyer sees clear config error; new attempt requires a fresh checkout session after merchant fixes config. | Yes. |
| **Core Completely Down (ECONNREFUSED / 503)** | `PAYMENT_INIT_UNKNOWN` (or `PAYMENT_INIT_FAILED` on immediate TCP `ECONNREFUSED` before connect) | Unreached | Safe retry reuses the same `order_id` + `idempotency_key` until `expires_at` (e.g. 15 min), after which Inbox marks stale `PAYMENT_INIT_UNKNOWN` orders `EXPIRED` only after confirming Core has `404` / `INIT_FAILED` / `EXPIRED`. | Yes. |
| **Concurrent Double-Click by Buyer** | Second request hits `uq_orders_tenant_idempotency_key` -> reads same `order_id`; if `INITIATING_PAYMENT` -> returns `409` / awaits same intent | Second request hits `uq_payment_intents_tenant_idempotency` with active lease -> returns `409 PAYMENT_INTENT_IN_FLIGHT` | Zero duplicate orders, zero duplicate Xendit calls. | Yes. |

**Timeout Budget Alignment:**
- Core -> Xendit: `connect=3.0s, read=6.0s` (single `POST /qr_codes` call; remove redundant `/v2/invoices`).
- Inbox -> Core: `AbortSignal.timeout(10000)` on BOTH `lib/checkout-service.ts:1019` and `app/api/v1/payments/qris/create/route.ts:514` (greater than Core's 6s read timeout, well below Vercel `maxDuration = 30` at `app/api/checkout/create-order/route.ts:23`).

---

## 7. SETTLEMENT, OUTBOX, AND LATE-EVENT PROPOSAL (DESIGN QUESTION 5)

### 7.1 Complete Dual-Writer & Race-Condition Hazard Inventory

#### A. Inbox Direct-Settlement / Dark-Mutation Surfaces (10 Found — Step 1 Cited Only 3)
1. `C:\boontrack-inbox-gateb-p2\app\api\webhooks\xendit\paid\route.ts:47,155-165` — Directly writes `orders.status='PAID'`, ignores `.update()` error/rowcount, bypasses auth when `NODE_ENV==='test'`, settles `EXPIRED` orders, 0 Core ledger/provenance.
2. `C:\boontrack-inbox-gateb-p2\app\api\webhooks\xendit\route.ts:28-44` -> `lib/payment-webhook-service.ts:517-524,1389-1396` — Direct `orders.status='PAID'` via single global `XENDIT_CALLBACK_TOKEN`.
3. `C:\boontrack-inbox-gateb-p2\app\api\webhooks\payment\route.ts:25-41` -> `lib/payment-webhook-service.ts` — Same direct `PAID` mutation.
4. `C:\boontrack-inbox-gateb-p2\app\api\webhook\payment\route.ts:27-43` -> `lib/payment-webhook-service.ts` — Proved in `SA-04` (`packet3c_e2e_evidence.json:343-349`) to settle `EXPIRED` orders directly to `PAID`.
5. `C:\boontrack-inbox-gateb-p2\app\api\v1\payments\qris\webhook\route.ts:15-17` -> `lib/payment-webhook-service.ts` — **Zero route-level callback token check!**
6. `C:\boontrack-inbox-gateb-p2\app\api\v1\reader\notification\route.ts:386-393,606` — Direct `orders.status='PAID'` on disabled Direct Tenant Rail.
7. `C:\boontrack-inbox-gateb-p2\app\api\v1\tenants\[slug]\orders\[id]\quick-paid\route.ts:281-295` (+ re-export alias `app/api/v1/orders/[id]/quick-paid/route.ts:3`) — Authenticated merchant directly writes `PAID`/`COMPLETED`, 0 Core ledger, 0 Ed25519 provenance, no `EXPIRED` guard.
8. `C:\boontrack-inbox-gateb-p2\app\api\orders\[orderId]\approve\route.ts:191-206` — Identical direct `PAID`/`COMPLETED` mutation, 0 Core ledger, 0 provenance, no `EXPIRED` guard.
9. `C:\boontrack-inbox-gateb-p2\lib\whatsapp\evolution-webhook-handler.ts:1176-1215` — **Unreported in Step 1:** Parses WhatsApp messages for payment notifications, matches `gross_amount`, and directly executes `supabase.from('orders').update({ status: 'PAID', payment_status: 'PAID' })` + dispatches Meta CAPI!
10. `C:\boontrack-inbox-gateb-p2\lib\financial-state-machine.ts:199,243-252` + PostgreSQL `SECURITY DEFINER` function `public.process_payment_match()` (`C:\boontrack-inbox-gateb-p2\supabase\migrations\20261004_create_payment_observations_and_outbox.sql:85-221`) — **Unreported in Step 1:** Directly updates `public.orders SET status='PAID'` (and references non-existent `total_amount`/`notes` columns).

#### B. Core Settlement & Provenance Hazards (5 Found in Raw Source)
1. **Ephemeral Ed25519 Key Fallback (`xendit.py:66-88`, `payment.py:51-73`):** If `PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON` is missing or unparseable, Core silently generates a throwaway in-memory key (`dev-xendit-key` / `dev-midtrans-key`), permanently breaking cross-process/post-restart provenance verification! **Fix:** Fail closed (`HTTP 503 PROVENANCE_SIGNER_UNAVAILABLE`) in all non-unit-test environments.
2. **Tautological Token Verification at Boundary (`xendit.py:967-1007` + `provenance_authority.py:497-503`):** `xendit.py:998` passes `provider_verification_secret=candidate_token` (the inbound header!) into `verify_pg_webhook_and_issue_capability`, causing `provenance_authority.py:499` (`hmac.compare_digest(callback_token, secret)`) to compare the inbound header against itself. **Fix:** Pass `CredentialProfileMapper` (or resolve the `ACTIVE`/`VERIFY_ONLY` secret inside `TrustedSettlementVerificationBoundary` itself) so capability minting performs real cryptographic verification internally.
3. **Duplicate FastAPI Route with Global Non-Constant-Time Token Check (`app/main.py:341`, `app/api/webhook_payment.py:51-53,81-107`):** Mounts a second `/webhook/xendit` (colliding with `xendit.py:1119`) that checks global `os.getenv("XENDIT_CALLBACK_TOKEN")` via `!=` before invoking `process_xendit_webhook_core`, breaking multi-tenant `CredentialProfileMapper`! **Fix:** Remove `webhook_payment_router` from `app/main.py:341` and retire `app/api/webhook_payment.py`.
4. **Fire-and-Forget Stage 4 Side Effects (`xendit.py:1076-1098`):** Spawns non-durable `asyncio.create_task(send_whatsapp_payment_notification)` and `asyncio.create_task(send_capi_task)` directly after commit, contradicting `provenance_authority.py:1786` ("strictly zero Stage 4 fulfillment or CAPI side effects") and `ARCHITECTURE.md:814-818` ("Hapus Pola Asinkron Fire-and-Forget"). **Fix:** Remove lines `1076-1098`; drive all downstream notifications/CAPI/fulfillment exclusively from the durable outbox!
5. **Direct Core Mutation of `public.orders` + Legacy `ON CONFLICT (event_id)` Writers:**
   - `provenance_authority.py:1872-1888, 2172-2187` directly locks and updates `public.orders`.
   - Dead helpers `xendit.py:315-384, 485-738` and legacy `app/services/checkout_service.py:184-189, 279` still execute `ON CONFLICT (event_id)` (which crashes once Migration `033c` drops `payment_events_event_id_key` at `033c_stage3_payment_settlement_contract_phase.sql:55-56`!) and mutate `orders` directly.

### 7.2 Minimum Safe End-to-End Settlement & Outbox Architecture (`ACCEPT` Target)

```text
[Xendit Webhook]
   │ POST /api/v1/payments/xendit/callback  (sole Xendit ingress; zero Inbox webhook ingestion)
   ▼
[Core: process_xendit_webhook_core]
   1. Reject TOPUP-* -> 403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD (xendit.py:771-781)
   2. Lookup Core-owned `payment_intents` INNER JOIN `tenants` (canonical UUID)
      (Not found -> 404 ORDER_NOT_FOUND; tenant claim mismatch -> 403)
   3. Validate IDR integer amount == payment_intents.total_amount (mismatch -> 400)
   4. Inside TrustedSettlementVerificationBoundary:
      - Resolve TenantCredentialProfile (bound credential_profile_id -> unique ACTIVE fallback)
      - Constant-time verify business_id + x-callback-token against ACTIVE / non-expired VERIFY_ONLY secret_ref
      - Mint VerifiedSettlementCapability
   5. Sign 17-field RFC 8785 provenance envelope with FAIL-CLOSED Ed25519 ProvenanceSigner
      and verify with public-key ProvenanceVerifier (provenance_authority.py:1602-1734)
   6. SINGLE ATOMIC POSTGRESQL TRANSACTION (Core-owned tables ONLY; ZERO UPDATE on `public.orders`):
      a. SELECT ... FROM payment_intents WHERE order_id = %s FOR UPDATE
      b. Check payment_events composite key (provider, event_id) / (provider, provider_event_id) FOR UPDATE
         - Conflicting replay (different order/tenant/amount/account/sku) -> ROLLBACK + 409
         - Already PROCESSED / QUARANTINED_LATE_SETTLEMENT -> ROLLBACK + 200 idempotent
      c. Branch on payment_intents.status:
         - If status IN ('EXPIRED', 'CANCELLED', 'FAILED'):
             * INSERT payment_events (status='QUARANTINED_LATE_SETTLEMENT', payload._provenance=envelope)
             * INSERT payment_outbox_events (event_type='PAYMENT_LATE_QUARANTINED', ...)
             * ZERO financial_ledger row; payment_intents stays EXPIRED/CANCELLED
             * COMMIT -> Return HTTP 200 QUARANTINED_LATE_SETTLEMENT
         - If status == 'SETTLED':
             * ROLLBACK -> Return HTTP 200 ALREADY_PROCESSED
         - If status IN ('ACTIVE', 'INITIATING', 'PROVIDER_UNKNOWN'):
             * INSERT payment_events (status='PROCESSED', payload._provenance=envelope) ON CONFLICT (provider, event_id) DO NOTHING
             * UPDATE payment_intents SET status='SETTLED', settled_at=NOW(), updated_at=NOW() WHERE id=%s AND status IN ('ACTIVE','INITIATING','PROVIDER_UNKNOWN')
             * INSERT financial_ledger (fee_amount=NULL, net_amount=NULL, transaction_status='SETTLED', reconciliation_status='PENDING_RECONCILIATION')
             * INSERT payment_outbox_events (event_type='PAYMENT_SETTLED', provenance_envelope=envelope, status='PENDING')
             * COMMIT -> Return HTTP 200 SUCCESS (zero in-process fire-and-forget WA/CAPI tasks!)
   │
   ▼ (Durable Async Delivery — Core Outbox Dispatcher Worker)
[Core Outbox Worker: SELECT ... FROM payment_outbox_events WHERE status='PENDING' AND next_attempt_at<=NOW() FOR UPDATE SKIP LOCKED]
   │ POST https://<inbox-internal>/api/internal/projections/payment-status
   │ Headers: InternalPaymentHMAC (PAYMENT_INTERNAL_HMAC_KEYRING_JSON)
   │ Body: { outbox_event_id, event_type, order_id, canonical_tenant_id, payment_intent_id,
   │         verified_amount, settled_at, provenance_envelope (Ed25519 signed!) }
   ▼
[Inbox Projection Consumer (NOT a settlement authority — pure verifier + projector)]
   1. Verify InternalPaymentHMAC signature + timestamp + nonce
   2. Verify Ed25519 provenance_envelope using PUBLIC KEY ONLY (`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON` — zero private key in Inbox!)
      and assert order_id, canonical_tenant_id, verified_amount match local `orders` row
   3. Atomic idempotent Inbox projection update:
      - If event_type == 'PAYMENT_SETTLED':
          UPDATE orders
          SET status='PAID', payment_status='PAID', order_status='PAID',
              paid_at=COALESCE(paid_at, $settled_at),
              last_settlement_event_id=$event_id,
              updated_at=NOW()
          WHERE id=$order_id AND tenant_id=$canonical_tenant_id
            AND status NOT IN ('PAID', 'EXPIRED', 'CANCELLED')
          -> Enqueue Inbox-owned fulfillment/email/capi_outbox/reseller_commission_ledger (all idempotent by order_id)
      - If event_type == 'PAYMENT_EXPIRED':
          UPDATE orders SET status='EXPIRED', payment_status='EXPIRED', order_status='EXPIRED'
          WHERE id=$order_id AND status IN ('INITIATING_PAYMENT', 'PAYMENT_PENDING', 'PAYMENT_INIT_UNKNOWN', 'PENDING')
      - If event_type == 'PAYMENT_LATE_QUARANTINED':
          UPDATE orders SET metadata = metadata || jsonb_build_object('late_settlement_quarantined', true, 'quarantined_event_id', $event_id)
          WHERE id=$order_id  (NEVER changes EXPIRED/CANCELLED to PAID!)
   4. Return HTTP 200 -> Core Outbox Worker marks payment_outbox_events.status = 'DELIVERED'
```

### 7.3 Race-Condition Guarantees
- **Webhook vs. Expiry Reconciler:** Both lock the **exact same single row** (`SELECT ... FROM payment_intents WHERE order_id = %s FOR UPDATE` in Core). Expiry worker uses `FOR UPDATE SKIP LOCKED` and checks provider status before committing `EXPIRED`. Whichever commits first wins deterministically; if expiry wins first, the subsequent webhook hits `QUARANTINED_LATE_SETTLEMENT`.
- **Duplicate / Out-of-Order Outbox Delivery:** Inbox checks `last_settlement_event_id` and enforces monotonic `WHERE status NOT IN ('PAID', 'EXPIRED', 'CANCELLED')`. Delivering `PAYMENT_EXPIRED` after `PAYMENT_SETTLED` is a no-op; delivering `PAYMENT_SETTLED` twice is a no-op.
- **Inbox Projection Lag (UX Safety):** If a buyer polls `GET /api/orders/[orderId]/status` during a brief outbox retry window (<2s normally), Inbox can optionally invoke a read-only HMAC-signed `GET /api/v1/payments/intents/{orderId}` on Core—if Core returns a verified Ed25519 `provenance_envelope`, Inbox can apply the identical verified projection immediately without waiting for the next worker tick.
- **Decommissioning `quick-paid` & `approve`:** In Phase 1 (where `DIRECT_TENANT` rail is disabled), return `HTTP 403 DIRECT_TENANT_RAIL_DISABLED` (and permanently `403 NATIVE_PG_MANUAL_SETTLEMENT_FORBIDDEN` for any `NATIVE_PG` order). In Phase 2, if manual merchant confirmation is re-enabled for Direct-Tenant orders, Inbox must delegate to a Core-owned authenticated settlement endpoint rather than mutating `orders` directly.

---

## 8. UNIQUE-CODE ADR RECOMMENDATION (DESIGN QUESTION 6)

### 8.1 Verified 4-Way Contract Contradiction (Zero Formula Invented)

| # | Authoritative Source | Exact Citation | Behavior / Constraint |
|---|---|---|---|
| 1 | `ARCHITECTURE.md §21.3` | `C:\boontrack-core-gateb-p2\ARCHITECTURE.md:1673-1680, 1755` | **DOWNWARD subtraction (discount):** `total_amount = base_amount - unique_code` (e.g., `100.000 - 825 = 99.175`, `"unique_code_system": "DOWNWARD"`). *(Note: `ARCHITECTURE.md:1304` self-contradicts with "ditambah/dikurangi kode unik acak downward 1-999".)* |
| 2 | `ARCHITECTURE.md §7.2` + Core Migration `035` | `C:\boontrack-core-gateb-p2\ARCHITECTURE.md:2189-2191`; `migrations\035_durable_checkout_sessions.sql:51-58`; `app\payments\qris_adapter.py:7` | **UPWARD addition:** Hard DB constraint `CHECK (base_amount >= 0 AND total_amount > 0 AND total_amount = base_amount + unique_code)` and `CHECK (unique_code = 0 OR (unique_code >= 100 AND unique_code <= 999))`. |
| 3 | Inbox Guardrail P1 | `C:\boontrack-inbox-gateb-p2\lib\unique-code-generator.ts:43-63`; `lib\checkout-service.ts:494-573`; `app\api\v1\payments\qris\create\route.ts:437-441` | **ZERO for all QRIS (`return 0`), UPWARD for `manual_transfer` only.** Confirmed live in `SA-00` (`packet3c_e2e_evidence.json:250-265`): `method=qris` -> `unique_code=0, final_amount=185000`; `method=manual_transfer` -> `unique_code=751, final_amount=185751`. |
| 4 | Core Direct Tenant Rail Hard-Lock | `C:\boontrack-core-gateb-p2\app\services\payment\factory.py:50-61`; `app\routes\payment.py:222-228`; `app\routes\payment_webhook.py:7-24`; `provenance_authority.py:447-452` | **HARD-LOCKED (`422 DIRECT_TENANT_RAIL_DISABLED` / `403 DIRECT_TENANT_RAIL_SIGNING_LOCKED`)** for `STATIC_QRIS`, `MANUAL_TRANSFER`, `DIRECT_TENANT`, and Android Reader auto-settlement. |

### 8.2 Hidden Operational Hazard Found in Inbox
Despite Core's hard lock on `STATIC_QRIS`, Inbox **still executes local static QRIS Tag 54 generation** for Shabu Aji (`lib/checkout-service.ts:966-968`, `app/api/v1/payments/qris/create/route.ts:495-497`), proved by `SA-01` (`packet3c_e2e_evidence.json:271-294`, `inbox_zero_core_bypass: true`, `unique_code_emitted: 0`). Shipping this in Phase 1 would create two unrecoverable production failures:
1. Two concurrent `Rp185.000` Shabu Aji static QRIS payments have `unique_code = 0` and identical bank mutation amounts—causing payment misattribution.
2. With Core's Direct Tenant Rail locked and Inbox's dark-settlement routes decommissioned, Shabu Aji static QRIS orders would have **no authorized Core settlement path**.

### 8.3 ADR Recommendation (`ADR-P3D-UNIQUE-CODE-PHASE1`)

| Decision Clause | Status | Specification |
|---|---|---|
| **Clause 1 — OnlineBoost Dynamic QRIS (Phase 1 Active)** | `ACCEPT` | OnlineBoost uses `rail = "NATIVE_PG"`, `provider = "XENDIT"`, `channel = "DYNAMIC_QRIS"`. **`unique_code` is strictly `0`**; `total_amount = base_amount = 249000` (exact `Rp249.000`). Satisfies Migration `035:51-58` (`249000 = 249000 + 0`), Inbox Guardrail P1, and Xendit per-order `reference_id` reconciliation with zero ambiguity. |
| **Clause 2 — Shabu Aji Static Merchant QRIS (Phase 1 Deferred)** | `BLOCKED` / `DEFER` | **Keep Shabu Aji Static Merchant QRIS (`DIRECT_TENANT` / `STATIC_QRIS`) DEFERRED during Phase 1.** Enforce fail-closed parity in Inbox (`checkout-service.ts:966-975`, `qris/create/route.ts:495-504`): disable local static EMVCo Tag 54 generation unless explicitly enabled in Phase 2 (`ENABLE_DIRECT_TENANT_RAIL=false` default -> `422 DIRECT_TENANT_RAIL_DISABLED`). *(Operational escape hatch: if Shabu Aji requires Phase 1 launch, onboard Shabu Aji onto `NATIVE_PG` Dynamic QRIS via Xendit/Duitku with `unique_code = 0`—zero static QRIS required!)* |
| **Clause 3 — Phase 2 Unblock Gate (Founder/CTO Sign-Off Required, Zero Formula Invented)** | `BLOCKED` | Before Phase 2 enables `DIRECT_TENANT` Static QRIS / Manual Transfer: Founder/CTO must sign one binary ADR selecting either **(A) Upward Addition (`total = base + code`, aligning `§21.3` to Migration `035` + `§7.2`)** OR **(B) Downward Subtraction (`total = base - code`, migrating `035` `chk_checkout_sessions_amounts` + `unique-code-generator.ts`)**, AND approve Direct-Tenant Rail settlement provenance/reconciliation security design. |

---

## 9. EXACT REPOSITORY / FILE OWNERSHIP MATRIX

To prevent concurrent edit collisions and preserve strict cross-repo authority boundaries, **every file below has exactly ONE authorized owner** once write authorization is granted:

| Repository | File Path | Single Assigned Owner | Scope / Blockers Addressed | Contention Level |
|---|---|---|---|---|
| **boontrack-core** | `app/core/security/payment_auth_guard.py` | **Core Security & Payment Lead** | Add `api_credentials.secret_ref` to `TenantCredentialProfile`; wire `InternalPaymentHMACVerifier` on payment intent creation (`BLK-P3C-01`, DQ4) | HIGH (Shared Security Core) |
| **boontrack-core** | `app/services/payment/factory.py` | **Core Security & Payment Lead** | Canonical `rail`/`provider`/`channel` normalizer (accept legacy `PAYMENT_GATEWAY` server-side only); resolve `api_secret_ref` via `CredentialProfileMapper`; remove plaintext secret dependency (`BLK-P3C-01`, `BLK-P3C-05`) | HIGH (Shared Factory) |
| **boontrack-core** | `app/services/payment/gateway_xendit.py` | **Core Security & Payment Lead** | Execute `POST /qr_codes` directly using instance `self.secret_key`, bounded `httpx.Timeout(connect=3, read=6)`, idempotency header, and `GET /qr_codes` reconciliation; stop delegating to global `xendit_service` (`BLK-P3C-01`, `BLK-P3C-03`) | HIGH |
| **boontrack-core** | `app/routes/payment.py` | **Core Security & Payment Lead** | Enforce `InternalPaymentHMACVerifier`; remove `"commerce"`/`"default"` bypass (line 164); use resolved `adapter` (stop discarding line 171!); persist durable `payment_intents` with `UNIQUE(tenant, idempotency_key)`; fail-closed Ed25519 signer (`payment.py:51-73`) (`BLK-P3C-01`, `BLK-P3C-03`) | CRITICAL (Shared Route) |
| **boontrack-core** | `app/routes/xendit.py` | **Core Financial Settlement Lead** | Fail-closed Ed25519 signer (`66-88`); fix tautological `provider_verification_secret=candidate_token` (`998`); delete dead legacy `_check_db_idempotency_sync` (`315-384`) & `_record_settlement_and_ledger_sync` (`485-738`); remove fire-and-forget `asyncio.create_task` WA/CAPI (`1076-1098`); lookup `payment_intents` instead of `orders` (`BLK-P3C-04`, `BLK-P3C-06`) | CRITICAL (Shared Route) |
| **boontrack-core** | `app/core/security/provenance_authority.py` | **Core Financial Settlement Lead** | Refactor `commit_verified_settlement_transaction` (`1763-2273`) to lock/update Core-owned `payment_intents` + insert `payment_outbox_events` atomically; **remove direct `UPDATE public.orders` (`2172-2187`)**; perform internal secret verification inside `TrustedSettlementVerificationBoundary` (`497-503`) (`BLK-P3C-04`, `BLK-P3C-06`, DQ2) | CRITICAL (Shared Authority) |
| **boontrack-core** | `app/main.py` & `app/api/webhook_payment.py` | **Core Financial Settlement Lead** | Unmount/remove duplicate `webhook_payment_router` (`app/main.py:341`) with global non-constant-time token check; mount Core outbox dispatcher worker (`BLK-P3C-04`) | MEDIUM |
| **boontrack-core** | `app/services/tenant_context_resolver.py` | **Core Security & Payment Lead** | Remove hardcoded `"onlineboost"` non-UUID fallback (`446-475, 745-774`) that returns empty `payment_config` (`BLK-P3C-01`) | MEDIUM |
| **boontrack-core** | `app/routes/d2c_order_routes.py` & `app/services/checkout_service.py` | **Core Financial Settlement Lead** | Fix dead `adapter` variable (`d2c_order_routes.py:88-120`) or disable unused legacy checkout path; retire `ON CONFLICT (event_id)` / direct `UPDATE orders` in `checkout_service.py:184-292` (`BLK-P3C-01`, `BLK-P3C-04`) | MEDIUM |
| **boontrack-core** | `app/workers/payment_outbox_dispatcher.py` *(new)* & `app/workers/payment_reconciler_worker.py` | **Core Financial Settlement Lead** | Implement `FOR UPDATE SKIP LOCKED` outbox delivery to Inbox projection endpoint + `PROVIDER_UNKNOWN` / expiry reconciler on `payment_intents` (DQ2, DQ4, DQ5) | LOW (New/Isolated) |
| **boontrack-core** | `migrations/037_core_payment_intent_idempotency_and_settlement_outbox.sql` *(new)* & `migrations/reconciliation/shared_db_migration_manifest.json` | **Core Schema & Migration Lead** | Expand Core `payment_intents` + create `payment_outbox_events` (ZERO DDL on `public.orders`!); update manifest for clean replay (DQ2, DQ3, DQ4) | HIGH (Schema Gate) |
| **boontrack-inbox** | `supabase/migrations/20261123_orders_idempotency_and_projection.sql` *(new)* | **Inbox Schema & Checkout Lead** | Inbox-owned minimal additive DDL on `public.orders`: `idempotency_key` (+ unique index), `payment_intent_id`, `last_settlement_event_id` (+ conditional `correlation_id` only if Quick POS is in Phase 1) (`BLK-P3C-02`, DQ3, DQ4) | HIGH (Schema Gate) |
| **boontrack-inbox** | `lib/checkout-service.ts`, `app/api/checkout/create-order/route.ts`, `lib/order-sanitizer.ts`, `lib/security/payment-destination-guard.ts` | **Inbox Checkout & Payment Lead** | Remove client `isGateway`/`isXendit` hints; strip 18 non-physical cols to `metadata`/`fulfillment_metadata`; implement `INITIATING_PAYMENT` -> `PAYMENT_INIT_UNKNOWN` saga with stable `idempotency_key` + `AbortSignal.timeout(10000)` + `InternalPaymentHMAC` signing; remove `DELETE` rollback on timeout; disable local static QRIS bypass for Phase 1 (`BLK-P3C-01`, `BLK-P3C-02`, `BLK-P3C-03`, `BLK-P3C-05`) | CRITICAL (Shared Checkout) |
| **boontrack-inbox** | `app/api/v1/payments/qris/create/route.ts` | **Inbox Checkout & Payment Lead** | Move terminal state guard (`PAID`, `EXPIRED`, `CANCELLED` -> `409`) **BEFORE** calling Core; add `AbortSignal.timeout(10000)` + `InternalPaymentHMAC` + stable `idempotency_key`; disable local static QRIS bypass; write QR projection to `metadata` (`BLK-P3C-01`, `BLK-P3C-02`, `BLK-P3C-03`, `BLK-P3C-05`, `BLK-P3C-06`) | CRITICAL (Shared Route) |
| **boontrack-inbox** | `app/api/internal/projections/payment-status/route.ts` *(new)* & `app/api/orders/[orderId]/status/route.ts` & `app/api/v1/orders/[id]/route.ts` | **Inbox Checkout & Payment Lead** | Create HMAC + Ed25519 public-key verified projection consumer (`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON`, zero private key!); update status/order readers to fallback cleanly to `metadata` (`BLK-P3C-02`, `BLK-P3C-04`, DQ2) | HIGH |
| **boontrack-inbox** | `app/api/webhooks/xendit/paid/route.ts`, `app/api/webhooks/xendit/route.ts`, `app/api/webhooks/payment/route.ts`, `app/api/webhook/payment/route.ts`, `app/api/v1/payments/qris/webhook/route.ts`, `app/api/v1/reader/notification/route.ts`, `app/api/v1/tenants/[slug]/orders/[id]/quick-paid/route.ts`, `app/api/orders/[orderId]/approve/route.ts`, `lib/whatsapp/evolution-webhook-handler.ts`, `lib/financial-state-machine.ts` | **Inbox Security Hardening Lead** | Hard-decommission (`410 GONE`) all 6 Inbox webhook/reader routes; hard-lock `quick-paid`/`approve` (`403`) for `NATIVE_PG` and Phase 1; disable WhatsApp payment parser auto-`PAID` (`evolution-webhook-handler.ts:1176-1215`) and `financial-state-machine.ts` direct `orders` mutation (`BLK-P3C-04`, `BLK-P3C-06`) | HIGH (Security Surface) |
| **boontrack-inbox** | `app/studio/desk/page.tsx`, `app/studio/desk/ugc-studio/page.tsx`, `app/studio/page.tsx`, `app/api/studio/billing/create-invoice/route.ts` | **Inbox Studio & Routing Integration Lead** | Sole conflict-resolution owner for merging `Recut-94` (`99dd1595`) + `Recut-101` (`a3301154`) on the 3 overlapping Studio files AND feature-gating Studio direct-Xendit billing OFF for Phase 1 per CTO Decision #2 (DQ7) | HIGH (3-Way Conflict Zone) |

---

## 10. INTEGRATION SEQUENCE (DESIGN QUESTION 7)

### 10.1 Verified Sibling Conflict Matrix (`boontrack-inbox`)
All three Inbox branches descend independently from `b6eec81fb2413ef99c4c3f05ecbd801fbaba76fc`—none contains another:
- **`P2 (133f178c)` ∩ `Recut-101 (a3301154)`:** **0 overlapping files** (clean).
- **`P2 (133f178c)` ∩ `Recut-94 (99dd1595)`:** **0 overlapping files**, but **1 semantic payment-authority violation**: `Recut-94`'s `app/api/studio/billing/create-invoice/route.ts:213-280` calls Xendit `/v2/invoices` directly from Inbox using `XENDIT_SECRET_KEY` and generates `TOPUP-STUDIO-*` external IDs that Core blocks with `403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD` (`xendit.py:771-781`).
- **`Recut-101 (a3301154)` ∩ `Recut-94 (99dd1595)`:** **3 overlapping files with semantic regression risk**:
  1. `app/studio/desk/page.tsx` (`Recut-101`: +17/- lines adding `isPreviewOrStagingHost` cookie scope guard and `/studio/register` origin routing; `Recut-94`: 1,935-line rewrite keeping `href="/register"` at line 670 and replacing `handleLogout` at line 418).
  2. `app/studio/desk/ugc-studio/page.tsx` (`Recut-101`: line 491 `/register` -> `/studio/register`; `Recut-94`: 106-line diff keeping `href="/register"` at line 490).
  3. `app/studio/page.tsx` (`Recut-101`: 4 `/register` links -> `/studio/register`; `Recut-94`: 860-line rewrite keeping `href="/register"` at lines 199, 229, 668, 742).

### 10.2 Safest Local Integration Sequence (Zero Remote Pushes/Merges)

```text
[TRACK A: boontrack-core]                              [TRACK B: boontrack-inbox]
Base: 3e4ffe21 (C:\boontrack-core-gateb-p2)            Base: b6eec81f (Canonical Baseline PR #106)
(DO NOT use dirty C:\boontrack-core @ 0e18979!)                │
          │                                                    ▼
          ▼                                            B1. Fast-forward to Packet 2 Inbox (133f178c)
A1. Core Migration 037 (payment_intents expand +           (6 files; establishes Core financial authority tests)
    payment_outbox_events; ZERO orders DDL)                    │
          │                                                    ▼
          ▼                                            B2. Merge Studio Phase 1 Recut (99dd1595)
A2. Core Payment Contract & Credential Profile             (0 file conflicts with 133f178c!)
    - api_secret_ref in payment_auth_guard.py              - Gate `app/api/studio/billing/create-invoice/route.ts`
    - Normalizer + adapter wiring in factory.py,             OFF for Phase 1 (`503 SAAS_BILLING_STAGE3_HOLD`)
      gateway_xendit.py, payment.py, d2c_order_routes        so Inbox has ZERO direct Xendit egress!
    - Enforce InternalPaymentHMACVerifier on                   │
      POST /api/v1/payments/intents & /qris/create             ▼
          │                                            B3. Rebase/Merge Creator Routing Recut (a3301154) LAST
          ▼                                                - Single owner reconciles the 3 Studio files:
A3. Core Settlement & Outbox Hardening                       `app/studio/desk/page.tsx`,
    - provenance_authority.py: lock payment_intents,         `app/studio/desk/ugc-studio/page.tsx`,
      emit payment_outbox_events, remove UPDATE orders       `app/studio/page.tsx`
    - xendit.py: fail-closed Ed25519, fix line 998,        - Preserve Recut-101 preview-host cookie isolation
      delete dead helpers, remove fire-and-forget WA/CAPI    & `/studio/register` links ON TOP OF Recut-94 UI
    - Unmount app/api/webhook_payment.py in main.py        - Re-run all 105 unit tests (P2 + #101 + #94)!
    - Add outbox dispatcher + expiry/unknown reconciler        │
          │                                                    ▼
          │                                            B4. Inbox Migration (orders idempotency_key + projection)
          │                                                & Metadata Cleanup (order-sanitizer, checkout-service,
          │                                                qris/create, status, email-service, payment-evidence)
          │                                                    │
          │                                                    ▼
          │                                            B5. Inbox Idempotent Saga, Timeout (10s), HMAC Client,
          │                                                Ed25519 Public-Key Projection Endpoint, Terminal Guard,
          │                                                Static-QRIS Phase 1 Lock, & 10x Dark-Settlement Shutdown
          └──────────────────────┬─────────────────────────────┘
                                 ▼
              [GATE C: JOINT LOCAL CLEAN-REPLAY & UN-SHIMMED E2E]
              1. Fresh tmpfs PG 17 (`--reset-db`), 110-step manifest replay
                 (ZERO ephemeral diagnostic ALTER TABLE shims!)
              2. Full un-mocked Inbox -> Core -> Xendit Sandbox -> Core Webhook
                 -> payment_outbox_events -> Inbox Projection E2E
                 (ZERO raw-SQL seeded orders!)
              3. Negative & Resilience Suite: timeout-after-Core-accept idempotency,
                 503/TCP-reset via deterministic in-network HTTP fault proxy
                 (eliminating Windows Docker port-proxy limitation!),
                 EXPIRED late-settlement quarantine, 10x dark-route 410/403 checks,
                 and 0 direct Inbox->Xendit / 0 production egress audit.
```

**Why `99dd1595` MUST land before `a3301154`:** `99dd1595` rewrites ~2,800 lines across `app/studio/desk/page.tsx` and `app/studio/page.tsx`, whereas `a3301154` makes surgical ~27-line routing/cookie fixes in those same 3 files. Re-applying a surgical 27-line routing patch onto the rewritten UI is auditable line-by-line and prevents accidental revert of Studio Phase 1 security guards (`studio-session-guard.ts`, `ssrf-guard.ts`).

---

## 11. REMAINING UNKNOWNS (`NOT VERIFIED` / `BLOCKED`)

| # | Unknown / Unverified Fact | Status | Impact & Verification Required Before Staging/Production |
|---|---|---|---|
| **U-01** | **Actual Live Production & Staging Supabase `public.orders` Schema** | `NOT VERIFIED` | Global Lock prohibits connecting to remote DBs. Unknown which (if any) of the 18 shim columns already exist physically in Production/Staging Supabase (`orders`), their exact data types, or existing triggers/RLS policies. Must inspect read-only `information_schema.columns` on Staging first once hold lifts. |
| **U-02** | **Actual Live `public.tenants.metadata` Payloads for OnlineBoost & Existing Tenants** | `NOT VERIFIED` | Unknown whether Production/Staging tenants currently store `payment_settings`, `payment_config`, plaintext keys, or `credential_profiles[]`. Server-side normalizer must be verified against a redacted Staging snapshot before cutover. |
| **U-03** | **Quick POS Chat (`TeamChatTab.tsx:1600`) Phase 1 Inclusion** | `NOT VERIFIED` | Determines whether `orders.correlation_id` requires an Inbox-owned indexed physical column or can be retired to `metadata.payment_token`. Product decision required before writing Inbox migration. |
| **U-04** | **Shabu Aji Phase 1 Commercial Requirement vs. Deferral** | `BLOCKED` | If Shabu Aji accepts deferral to Phase 2 (or onboarding to `NATIVE_PG` Dynamic QRIS), `BLK-P3C-05` closes immediately for Phase 1. If Shabu Aji mandates Static Merchant QRIS in Phase 1, release is `BLOCKED` pending Founder/CTO Unique-Code ADR + Direct-Tenant Rail security audit. |
| **U-05** | **Studio Token Top-Up (`TOPUP-STUDIO-*`) Phase 1 Inclusion** | `BLOCKED` | `Recut-94` (`app/api/studio/billing/create-invoice/route.ts:205-280`) calls Xendit directly, while Core blocks `TOPUP-*` webhooks (`xendit.py:771-781`, CTO Decision #2 `SAAS_BILLING_WEBHOOK_STAGE3_HOLD`). Confirm Studio paid top-up stays feature-flagged OFF in Phase 1 (free/sandbox/existing quota only) until Stage 3 SaaS billing milestone. |
| **U-06** | **OnlineBoost `OB-BATCH1-249K` Hardcoded Mock Guard (`lib/checkout-service.ts:126-207`)** | `NOT VERIFIED` | `OB-BATCH1-249K` is hardcoded to return `getBatch1MockCheckoutResult()` when `strict_hold` / mock flags are active. Confirm exact SKU ID (`OB-PRO-249K` vs `OB-BATCH1-249K`) and lift condition for live Phase 1 launch. |
| **U-07** | **Core `app/services/academy_service.py:1421,2181-2515` Production Traffic** | `NOT VERIFIED` | `academy_service.py` still writes directly to `orders` and `checkout_sessions` in Core. Confirm whether WhatsApp bot / Academy checkout flows are active in Phase 1 release scope or deferred. |
| **U-08** | **HTTP 503 & Mid-Stream TCP Reset Recovery (`OB-05` Sub-tests 5b/5c)** | `NOT VERIFIED` | Skipped in Packet 3C (`run_e2e_smoke_tests.py:986-996`) due to Docker Desktop Windows port-proxy behavior. Must be verified in Packet 3D local E2E using an in-network Nginx/Python fault-injection proxy container between Inbox and Core (works deterministically on Windows Docker without stopping containers). |
| **U-09** | **PostgreSQL Security Definer `public.process_payment_match()` Exposure** | `NOT VERIFIED` | Defined in `20261004_create_payment_observations_and_outbox.sql:85-221` without `SET search_path` or `REVOKE EXECUTE FROM PUBLIC, anon, authenticated` (checked in `R04` only for `is_jti_revoked`? Needs explicit verification in `R04_c07_c08_post_rls_and_privilege_hardening.sql`!). Must explicitly revoke/drop or guard this RPC in Inbox migration. |
| **U-10** | **Exact Cause of `A-02` `HTTP 200` in Packet 3C Run** | `NOT VERIFIED` | Raw source proves `A-02` cannot pass on an unmodified 108-step schema (`checkout-service.ts:833,834,846,847,1119`), and log timestamps (`19:44` vs `20:06`) strongly indicate prior-run container state carryover, but prior-run stdout was overwritten. Will be resolved cleanly by mandatory fresh `--reset-db` container per E2E run. |

---

## 12. MINIMUM IMPLEMENTATION SCOPE FOR RELEASE

To close all six Packet 3C blockers (`BLK-P3C-01`..`BLK-P3C-06`) **without rewriting BoonTrack or expanding Phase 1 scope**, lock the initial release strictly to **OnlineBoost `NATIVE_PG` Dynamic QRIS (`Rp249.000`, `unique_code = 0`) + Creator Routing (`#101`) + Studio Phase 1 Honest Slice (`#94`, billing gated OFF)**, with exactly these minimal deliverables:

### Core (`boontrack-core` branched from `3e4ffe21`) — 6 Focused Changes
1. **Migration `037_core_payment_intent_idempotency_and_settlement_outbox.sql`:** Expand `public.payment_intents` (idempotency unique index, provider/channel/profile/lease columns, `FORCE RLS`) + create `public.payment_outbox_events` (`FORCE RLS`). Zero DDL on `public.orders`.
2. **Payment Contract & Adapter Wiring (`payment_auth_guard.py`, `factory.py`, `gateway_xendit.py`, `payment.py`, `tenant_context_resolver.py`):** Canonical `rail`/`provider`/`channel` normalizer (accepting legacy `PAYMENT_GATEWAY` server-side only), `api_credentials.secret_ref` resolution, real per-tenant `XenditAdapter` execution (`POST /qr_codes` only, `connect=3s, read=6s`, zero redundant `/v2/invoices`), `InternalPaymentHMACVerifier` on intent creation, durable `payment_intents` idempotency state machine, remove hardcoded `"onlineboost"`/`"commerce"`/`"default"` bypasses.
3. **Settlement & Provenance Boundary (`provenance_authority.py`, `xendit.py`):** Lock/update Core-owned `payment_intents` + write `payment_events` + `financial_ledger` + `payment_outbox_events` in one ACID transaction (**zero `UPDATE public.orders` in Core**); fail-closed Ed25519 signer (remove dev fallback); fix tautological `xendit.py:998`; remove fire-and-forget WA/CAPI tasks (`xendit.py:1076-1098`); delete dead legacy helpers (`xendit.py:315-384, 485-738`).
4. **Retire Duplicate/Legacy Core Paths (`main.py`, `webhook_payment.py`, `d2c_order_routes.py`, `checkout_service.py`):** Unmount `webhook_payment_router`; fix/retire dead `adapter` & legacy `ON CONFLICT (event_id)` writers.
5. **Lightweight Core Workers (`payment_outbox_dispatcher.py`, `payment_reconciler_worker.py`):** `FOR UPDATE SKIP LOCKED` delivery of Ed25519-signed `payment_outbox_events` to Inbox projection endpoint + bounded `PROVIDER_UNKNOWN` / `ACTIVE` expiry reconciliation.
6. **Manifest Update (`shared_db_migration_manifest.json`):** Add Core `037` + Inbox `20261123` for clean 110-step PG17 replay.

### Inbox (`boontrack-inbox` integrating `b6eec81f -> 133f178c -> 99dd1595 -> a3301154`) — 6 Focused Changes
1. **3-File Sibling Reconciliation (`Recut-94` + `Recut-101`):** Single-owner merge of `app/studio/desk/page.tsx`, `app/studio/desk/ugc-studio/page.tsx`, `app/studio/page.tsx` + feature-gate `app/api/studio/billing/create-invoice/route.ts` OFF (`503 SAAS_BILLING_STAGE3_HOLD`).
2. **Inbox Migration `20261123_orders_idempotency_and_projection.sql`:** Add `idempotency_key` (+ unique index), `payment_intent_id`, `last_settlement_event_id` (plus `correlation_id` only if U-03 confirms Quick POS in Phase 1), and `REVOKE EXECUTE` / disable `public.process_payment_match()`.
3. **Minimal Schema Alignment (`order-sanitizer.ts`, `checkout-service.ts`, `qris/create`, `orders/route.ts`, `orders/[id]`, `status`, `email-service.ts`, `payment-evidence-service.ts`):** Write all non-physical attribution/briefing/QR/email fields into `metadata`/`fulfillment_metadata`/outbox; remove `coreOrderData` fallback mask.
4. **Idempotent Checkout Saga & Bounded Timeout (`checkout-service.ts`, `checkout/create-order/route.ts`, `qris/create/route.ts`):** Strip client `isGateway`/`isXendit` hints; persist `INITIATING_PAYMENT` with stable `idempotency_key`; sign Core requests with `InternalPaymentHMAC` + `AbortSignal.timeout(10000)`; transition timeouts/5xx to `PAYMENT_INIT_UNKNOWN` (**never `DELETE` on timeout**); enforce terminal `PAID`/`EXPIRED`/`CANCELLED` guard **before** calling Core; disable local static QRIS generator for Phase 1 (`BLK-P3C-05`).
5. **Signed Projection Endpoint (`app/api/internal/projections/payment-status/route.ts`):** Verify HMAC + Ed25519 public key (`PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON`), apply monotonic `orders` projection updates (`PAID` / `EXPIRED` / `late_settlement_quarantined`), and enqueue Inbox fulfillment/email/`capi_outbox`/reseller commission idempotently.
6. **Decommission All 10 Inbox Direct-Settlement Surfaces:** Return `410 GONE` on all 6 Inbox webhook/reader routes; return `403` on `quick-paid`/`approve` (for `NATIVE_PG` and Phase 1); disable WhatsApp payment auto-`PAID` (`evolution-webhook-handler.ts:1176-1215`) and `financial-state-machine.ts` direct `orders` writes.

### Release Verification Gate (Local Disposable Stack Before Any Staging Promotion)
- 100% pass across all 105+ existing unit/security tests (P2 + `#101` + `#94`) + new unit tests for `api_secret_ref`, outbox delivery, Ed25519 projection verification, and saga timeout/retry idempotency.
- Fresh `--reset-db` PG17 110-step replay with **0 ephemeral shims**.
- Un-mocked, un-seeded end-to-end OnlineBoost `Rp249.000` checkout -> Core `payment_intents` -> Xendit Sandbox Dynamic QRIS (exact `Tag 54 = 249000`, `unique_code = 0`) -> Core Xendit Webhook -> Ed25519 `payment_events` + `financial_ledger` + `payment_outbox_events` -> Inbox verified `orders` projection (`PAID`).
- Deterministic fault-proxy verification of timeout-after-Core-accept (1 intent, 1 Xendit QR, 0 deleted orders), HTTP 503, TCP reset, `EXPIRED` late-settlement quarantine, 10x Inbox dark-route `410`/`403` rejection, and `0` direct Inbox->Xendit / `0` production egress calls.

---
*End of `PACKET_3D_NEON_ARCHITECTURE_CHALLENGE.md` — Strictly Read-Only Principal Design Review Complete.*
