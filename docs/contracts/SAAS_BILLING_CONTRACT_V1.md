# Core SaaS Billing Contract v1

**Status:** S1–S6 CI PASS — Staging preflight pending — non-production only  
**Owner:** BoonTrack Core Engineering  
**Consumers:** BoonTrack Shop and BoonTrack Studio  
**Baseline:** Core main at 2bed59f99050001ad6bf0b35881f381f5c9e91d5  
**Contract version:** saas-billing.v1  
**Live billing:** DISABLED

## 0.1 Staging implementation gate — 28 Nov 2026

This document defines the target contract. It is not evidence that every route is deployed or ready for UI consumption.

Implemented in the feature branch:
- Founder-approved Shop and Studio catalog values, including existing Team Scale as TEAM_SCALE -> ENTERPRISE.
- Server-calculated quote primitive and product-server HMAC authorization helper.
- PostgreSQL-only SaaSBillingRepository source for atomic payment-intent + purchase reservation, durable idempotency, Core outbox enqueue, and effective entitlement reads.
- Legacy Shop entitlement lookup is read-only; Team Scale is normalized to ENTERPRISE. No existing subscription row is rewritten.
- WABA Official line items retain META_FEES_PASS_THROUGH metadata; Meta fees are not included in the Rp149,000 SKU price.

Not yet verified or available as a staging API:
- CI P0 must pass on the latest branch HEAD, including catalog, legacy Team Scale, repository fail-closed tests, and targeted typecheck.
- Migration 038 has been applied only to a disposable GitHub Actions CI database for schema/test verification; it has not been applied to Staging or Production. The repository cannot run against Staging until the required Core-owned tables exist there under separate authorization.
- FastAPI router code is registered in `app/main.py` on the feature branch. Catalog and authenticated quote preview are implemented in code; payment-intent creation, payment status, webhook settlement, and reconciliation remain fail-closed or unavailable as detailed in Section 4.0. This is not a Staging deployment.
- `app/services/saas_billing_xendit.py` provides a thin wrapper around the existing Core `XenditAdapter`, with a separate SaaS sandbox profile and support for invoice/Web Checkout and Dynamic QRIS. Provider calls have not been executed against an actual SaaS sandbox profile. Verified SaaS settlement, Core SaaS ledger writer, entitlement activation consumer, and recovery worker are not yet wired. Core already has a generic Xendit adapter and webhook/payment primitives on main; see Section 6.1 for mandatory reuse boundaries.
- No Shop, Creator, or Studio UI candidate may assume these endpoints are reachable. Until a later CCC handover explicitly marks the contract READY, consumers must fail closed and must not create local payment intents or activate entitlements.

The API paths in Section 4 are target paths, not a statement of deployed endpoint availability. TAX_POLICY_PENDING remains a hard payment-intent gate.

## 0.2 P0/P1 closure evidence — 28 Nov 2026

- **P0 prior run `46133764556`: FAIL (20 passed, 2 failed).** PostgreSQL bootstrap, disposable Migration 038 application, and Redis startup succeeded. Both failures were async tests in `tests/test_subscription_pricing.py` because `pytest-asyncio` was absent; the Team Scale/catalog assertions were among the passing synchronous tests. Mypy was skipped after pytest failed.
- **P0 corrective change:** workflow dependency `pytest-asyncio` added in commit `0d8dbf9ec3fef7354d50483afbb5e062b3781002`. A new push run is expected from subsequent branch commits; its final result must be read from Actions before P0 is marked PASS. This document does not claim that rerun passed.
- **P1 repository source:** `app/services/saas_billing_repository.py` provides PostgreSQL-only purchase reservation, advisory-lock idempotency, shared payment-intent + purchase + outbox writes in one transaction, rollback on failure, and read-only legacy entitlement lookup. No in-memory fallback is used.
- **P1 PostgreSQL integration evidence:** Run `46138991733` completed successfully with 32 passed and 20 subtests passed. This includes same-key/same-payload replay, changed-payload conflict, outbox-triggered transaction rollback, and read-only legacy Team Scale → ENTERPRISE mapping. Mypy reported no issues in six SaaS billing source files. P1 is closed for these tested repository invariants; concurrent race/load behavior and duplicate entitlement event consumer behavior are not covered by this run.

## 0.3 Latest execution synchronization — 28 Nov 2026

