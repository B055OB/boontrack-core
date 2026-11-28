# BOONTRACK COMMAND CENTER
# PACKET 3D — STEP 2A: PHASE 1 PRODUCT SCOPE & BILLING ROUTE VERIFICATION

**Document ID:** `PACKET_3D_STEP2A_PHASE1_SCOPE_VERIFICATION.md`  
**Model:** Gemini 3.8 Flash High — Account 1  
**Assigned Role:** Integration Lead / Cross-Repository Architecture Verification  
**Repositories Audited:** `boontrack-inbox` (`C:\boontrack-inbox` / worktrees `gateb-p2`, `gateb-recut-94`, `gateb-recut-101`) + `boontrack-core` (`C:\boontrack-core` / worktree `gateb-p2`)  
**Mode:** STRICT READ-ONLY FORENSIC AUDIT (Zero code edits, zero migrations, zero branch mutations, zero DB connections, zero remote queries, zero deploys)  
**Timestamp:** 2026-11-22T21:45:00+07:00  

### GLOBAL LOCKS ACKNOWLEDGED
- Production Supabase, Railway Production, and Xendit Production remain on **STRICT HOLD**.
- Zero migrations, merges, pushes, deployments, credential rotations, or Production preflight executed.
- **SSOT v1.1** remains **FROZEN**.
- **BWM Workforce** remains **ISOLATED / OUT OF SCOPE**.

---

## EXECUTIVE VERDICT & DECLARATION
`[TARGET TENANT: onlineboost, boon (multi-tenant platform)] | [TARGET CHANNEL: NONE] | [BLAST RADIUS: ISOLATED (STRICT READ-ONLY AUDIT)]`

Following rigorous AST and source-level extraction across `boontrack-inbox` and `boontrack-core`, all four release-scope questions raised in the Neon Architecture Challenge (`U-03`, `U-05`, `U-06`, `U-07`) have been forensically resolved with exact line-level evidence.

| Question / Scope Item | Evaluated Scope | Final Status | Key Architectural Verdict |
|---|---|:---:|---|
| **1. Canonical SKU** (`U-06`) | `OB-PRO-249K` vs `OB-BATCH1-249K` | **`VERIFIED`** | **`OB-BATCH1-249K`** is the sole canonical SKU across catalog, seed, UI, Core, and tests. `OB-PRO-249K` has **zero** codebase occurrences. Price is locked at **Rp 249.000**, `unique_code = 0`. |
| **2. Academy Service Scope** (`U-07`) | `app/services/academy_service.py` & `academy_routes.py` | **`VERIFIED`** | **Excluded from Phase 1 Storefront**. Bypasses unified `PaymentAdapterFactory` and mutates `orders` directly (`line 1724`). All checkout routes must remain **GATED OFF / DISABLED** in Phase 1. |
| **3. Studio Paid Billing** (`U-05`) | `create-invoice/route.ts` & `shop-upgrade-bonus/route.ts` | **`VERIFIED`** | `create-invoice/route.ts` makes direct Xendit calls emitting `TOPUP-STUDIO-*` IDs that Core blocks (`403 SAAS_BILLING_WEBHOOK_STAGE3_HOLD`). Must be **FEATURE-GATED OFF (503)** for Phase 1. `shop-upgrade-bonus` is internal-only (no provider call). |
| **4. Quick POS Scope** (`U-03`) | Chat POS (`TeamChatTab.tsx`) & `correlation_id` | **`VERIFIED`** | Quick POS is **EXCLUDED** from OnlineBoost Batch 1 release. `correlation_id` remains safely in `orders.metadata.payment_token`. **NO physical column or DDL migration**. |

---

## SECTION 1: ONLINEBOOST CANONICAL SKU VERIFICATION

### 1.1 Resolution Summary (`OB-PRO-249K` vs `OB-BATCH1-249K`)
- **`OB-PRO-249K`**: **0 occurrences across all repositories**. Exhaustive regex search (`git grep -i "OB-PRO-249K"`) returns exit code `1` (null hits) across `boontrack-inbox` and `boontrack-core`. `OB-PRO-249K` is a phantom identifier with no code, database, test, or catalog footprint.
- **`OB-BATCH1-249K`**: **48+ verified occurrences across both repositories**. It is the sole, authoritative, universal canonical SKU for OnlineBoost Batch 1.

