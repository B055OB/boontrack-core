# BOONTRACK CORE — CHECKOUT RECOVERY DECISION (WORKSTREAM A)

**Target Repository:** `C:\boontrack-core`  
**Target Deployed Commit SHA:** `05ac51c907dd46d8213d29442edd1a54145a22d9`  
**Railway Service / Environment:** `boontrack-core` / `production`  
**Mode:** Strict Read-Only Assessment (Production Mutation: **NOT AUTHORIZED**)  
**Status:** Prepared for CTO Review  

---

## Epistemic Labeling Standard Used in This Document

Every technical claim below is explicitly classified using reconciled provenance tags:

- **`VERIFIED FACT` / `Independently verified source evidence`** — Directly observed in source files, SQL/migration definitions, or test suites at commit `05ac51c907dd46d8213d29442edd1a54145a22d9`.
- **`Independently verified runtime evidence`** — Observed locally in the workspace runtime environment (e.g., installed `uvicorn==0.52.1` source inspection; live Railway container runtime still unverified).
- **`Operator-provided live dashboard evidence`** — Live Railway Dashboard settings reported by the CTO/operator (`Builder: Dockerfile`, `Custom Start Command: python -m app.main`, `Target Port: 8080`, `PORT=8080`, `Replica count: 1`, `WEB_CONCURRENCY: absent`, `Checkout keyring: absent`); not directly verified via Railway API/CLI/logs in this session.
- **`SOURCE-BASED INFERENCE`** — Logical deduction derived strictly from verified source/runtime evidence in `05ac51c`.
- **`UNVERIFIED RUNTIME FACT` / `Unverified`** — Live Railway deployment logs, live Railway environment variables not supplied by the operator, or live production PostgreSQL state not inspectable in read-only mode.
- **`RECOMMENDATION`** — Engineering decision or operator action proposed for CTO authorization.

---

## 0. Executive Recovery Decision (Three Separate Decisions)