- **P0:** GitHub Actions Run `46135979192` — SUCCESS; 22 passed, 20 subtests passed; targeted mypy clean.
- **P1:** GitHub Actions Run `46138991733` — SUCCESS; 32 passed, 20 subtests passed; mypy clean in six source files. Repository integration tests prove same-key replay, changed-payload rejection, outbox-failure rollback, and Team Scale legacy normalization.
- **P2 source:** `SaaSXenditSandboxProfile` requires separate `SAAS_XENDIT_SANDBOX_*` profile values, rejects production context and reuse of generic OnlineBoost Xendit credentials, and binds the callback URL. `SaaSXenditProvider` reuses Core `XenditAdapter` for invoice/Web Checkout and Dynamic QRIS. The generic adapter accepts a validated explicit callback URL for QRIS. No real SaaS sandbox provider call has been made; credential profile values are not configured in this branch.
- **P3 source:** `app/routes/saas_billing_routes.py` is registered from `app/main.py`. Catalog and quote preview are implemented in feature-branch code. Payment-intent route remains blocked by `TAX_POLICY_PENDING`; status, webhook settlement and reconciliation remain fail-closed. These are not deployed Staging APIs.
- **Deployment and database boundary:** no Staging deployment has been executed and Migration 038 remains unapplied to Staging/Production. No Production, Main, or live SaaS activation is authorized.

## 0.4 S1–S6 implementation candidate — 28 Nov 2026

This section supersedes the earlier pre-implementation status above for source-code readiness. The CI gate has now passed on the S1–S6 implementation commit; Staging read-only inspection remains a separate pending gate.

- **S1 — Migration 038 multi-SKU and deduplication:** the ledger uniqueness boundary is now per provider event + purchase + SKU + entry kind. Provider webhook event dedup remains unique by provider + provider event ID. Ledger rows remain append-only; purchase line-item amounts are reconciled to the persisted subtotal and tax snapshot.
- **S2 — Atomic settlement repository:** `app/services/saas_billing_settlement.py` verifies invoice reference, dedicated credential profile, provider business ID, sandbox environment, IDR currency, settled status, and exact amount. Payment state, webhook event, SKU ledger entries, entitlement requests, and activation outbox are written in one PostgreSQL transaction.
- **S3 — Dedicated SaaS Xendit webhook:** `POST /api/v1/saas-billing/webhooks/xendit` uses the dedicated SaaS callback token and routes only into the SaaS settlement repository. It does not call the generic merchant `handle_webhook` path.
- **S4 — Idempotent SaaS outbox consumer:** `app/workers/saas_billing_outbox_consumer.py` handles sandbox invoice creation and post-settlement entitlement activation with a durable claim/lease and retries. The generic Inbox payment outbox dispatcher explicitly excludes `SAAS_*` event types.
- **S5 — Reconciliation service:** `app/services/saas_billing_reconciliation.py` checks the bound sandbox invoice using the provider status adapter, sends verified paid states through the same atomic settlement repository, and records expiry only for a non-paid purchase.
- **S6 — Disposable CI and schema preflight:** `.github/workflows/saas-billing-p0.yml` applies Migration 038 only to runner-local disposable PostgreSQL, executes the schema preflight script, then runs the PostgreSQL integration suite and targeted typecheck. `scripts/preflight_saas_billing_migration_038.py --staging-read-only` is an independent read-only Staging check; it cannot apply DDL.

**CI closure evidence — 28 Nov 2026:** GitHub Actions Run `46150120630` / Run #42 (`https://github.com/B055OB/boontrack-core/actions/runs/46150120630`) completed `SUCCESS` for implementation commit `f704f15b00f51cf99f085086c5a8e3fec890efbe`. Runner-local PostgreSQL initialization and Migration 038 application succeeded; the disposable preflight returned `APPLIED_AND_VERIFIED`, with all four SaaS tables, the multi-SKU deduplication index, forced RLS, append-only ledger trigger, and isolated fake sandbox credential profile present. Integration/regression tests: **38 passed, 20 subtests passed**. Targeted mypy: **no issues in 9 source files**. This verifies S1–S6 in disposable CI only; it does not claim a real Xendit provider round-trip or Staging database access.