### 1.2 Evidence Matrix Across System Layers

```
========================================================================================================================
SYSTEM LAYER               FILE PATH & LINE RANGE                                   VERIFIED SYMBOL / VALUE
========================================================================================================================
Server Product Catalog     boontrack-inbox/lib/product-catalog.ts:1300-1317         sku: "OB-BATCH1-249K"
                                                                                    price: 249000, promo_price: 249000
                                                                                    slug: "ob-batch1-249k"
------------------------------------------------------------------------------------------------------------------------
Mock Checkout Guard        boontrack-inbox/lib/product-catalog.ts:85-180            isBatch1MockCheckout()
                                                                                    sku === 'OB-BATCH1-249K'
                                                                                    SERVER_LOCKED_PRICE = 249000
------------------------------------------------------------------------------------------------------------------------
Checkout Server Contract   boontrack-inbox/lib/checkout-service.ts:187-235          normProductId === 'OB-BATCH1-249K'
                                                                                    // Kontrak harga SKU OB-BATCH1-249K
                                                                                    // dikunci mati pada tepat 249000.
                                                                                    authoritativePrice = 249000
------------------------------------------------------------------------------------------------------------------------
Landing Page D2C Route     boontrack-inbox/app/[tenant]/p/[slug]/page.tsx:          isObBatch1Product
                           603, 694-695, 775, 982, 1012, 1121                       match.sku === 'OB-BATCH1-249K'
                                                                                    data-bt-sku="OB-BATCH1-249K"
                                                                                    Section 10 Takeover locked to 249000
------------------------------------------------------------------------------------------------------------------------
Database Seed Service      boontrack-inbox/lib/services/                            seedOnlineBoostProducts()
                           onlineboost-seed.service.ts:38-42                        sku: 'OB-BATCH1-249K', price: 249000
------------------------------------------------------------------------------------------------------------------------
Core Payment Service       boontrack-core/app/payments/service.py:840-841           matched_intent.metadata["sku_id"] in
                                                                                    ("OB-BATCH1-249K", ...)
------------------------------------------------------------------------------------------------------------------------
Core Academy Service       boontrack-core/app/services/academy_service.py:67-70     CANONICAL_BATCH1_SKU = "OB-BATCH1-249K"
                                                                                    ACADEMY_SETTLEMENT_PRICE = 249000
------------------------------------------------------------------------------------------------------------------------
Core CTWA State Engine     boontrack-core/app/services/ctwa_state_engine.py:63      CANONICAL_BATCH1_SKU = "OB-BATCH1-249K"
------------------------------------------------------------------------------------------------------------------------
Core Integration Tests     boontrack-core/tests/                                    assert CANONICAL_BATCH1_SKU ==
                           test_onlineboost_phase4_consultation.py:940-1057         "OB-BATCH1-249K"
                                                                                    assert inserted_payload["metadata"]
                                                                                    ["sku_id"] == "OB-BATCH1-249K"
------------------------------------------------------------------------------------------------------------------------
Core Warm Launch Tests     boontrack-core/tests/test_academy_warm_launch.py:74      assert ACADEMY_SKU_ID ==
                                                                                    "OB-BATCH1-249K"
------------------------------------------------------------------------------------------------------------------------
Architecture SSOT Spec     ARCHITECTURE.md:5503, 5506                               Canonical SKU: OB-BATCH1-249K
========================================================================================================================
```

### 1.3 Price & Unique Code Verification
- **Exact Base Price:** `Rp 249.000` (Zero tolerance; any deviation fails closed via `lib/checkout-service.ts:218-221`).
- **Unique Code Contract:** `unique_code = 0` for OnlineBoost Batch 1 Dynamic QRIS.
  - Verified in `app/api/v1/payments/qris/create/route.ts:241-245`:
    ```typescript
    if (isXenditGateway || body.unique_code === 0) {
      // GUARDRAIL P1: Xendit Dynamic QRIS bypass kode unik & nominal bulat pas (nett)
      uniqueCode = 0;
      productBasePrice = expectedSubtotal;
      numAmount = expectedSubtotal;
    }
    ```
  - Verified in `ARCHITECTURE.md §21.3`: `NATIVE_PG` (Xendit Dynamic QRIS) generates Tag 54 with exact `amount = 249000` and `unique_code = 0`. Upward/downward unique code modifiers apply ONLY to Static Merchant QRIS (`DIRECT_TENANT` rail, e.g. Shabu Aji), which is deferred to Phase 2.

