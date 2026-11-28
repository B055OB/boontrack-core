# Core SaaS Billing Contract v1

**Status:** Controlled implementation draft — non-production only  
**Owner:** BoonTrack Core Engineering  
**Consumers:** BoonTrack Shop and BoonTrack Studio  
**Baseline:** Core main at 2bed59f99050001ad6bf0b35881f381f5c9e91d5  
**Contract version:** saas-billing.v1  
**Live billing:** DISABLED

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

### 3.1 Current price decisions

Studio Pricing v3 has Founder-ratified top-up mappings:
- STUDIO_TOPUP_KETENGAN_50: 50 credits, Rp25,000.
- STUDIO_TOPUP_STARTER_200: 200 credits, Rp89,000.
- STUDIO_TOPUP_KREATOR_500: 500 credits, Rp199,000.
- STUDIO_TOPUP_PRO_AGENCY_1000: 1,000 credits, Rp349,000.
- Credit validity: 12 months.
- Usage metering: Naskah 10 credits; Image Carousel (5 slides) 25 credits; Video 50 credits. These are usage tariffs, not payment products.

Shop FREE_FOREVER is Rp0 and does not create a payment intent. Shop Growth, Ads Performance, Team Scale and paid add-on pricing remain non-sellable until the corresponding CFO price decision is approved and recorded in the Core catalog. Proposed prices are not treated as approvals.

The tax display and tax calculation policy must be explicit in the catalog before a live checkout can be enabled. Until ratified, the quote may report the approved catalog price but must carry TAX_POLICY_PENDING and must not be used to create a live provider invoice.

## 4. API contract

The following is the target server-to-server contract. Paths are versioned and owned by Core.

- GET /api/v1/saas-billing/catalog?product=SHOP|STUDIO
- POST /api/v1/saas-billing/quotes
- POST /api/v1/saas-billing/payment-intents
- GET /api/v1/saas-billing/payment-intents/{intent_id}
- POST /api/v1/saas-billing/webhooks/xendit
- POST /api/v1/saas-billing/reconciliation/{intent_id}

Mutation routes require authenticated product server identity plus verified principal/tenant authorization, or an approved Core operator identity for recovery. Provider callbacks use a separate provider authentication path and cannot use merchant session authentication.

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

## 7. Webhook verification and atomic settlement

The provider callback is not proof of payment until Core verifies it.

For each callback Core must:
1. Parse provider event identifiers and resolve the expected Core purchase and payment intent from the stored provider reference.
2. Resolve the stored platform sandbox credential profile and its active/grace verification secret.
3. Verify callback token/signature in constant time; verify provider account ID, provider invoice/reference, currency, amount, tenant binding, product, SKU and expected status against authoritative persisted records.
4. Reject malformed, mismatched, replayed, expired, or unsupported events. Late settlement is quarantined, not silently activated.
5. In one DB transaction, insert a provider-event idempotency record, lock the purchase and payment intent, transition the shared Core payment intent, append the immutable SaaS billing ledger entry, and enqueue a SaaS entitlement activation event in Core's outbox.
6. Commit once. Duplicate delivery returns an idempotent acknowledgement and creates no second ledger entry or entitlement event.

The existing TrustedSettlementVerificationBoundary is the cryptographic verification primitive. The existing order-specific commit_verified_settlement_transaction must not be called for SaaS purchases unless the authoritative object is a valid order under that API's contract. SaaS settlement requires a SaaS-specific repository transaction around the shared Core payment intent and outbox.

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
- app/services/saas_billing_catalog.py — Shop/Studio catalog map and deterministic quote calculation;
- app/services/saas_billing_auth.py — product-scoped server-to-server HMAC boundary with signed idempotency input;
- migrations/038_core_saas_billing_contract_v1.sql — draft Core-owned purchase, webhook, ledger and entitlement-event tables;
- tests/test_saas_billing_catalog.py and tests/test_saas_billing_auth.py — automated cases authored, not yet executed.

Still outstanding: registered HTTP routes, durable purchase/payment-intent orchestration, sandbox Xendit adapter and platform credential-profile resolution, verified webhook settlement transaction, shared outbox dispatch/entitlement consumer, recovery worker, integration tests, local build/typecheck, and source-SHA Preview evidence. The draft migration has not been applied to any database. SAAS_BILLING_LIVE_ENABLED remains false. No claim of build/typecheck/test PASS is made by this document.