**Staging preflight status:** NOT RUN / BLOCKED because `SAAS_BILLING_STAGING_PREFLIGHT_DSN` was not configured in the workflow/runtime. `scripts/preflight_saas_billing_migration_038.py --staging-read-only` requires that explicit DSN, rejects a target whose host/database does not identify as Staging, opens a read-only transaction, performs no DDL, and reports `migration_application_authorized: false`. The current CI environment shows `STAGING_DATABASE_URL`, `SUPABASE_DB_URL`, and `REVOKED_STAGING_DB_PASSWORD` empty; no alternate Staging read-only connection was supplied. Therefore there is no Staging catalog/schema evidence yet, and Migration 038 remains unapplied there.

**Unchanged hard gates:** the product payment-intent route remains HTTP 409 `BILLING_TAX_POLICY_PENDING`. Explicit approved 0-bps tax policy appears only inside deterministic CI/test fixtures, not runtime defaults. CI uses fake Xendit profile credentials and a fake provider; no real Xendit sandbox request has been made. Migration 038 has not been applied to Staging or Production. Main, Production, Live SaaS Billing, OnlineBoost Live `ORD-OB-3B137B30`, and Shabu Ajhi remain STRICT HOLD.

## 1. Purpose and authority

Shop and Studio consume one Core-owned SaaS billing contract. Core is the sole authority for catalog price, quote, payment intent, provider profile selection, webhook acceptance, settlement, billing ledger, payment state, and entitlement activation.

Shop and Studio may own product presentation, authenticated user journeys, and local read models. They must not:
- send an authoritative amount, currency, provider, merchant account, credential, or entitlement result;
- create provider invoices directly;
- verify or settle payment callbacks;
- write financial ledger entries or activate paid entitlements locally;
- introduce a second payment-intent or settlement engine.

The contract covers SaaS package and add-on purchases only. It does not change buyer order checkout, Shabu Ajhi tenant payment, OnlineBoost revenue collection, or Creator commission/payout settlement.

## 2. Product identity and tenant authorization

The authenticated Shop or Studio server must call Core. A browser must never call the provider or a Core mutation endpoint using an unverified tenant identifier.

Core must resolve, from a verified session or approved service-to-service identity:
- principal ID and authentication strength;
- canonical tenant UUID;
- tenant membership and role;
- product context: SHOP or STUDIO;
- entitlement and billing permission for that product.

The tenant ID supplied by a browser, query string, route slug, or arbitrary X-Tenant header is not authoritative. Core derives the canonical tenant from verified identity and membership. Product context is allowlisted and bound to the authenticated client; it cannot be used to cross-purchase or read another product's billing records.

A platform-owned SaaS billing credential profile is distinct from each tenant's customer-payment credential profile. It is never selected from tenant-supplied metadata.

## 3. Catalog and price authority

The authoritative catalog is versioned and served by Core. Each entry contains:
- product owner (SHOP or STUDIO);
- SKU and entitlement key;
- purchase type (BASE_TIER, SUBSCRIPTION, STANDALONE_ADDON, BUNDLE_INCLUDED, CREDIT_TOPUP, or LIFETIME_LICENSE);
- amount in integer IDR, or null while unpriced;
- catalog approval state;
- billing cadence and validity policy;
- prerequisites and dependency keys;
- catalog version and effective timestamp.

No amount is accepted from the client. A quote is derived only from the catalog version and SKU list held by Core.

### 3.1 Founder-approved Staging price book — 28 November 2026

Studio:
- `STUDIO-MONTHLY-29K`: Rp29,000; monthly; 25 credits; 30-day validity.
- `STUDIO-ANNUAL-99K`: Rp99,000; annual; 100 credits; 365-day validity; default checkout.
- `STUDIO-ANNUAL-299K`: Rp299,000; annual; 500 credits; 365-day validity; campaign key `ONLINEBOOST_CAMPAIGN`.

Shop sellable Staging catalog:
- Free Forever: Rp0, lifetime/free base entitlement; no payment intent.
- Starter / Shop Growth Bundle: Rp99,000 monthly.
- Ads Performance: Rp299,000 monthly.
- Dynamic QRIS: Rp39,000 monthly.
- SmartChatbox / Multi-CS: Rp149,000 monthly.
- AI Auto-Reply (300 replies): Rp199,000 monthly.
- Booking Pro: Rp49,000 monthly.
- WABA Official: Rp149,000 monthly; Meta fees are a separate pass-through and are not included in this SKU price.