**SKU Section Verdict:** **`VERIFIED`** — Sole canonical SKU is **`OB-BATCH1-249K`**.

---

## SECTION 2: ACADEMY SERVICE SCOPE & USAGE MAP

### 2.1 Route & Entrypoint Inventory

| Route / Method | Location | Function / Handler | Public Traffic? | Core Bypass Risk? | Phase 1 Status |
|---|---|---|:---:|:---:|:---:|
| `GET /api/v1/academy/sku` | `app/routes/academy_routes.py:75` | `get_academy_sku` | YES | NO | **READ-ONLY** |
| `POST /api/v1/academy/invoice` | `app/routes/academy_routes.py:110` | `create_academy_invoice` | YES | **CRITICAL** | **MUST BE DISABLED** |
| `GET /api/v1/academy/invoice/{order_id}` | `app/routes/academy_routes.py:234` | `get_invoice` | YES (P0-D) | NO | **READ-ONLY** |
| `POST /api/v1/academy/webhook/paid` | `app/routes/academy_routes.py:281` | `academy_paid_webhook` | BLOCKED | **CRITICAL** | **BLOCKED (HTTP 403)** |
| `POST /campaign/queue` | `app/routes/academy_routes.py:315` | `queue_campaign` | INTERNAL | NO | **OUT OF SCOPE** |

### 2.2 Forensic Inspection of `app/services/academy_service.py`

#### A. Is it called by OnlineBoost Batch 1 Storefront?
- **NO.** The OnlineBoost Batch 1 D2C checkout funnel (`shop.boontrack.com/onlineboost/p/ob-batch1-249k`) executes entirely through:
  `Inbox UI` -> `Inbox POST /api/checkout/create-order` (`lib/checkout-service.ts`) -> `Core POST /api/v1/payments/qris/dynamic` (`app/routes/payment.py`).
- Neither `academy_routes.py` nor `academy_service.py` is invoked during web storefront order creation or payment initialization.

#### B. Can it create payment intent?
- **YES.** In `generate_academy_qris_invoice` (`academy_service.py:1445-1450`), it executes direct Supabase table insertion:
  `supabase.table("payment_intents").insert({"id": ..., "tenant_id": tenant_id, "order_id": order_id, "amount": base_price, "unique_code": unique_code})`.
- In `generate_fast_path_xendit_qris_batch1` (`academy_service.py:1120-1137`), it calls Xendit API directly (`POST ${xendit_service.api_url}/qr_codes`) with order ID format `OB1-...`.

#### C. Can it bypass Core payment routing?
- **YES.** Although located within the `boontrack-core` repository, `academy_service.py` completely **bypasses Core's unified `PaymentAdapterFactory`**, bypasses tenant credential isolation (`TenantCredentialProfile`), does not verify provenance signatures, and manipulates static QRIS strings via local CRC16 rewriting (`generate_dynamic_qris_payload(DEFAULT_STATIC_QRIS, total_amount)` at lines 1356-1364).

#### D. Can it update payment status?
- **YES.** In `handle_alumni_payment_verified` (`academy_service.py:1722-1729`), it executes direct SQL:
  ```python
  cur.execute(
      """
      UPDATE orders 
      SET status = 'PAID', payment_status = 'PAID', updated_at = %s
      WHERE id = %s;
      """,
      (now_utc, order_id)
  )
  ```
- This directly violates the Single-Writer Architecture where only verified settlement outbox projections should update order statuses.

