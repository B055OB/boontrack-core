# BOONTRACK CORE — DURABLE CHECKOUT SESSION ARCHITECTURE (WORKSTREAM B)

**Target Repository:** `C:\boontrack-core`  
**Baseline Commit SHA:** `05ac51c907dd46d8213d29442edd1a54145a22d9`  
**Scope:** Architectural Assessment & Target Design Proposal (**Zero Code / Schema Implementation in This Phase**)  
**Status:** Prepared for CTO Review  

---

## Epistemic Labeling Standard Used in This Document

- **`VERIFIED FACT`** — Directly observed in source code, SQL DDL/migrations, or tests at `05ac51c907dd46d8213d29442edd1a54145a22d9`.
- **`SOURCE-BASED INFERENCE`** — Logical deduction derived strictly from `VERIFIED FACT` evidence in `05ac51c`.
- **`UNVERIFIED RUNTIME FACT`** — Live Railway / production PostgreSQL / Supabase state (such as live `public.orders` constraints, RLS enforcement role, or connection pooling) not observable in read-only repository inspection.
- **`RECOMMENDATION`** — Proposed architectural design, schema contract, or engineering change for future CTO-authorized implementation.

---

## 1. Current Root Architectural Gaps in `05ac51c`

1. **`VERIFIED FACT` — Split Persistence Order & Ephemeral Session Authority:**  
   In [`create_academy_invoice`](file:///c:/boontrack-core/app/routes/academy_routes.py#L158-L209):
   - Line `158` calls `generate_academy_qris_invoice(...)`, which inserts into process-local RAM (`_ACADEMY_INVOICES[order_id]`, `_ACADEMY_INVOICES_BY_AMOUNT[total_amount]` at [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1392-L1393)), then inserts a partial row into PostgreSQL `orders` (`L1401-L1420`) and best-effort into Supabase `payment_intents` (`L1442-L1459`).
   - Only **after** DB writes have already finished does [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L203-L208) call `_CHECKOUT_TOKEN_MANAGER.issue_token(...)` and attach `canonical_tenant_id` and `checkout_session` (`jti`, `iat`, `exp`, `revoked`, `order_id`, `canonical_tenant_id`, `cs_key_id`) **exclusively to the RAM dictionary**.
2. **`VERIFIED FACT` — Non-Durable Read & Amount-Allocation Paths:**  
   - [`get_academy_invoice(order_id)`](file:///c:/boontrack-core/app/services/academy_service.py#L1464-L1466) reads strictly `_ACADEMY_INVOICES.get(order_id)`.
   - Unique-code collision avoidance ([`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1362-L1373)) scans only in-memory `_ACADEMY_INVOICES`.
   - Public SKU (`OB-BATCH1-249K`) logs `orders` DB insert errors at [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1430) **without failing invoice creation** (`is_penny_test` only raises at `L1431-L1439`).
3. **`VERIFIED FACT` — Incomplete Durable Columns & Missing Tenant FK Normalization:**  
   - The `orders` insert ([`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1401-L1420)) writes `tenant_slug`, omitting `orders.tenant_id`, `base_amount`, `unique_code`, `qr_string`, `qr_image_url`, `expires_at`, and `checkout_session` metadata (`metadata JSONB` column exists on `orders` per [`database.py`](file:///c:/boontrack-core/app/core/database.py#L490) and [`033a`](file:///c:/boontrack-core/migrations/033a_stage3_payment_settlement_expand_phase.sql#L46), but is left at `{}`).
   - [`settle_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1662-L1780) falls back to `SELECT product_id, gross_amount, tenant_slug FROM orders` only for amount/SKU verification, skips RAM expiry enforcement (`L1604`) if `invoice` is not in local RAM, writes `payment_events` without `tenant_id` (`L1700`), and updates `invoice["status"] = "PAID"` only inside local process RAM (`L1775-L1778`).
4. **`UNVERIFIED RUNTIME FACT` — Live Production Schema Drift Risk:**  
   Between [`migrations/031`](file:///c:/boontrack-core/migrations/031_b2_remediation_suite.sql#L236, L415), [`migrations/033a`](file:///c:/boontrack-core/migrations/033a_stage3_payment_settlement_expand_phase.sql#L17-L18), and [`staging_baseline_generated.sql`](file:///c:/boontrack-core/scripts/staging_baseline_generated.sql#L48-L97), whether production `public.orders.tenant_id` is currently `NOT NULL` or nullable, and whether the DB role used by `get_db_connection()` bypasses RLS or executes under `FORCE ROW LEVEL SECURITY`, could not be checked live in read-only mode.

---

## 2. Database Technology Evaluation: PostgreSQL vs Redis

### 2.1 Why PostgreSQL Is the Correct Primary Source of Truth

- **`VERIFIED FACT` — Already Required & Transactionally Authoritative:**  
  [`orders`](file:///c:/boontrack-core/scripts/init_test_postgres_schema.py#L198-L219), [`payment_events`](file:///c:/boontrack-core/app/core/database.py#L531-L560), [`financial_ledger`](file:///c:/boontrack-core/app/core/database.py#L620), and `payment_intents` ([`migrations/005`](file:///c:/boontrack-core/migrations/005_create_core_payment_tables.sql#L5-L22)) all reside in PostgreSQL / Supabase.
- **`VERIFIED FACT` — Redis Is Optional & Unbacked:**  
  `REDIS_URL` appears in [`docker-compose.prod.yml`](file:///c:/boontrack-core/docker-compose.prod.yml#L31) as `${REDIS_URL:-}` (empty default); no Redis usage exists in Academy checkout (`academy_routes.py` / `academy_service.py`), and presence/capacity of Redis in Railway Production is an `UNVERIFIED RUNTIME FACT`.
- **`SOURCE-BASED INFERENCE` — Why Redis Should NOT Be Introduced Here:**
  1. **Eliminates Dual-Write Split-Brain:** A checkout invoice creation or payment settlement (`orders` + `payment_events` + `financial_ledger`) happens inside a PostgreSQL transaction. Putting authoritative checkout session state (`jti`, `revoked`, `exp`, `status`) in Redis creates a crash window where PostgreSQL commits `orders` (or `PAID`) while Redis fails, evicts, or diverges—causing spurious `HTTP 404` for paying customers.
  2. **Avoids Ephemeral Eviction Hazards:** Redis under `allkeys-lru` / container memory pressure can evict active `PENDING` sessions before `exp`, silently invalidating valid tokens (violating restart/rolling-deploy survivability).
  3. **Minimal Read/Write Load Profile:** Each Academy checkout session has a `15`-minute TTL (`ACADEMY_INVOICE_TTL_MINUTES = 15`). Even at thousands of concurrent checkouts polling every `3–5s`, a primary-key indexed PostgreSQL read (`order_id`) executes in sub-millisecond DB time cleanly with standard connection pooling.
  4. **Zero New Infrastructure, Secrets, or Failure Modes:** No new Railway Redis add-on, TLS credential management, network partition surface, or startup gate.

### 2.2 Explicit Trigger Conditions That Would Justify Redis Later

- **`RECOMMENDATION`:** Keep **Redis OUT** of `boontrack-core` checkout session design unless **all three** future criteria are empirically observed:
  1. PostgreSQL read IOPS / connection saturation directly caused by `GET /api/v1/academy/invoice/{order_id}` exceeds pooled DB capacity (e.g., sustained polling traffic `> 500–1,000 req/s` after connection pooling & primary-key indexing are in place).
  2. Even then, Redis acts strictly as a **short-TTL write-through cache and rate limiter** (fail-open to PostgreSQL SSoT on cache miss; **never** sole authority for `jti`, `revoked`, or `status`), with explicit invalidation on cancellation/revocation/settlement.

---

## 3. Target Durable Checkout Architecture (`RECOMMENDATION`)

### 3.1 Authoritative Persistence Model (`public.checkout_sessions` + `public.orders`)

**Design Choice (`RECOMMENDATION`):** Persist immutable QRIS invoice details + checkout session security state in PostgreSQL within **one ACID transaction** *before* returning the token/cookie to the buyer. Specifically:

1. **Normalize Durable Order Record (`public.orders`) & QRIS Snapshot:**  
   - Fix [`generate_academy_qris_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1401-L1420) so `orders` always stores valid canonical `tenant_id` **and** `tenant_slug` (ensuring `NOT NULL` and RLS policy compatibility in [`init_test_postgres_schema.py`](file:///c:/boontrack-core/scripts/init_test_postgres_schema.py#L222-L232)), `sku_id`, `amount` / `base_amount`, `unique_code`, `total_amount` / `gross_amount`, QRIS payload (`qr_string`, `qr_image_url`), and `expires_at` (stored either in additive columns or structured `orders.metadata` + dedicated `public.checkout_sessions` columns).
   - Remove silent error swallowing (`L1430`) on `POST /api/v1/academy/invoice`: **all** SKUs (both `OB-BATCH1-249K` and `TEST-PENNY-1500`) must fail closed (`HTTP 500` or `503`) if PostgreSQL persistence fails, rather than returning a non-durable RAM-only token.

2. **Dedicated `public.checkout_sessions` Table (Canonical Session Authority):**  
   While `orders.metadata` (`JSONB`) exists at `05ac51c`, keeping cryptographic session binding in a narrow, indexed relational table `public.checkout_sessions` keyed by `order_id` provides foreign-key integrity, strict column constraints, fast indexed lookups, unambiguous token revocation/rotation auditability, and clean retention pruning without mutating immutable financial ledger columns:

   ```sql
   -- RECOMMENDATION ONLY (Design Proposal — NOT Applied)
   CREATE TABLE IF NOT EXISTS public.checkout_sessions (
       order_id            TEXT PRIMARY KEY REFERENCES public.orders(id) ON DELETE CASCADE,
       canonical_tenant_id VARCHAR(100) NOT NULL,
       jti                 VARCHAR(64) NOT NULL UNIQUE,
       cs_key_id           VARCHAR(128) NOT NULL,
       iat_epoch           BIGINT NOT NULL,
       exp_epoch           BIGINT NOT NULL,
       expires_at          TIMESTAMPTZ NOT NULL,
       revoked             BOOLEAN NOT NULL DEFAULT FALSE,
       revoked_at          TIMESTAMPTZ,
       revocation_reason   VARCHAR(128),
       invoice_snapshot    JSONB NOT NULL, -- base_amount, unique_code, total_amount, qr_string, qr_image_url, ttl_minutes, currency
       created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
   );

   CREATE INDEX IF NOT EXISTS idx_checkout_sessions_exp
       ON public.checkout_sessions (expires_at);
   CREATE INDEX IF NOT EXISTS idx_checkout_sessions_tenant_order
       ON public.checkout_sessions (canonical_tenant_id, order_id);
   ```

   **Bound Attributes Guarantee:** Every required binding exists transactionally outside RAM:
   - `order_id` (`invoice_id`) — `PK`, FK → `orders(id)`
   - `canonical_tenant_id` — normalized lowercase canonical tenant identifier matching HMAC payload `cs:v1:{cs_key_id}:{iat}:{exp}:{jti}:{order_id}:{canonical_tenant_id}` ([`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1444))
   - `cs_key_id` — key ID from `CHECKOUT_SESSION_HMAC_KEYRING_JSON` used at issuance
   - `jti` — unique per-session token ID (`secrets.token_hex(16)`)
   - `iat_epoch` / `exp_epoch` & `expires_at` — issue/expiry timestamps (`TTL = 15m`, bounded `[60, 86400]`)
   - `revoked` + `orders.status` (`PENDING`, `PAID`, `CANCELLED`, `REVOKED`, `EXPIRED`) — durable revocation & settlement state.

3. **Multi-Worker Safe Unique-Code Allocation (`unique_code` 100–999):**  
   - **`VERIFIED FACT`:** Current [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1362-L1373) checks active `total_amount` occupancy only in local RAM.
   - **`RECOMMENDATION`:** Query active `PENDING` Academy orders in PostgreSQL (`expires_at > NOW()`) or use a PostgreSQL advisory lock / partial unique index `(total_amount) WHERE status = 'PENDING' AND expires_at > NOW()` (retry on conflict) so concurrent workers/replicas never assign the same active QRIS `total_amount`.

### 3.2 Atomic Issuance Transaction Flow (`POST /api/v1/academy/invoice`)

1. Normalize `canonical_tenant_id` (`str(...).strip().lower()`).
2. Generate `order_id`, QRIS payload (`total_amount`, `qr_string`, `qr_image_url`), and `expires_at`.
3. Call `_CHECKOUT_TOKEN_MANAGER.issue_token(order_id=order_id, canonical_tenant_id=canonical_tenant_id)` **in-memory cryptographic computation first** (produces `token_str` and `session_meta`: `jti`, `iat`, `exp`, `cs_key_id`, `revoked=False`).
4. Inside **one** offloaded PostgreSQL transaction (`asyncio.to_thread` or async pool, preventing event-loop blocking noted in Workstream A):
   - `INSERT INTO public.orders (...)` (including `tenant_id`, `tenant_slug`, `sku_id`, `gross_amount`, `amount`, `status='PENDING'`, `payment_status='PENDING'`, `order_status='PENDING'`).
   - `INSERT INTO public.checkout_sessions (...)` (storing `order_id`, `canonical_tenant_id`, `jti`, `cs_key_id`, `iat_epoch`, `exp_epoch`, `expires_at`, `revoked=FALSE`, and `invoice_snapshot`).
   - `COMMIT`. If any SQL error occurs, `ROLLBACK` and fail closed (`HTTP 500`/`503`) with zero token returned to caller.
5. Best-effort secondary sync to Supabase `payment_intents` (non-authoritative telemetry/mirror if Supabase REST is used separately, **never** gating session verification).
6. Return masked public DTO + `checkout_session_token` + `__Host-bt_checkout_st` cookie + `CHECKOUT_SECURITY_HEADERS`.

### 3.3 Cross-Replica / Cross-Worker Polling & Verification Flow (`GET /api/v1/academy/invoice/{order_id}`)

1. **Pre-DB Constant-Shape Guards (FastAPI & aiohttp parity):**  
   - Check query string presence (`raw_query_string`) and token extraction (`X-Checkout-Session-Token` header or `__Host-bt_checkout_st` / `bt_checkout_st` cookie) and token structural split (`6` parts, `"v1"`, int `iat`/`exp`, valid non-`REVOKED` `cs_key_id`) **either before DB I/O with identical `dummy_sig` timing work, or consistently around one uniform DB read** (see §3.4 timing analysis).
2. **PostgreSQL Lookup Across Any Replica / Worker:**  
   - Query `public.checkout_sessions cs INNER JOIN public.orders o ON o.id = cs.order_id WHERE cs.order_id = %s LIMIT 1;` (executed outside RAM—no `_ACADEMY_INVOICES` authority!).
   - Reconstruct the `invoice_record` mapping expected by [`verify_request_and_authorize_invoice`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1491-L1620):
     - Top-level invoice fields (`order_id`, `sku_id`, `sku`, `base_amount`, `unique_code`, `total_amount`, `qr_string`, `qr_image_url`, customer fields for `sanitize_public_invoice_dto` masking, `tenant_id`, `ttl_minutes`, `expires_at`, `created_at`, **`status = o.status`**).
     - `canonical_tenant_id = cs.canonical_tenant_id`.
     - `checkout_session = {"jti": cs.jti, "iat": cs.iat_epoch, "exp": cs.exp_epoch, "revoked": cs.revoked, "cs_key_id": cs.cs_key_id, "order_id": cs.order_id, "canonical_tenant_id": cs.canonical_tenant_id}`.
   - **Important RLS Note (`VERIFIED FACT` [`init_test_postgres_schema.py`](file:///c:/boontrack-core/scripts/init_test_postgres_schema.py#L220-L232)):** Because unauthenticated buyer polling supplies `order_id` + opaque HMAC token (not an untrusted caller `tenant_id` query/header), DB reads should either bind a read-scoped helper function that parses/verifies the token format first or run under a least-privilege session reader policy explicitly scoping returned columns to `cs.order_id = %s` before `verify_request_and_authorize_invoice()` validates cryptographic binding (`cs_key_id`, `sig_ok`, `order_ok`, `jti_ok`, `canonical_tenant_id`) inside the process. Never execute transactionally mutating admin roles on read paths, and never trust any client-supplied tenant header to select DB tenant context!
3. **Zero Stale-RAM Caching:**  
   - `RECOMMENDATION`: Do **not** short-circuit `get_academy_invoice()` using process-local `_ACADEMY_INVOICES` for status/revocation fields (`status`, `revoked`, `exp`). Every replica/worker must observe PostgreSQL commits (`PAID`, `CANCELLED`, `REVOKED`, `EXPIRED`) immediately on the very next poll.

### 3.4 Preserving Anti-Enumeration & Constant-Time Verification

- **`VERIFIED FACT` (`05ac51c` Baseline):**  
  [`verify_request_and_authorize_invoice`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1513-L1617) computes `dummy_sig` via HMAC-SHA256 and raises `PaymentAuthorizationError("Invoice not found", ..., http_status=404)` across all failure modes; routes map it identically to `HTTP 404 {"detail": "Invoice not found"}` + `CHECKOUT_SECURITY_HEADERS`.
- **`SOURCE-BASED INFERENCE` — Subtle Timing Side-Channel When Adding PostgreSQL I/O:**  
  If a route skips DB lookup when no token is provided (`if not token`), then valid-token-to-nonexistent-order vs valid-token-to-existing-order differs only in HMAC failure vs pass—except if DB lookup itself only happens when token parsing passes, DB latency (`~1–3ms`) is incurred for valid-format tokens targeting BOTH existing and non-existing `order_id`s identically! Conversely, never skip HMAC computation on DB miss: [`verify_request_and_authorize_invoice`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1538-L1540) ALREADY runs `dummy_sig` + `hmac.compare_digest(dummy_sig, "0" * 64)` when `invoice_record is None`.
- **`RECOMMENDATION`:**
  1. Perform query-string rejection (`raw_query_string != ""`), missing-token rejection, malformed-token rejection, and `REVOKED`/unknown-key rejection **before or alongside uniform timing**, and when DB is queried, execute a single parameterized primary-key query `WHERE cs.order_id = %s` (taking uniform indexed lookup time whether `0` or `1` row returns) and ALWAYS pass `invoice_record` (or `None`) into `verify_request_and_authorize_invoice()` so `dummy_sig` executes unconditionally on DB miss.
  2. Never translate PostgreSQL transient read errors into an enumeration signal; log internally and map authorization/lookup failures cleanly (`404` on invalid/missing/revoked/expired; `503` only without leaking order existence if DB pool itself is unreachable).
  3. Preserve masked DTO serialization ([`sanitize_public_invoice_dto`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1329-L1350)) so `jti`, `cs_key_id`, `checkout_session`, and unmasked buyer PII never leave the server.

### 3.5 Lifecycle Semantics: Expiry, Cancellation, Settlement & Key Rotation

| Lifecycle Event | Persistent State Transition (`PostgreSQL`) | Polling (`GET /invoice/{order_id}`) | Webhook / Settlement Behavior |
|---|---|---|---|
| **Active Invoice (`PENDING`)** | `orders.status='PENDING'`, `checkout_sessions.revoked=FALSE`, `NOW() <= expires_at` | Valid `v1` HMAC + matching `jti` + `canonical_tenant_id` → **`HTTP 200`** (masked DTO, `"status": "PENDING"`) | Normal settlement allowed up to `expires_at`. |
| **Invoice / Token Expiry** | `now_epoch > min(exp, cs.exp_epoch)` (and/or lazy/scheduled update `orders.status='EXPIRED'`) | Fails `not_expired` & `inv_status` check ([`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1582-L1617)) → **`HTTP 404`** | [`settle_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1604) MUST compare `now_utc` against DB `cs.expires_at` (not RAM), routing late payments to durable DB reconciliation queue (not RAM `_MANUAL_RECONCILIATION_QUEUE`). |
| **Explicit Cancellation / Token Revocation** | Atomic update: `checkout_sessions.revoked=TRUE, revoked_at=NOW()`, and/or `orders.status='CANCELLED'` | Fails `not_revoked` ([`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1605-L1608)) on ALL workers → **`HTTP 404`** | Settlement guard rejects cancelled/revoked orders (or routes unexpected late funds to manual reconciliation). |
| **Payment Settlement (`PAID`)** | Transactional update in [`settle_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1698-L1752): `payment_events` (include canonical `tenant_id`!) + `orders` (`status='PAID', payment_status='PAID', paid_at=NOW()`) + `financial_ledger`; keep `checkout_sessions.revoked=FALSE` | Buyer browser with valid unexpired session token polls on ANY worker → **`HTTP 200`** with `"status": "PAID"` so checkout UI confirms payment! After `exp`, polls return `404`. | Idempotent via PostgreSQL `financial_ledger` unique index `uq_financial_ledger_order_credit` + `payment_events.event_id` UNIQUE (not RAM `_SETTLED_ORDERS`). |
| **Key Rotation (`ACTIVE` → `VERIFY_ONLY` → `REVOKED`)** | All replicas/workers load same `CHECKOUT_SESSION_HMAC_KEYRING_JSON`. `cs_key_id` stored on `checkout_sessions` for auditability. | Old tokens signed by `VERIFY_ONLY` key remain **`HTTP 200`** on both old and new rolling containers; tokens signed by `REVOKED` key immediately fail closed **`HTTP 404`** ([`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1568)) across all processes. | New `POST /invoice` requests mint tokens using the newly promoted `"ACTIVE"` key. |

### 3.6 Rolling Deployments & Container Restart Survival

- **`SOURCE-BASED INFERENCE` & `RECOMMENDATION`:**  
  During a rolling deploy on Railway (or after container crash/restart):
  1. New and old containers share the exact same `CHECKOUT_SESSION_HMAC_KEYRING_JSON` and PostgreSQL connection string (`DATABASE_URL`).
  2. When rotating keys, keep the prior key as `"VERIFY_ONLY"` in `CHECKOUT_SESSION_HMAC_KEYRING_JSON` for at least `15 minutes` (or `max_ttl` if longer-lived tokens are ever issued) *before* marking `"REVOKED"`.
  3. Because `orders` + `checkout_sessions` are committed atomically before `POST /api/v1/academy/invoice` responds `200`, an old container can issue an invoice at `t=0`, get terminated during rollout at `t=10s`, and the new container/worker seamlessly serves `GET /api/v1/academy/invoice/{order_id}` (`200 PENDING` → `200 PAID`) for the remaining `14m50s`.
  4. **Eliminate Startup Ambiguity (`payment_auth_guard.py:L1430`):** Enforce fail-closed startup check in `CheckoutSessionTokenManager.__init__` when **no `"ACTIVE"` key** exists in production (`is_production_environment(env)`), rather than letting boot succeed with only `"VERIFY_ONLY"`/`"REVOKED"` keys and crashing later on first `POST /invoice`.

### 3.7 Minor Pre-Existing Implementation Defects to Remediate Under Workstream B

When CTO authorizes Workstream B implementation, fix these verified `05ac51c` bugs alongside persistence migration:
1. [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1415): Guard `if not isinstance(meta, Mapping): raise PaymentConfigurationError(...)` before `meta.get(...)` (currently raises unhandled `AttributeError` on non-dict metadata like `"cs_v1": "bad_string"`).
2. [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1412-L1413): Reject leading/trailing or internal whitespace in raw `kid` cleanly (`kid != kid.strip()` or `any(ch.isspace() for ch in clean_kid)`) instead of silent `.strip()`.
3. [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1430): Fail closed during `__init__` in production if zero `"ACTIVE"` keys exist (currently deferred until `issue_token()`).
4. [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1698-L1719): Supply `tenant_id` explicitly in `INSERT INTO payment_events` so settlement matches `NOT NULL` constraint in `database.py:L538` and `migrations/033a`.
5. [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L221) vs [`L370`](file:///c:/boontrack-core/app/routes/academy_routes.py#L370): Align `samesite="strict"` / `"Strict"` and run synchronous DB calls off the asyncio event loop (`asyncio.to_thread` / async driver).