Shop Team Scale is an existing Tier 4 subscription at Rp499,000/month. It remains sellable in the catalog as `TEAM_SCALE` and retains the existing canonical `ENTERPRISE` entitlement mapping used by legacy subscription logic. Existing customer subscription rows, renewals, entitlement state, and billing history must remain intact; do not reset, rewrite, or migrate them as part of this delta. This catalog entry is an adapter to the existing tier, not a replacement subscription system. The six HOLD categories remain strictly non-purchasable: WhatsApp Non-WABA / Scan Barcode; Frontpage E-Commerce, Microsite, and Web Profile templates; Affiliate Domain; and Offline Event Upload. They must remain absent from the purchasable catalog, checkout controls, and upsells.

The Founder directive does not specify the exact entitlement inclusions of Starter or Ads Performance. Until Product ratifies a tier-to-add-on inclusion map, Core rejects a quote combining a Shop package/base tier and any standalone add-on with `BILLING_BUNDLE_MAPPING_PENDING`. Repeated entitlement keys are also rejected. This is a quote-level fail-closed guard, not yet a substitute for checking existing effective tenant entitlements in the durable repository before intent creation.

SmartChatbox's directed product scope includes WhatsApp, Instagram DM, Facebook Messenger, Threads, TikTok DM, and Web Chat. This is a product scope statement, not a claim that each connector, provider dependency, agent capacity, or quota is currently production-ready. Product/Core must ratify channel definitions, WABA versus non-WABA treatment, agent limits, quotas, and provider dependencies before public sale.

Monthly entitlements are designed for 30 calendar days and annual entitlements for 365 calendar days. These durations must be applied only where the product entitlement contract calls for them. The 365-day and perpetual rules for Affiliate Domain and Frontpage templates remain design notes while those items are HOLD.

Tax policy remains `TAX_POLICY_PENDING`. Approved Staging prices do not authorize live invoice creation or bypass the tax gate.

## 4. API contract

The following is the target server-to-server contract. Paths are versioned and owned by Core.

- GET /api/v1/saas-billing/catalog?product=SHOP|STUDIO
- POST /api/v1/saas-billing/quotes
- POST /api/v1/saas-billing/payment-intents
- GET /api/v1/saas-billing/payment-intents/{intent_id}
- POST /api/v1/saas-billing/webhooks/xendit
- POST /api/v1/saas-billing/reconciliation/{intent_id}

Mutation routes require authenticated product server identity plus verified principal/tenant authorization, or an approved Core operator identity for recovery. Provider callbacks use a separate provider authentication path and cannot use merchant session authentication.

### 4.0 Endpoint readiness and consumer contract — 28 Nov 2026

**Current implementation status for every route below: NOT IMPLEMENTED (contract published; no FastAPI route is registered).** These definitions are safe for Shop and Studio UI integration against typed client interfaces, but they are not reachable staging APIs. Do not substitute mocks or local payment-intent creation. All transaction mutations remain fail-closed until a separate CCC handover confirms route deployment and staging smoke tests.

| Method and path | Consumer / purpose | Authentication | Request schema | Success response | Current status |
|---|---|---|---|---|---|
| GET `/api/v1/saas-billing/catalog?product=SHOP\|STUDIO` | Read-only product pricebook | Public read-only response; no tenant or credential data | Query: `product` enum; optional `catalog_version` | `{catalog_version, product, currency: "IDR", items:[...]}` | IMPLEMENTED IN FEATURE BRANCH; not deployed to Staging |
| POST `/api/v1/saas-billing/quotes` | Shop or Studio server; server-side quote | Product-scoped HMAC; verified principal, canonical tenant membership and billing permission; PostgreSQL anti-replay | `{product, items:[{sku, quantity}], catalog_version?, request_reference, idempotency_key}`; no amount, tenant, tax or provider input | `{quote_id, canonical_tenant_id, product, catalog_version, lines:[...], subtotal_idr, tax_status, tax_amount_idr, total_idr, currency, quote_status, payment_intent_allowed}` | IMPLEMENTED IN FEATURE BRANCH; returns `TAX_POLICY_PENDING`; not deployed to Staging |
| POST `/api/v1/saas-billing/payment-intents` | Shop or Studio server; reserve Core purchase and initiate provider checkout | Product-scoped HMAC and quote ownership required when enabled | `{product, quote_id, request_reference, idempotency_key}`; amount/provider/credential/tenant fields prohibited | `{purchase_id, payment_intent_id, status, provider:"XENDIT", checkout_url, expires_at, reused}` | REGISTERED FAIL-CLOSED; returns 409 `BILLING_TAX_POLICY_PENDING`; no DB/provider write |
| GET `/api/v1/saas-billing/payment-intents/{intent_id}` | Shop or Studio server; retrieve authoritative payment status | Product-scoped HMAC; same tenant/product scope as purchase | Path: Core intent ID; no client-supplied tenant override | `{payment_intent_id, purchase_id, product, status, amount_idr, currency, provider_reference, checkout_url?, expires_at, settled_at?}` | REGISTERED FAIL-CLOSED; returns 503 `CORE_BILLING_UNAVAILABLE` |
| POST `/api/v1/saas-billing/webhooks/xendit` | Xendit callback to Core | Dedicated SaaS sandbox callback token; provider profile isolated from OnlineBoost | Raw provider callback body + provider headers | Stable accepted/duplicate response only after verified durable settlement | REGISTERED FAIL-CLOSED; token gate exists, settlement handler returns 503 |
| POST `/api/v1/saas-billing/reconciliation/{intent_id}` | Core operator/recovery worker only | Core operator/service identity with explicit reconciliation permission | `{reason, correlation_id}` | `{payment_intent_id, status, reconciliation_status, checked_at}` | NOT IMPLEMENTED; returns 503 |