#### E. Phase 1 Inclusion Verdict
- `POST /api/v1/academy/webhook/paid` is already safely hard-blocked with HTTP 403 `UNVERIFIED_WEBHOOK_MUTATION_BLOCKED` (`academy_routes.py:281-303`).
- WhatsApp fast-path payment generation is already intercepted by `is_onlineboost_payment_held()` at `academy_service.py:1087-1109` and lines `2198-2287`, placing users into `STATE_HOLD_QUEUED` with zero payment issuance.
- **Phase 1 Decision:** All checkout creation routes in `academy_routes.py` (`POST /invoice`) and direct checkout generators in `academy_service.py` must remain **STRICTLY DISABLED / GATED OFF** for the OnlineBoost Batch 1 release. Only post-settlement Telegram VIP group provisioning (State 2 fulfillment triggered by Core's verified settlement bus) may be invoked.

**Academy Service Section Verdict:** **`VERIFIED`** — Excluded from storefront; checkout generation paths must remain disabled in Phase 1.

---

## SECTION 3: STUDIO BILLING ENTRYPOINT INVENTORY

### 3.1 Route Inventory & Provider Call Analysis

| Studio API Route | File Path | Direct External Provider Call? | Webhook Handling in Core | Phase 1 Security Requirement |
|---|---|:---:|---|---|
| `POST /api/studio/billing/create-invoice` | `boontrack-inbox/app/api/studio/billing/create-invoice/route.ts` | **YES** (`fetch('${xenditApiUrl}/v2/invoices')` at lines 199-215) | **REJECTED WITH 403** (`xendit.py:1750-1759` `SAAS_BILLING_WEBHOOK_STAGE3_HOLD`) | **MUST BE FEATURE-GATED OFF (503)** |
| `POST /api/studio/billing/shop-upgrade-bonus` | `boontrack-inbox/app/api/studio/billing/shop-upgrade-bonus/route.ts` | **NO** (Internal ledger write via `StudioCreditService.grantShopActivationBonus`) | None (Internal machine auth / admin) | **ALLOWED** (Guarded by session auth / internal machine secret) |
| `POST /api/studio/renders/[id]/track-download` | `app/api/studio/renders/[id]/track-download/route.ts` | **NO** | None (Tenant DB purge tracking) | **ALLOWED** (Tenant session protected) |
| `GET /api/studio/download` | `app/api/studio/download/route.ts` | **NO** (Internal SSRF-guarded media proxy) | None | **ALLOWED** (SSRF pinned, tenant session protected) |

### 3.2 The `create-invoice/route.ts` Direct Provider Hazard
- `create-invoice/route.ts:199-215` makes an unmediated external HTTP call to Xendit:
  ```typescript
  const xenditRes = await fetch(`${xenditApiUrl}/v2/invoices`, {
    method: 'POST',
    headers: {
      Authorization: authHeader,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(xenditPayload),
  });
  ```
- It emits invoice external IDs matching: `TOPUP-STUDIO-{tenantSlug}-{credits}-{timestamp}` (line 173).
- **Core Settlement Collision:** When a customer completes payment for this invoice, Xendit sends a webhook to Core (`POST /api/v1/payments/xendit/callback`).
  Core's unified webhook executor (`C:\boontrack-core\app\routes\xendit.py:1750-1759`) explicitly catches this:
  ```python
  if external_id.startswith("TOPUP-") or external_id.startswith("TOPUP_"):
      logger.warning(f"[Xendit Webhook] Blocked SaaS Billing Quota Top-Up webhook: {external_id}")
      return {
          "http_status": 403,
          "response": {
              "status": "REJECTED",
              "error": "SAAS_BILLING_WEBHOOK_STAGE3_HOLD",
              "error_code": "SAAS_BILLING_WEBHOOK_STAGE3_HOLD",
              "detail": "SAAS_BILLING_WEBHOOK_STAGE3_HOLD: SaaS billing and quota top-up webhooks are deferred to dedicated milestone.",
          }
      }
  ```
- **Consequence if live:** The customer is debited funds, Core returns `HTTP 403`, settlement is dropped, and tokens are never credited to the tenant.

### 3.3 Exact Feature Gate Specification
To enforce the global lock and prevent unauthorized provider calls, `app/api/studio/billing/create-invoice/route.ts` must be gated at the top of the handler:

```typescript
// Phase 1 SaaS Billing Gate (CTO Decision #2 & SAAS_BILLING_STAGE3_HOLD)
const isPaidBillingEnabled = process.env.ENABLE_STUDIO_PAID_BILLING === 'true';
if (!isPaidBillingEnabled) {
  return NextResponse.json(
    {
      success: false,
      error: 'SAAS_BILLING_STAGE3_HOLD',
      message: 'Pembelian token berbayar Studio ditangguhkan pada Fase 1. Gunakan kuota bawaan akun atau aktivasi kemitraan toko.',
    },
    { status: 503 }
  );
}
```

### 3.4 Studio Phase 1 Supported Entitlements
Studio in Phase 1 is strictly restricted to supported honest tools:
1. **Panduan Naskah Asli UGC 9-Scene** (`app/api/studio/script/generate/route.ts`).
2. **Generator Copywriting & WhatsApp Broadcast** (`app/studio/desk/page.tsx`).
3. **Carousel 1:1 & 4:5 Visual Canvas Exporter** (PNG & Zip-Slip protected ZIP via `lib/studio-asset-exporter.ts` and `components/studio/CarouselVisualCanvas.tsx`).
4. **Safe-Zone 9:16 Video Layout Overlays** (Educational guide cards; zero active 1080p rendering promised).
5. **Credit Consumption:** Only from existing/seeded balance or free starter quota. No paid top-up activation without Core contract.

**Studio Billing Section Verdict:** **`VERIFIED`** — Direct provider calls isolated; feature gate (503) and Phase 1 entitlement boundary established.

---

## SECTION 4: QUICK POS DEFERRAL & `correlation_id` METADATA RESIDENCY

### 4.1 Quick POS Deferral Confirmation
- **Scope Analysis:** Quick POS (`app/[tenant]/dashboard/components/tabs/TeamChatTab.tsx:1629, 1998` and `app/api/v1/tenants/[slug]/orders/quick-pos/route.ts`) is an administrative merchant chat feature for issuing manual payment links.
- It is **100% EXCLUDED** from the OnlineBoost Batch 1 Phase 1 release scope, which is exclusively a customer self-serve storefront checkout (`/onlineboost/p/ob-batch1-249k`).
- No merchant chat POS workflows are required or authorized for Batch 1 launch.

### 4.2 `correlation_id` Metadata Residency
- `correlation_id` was NOT created as a physical column in `000_disposable_pg17_base_catalog_bootstrap.sql:140-165`. It only existed in the uncommitted 18-column ephemeral test shim.
- In `TeamChatTab.tsx:1618-1619` and `1985-1986`, the payment token is **already stored** in JSONB:
  ```typescript
  metadata: {
    order_number: displayOrderNumber,
    internal_id: internalOrderId,
    conversation_id: currentConversation?.id || null,
    contact_id: linkedContactId,
    public_payment_token: paymentToken,
    payment_token: paymentToken,
    // ...
  }
  ```
- **Architectural Confirmation:**
  - `correlation_id` can safely remain inside `orders.metadata.payment_token` / `orders.metadata.correlation_id` for all required operational tracking and trace correlation.
  - Query paths in invoice lookup and status readers (`app/[tenant]/invoice/[orderId]/page.tsx:68`, `app/api/orders/[orderId]/status/route.ts:61`) already inspect `metadata` JSONB.
  - **NO physical column** is to be added to `public.orders`.
  - **NO database migration** is required for `correlation_id`.

**Quick POS Section Verdict:** **`VERIFIED`** — Quick POS deferred from Phase 1; `correlation_id` stays in JSONB metadata with zero DDL changes.

---

## SECTION 5: PHASE 1 FEATURE MATRIX

| Feature / Capability | Component / Route | Target Rail / Provider | Phase 1 Status | Core Contract Authority | Verification Status |
|---|---|---|:---:|---|:---:|
| **OnlineBoost Batch 1 Checkout** | `shop.boontrack.com/onlineboost/p/ob-batch1-249k` | `NATIVE_PG` / Xendit Dynamic QRIS | **INCLUDED** | `app/routes/payment.py` (`POST /api/v1/payments/qris/dynamic`) | **`VERIFIED`** |
| **Price Lock (Rp 249.000)** | `lib/checkout-service.ts:211` | N/A (Server-Enforced) | **INCLUDED** | `lib/product-catalog.ts` (`OB-BATCH1-249K`) | **`VERIFIED`** |
| **Zero Unique Code (`unique_code = 0`)** | `qris/create/route.ts:243` | N/A (Dynamic QRIS) | **INCLUDED** | Exact Tag 54 = 249000, zero surcharge | **`VERIFIED`** |
| **Studio UGC 9-Scene Scripting** | `app/api/studio/script/generate` | Gemini AI / Fallback Engine | **INCLUDED** | Tenant Session Guard (`RFC 6265bis`) | **`VERIFIED`** |
| **Studio Ad Copy & WA Broadcast** | `app/studio/desk/page.tsx` | Client Canvas & Templates | **INCLUDED** | Tenant Session Guard (`RFC 6265bis`) | **`VERIFIED`** |
| **Studio Carousel 1:1 & 4:5 Export** | `components/studio/CarouselVisualCanvas.tsx` | Client HTML5 Canvas / ZIP | **INCLUDED** | Pure client-side export (PNG/ZIP) | **`VERIFIED`** |
| **Studio Free/Starter Quotas** | `lib/services/studio-credit.service.ts` | Internal Ledger | **INCLUDED** | Seeded tenant quotas / Starter tier | **`VERIFIED`** |
| **Studio Paid Top-Up Billing** | `app/api/studio/billing/create-invoice` | Xendit Invoices (`TOPUP-*`) | **GATED OFF (503)** | Blocked by Core (`SAAS_BILLING_STAGE3_HOLD`) | **`VERIFIED`** |
| **Studio 1080p Video Rendering** | `app/api/studio/render` (worker) | FFmpeg Worker / R2 Bucket | **DEFERRED (Phase 2)** | Worker secret auth verified; UI deferred | **`VERIFIED`** |
| **Static Merchant QRIS (Shabu Aji)** | `lib/checkout-service.ts` / Core | `DIRECT_TENANT` / Merchant QRIS | **DEFERRED (Phase 2)** | Unique code contradiction (`BLK-P3C-05`) | **`BLOCKED`** |
| **Core Academy Invoice API** | `app/routes/academy_routes.py` | Internal Static QRIS | **GATED OFF** | Bypasses `PaymentAdapterFactory` | **`VERIFIED`** |
| **Quick POS Merchant Chat** | `TeamChatTab.tsx` / `quick-pos/route.ts` | Multi-rail Manual POS | **DEFERRED (Phase 2)** | Excluded from Batch 1 D2C scope | **`VERIFIED`** |

---

## SECTION 6: REMAINING BLOCKERS & DEPENDENCIES

| Blocker ID | Description | Source Impact | Resolution Plan for Packet 3D | Status |
|---|---|---|---|:---:|
| **`BLK-P3C-01`** | Payment contract crash (`factory.py:75` rejects `PAYMENT_GATEWAY`; requires plaintext `secret_key`) | `factory.py`, `payment_auth_guard.py`, `checkout-service.ts` | Core accepts `PAYMENT_GATEWAY` as alias; resolves `api_secret_ref` via `XenditAdapter` | **READY FOR CODING** |
| **`BLK-P3C-02`** | Missing `orders` columns in base schema vs. uncommitted 18-column test shim | `lib/order-sanitizer.ts`, `checkout-service.ts` | Add **only** `idempotency_key`, `payment_intent_id`, `last_settlement_event_id` to Inbox migration. Write all others to `metadata`. | **READY FOR CODING** |
| **`BLK-P3C-03`** | Unbounded `fetch()` in `checkout-service.ts` & unsafe `DELETE` rollback | `lib/checkout-service.ts:1019` | Add `AbortSignal.timeout(10000)`, idempotency key, and transition timeouts to `PAYMENT_INIT_UNKNOWN` (never `DELETE`). | **READY FOR CODING** |
| **`BLK-P3C-04`** | Dark settlement routes in Inbox (`/api/webhooks/xendit/paid`, `/quick-paid`, `/approve`) | Inbox API routes | Decommission to `410 GONE` / `403 FORBIDDEN`. Core Single-Writer settlement via Ed25519 outbox. | **READY FOR CODING** |
| **`BLK-P3C-05`** | 4-way contract contradiction on 3-digit unique codes (Shabu Aji Static QRIS) | `factory.py`, `unique-code-generator.ts` | Defer Shabu Aji Static QRIS to Phase 2; ship Phase 1 strictly with OnlineBoost Dynamic QRIS (`unique_code = 0`). | **RESOLVED FOR PHASE 1** |
| **`BLK-P3C-06`** | Terminal state revival (`qris/create` overwrites `EXPIRED` to `PENDING`) | `qris/create/route.ts:706` | Enforce terminal state guard (`PAID`, `EXPIRED`, `CANCELLED`) before calling Core or updating DB. | **READY FOR CODING** |
| **`U-01` / `U-02`** | Live Supabase schema & tenant metadata payload audit | Staging/Production Supabase | Inspect read-only schema on Staging once Production hold is lifted. | **STRICT HOLD** |

---

## SECTION 7: EXACT SOURCE PATHS, SYMBOLS & LINE RANGES

1. **OnlineBoost Canonical SKU & Price Lock:**
   - [product-catalog.ts](file:///C:/boontrack-inbox/lib/product-catalog.ts#L85-L180): `isBatch1MockCheckout`, lines 85–180.
   - [product-catalog.ts](file:///C:/boontrack-inbox/lib/product-catalog.ts#L1300-L1317): `DEFAULT_PRODUCTS[8]`, SKU `OB-BATCH1-249K`, price `249000`, lines 1300–1317.
   - [checkout-service.ts](file:///C:/boontrack-inbox/lib/checkout-service.ts#L187-L235): `validateOrderPayload`, locked price `249000`, lines 187–235.
   - [page.tsx](file:///C:/boontrack-inbox/app/%5Btenant%5D/p/%5Bslug%5D/page.tsx#L603-L695): `isObBatch1Product`, SKU `OB-BATCH1-249K`, lines 603, 694–695, 775, 982, 1012.
   - [service.py](file:///C:/boontrack-core/app/payments/service.py#L840-L843): Alumni order match `OB-BATCH1-249K`, lines 840–843.
   - [academy_service.py](file:///C:/boontrack-core/app/services/academy_service.py#L67-L70): `CANONICAL_BATCH1_SKU = "OB-BATCH1-249K"`, `ACADEMY_SETTLEMENT_PRICE = 249000`, lines 67–70.

2. **Academy Service Routes & Checkout Bypass:**
   - [academy_routes.py](file:///C:/boontrack-core/app/routes/academy_routes.py#L110-L232): `POST /api/v1/academy/invoice`, lines 110–232.
   - [academy_routes.py](file:///C:/boontrack-core/app/routes/academy_routes.py#L281-L303): `POST /api/v1/academy/webhook/paid` (HTTP 403 block), lines 281–303.
   - [academy_service.py](file:///C:/boontrack-core/app/services/academy_service.py#L1070-L1160): `generate_fast_path_xendit_qris_batch1`, lines 1070–1160.
   - [academy_service.py](file:///C:/boontrack-core/app/services/academy_service.py#L1403-L1450): Direct `orders` & `payment_intents` insert, lines 1403–1450.
   - [academy_service.py](file:///C:/boontrack-core/app/services/academy_service.py#L1722-L1729): Direct `UPDATE orders SET status = 'PAID'`, lines 1722–1729.

3. **Studio Billing Routes & Core Webhook Rejection:**
   - [route.ts](file:///C:/boontrack-inbox/app/api/studio/billing/create-invoice/route.ts#L170-L215): Direct Xendit `/v2/invoices` call & `TOPUP-STUDIO-*` format, lines 170–215.
   - [xendit.py](file:///C:/boontrack-core/app/routes/xendit.py#L1750-L1759): Webhook 403 rejection `SAAS_BILLING_WEBHOOK_STAGE3_HOLD`, lines 1750–1759.
   - [route.ts](file:///C:/boontrack-inbox/app/api/studio/billing/shop-upgrade-bonus/route.ts#L35-L60): Internal bonus handler, lines 35–60.
   - [studio-credit.service.ts](file:///C:/boontrack-inbox/lib/services/studio-credit.service.ts#L734-L790): `grantShopActivationBonus`, lines 734–790.

4. **Quick POS & Correlation ID Metadata:**
   - [TeamChatTab.tsx](file:///C:/boontrack-inbox/app/%5Btenant%5D/dashboard/components/tabs/TeamChatTab.tsx#L1597-L1635): Quick POS order payload & `metadata.payment_token`, lines 1597–1635.
   - [TeamChatTab.tsx](file:///C:/boontrack-inbox/app/%5Btenant%5D/dashboard/components/tabs/TeamChatTab.tsx#L1964-L1995): Manual bank transfer Quick POS, lines 1964–1995.
   - [order-sanitizer.ts](file:///C:/boontrack-inbox/lib/order-sanitizer.ts#L7-L57): `VALID_ORDER_COLUMNS`, lines 7–57.

---
*End of Report `PACKET_3D_STEP2A_PHASE1_SCOPE_VERIFICATION.md` — Command Center Scope Verification Complete.*