1. **Decision 1 — Process Startup Availability (After Keyring Configuration): `CONDITIONAL YES` (`RECOMMENDATION`)**  
   Commit `05ac51c` can safely start and bind HTTP port `8080` under `python -m app.main` once `CHECKOUT_SESSION_HMAC_KEYRING_JSON` is configured with at least one valid `"ACTIVE"` key (`secret` >= 32 chars, distinct from `APP_MASTER_KEY`, no `:` or `.` in `key_id`, see [CHECKOUT_SESSION_HMAC_KEYRING_PRODUCTION_SETUP.md](file:///c:/boontrack-core/CHECKOUT_SESSION_HMAC_KEYRING_PRODUCTION_SETUP.md)), **provided** all other import-time Group A variables (`SUPABASE_URL`, `SUPABASE_ANON_KEY` or `SUPABASE_KEY`, `XENDIT_SECRET_KEY`, `XENDIT_WEBHOOK_VERIFICATION_TOKEN` or `XENDIT_CALLBACK_TOKEN`, `EVOLUTION_API_KEY` or fallback alias) are present in Railway Production (presence currently **`Unverified`**). Port conflict between `Dockerfile:L18` (`8000`) and `Procfile:L1` (`8080`) is **reconciled** per `Operator-provided live dashboard evidence` (`Custom Start Command: python -m app.main`, `PORT=8080`, `Target Port: 8080`), because `Dockerfile` defines no `ENTRYPOINT` and `app/main.py:L612-L613` reads `PORT=8080`.

2. **Decision 2 — Emergency Checkout Operation Under `1 Replica × 1 Worker`: `CONDITIONAL YES — TEMPORARY EMERGENCY MITIGATION ONLY` (`RECOMMENDATION`)**  
   Under `Operator-provided live dashboard evidence` (`Replica count: 1`, `WEB_CONCURRENCY: absent`) and `Independently verified source evidence` (`app/main.py:L613` passes no `workers` argument to `uvicorn.run(...)`), multi-worker/multi-replica split-brain on RAM-backed `_ACADEMY_INVOICES` ([`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L99-L100)) is eliminated while that single-process topology holds. **However, startup availability does not equal checkout reliability:**
   - Any process restart, OOM, healthcheck recycle, or redeploy wipes `_ACADEMY_INVOICES` RAM, turning active buyer polling (`GET /api/v1/academy/invoice/{order_id}`) into `HTTP 404 {"detail": "Invoice not found"}` ([`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L255-L269)) and bypassing RAM 15-minute expiry enforcement on late settlement (`academy_service.py:L1604`).
   - Settlement persistence in [`settle_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1698-L1779) omits `tenant_id` when inserting into `payment_events` (contrary to `NOT NULL` in [`database.py`](file:///c:/boontrack-core/app/core/database.py#L538, L601-L610)), catching the SQL failure via `logger.warning`, calling `conn.rollback()`, and still returning `"status": "PAID"` in RAM — risking silent PostgreSQL settlement rollback even in 1 replica × 1 worker mode.

3. **Decision 3 — Minimum Changes Required Before Declaring Checkout Production-Reliable (`RECOMMENDATION`):**  
   Do **not** declare Academy checkout production-reliable (or scale `> 1` worker/`> 1` replica) until all minimum code, schema, and test gates are completed:
   - Fix `payment_events.tenant_id` omission and remove silent DB settlement rollback/swallowing in [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1698-L1779), plus public-SKU silent DB error swallowing at [`L1430-L1434`](file:///c:/boontrack-core/app/services/academy_service.py#L1430-L1434).
   - Implement durable PostgreSQL `public.orders` + `public.checkout_sessions` issuance and polling (Workstream B in [CHECKOUT_DURABLE_SESSION_ARCHITECTURE.md](file:///c:/boontrack-core/CHECKOUT_DURABLE_SESSION_ARCHITECTURE.md)), multi-worker-safe unique-code allocation, and offload blocking DB I/O off the asyncio event loop.
   - Remediate `CheckoutSessionTokenManager` configuration hardening defects (`payment_auth_guard.py:L1411-L1431`: non-mapping `meta` guard, raw key ID whitespace rejection, fail-closed startup check when zero `"ACTIVE"` keys exist in production, and full `APP_MASTER_KEY` fallback/sibling separation).
   - Add automated tests for `CHECKOUT_SESSION_HMAC_KEYRING_JSON`, key lifecycle, cross-worker/restart polling, cross-tenant authorization, and settlement ledger persistence ([CHECKOUT_SESSION_SECURITY_TEST_MATRIX.md](file:///c:/boontrack-core/CHECKOUT_SESSION_SECURITY_TEST_MATRIX.md) Items 1–14).

---

## 1. Single-Replica & Single-Worker Safety Assessment (`05ac51c`)

### 1.1 How Checkout Session State Behaves in `05ac51c`

1. **`VERIFIED FACT` — Process-Local In-Memory Invoice Store:**  
   In [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L99-L100), invoice storage uses two module-level in-memory dictionaries:
   - `_ACADEMY_INVOICES = {}`
   - `_ACADEMY_INVOICES_BY_AMOUNT = {}`
2. **`VERIFIED FACT` — Read Path Has Zero Database or Redis Fallback:**  
   [`generate_academy_qris_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1392-L1393) populates `_ACADEMY_INVOICES[order_id]` and `_ACADEMY_INVOICES_BY_AMOUNT[total_amount]` in local RAM, then inserts a subset of order fields into PostgreSQL `orders` (`L1401-L1420`) and best-effort into Supabase `payment_intents` (`L1442-L1459`). However, [`get_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1464-L1466) executes only:
   ```python
   return _ACADEMY_INVOICES.get(order_id)
   ```
   There is no fallback query to PostgreSQL `orders`, Supabase `payment_intents`, or Redis.
3. **`VERIFIED FACT` — Checkout Session Metadata Never Reaches Persistent Storage:**  
   In [`create_academy_invoice`](file:///c:/boontrack-core/app/routes/academy_routes.py#L158-L209), `generate_academy_qris_invoice(...)` completes its PostgreSQL and Supabase writes *before* [`_CHECKOUT_TOKEN_MANAGER.issue_token(...)`](file:///c:/boontrack-core/app/routes/academy_routes.py#L203-L208) runs. The returned `session_meta` (`jti`, `iat`, `exp`, `revoked`, `order_id`, `canonical_tenant_id`, `cs_key_id`) is attached strictly to the RAM dictionary:
   - `invoice["canonical_tenant_id"] = canonical_tenant_id` (`L207`)
   - `invoice["checkout_session"] = session_meta` (`L208`)
4. **`VERIFIED FACT` — Process-Scoped Token Manager Singleton:**  
   [`_CHECKOUT_TOKEN_MANAGER = CheckoutSessionTokenManager()`](file:///c:/boontrack-core/app/routes/academy_routes.py#L44) is instantiated once per worker process at import time (via `from app.routes.academy_routes import academy_router` in [`app/main.py`](file:///c:/boontrack-core/app/main.py#L100)). Because production mode fails closed if `CHECKOUT_SESSION_HMAC_KEYRING_JSON` is absent ([`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1393-L1396)), all processes sharing identical `CHECKOUT_SESSION_HMAC_KEYRING_JSON` share cryptographic keys—**but do not share `invoice["checkout_session"]` or `_ACADEMY_INVOICES[order_id]`**.
5. **`VERIFIED FACT` — Committed Entrypoints Specify Single-Worker Execution:**  
   None of [`Dockerfile`](file:///c:/boontrack-core/Dockerfile#L18), [`docker/Dockerfile`](file:///c:/boontrack-core/docker/Dockerfile#L15), [`Procfile`](file:///c:/boontrack-core/Procfile#L1), [`docker-compose.prod.yml`](file:///c:/boontrack-core/docker-compose.prod.yml#L8), [`main.py`](file:///c:/boontrack-core/main.py#L16), or [`app/main.py`](file:///c:/boontrack-core/app/main.py#L612-L613) pass `--workers` or define `WEB_CONCURRENCY`. No `railway.toml` or `railway.json` exists in `05ac51c`.
6. **`VERIFIED FACT` — Settlement State Partial Divergence:**  
   [`settle_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1504-L1778) protects in-process writes with `_SETTLE_THREAD_LOCK`, reads `_ACADEMY_INVOICES.get(order_id)` (`L1517`), checks `financial_ledger` and `orders` (`L1642-L1693`), updates PostgreSQL `orders` (`L1722-L1729`), and updates `invoice["status"] = "PAID"` in RAM (`L1775-L1778`).
7. **`VERIFIED FACT` — Blocking Sync I/O Inside Async Invoice Handler:**  
   [`create_academy_invoice`](file:///c:/boontrack-core/app/routes/academy_routes.py#L111) is `async def` and calls synchronous [`generate_academy_qris_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1398-L1457) (`psycopg2.connect(...)` and `supabase-py` network calls) directly on the asyncio event loop thread without `asyncio.to_thread(...)`.

### 1.2 Live Railway Scaling Status & Risk Matrix

- **`Operator-provided live dashboard evidence` vs `Independently verified` / `Unverified`:**  
  Operator-supplied dashboard evidence reports **`Replica count: 1`** and **`WEB_CONCURRENCY: absent`**. Under [`app/main.py:L613`](file:///c:/boontrack-core/app/main.py#L613), `uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)` omits `workers`, so `workers` defaults to `None` (`Independently verified runtime evidence` on local `uvicorn==0.52.1`: `self.workers = workers or 1` unless `WEB_CONCURRENCY` is present in `os.environ`, per `uvicorn/config.py:L268, L352-L353`; `UVICORN_WORKERS` applies only to Click CLI `uvicorn/main.py:L61`, not `uvicorn.run`). Note that live container `ps` / deploy log worker confirmation and Railway's resolved `uvicorn[standard]>=0.22.0` exact build version remain **`Unverified`**.
- **`SOURCE-BASED INFERENCE` — Safety Verdict Under Strict 1 Replica × 1 Worker × No `WEB_CONCURRENCY` Override:**
  - **Multi-process split-brain (`POST /invoice` vs `GET /invoice/{order_id}`):** **Eliminated** while strictly 1 replica and 1 Uvicorn worker serve traffic, because every HTTP request routes to the same `_ACADEMY_INVOICES` memory space.
  - **Event-loop latency risk:** During DB/Supabase slowness in `POST /api/v1/academy/invoice`, synchronous `psycopg2`/`supabase` calls pause the single event loop for concurrent requests (`SOURCE-BASED INFERENCE`).
  - **Memory growth risk:** `_ACADEMY_INVOICES` and `_ACADEMY_INVOICES_BY_AMOUNT` have no TTL pruning/eviction loop (`VERIFIED FACT` across [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L99-L100); bounded at low traffic, grows linearly with uptime).
  - **Settlement persistence defect (`VERIFIED FACT`):** [`settle_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1698-L1779) omits `tenant_id` on `INSERT INTO payment_events` (contrary to `NOT NULL` enforced in [`database.py`](file:///c:/boontrack-core/app/core/database.py#L538, L601-L610)), catches the DB error (`L1753`), rolls back `conn` (`L1757`), and still updates RAM `_SETTLED_ORDERS` / returns `"status": "PAID"` (`L1764-L1781`).
  - **Restart / rolling deploy fragility (CRITICAL RESIDUAL RISK):** Any container crash, OOM, Railway healthcheck recycle, or subsequent deployment destroys `_ACADEMY_INVOICES` and `_SETTLED_ORDERS`, breaking polling (`404 {"detail": "Invoice not found"}`) for buyers who created QRIS invoices within the preceding 15 minutes (`ACADEMY_INVOICE_TTL_MINUTES`), and breaking 15-minute expiry reconciliation in `settle_academy_invoice` if the RAM entry is gone (`academy_service.py:L1604`).
  - **Horizontal scaling prohibition (`05ac51c`):** Scaling to ≥ 2 replicas or ≥ 2 Uvicorn workers (`--workers > 1` or `WEB_CONCURRENCY > 1`) will cause immediate random `HTTP 404` failures on buyer polling whenever polling lands on a different worker/replica than invoice creation (`SOURCE-BASED INFERENCE`).

- **`RECOMMENDATION`:** Approve `1 replica × 1 Uvicorn worker` **solely as a temporary emergency startup mitigation** on `05ac51c` (not production checkout reliability). Enforce `WEB_CONCURRENCY` unset (or `1`), disallow multi-worker overrides, and treat fixing `payment_events.tenant_id` plus Workstream B durable session persistence as mandatory before enabling horizontal scaling, multi-worker Uvicorn, or routine rolling deployments during active Academy checkout traffic.

---

## 2. `Dockerfile` Port `8000` vs `Procfile` Port `8080` Analysis

### 2.1 Committed Configurations at `05ac51c`

| Artifact | Line Ref | Exact Binding / Command | Uses `$PORT`? | Notes |
|---|---|---|---|---|
| [`Dockerfile`](file:///c:/boontrack-core/Dockerfile#L18) | `L18` | `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` | **No** (hardcoded `8000`) | `VERIFIED FACT`; active root Dockerfile in `05ac51c`. |
| [`docker/Dockerfile`](file:///c:/boontrack-core/docker/Dockerfile#L12-L15) | `L12, L15` | `EXPOSE 8000` / `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]` | **No** (hardcoded `8000`) | `VERIFIED FACT`; includes dev `--reload`. |
| [`Procfile`](file:///c:/boontrack-core/Procfile#L1) | `L1` | `web: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}` | **Yes** (fallback `8080`) | `VERIFIED FACT`; active if Railpack/Nixpacks/Procfile runs. |
| [`main.py`](file:///c:/boontrack-core/main.py#L12-L16) & [`app/main.py`](file:///c:/boontrack-core/app/main.py#L610-L613) | `L612-L613` | `port = int(os.getenv("PORT", 8080)); uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)` | **Yes** (fallback `8080`) | `VERIFIED FACT`; used only if launched via `python main.py` or `python app/main.py`. |
| [`docker-compose.prod.yml`](file:///c:/boontrack-core/docker-compose.prod.yml#L8-L16) | `L8, L16` | `command: uvicorn app.main:app --host 0.0.0.0 --port 8000` + `PORT=8000` | Fixed `8000` | `VERIFIED FACT`; references root `Dockerfile`. |
| `railway.toml` / `railway.json` | N/A | **Absent at `05ac51c`** | N/A | `VERIFIED FACT`; Railway relies on Dashboard/service settings. |

### 2.2 Runtime Reconciliation & Risk Assessment

| Dashboard / Runtime Item | Reported Value | Epistemic Classification | Reconciliation Against `05ac51c` Source & Runtime |
|---|---|---|---|
| **Builder** | `Dockerfile` | **`Operator-provided live dashboard evidence`** (not Railway-API verified) | Matches root [`Dockerfile`](file:///c:/boontrack-core/Dockerfile#L1-L18) (`Independently verified source evidence`); `Dockerfile` has **no `ENTRYPOINT`**, only `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` (`L18`). |
| **Custom Start Command** | `python -m app.main` | **`Operator-provided live dashboard evidence`** | Overrides `Dockerfile:L18` `CMD` at deploy launch; executes [`app/main.py:L610-L613`](file:///c:/boontrack-core/app/main.py#L610-L613) (`__main__`), binding `0.0.0.0` instead of hardcoded `8000` (`Independently verified source evidence`). Live startup log line remains **`Unverified`**. |
| **Target Port & `PORT`** | `Target Port: 8080`, `PORT=8080` | **`Operator-provided live dashboard evidence`** | [`app/main.py:L612`](file:///c:/boontrack-core/app/main.py#L612) runs `port = int(os.getenv("PORT", 8080))`; with `PORT=8080`, listening port and Target Port reconcile to **`8080 == 8080`** (`SOURCE-BASED INFERENCE`). |
| **Replica Count & `WEB_CONCURRENCY`** | `Replica count: 1`, `WEB_CONCURRENCY: absent` | **`Operator-provided live dashboard evidence`** | [`app/main.py:L613`](file:///c:/boontrack-core/app/main.py#L613) omits `workers`; local `uvicorn==0.52.1` (`uvicorn/config.py:L268, L352-L353` — **`Independently verified runtime evidence`**) sets `workers = 1` when `workers is None` and `"WEB_CONCURRENCY"` is absent (`UVICORN_WORKERS` applies only to Click CLI `uvicorn/main.py:L61`). Live container `ps`/built `uvicorn` version (`requirements.txt:L2` `>=0.22.0`) remain **`Unverified`**. |
| **Checkout Keyring** | `CHECKOUT_SESSION_HMAC_KEYRING_JSON: absent` | **`Operator-provided live dashboard evidence`** | Triggers fail-closed [`PaymentConfigurationError`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1393-L1396) during `import app.main` (`L100` -> [`academy_routes.py:L44`](file:///c:/boontrack-core/app/routes/academy_routes.py#L44)) whenever production env is active (`Independently verified source evidence`). Exact startup traceback / deploy log `dc6ffa8c` remains **`Unverified`** in local read-only inspection. |
| **Other Env Vars & Healthcheck** | Remaining Group A/B/C vars, live `RAILWAY_ENVIRONMENT` value, Healthcheck Path | **`Unverified`** | Not included in operator-provided dashboard summary; must be verified in Railway Dashboard before redeploy. |

- **`RECOMMENDATION`:** Confirm in deploy logs after any CTO-authorized recovery deploy that Uvicorn logs `Uvicorn running on http://0.0.0.0:8080` (`Custom Start Command: python -m app.main` active) and check Railway Healthcheck Path (`/health` or `/ready`). Long-term (`Workstream B / hardening PR`, not authorized now): align `Dockerfile`, `Procfile`, and `railway.toml` to eliminate dual-port drift if Custom Start Command were ever cleared.

---

## 3. Production Environment Variable Classification (`05ac51c`)

> **Confidentiality Guarantee:** This section lists variable names and verified AST/import contracts (`265` reachable Python modules from `05ac51c:app/main.py`). No secret values were read or printed.

### 3.1 Group A — Strictly Mandatory at Boot / Module Import (`python -m app.main`)

When executing `python -m app.main` (`uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)` at [`app/main.py:L610-L613`](file:///c:/boontrack-core/app/main.py#L610-L613)), if **any** variable in Group A is missing or invalid in `production`, Python raises an uncaught exception during module import **before** Uvicorn binds port `8080` (`VERIFIED FACT`):

| Variable Name | Requirement Rule | Source Location at `05ac51c` | Classification |
|---|---|---|---|
| `SUPABASE_URL` | Non-empty URL string; initialized into `supabase_client`. | [`app/main.py`](file:///c:/boontrack-core/app/main.py#L30-L48), [`app/api/webhook_payment.py`](file:///c:/boontrack-core/app/api/webhook_payment.py#L13-L26) | `VERIFIED FACT` |
| `SUPABASE_ANON_KEY` **or** `SUPABASE_KEY` | At least one public/anon key required; `SUPABASE_SERVICE_ROLE_KEY` rejected as standard client. *(Note: `AnalyticsService.__init__` at [`analytics_service.py:L8-L16`](file:///c:/boontrack-core/app/services/analytics_service.py#L8-L16) calls unguarded `create_client(url, key)` only if both `SUPABASE_URL` and `SUPABASE_KEY` are truthy, safely falling back to `None` when `SUPABASE_KEY` is unset.)* | [`app/main.py`](file:///c:/boontrack-core/app/main.py#L31-L38), [`test_fail_closed_config_entrypoints.py`](file:///c:/boontrack-core/tests/test_fail_closed_config_entrypoints.py#L239-L250) | `VERIFIED FACT` |
| `XENDIT_SECRET_KEY` | Non-empty string; required by module-level singleton `xendit_service = XenditService()` imported via `payment.py` (`L70` -> `L21`) and `xendit.py` (`L73` -> `L31`). | [`app/main.py`](file:///c:/boontrack-core/app/main.py#L70, L73), [`xendit_service.py`](file:///c:/boontrack-core/app/services/xendit_service.py#L62-L65, L425) | `VERIFIED FACT` |
| `XENDIT_WEBHOOK_VERIFICATION_TOKEN` **or** `XENDIT_CALLBACK_TOKEN` | At least one non-empty callback/verification token required by `XenditService.__init__()`. | [`xendit_service.py`](file:///c:/boontrack-core/app/services/xendit_service.py#L70-L79, L425) | `VERIFIED FACT` |
| `EVOLUTION_API_KEY` *(or `AUTHENTICATION_API_KEY` / `WA_GATEWAY_INTERNAL_API_KEY`)* | Non-empty string; checked at module top-level in `evolution.py`, transitively imported via `payment.py:L17` → `whatsapp_service.py:L20` → `whatsapp/__init__.py:L72`. | [`evolution.py`](file:///c:/boontrack-core/app/services/whatsapp/evolution.py#L34-L41), [`whatsapp/__init__.py`](file:///c:/boontrack-core/app/services/whatsapp/__init__.py#L72-L74), [`payment.py`](file:///c:/boontrack-core/app/routes/payment.py#L17) | `VERIFIED FACT` |
| `CHECKOUT_SESSION_HMAC_KEYRING_JSON` | **Required in production** (`APP_ENV`, `ENVIRONMENT`, `RAILWAY_ENVIRONMENT`, or `NODE_ENV` in `{"production","prod","live"}`); instantiated at [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L44) via [`app/main.py`](file:///c:/boontrack-core/app/main.py#L100). Valid JSON object, ≥ 1 key, `secret` ≥ 32 chars, distinct from `APP_MASTER_KEY`, status in `{"ACTIVE","VERIFY_ONLY","REVOKED"}` (and ≥ 1 `"ACTIVE"` required before `issue_token`). | [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1145-L1152, L1375-L1463), [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L44) | `VERIFIED FACT` |

> **Special Cases (`VERIFIED FACT`):**  
> 1. If the alternative entrypoint [`app/core/server.py`](file:///c:/boontrack-core/app/core/server.py#L23-L28) were imported directly or started instead of `python -m app.main`, `DATABASE_URL` also becomes mandatory at import time ([`test_fail_closed_config_entrypoints.py:L178-L184`](file:///c:/boontrack-core/tests/test_fail_closed_config_entrypoints.py#L178-L184)). Under `python -m app.main`, `app.core.server` is only imported lazily inside request/worker functions (e.g., `app/api/deps.py:L117`, `app/services/idempotency.py:L300`), so `DATABASE_URL` is **request-time** (`Group B`).  
> 2. `APP_MASTER_KEY` is read during `CheckoutSessionTokenManager.__init__` (`payment_auth_guard.py:L1382`) only to reject key reuse collision, **not** required to boot.  
> 3. If `"WEB_CONCURRENCY"` is set in `os.environ` with a non-integer value, `uvicorn/config.py:L353` raises `ValueError` during `Config` construction prior to bind. Under `Operator-provided live dashboard evidence`, `WEB_CONCURRENCY` is absent.

### 3.2 Group B — Request-Time Security, Persistence & Runtime Variables

The FastAPI process can boot if these are absent, but specific routes, settlement flows, health readiness, or DB writes fail closed at request time (`VERIFIED FACT`):

| Variable Name | Impact When Absent / Misconfigured | Source Location at `05ac51c` |
|---|---|---|
| `DATABASE_URL` **or** (`POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, optional `POSTGRES_PORT` default `5432`) | [`get_db_connection()`](file:///c:/boontrack-core/app/core/database.py#L91-L128) raises `RuntimeError("[SECURITY FAIL-CLOSED]...")` on any direct PostgreSQL operation (`TEST-PENNY-1500` invoice creation fails closed `HTTP 500`; public SKU `OB-BATCH1-249K` logs error at `academy_service.py:L1430` without failing RAM creation; DB settlement fails). | [`app/core/database.py`](file:///c:/boontrack-core/app/core/database.py#L91-L128), [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L1398-L1439) |
| `SUPABASE_SERVICE_ROLE_KEY` | [`get_admin_supabase_client()`](file:///c:/boontrack-core/app/main.py#L51-L66) and verified webhook admin client ([`webhook_payment.py`](file:///c:/boontrack-core/app/api/webhook_payment.py#L34)) fail closed at request time. | [`app/main.py`](file:///c:/boontrack-core/app/main.py#L51-L66), [`app/api/webhook_payment.py`](file:///c:/boontrack-core/app/api/webhook_payment.py#L34) |
| `ENVIRONMENT` / `APP_ENV` / `RAILWAY_ENVIRONMENT` / `NODE_ENV` | Controls `is_production_environment()` detection (any matching `production`/`prod`/`live` enforces fail-closed keyring & simulation lockdown). Note Railway automatically injects `RAILWAY_ENVIRONMENT`. | [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1145-L1152), [`app/main.py`](file:///c:/boontrack-core/app/main.py#L555) |
| `BOONTRACK_HMAC_SECRET` | `get_hmac_secret()` raises `ValueError("CRITICAL_SECURITY_ERROR...")` on inter-service HMAC calls when called; not invoked at `app.main` import. | [`inter_service_auth.py`](file:///c:/boontrack-core/app/core/security/inter_service_auth.py#L167-L182) |
| `BOONTRACK_INTERNAL_HMAC_SECRET` | Required specifically when requesting internal SKU `TEST-PENNY-1500` on `POST /api/v1/academy/invoice`; missing causes `HTTP 500` fail-closed. | [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L123, L140-L147) |
| `PAYMENT_INTERNAL_HMAC_KEYRING_JSON` | Request-time internal payment mutation HMAC authentication. | [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L40, L646) |
| `PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON` / `PAYMENT_PROVENANCE_VERIFY_PUBLIC_KEYRING_JSON` | Request-time payment event Ed25519 provenance signing/verification (`payment_events`; legacy aliases forbidden). | [`provenance_authority.py`](file:///c:/boontrack-core/app/core/security/provenance_authority.py#L61-L70, L1156-L1160) |
| `APP_MASTER_KEY` | Used lazily for key-separation checks (`payment_auth_guard.py:L1382`, `academy_routes.py:L124`, prohibited as mutation credential) and `encryption.py:L9` (has fallback default in `encryption.py`). | [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1382), [`encryption.py`](file:///c:/boontrack-core/app/core/security/encryption.py#L9) |
| `PORT` | Ignored if `Dockerfile:L18` `CMD` were run directly; **used** by `Custom Start Command: python -m app.main` ([`app/main.py:L612`](file:///c:/boontrack-core/app/main.py#L612), `default 8080`, set to `8080` per operator dashboard evidence) and `Procfile:L1`. | [`Procfile`](file:///c:/boontrack-core/Procfile#L1), [`app/main.py`](file:///c:/boontrack-core/app/main.py#L612) |

### 3.3 Group C — Optional / Feature-Specific Integration Variables

Absent values do not crash `app.main` boot (`VERIFIED FACT` in `config.py`, `xendit_service.py`, `docker-compose.prod.yml`):

- **AI Providers:** `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` (`app/core/config.py:L58-L67`).
- **Telegram Academy / Creator Bots:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ONLINEBOOST_BOT_TOKEN`, `TELEGRAM_ONLINEBOOST_CHAT_ID` (default `"-1004371114362"`), `TELEGRAM_CREATOR_BOT_TOKEN` (`app/core/config.py:L70-L83`).
- **Academy QRIS / Promo Defaults:** `DANA_STATIC_QRIS`, `PROMO_EXPIRY_DATE` (`default "2026-08-31"`, `app/core/config.py:L87-L92`).
- **Payment Gateway Selection & Links:** `PAYMENT_GATEWAY_PROVIDER` (`default "midtrans"`), `XENDIT_API_URL` (`default "https://api.xendit.co"`), `XENDIT_ENV` (`default "sandbox"`), `APP_DOMAIN` (`xendit_service.py:L60-L68, L140, L190`).
- **Messaging / Cache / Object Storage:** `REDIS_URL`, `META_WABA_PHONE_NUMBER_ID`, `WABA_PHONE_NUMBER_ID`, `WHATSAPP_PHONE_NUMBER_ID`, `PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, `EVOLUTION_API_URL`, `RESEND_API_KEY`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID` (`docker-compose.prod.yml:L31-L38`, `app/main.py:L557-L560`, `evolution.py:L25`).

- **`UNVERIFIED RUNTIME FACT`:** Operator-provided live dashboard evidence covers `PORT=8080`, `WEB_CONCURRENCY: absent`, and `CHECKOUT_SESSION_HMAC_KEYRING_JSON: absent`. Live presence of the remaining Group A, Group B, and Group C variables in Railway Production has **not** been independently verified in this session. Operator must verify Group A variables + `DATABASE_URL` + `RAILWAY_ENVIRONMENT` directly in Railway Dashboard **Variables** before triggering a deploy.

---

## 4. Minimum Safe Post-Recovery HTTP Verification

`RECOMMENDATION`: Once the CTO authorizes recovery and Railway confirms a running deployment (`status = ACTIVE/SUCCESS` with Uvicorn listening cleanly on the matched port and zero `PaymentConfigurationError` in deploy logs), execute **strictly non-secret, read-first** checks in sequence:

### Step 1 — Read-Only Infrastructure & Public Endpoints (Zero Mutation)

1. **`GET https://api.boontrack.com/` and `GET https://api.boontrack.com/health`**  
   - **Expected (`VERIFIED FACT` [`app/main.py`](file:///c:/boontrack-core/app/main.py#L371-L384)):** `HTTP 200`, JSON `{"status": "healthy", "service": "boontrack-core", "version": "1.0.0", "database": {"supabase": "configured"}}`.
2. **`GET https://api.boontrack.com/ready`**  
   - **Expected (`VERIFIED FACT` [`app/main.py`](file:///c:/boontrack-core/app/main.py#L387-L452)):** `HTTP 200`, JSON `{"status": "ready", ... "database": {"supabase": "active"}}` (proves outbound Supabase connectivity works). If `HTTP 503`, inspect sanitized `dependencies.supabase.category` (`DEPENDENCY_TIMEOUT`, `DEPENDENCY_UNREACHABLE`, etc.).
3. **`GET https://api.boontrack.com/api/v1/academy/sku`**  
   - **Expected (`VERIFIED FACT` [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L75-L92)):** `HTTP 200`, `"sku_id": "OB-BATCH1-249K"`, `"settlement_price": 249000`, `"ttl_minutes": 15`. Proves `academy_router` loaded with `CheckoutSessionTokenManager` initialized.
4. **Anti-Enumeration & Query-Token Rejection Probes (`GET /api/v1/academy/invoice/BTA-ALUMNI-PROBE000`):**  
   - Probe A (no headers/cookies) and Probe B (`?token=probe_dummy` with dummy query param):  
   - **Expected (`VERIFIED FACT` [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L234-L278)):** Both return **identical** `HTTP 404` JSON `{"detail": "Invoice not found"}` with security headers `Referrer-Policy: no-referrer`, `Cache-Control: no-store, no-cache, must-revalidate, private`, `Pragma: no-cache`, and `X-Content-Type-Options: nosniff` (`payment_auth_guard.py:L1281-L1287`).

### Step 2 — Optional Synthetic Checkout Verification (CTO Explicit Approval Only)

- **Side-Effect Warning (`VERIFIED FACT`):** Calling `POST /api/v1/academy/invoice` mutates live state (`_ACADEMY_INVOICES` RAM, PostgreSQL `orders`, and Supabase `payment_intents` when configured). Do **not** run during read-only checks unless CTO authorizes one synthetic smoke record (`use_unique_code: false` or synthetic test customer details, never real customer PII):
  1. If authorized via `POST /api/v1/academy/invoice`: confirm `HTTP 200`, `checkout_session_token` starts with `v1.<ACTIVE_KEY_ID>.` (matching the key ID configured in Railway, **never** `cs_ephemeral_dev_k1` from [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1290)), masked buyer PII in response `invoice`, `Set-Cookie: __Host-bt_checkout_st=...; Path=/api/v1/academy/invoice; Secure; HttpOnly; SameSite=Strict; Max-Age=900`, and `Referrer-Policy: no-referrer`.
  2. Immediately poll `GET /api/v1/academy/invoice/{order_id}` with header `X-Checkout-Session-Token: <token>` → expect `HTTP 200` with masked PII and stripped internal fields.
  3. Repeat `GET /api/v1/academy/invoice/{order_id}?token=<token>` → expect `HTTP 404 {"detail": "Invoice not found"}`.
  4. Never invoke settlement mutations or unverified webhooks (`POST /api/v1/academy/webhook/paid` stays blocked `HTTP 403 UNVERIFIED_WEBHOOK_MUTATION_BLOCKED` at [`academy_routes.py`](file:///c:/boontrack-core/app/routes/academy_routes.py#L281-L302)).