**Shared error envelope:** `{error:{code, message, request_id, retryable}}`. Stable codes and HTTP mappings are in Section 10. Responses must not include secret refs, credentials, raw provider payloads, or internal stack traces. Authentication/tenant errors are 401/403; unknown SKU 404; quote, tax, idempotency and settlement conflicts 409; persistence/provider/profile unavailability 503; quarantined late settlement and reconciliation-required outcomes 202.

**Tax gate:** until an approved tax policy is supplied by Core, quote responses remain `tax_status=TAX_POLICY_PENDING`, `total_idr=null`, `payment_intent_allowed=false`; POST payment-intents returns `BILLING_TAX_POLICY_PENDING` (409). This is intentional, not a temporary UI mock state.

**Consumer boundary:** Shop and Studio may implement catalog rendering, quote review UI, pending/error states, and typed API clients now. They must disable checkout submission and must not display a fabricated checkout URL. Creator has no SaaS billing endpoint in this contract; do not infer one from Shop or Studio routes.

### 4.1 Quote request

Request fields:
- product: SHOP or STUDIO;
- items: one or more SKU and quantity pairs;
- catalog_version: optional; when supplied it must match a valid retained version;
- request_reference: caller-generated non-secret purchase reference used as the HMAC-bound order reference;
- idempotency_key: caller-generated value included in the signed request body (an Idempotency-Key header may mirror it, but the body value is authoritative for signature binding).

The request must reject amount, subtotal, tax, currency, provider, merchant account, tenant_id, entitlement status, or credential fields. Core resolves tenant identity separately from the request body.

The response contains quote_id, canonical tenant_id, product, immutable line items, catalog_version, subtotal, tax state, total, currency, expiry, and quote status. A quote is bound to tenant, product, and principal; another tenant cannot reuse it.

## 5. Payment-intent lifecycle

Core is the only writer of payment intents. Shop and Studio receive only a public payment-intent DTO.

Creation flow:
1. Verify principal, product server identity, tenant membership, and billing permission.
2. Resolve catalog entries and server-side prices; reject any non-sellable SKU or missing dependency.
3. Create a short-lived immutable quote and calculate the request fingerprint.
4. Require idempotency_key in the HMAC-signed request body. Core scopes it as saas:{product}:{canonical_tenant_id}:{client_key}; reject reuse with a different fingerprint using HTTP 409.
5. Open a durable PostgreSQL connection. If persistence is unavailable, fail with 503. SaaS billing must never use PaymentIntentLifecycleService's in-memory fallback.
6. Persist the SaaS purchase record and the shared Core payment_intents record. The payment_intents row uses canonical tenant UUID, a unique Core purchase order ID, exact server-derived amount, and namespaced idempotency key.
7. Resolve the platform SaaS Xendit sandbox credential profile from Core configuration. Create the provider invoice using only the resolved sandbox credential.
8. Persist provider reference, checkout URL, expiry and provider result. A timeout or ambiguous provider response becomes PROVIDER_UNKNOWN; do not create a second invoice on blind retry.
9. Emit the normal Core payment-intent lifecycle event and a SaaS-specific event through the Core outbox.

The existing PaymentIntentLifecycleService is reused for durable intent lifecycle and idempotency. The SaaS flow must explicitly pass the same open DB connection and own the transaction boundary. Its default memory fallback is prohibited for this route.

## 6. Credential profile isolation

The initial non-production adapter is Xendit sandbox only. The platform SaaS credential profile must:
- have an explicit profile ID and provider account ID;
- be scoped to the BoonTrack SaaS billing platform identity, not to the buying tenant's merchant credential;
- use environment=sandbox and profile_status=ACTIVE;
- store secret_ref pointers only (env:// or vault://), never plaintext secrets;
- reject profile, secret, account, and environment mismatch;
- fail closed if secret resolution or provider account binding is unavailable.

The existing CredentialProfileMapper and secret-pointer rules are the baseline for isolation. A tenant's own Shop buyer-checkout credential is never reused to bill that tenant for SaaS packages.

No production profile may be loaded by the non-production deployment. No production Xendit secret, Dodo credentials, Midtrans credentials or tenant payment profile may be used by the initial SaaS billing adapter.

### 6.1 Existing Core Xendit pattern — reuse decision

The following existing Core modules are the reference implementation on `main` and must be reused or safely wrapped rather than replaced with a new provider integration:

| Existing component | Existing pattern to reuse | SaaS adaptation required |
|---|---|---|
| `app/services/payment/gateway_xendit.py` | Shared `PaymentAdapter` contract; Xendit Basic Auth from instance secret; Dynamic QRIS `POST /qr_codes`; invoice/Web Checkout `POST /v2/invoices`; status lookup; `X-CALLBACK-TOKEN` constant-time comparison | Instantiate only with a Core platform SaaS sandbox profile; remove implicit OnlineBoost tenant defaults; inject the SaaS callback URL; avoid current invalid-token log that includes the supplied token; preserve unknown provider outcomes rather than collapsing transport failures to PENDING |
| `app/services/xendit_service.py` | Existing invoice/checkout payload shape, Dynamic QRIS API request shape, Xendit error classification for definitive vs ambiguous outcomes | Reuse request/response mapping only. Do not reuse its process-memory `PAYMENT_INTENTS` registry or use it as SaaS persistence/idempotency authority |
| `app/routes/xendit.py` | Canonical persisted reference lookup, IDR/amount comparison, provider callback-token boundary, trusted settlement capability, duplicate handling, late-settlement quarantine, structured tracing | Existing route is order/tenant-merchant-profile scoped and uses order-specific `commit_verified_settlement_transaction`. Do not route SaaS purchase callbacks through that transaction. Build a SaaS-specific handler using the same provider-authentication and verification primitives, SaaS purchase lookup, shared payment intent, SaaS ledger and Core outbox in one DB transaction. Require an explicit paid status; do not inherit any permissive missing-status default |
| `app/core/security/payment_auth_guard.py` | Canonical tenant identity and PostgreSQL-backed anti-replay/HMAC primitives | Reuse only after mapping product-server identity to the authenticated canonical tenant; do not trust caller tenant or merchant credential fields |
| `app/core/security/provenance_authority.py` | `TrustedSettlementVerificationBoundary` mints a verified settlement capability after Xendit callback-token verification; provider method is `XENDIT_CALLBACK_TOKEN` | Reuse the Xendit callback-token verification primitive, but define a SaaS-specific authoritative purchase context and atomic commit. Ed25519 provenance is an internal Core signing layer, not a Xendit webhook signature; never describe it as such |
| `app/models/payment_event.py` | Provider event identity and append-only payment event audit patterns | SaaS event identity must be tied to SaaS purchase/payment intent; do not mutate order-scoped events or create a second financial authority |
| `app/workers/payment_reconciler_worker.py` | Existing intent state model, bounded reconciliation outcomes, terminal-state and late-settlement quarantine semantics | Do not use its in-memory order/intent stores or inventory-restoration branch for SaaS. Implement SaaS recovery against persisted SaaS purchase + shared Core payment intent and existing outbox |

**Reuse boundary:** provider connectivity and its tested request/response/authentication primitives are shared Core capabilities. OnlineBoost's order-specific pricing, unique-amount policy, tenant merchant profile, WhatsApp/Telegram fulfillment, CAPI dispatch and order settlement commit are not SaaS billing behavior. Shop purchases activate Shop entitlements; Studio purchases grant Studio credits only after the SaaS settlement transaction has committed. No OnlineBoost fulfillment function is called by SaaS.

**Current source-level caveats to close before reuse:** the generic adapter's QRIS and invoice flows are separate provider operations; confirm the selected product's intended flow rather than issuing both blindly. Its webhook normalizer currently accepts several event shapes and its route contains order-specific defaults. Its invalid-token warning must not log the candidate token. Its status lookup currently catches provider errors and returns a PENDING-shaped result, which is insufficient to distinguish an ambiguous provider outcome. These are targeted adapter hardening items, not reasons to rebuild Xendit connectivity.

## 7. Webhook verification and atomic settlement

The provider callback is not proof of payment until Core verifies it.

For each callback Core must:
1. Parse provider event identifiers and resolve the expected Core purchase and payment intent from the stored provider reference.
2. Resolve the stored platform sandbox credential profile and its active/grace verification secret.
3. Verify callback token/signature in constant time; verify provider account ID, provider invoice/reference, currency, amount, tenant binding, product, SKU and expected status against authoritative persisted records.
4. Reject malformed, mismatched, replayed, expired, or unsupported events. Late settlement is quarantined, not silently activated.
5. In one DB transaction, insert a provider-event idempotency record, lock the purchase and payment intent, transition the shared Core payment intent, append the immutable SaaS billing ledger entry, and enqueue a SaaS entitlement activation event in Core's outbox.
6. Commit once. Duplicate delivery returns an idempotent acknowledgement and creates no second ledger entry or entitlement event.

The existing TrustedSettlementVerificationBoundary is the cryptographic verification primitive. Do not claim Xendit provides Ed25519 provenance unless the selected Xendit integration contract explicitly documents and verifies that mechanism. Provider-supported callback token/signature validation remains authoritative; an unrelated Ed25519 layer must not replace it. The existing order-specific commit_verified_settlement_transaction must not be called for SaaS purchases unless the authoritative object is a valid order under that API's contract. SaaS settlement requires a SaaS-specific repository transaction around the shared Core payment intent and outbox.

## 8. Ledger, status and entitlement event

The append-only SaaS billing ledger records purchase/settlement facts; it is not a second payment authority. Each record is uniquely tied to:
- canonical tenant UUID;
- product and SKU;
- quote and purchase ID;
- shared Core payment_intent_id;
- provider and provider event ID;
- immutable amount and currency;
- settlement time and catalog version.

Corrections are compensating entries (refund, reversal, adjustment), never in-place edits or deletion.

Payment status is read from Core: INITIATING, ACTIVE/PENDING, PROVIDER_UNKNOWN, PAID/SETTLED, EXPIRED, CANCELLED/FAILED, or QUARANTINED_LATE_SETTLEMENT. Client-side success redirects never activate entitlements.

Only a verified settlement transaction may enqueue SAAS_ENTITLEMENT_ACTIVATION_REQUESTED. The entitlement consumer must:
- verify tenant, product, SKU, quantity, validity, and source ledger reference;
- deduplicate by immutable event ID and entitlement source reference;
- activate only the purchased entitlement;
- record its own result and emit SAAS_ENTITLEMENT_ACTIVATED or SAAS_ENTITLEMENT_ACTIVATION_FAILED;
- be safe to replay.

Shop and Studio read the effective entitlement from Core. A paid receipt or provider redirect alone is not entitlement proof.

## 9. Recovery and reconciliation

A scheduled Core worker reconciles INITIATING and PROVIDER_UNKNOWN intents, and stale ACTIVE intents nearing expiry, using provider lookup with the same sandbox profile. Recovery is keyed by shared payment_intent_id and provider reference, never by a newly generated invoice ID.

Required outcomes:
- provider confirms paid: run the same verified settlement path;
- provider confirms pending: retain ACTIVE/PENDING and retry with bounded backoff;
- provider confirms absent/failed/cancelled: mark terminal only after authoritative provider lookup;
- provider unavailable or conflicting data: retain PROVIDER_UNKNOWN and escalate;
- late paid callback after expiry: quarantine and require explicit reconciliation;
- duplicate callback or recovery job: no duplicate ledger entry or entitlement activation.

Every action records actor, reason, source, old state, new state, correlation ID, and timestamp in the Core audit/outbox trail. Recovery must not mutate catalog price, tenant identity, or payment ownership.

## 10. Error contract

Stable error codes:
- BILLING_AUTH_REQUIRED (401)
- BILLING_TENANT_FORBIDDEN (403)
- BILLING_PRODUCT_MISMATCH (403)
- BILLING_SKU_NOT_FOUND (404)
- BILLING_SKU_NOT_SELLABLE (409)
- BILLING_CATALOG_VERSION_UNAVAILABLE (409)
- BILLING_QUOTE_EXPIRED (409)
- BILLING_IDEMPOTENCY_CONFLICT (409)
- BILLING_CREDENTIAL_PROFILE_INVALID (503)
- BILLING_PROVIDER_UNAVAILABLE (503)
- BILLING_PERSISTENCE_UNAVAILABLE (503)
- BILLING_TAX_POLICY_PENDING (409)
- BILLING_WEBHOOK_INVALID (401)
- BILLING_SETTLEMENT_MISMATCH (409)
- BILLING_LATE_SETTLEMENT_QUARANTINED (202)
- BILLING_RECONCILIATION_REQUIRED (202)

Errors must not expose secret refs, plaintext provider responses, or internal credential values.

## 11. Feature and environment gates

- SAAS_BILLING_LIVE_ENABLED defaults to false and remains false in this work.
- SAAS_BILLING_PROVIDER defaults to XENDIT_SANDBOX only for explicitly configured non-production environments.
- Live provider calls, live credentials, Main changes, production DB changes and production deployment are prohibited by this contract.
- A non-production test adapter may simulate provider create, webhook and lookup; it must not write a simulated PAID state through a public route.
- A release requires explicit Founder approval separate from this controlled-implementation directive.

## 12. Acceptance test matrix

| ID | Scenario | Expected result |
|---|---|---|
| CAT-01 | Approved Studio top-up SKU | Exact amount/credit mapping from Core catalog |
| CAT-02 | Shop Free Forever | Rp0; no provider payment intent |
| CAT-03 | Shop paid tier with pending CFO price | Rejected as not sellable |
| CAT-04 | Client sends amount/provider/tenant override | Request rejected |
| AUTH-01 | Unauthenticated or non-member principal | 401/403; no intent |
| TEN-01 | Tenant ID spoofed in body/header | Ignored/rejected; canonical identity from auth |
| IDEM-01 | Same idempotency key and fingerprint | Existing intent returned |
| IDEM-02 | Same key, different fingerprint | 409 |
| DB-01 | PostgreSQL unavailable | 503; no memory fallback |
| CRED-01 | Production profile in non-production | Fail closed |
| CRED-02 | Wrong provider account or secret unavailable | Fail closed |
| WH-01 | Invalid callback token/signature | 401; no settlement |
| WH-02 | Wrong amount/currency/tenant/reference | 409; no settlement |
| WH-03 | Duplicate provider event | Idempotent acknowledgement; one ledger entry |
| SET-01 | Verified settled callback | Shared intent settled + immutable ledger + outbox event atomically |
| ENT-01 | Valid activation event | One entitlement activation for source ledger |
| REC-01 | Provider unknown outcome | Same intent reconciled; no second invoice |
| REC-02 | Late settlement after expiry | Quarantined; no automatic activation |

## 13. Implementation status at this revision

This contract is the implementation target. The current branch contains:
- app/schemas/saas_billing.py — typed request/quote contract;
- app/services/saas_billing_catalog.py — Founder-approved Shop/Studio Staging catalog map, deterministic quote calculation, default Studio Annual checkout marker, campaign marker, and conservative bundle guard;
- app/services/saas_billing_auth.py — product-scoped server-to-server HMAC boundary with signed idempotency input;
- migrations/038_core_saas_billing_contract_v1.sql — draft Core-owned purchase, webhook, ledger and entitlement-event tables;
- tests/test_saas_billing_catalog.py and tests/test_saas_billing_auth.py — automated cases authored, not yet executed.

Still outstanding: registered HTTP routes, durable purchase/payment-intent orchestration with effective-tenant-entitlement checks, sandbox Xendit adapter and platform credential-profile resolution, verified webhook settlement transaction, shared outbox dispatch/entitlement consumer, recovery worker, integration tests, local build/typecheck, and source-SHA Preview evidence. Product must ratify the exact entitlements included in each Shop tier and the channel/agent/quota/provider definitions for SmartChatbox before the bundle guard can be relaxed. The draft migration has only been applied to disposable CI for verification and has not been applied to Staging or Production. SAAS_BILLING_LIVE_ENABLED remains false. No claim of build/typecheck/test PASS is made by this document.
