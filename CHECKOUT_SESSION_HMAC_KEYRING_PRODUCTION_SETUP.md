# `CHECKOUT_SESSION_HMAC_KEYRING_JSON` — Production Configuration Setup & Validation

**Target Commit Verified:** `05ac51c907dd46d8213d29442edd1a54145a22d9` (`Merge pull request #28 from B055OB/security/upload-auth-hardening-issue-27`)  
**Mode:** Read-Only Design & Preparation (No production secrets generated; no Railway, code, or DB mutations performed)  
**Target Service:** `boontrack-core` (`uvicorn app.main:app`, Railway Production)

---

## 1. Executive Summary

At deployed commit `05ac51c907dd46d8213d29442edd1a54145a22d9`, booting `app.main` imports [`academy_router`](file:///c:/boontrack-core/app/routes/academy_routes.py#L42) (`05ac51c:app/main.py:100`), which unconditionally executes module-level [`_CHECKOUT_TOKEN_MANAGER = CheckoutSessionTokenManager()`](file:///c:/boontrack-core/app/routes/academy_routes.py#L44).

Inside [`CheckoutSessionTokenManager.__init__`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1375-L1431), when [`ENV_CHECKOUT_SESSION_KEYRING`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1277) (`CHECKOUT_SESSION_HMAC_KEYRING_JSON`) is unset or blank and [`is_production_environment`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1145-L1152) detects `"production"`, `"prod"`, or `"live"` in `APP_ENV`, `ENVIRONMENT`, `RAILWAY_ENVIRONMENT`, or `NODE_ENV`, startup aborts immediately with:

```text
PaymentConfigurationError: CHECKOUT_SESSION_HMAC_KEYRING_JSON must be configured in production.
```

Because `CHECKOUT_SESSION_HMAC_KEYRING_JSON` was never created in Railway Production, deploying `05ac51c907dd46d8213d29442edd1a54145a22d9` fails closed at import time.

---

## 2. Exact Contract From Deployed Source (`05ac51c`)

### 2.1 Environment Variable Name & Alias Policy
- **Canonical Name:** `CHECKOUT_SESSION_HMAC_KEYRING_JSON` ([`payment_auth_guard.py:L1277`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1277)).
- **Fallback Aliases:** None. [`__init__`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1385) reads only `os.environ.get("CHECKOUT_SESSION_HMAC_KEYRING_JSON", "")` with `.strip()`. Any typo or alternative variable name fails closed in production.
- **No Unquoted Outer Quotes Trap:** `json.loads(raw_json)` parses the raw string directly (`L1388`). In Railway Dashboard Variables, paste the raw JSON object directly (`{"cs_prod_202611_v1":{...}}`), **not** wrapped in outer single quotes (`'...'`) or escaped as a nested JSON string.

### 2.2 Exact JSON Schema
From [`CheckoutSessionTokenManager.__init__`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1384-L1431):

```json
{
  "cs_prod_202611_v1": {
    "secret": "<OPERATOR_GENERATED_64_HEX_CHAR_CSPRNG_SECRET>",
    "status": "ACTIVE"
  }
}
```

- Top-level JSON value **must** be a non-empty JSON object (`isinstance(keys, Mapping) and bool(keys)`, `L1405-1406`) mapping string `<cs_key_id>` to per-key metadata objects (`dict`).
- Empty `{}` or non-dict JSON raises `PaymentConfigurationError("CheckoutSessionTokenManager requires at least one key.")`.
- Non-object values under a `key_id` fail at `meta.get(...)` (`L1415`).

### 2.3 Required and Optional Fields

| Level | Field | Requirement | Type / Rule Enforced at `05ac51c` | Source |
| :--- | :--- | :--- | :--- | :--- |
| Top-level | `<cs_key_id>` | **Required** (`>= 1` entry) | Non-empty string after `.strip()`, **must not contain `.` or `:`** | [`L1405-1414`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1405-L1414) |
| Key Entry | `secret` | **Required** | String, stripped via `.strip()`, **`len(secret) >= 32`**, must differ from `APP_MASTER_KEY` via `hmac.compare_digest` | [`L1415-1424`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1415-L1424) |
| Key Entry | `status` | **Required** | String, `.strip().upper()`, strictly in `{"ACTIVE", "VERIFY_ONLY", "REVOKED"}` | [`L1416, L1425-1428`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1416-L1428) |
| Key Entry | *(Any other keys)* | **Not used / Omit** | Ignored by `CheckoutSessionTokenManager.__init__` (`bound_principal`, `bound_tenant_id`, `not_after_epoch` are **not** read or enforced here) | [`L1411-1431`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1411-L1431) |

> **Operational Issuance Constraint:** `__init__` checks only that each configured entry has a valid status, whereas [`issue_token`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1457-L1462) raises `PaymentConfigurationError("No ACTIVE checkout session signing key available.")` if `self._active_key_id` is `None`. At least **one** key entry in production **must** have `"status": "ACTIVE"`. If multiple `"ACTIVE"` entries exist, the **first** `"ACTIVE"` entry in JSON object order becomes `self._active_key_id` ([`L1430-1431`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1430-L1431)).

### 2.4 Accepted Key ID Format & Key ID Recommendation
- **Validation in code (`L1412-1414`):** `clean_kid = str(kid).strip()`. Rejected if `not clean_kid`, `"." in clean_kid`, or `":" in clean_kid`.
- **Why `.` and `:` are prohibited:**
  - Tokens use `.` as segment separator: `v1.<cs_key_id>.<iat>.<exp>.<jti>.<hmac_sha256_hex>` ([`L1479`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1479), parsed by `token.split(".")` requiring 6 parts at [`L1546-1547`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1546-L1547)).
  - Canonical HMAC message uses `:` as field separator: `cs:v1:{cs_key_id}:{iat}:{exp}:{jti}:{order_id}:{canonical_tenant_id}` ([`L1444`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1444)).
- **Transport constraint:** `<cs_key_id>` is transmitted verbatim in `X-Checkout-Session-Token` header and `__Host-bt_checkout_st` cookie ([`academy_routes.py:L215-230`](file:///c:/boontrack-core/app/routes/academy_routes.py#L215-L230)), so avoid spaces, semicolons, quotes, and non-ASCII characters.
- **Recommended Initial Key ID:** **`cs_prod_202611_v1`** (matches repo naming style `prv_k202611_v1` in [`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md:L254`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md#L254) and `cs_ephemeral_dev_k1` in [`payment_auth_guard.py:L1290`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1290)). For subsequent rotations, increment cleanly (`cs_prod_202611_v2`, `cs_prod_202612_v1`, etc.). Never reuse a revoked `key_id`.

### 2.5 Secret Encoding, Minimum Entropy & Key Separation
- **Encoding in code (`L1415, L1445`):** `secret` is `.strip()`-ped and passed directly as UTF-8 bytes (`secret.encode("utf-8")`) to `hmac.new(..., hashlib.sha256).hexdigest()`. No hex or Base64 decoding is performed on the string.
- **Minimum Enforced Length (`L1417-1420`):** `len(secret) >= 32` characters after `.strip()`.
- **Recommended Format & Entropy:** Generate **32 random bytes as 64 lowercase hex characters** via `secrets.token_hex(32)` (256 bits of CSPRNG entropy — matching the codebase's own dev generator at [`payment_auth_guard.py:L1291`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1291)). Using lowercase hex avoids JSON escaping, shell-quoting errors, and whitespace trimming surprises.
- **Key Separation Requirement:**
  - Enforced by code against `APP_MASTER_KEY` (`L1421-1424`).
  - Required by architecture ([`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md:L242-243`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md#L242-L243)): Must be cryptographically independent from `APP_MASTER_KEY`, `PII_HASH_SALT`, `PAYMENT_INTERNAL_HMAC_KEYRING_JSON`, `PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON`, `BOONTRACK_HMAC_SECRET`, `BOONTRACK_INTERNAL_HMAC_SECRET`, `JWT_SECRET`, and `SUPABASE_SERVICE_ROLE_KEY`.

### 2.6 Accepted Key Statuses

| Status | Startup Valid? | Signs New Tokens (`issue_token`)? | Verifies Existing Tokens? | Operational Role |
| :--- | :--- | :--- | :--- | :--- |
| `ACTIVE` | Yes | **Yes** (first `ACTIVE` key used by default) | **Yes** | Primary signing & verification key |
| `VERIFY_ONLY` | Yes | **No** (rejected at [`L1461-1462`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1461-L1462)) | **Yes** (accepted at [`L1567-1568`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1567-L1568)) | Outgoing key kept during rotation TTL window |
| `REVOKED` | Yes | **No** | **No** (`CHECKOUT_SESSION_KEY_INVALID`, HTTP 404 at [`L1568-1574`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1568-L1574)) | Compromised or permanently decommissioned key |
| `PREVIOUS` | **No (Fails boot!)** | No | No | Rejected by `CheckoutSessionTokenManager`; unlike [`ALLOWED_INTERNAL_KEY_STATUSES`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L62-L64), `"PREVIOUS"` is **not** valid here |

---

## 3. Token Signing, Verification & Rotation Behavior

### 3.1 Token Signing & Verification Mechanics
- **Issuance ([`issue_token`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1447-L1489) via [`academy_routes.py:L203-231`](file:///c:/boontrack-core/app/routes/academy_routes.py#L203-L231)):**
  - Signs `cs:v1:{cs_key_id}:{iat}:{exp}:{jti}:{order_id}:{canonical_tenant_id}` with HMAC-SHA256 using `key_rec["secret"]` (`status == "ACTIVE"`).
  - TTL is clamped to `[60, 86400]` seconds; `academy_routes.py` uses default `ttl_seconds = 900` (15 minutes, matching [`ACADEMY_INVOICE_TTL_MINUTES = 15`](file:///c:/boontrack-core/app/services/academy_service.py#L71)).
  - Embeds `cs_key_id`, `jti` (128-bit random hex), `iat`, and `exp` into the wire token `v1.<cs_key_id>.<iat>.<exp>.<jti>.<hmac_sha256_hex>`.
  - Sends token in response JSON (`checkout_session_token`) and cookie `__Host-bt_checkout_st` (`Path=/api/v1/academy/invoice; Secure; HttpOnly; SameSite=Strict; Max-Age=900`), alongside [`CHECKOUT_SECURITY_HEADERS`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1282-L1287) (`Referrer-Policy: no-referrer`, `Cache-Control: no-store, no-cache, must-revalidate, private`, `Pragma: no-cache`, `X-Content-Type-Options: nosniff`).
- **Verification ([`verify_request_and_authorize_invoice`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1491-L1619) via [`academy_routes.py:L258-278`](file:///c:/boontrack-core/app/routes/academy_routes.py#L258-L278)):**
  - Executes a constant-time dummy HMAC on early failures (`L1513-1522`) using `next(iter(self._keys.values()))["secret"]`.
  - Rejects any URL query string token (`raw_query_string != ""`, `L1525-1531`).
  - Extracts token from `X-Checkout-Session-Token` header or `__Host-bt_checkout_st` / `bt_checkout_st` cookie (`L1534-1536`).
  - Looks up `self._keys.get(cs_key_id)`; accepts `ACTIVE` and `VERIFY_ONLY`, rejects missing keys and `REVOKED` (`L1567-1574`).
  - Recomputes HMAC against `requested_order_id` and `canonical_tenant_id`, checks constant-time signature match, order ID match, expiry (`current_ts <= min(exp, recorded_exp)`), non-revocation (`not revoked` and invoice status not in `CANCELLED`/`REVOKED`/`EXPIRED`), and `jti` match (`L1585-1617`).
  - Any failure returns uniform anti-enumeration `HTTP 404 {"detail": "Invoice not found"}`.

### 3.2 Rotation & Backward-Compatibility Behavior
- **Should old tokens remain verifiable during key rotation?**
  - **Planned Rotation (Yes):** Keep the outgoing key in `CHECKOUT_SESSION_HMAC_KEYRING_JSON` with `"status": "VERIFY_ONLY"` while introducing the new key with `"status": "ACTIVE"`. This preserves in-flight buyer checkout polling sessions (default TTL `900s` = 15 minutes; code ceiling `86400s` = 24 hours) without rejecting valid sessions mid-checkout ([`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md:L339`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md#L339)). Remove or move the `VERIFY_ONLY` key to `"REVOKED"` only after `>= 86400s` (or `>= 900s` after rollout stabilizes if only 15-minute Academy tokens are issued).
  - **Compromise / Emergency Rotation (No):** Immediately mark the compromised `key_id` as `"REVOKED"` (keep entry as `"REVOKED"` or remove it) and add a new `"ACTIVE"` key. Previously issued tokens signed with that `key_id` will immediately fail closed with HTTP 404 (`CHECKOUT_SESSION_KEY_INVALID`).
- **Bootstrap & Persistence Caveats at `05ac51c`:**
  1. **Zero Existing Production Tokens Today:** Because `CHECKOUT_SESSION_HMAC_KEYRING_JSON` was never created in Railway Production and `05ac51c` crashed at startup, there are no previously issued `CHECKOUT_SESSION_HMAC_KEYRING_JSON` production tokens to migrate or preserve on initial bootstrap — a single `ACTIVE` key (`cs_prod_202611_v1`) is sufficient for initial recovery.
  2. **In-Memory Invoice Store at `05ac51c`:** Currently [`academy_service.py`](file:///c:/boontrack-core/app/services/academy_service.py#L99) stores [`_ACADEMY_INVOICES`](file:///c:/boontrack-core/app/services/academy_service.py#L1392) (`checkout_session` metadata including `jti`/`exp`) in process-local memory ([`get_academy_invoice`](file:///c:/boontrack-core/app/services/academy_service.py#L1464-1466)). On an in-place single-container restart, `_ACADEMY_INVOICES` resets anyway; however, `"VERIFY_ONLY"` rotation remains essential during rolling/blue-green restarts or once invoice session state is DB-persisted.

---

## 4. Audit of Existing Keyring Sources & Scope Analysis

### 4.1 Search Across Authorized Local & Repo Sources (No Secret Values Accessed/Printed)

| Source Checked | Finding | Notes |
| :--- | :--- | :--- |
| Railway Production (`boontrack-core`) | **Absent** | Confirmed by CTO directive: `CHECKOUT_SESSION_HMAC_KEYRING_JSON` was never created |
| Local `.env` (key-name-only scan) | **Absent** | Has `APP_MASTER_KEY`, `PII_HASH_SALT`, `BOONTRACK_HMAC_SECRET`, `BOONTRACK_INTERNAL_HMAC_SECRET`; zero `*_KEYRING_JSON` vars exist |
| Repo configs (`05ac51c` & `HEAD`) | **Absent** | Absent from `.env.example`, `.env.test`, `docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.test.yml`, `Dockerfile`, `docker/Dockerfile`, `Procfile`, `app/core/config.py`, and `.github/workflows/*.yml` |
| Repo docs & tests (`05ac51c` & `HEAD`) | **Design docs only** | `CHECKOUT_SESSION_HMAC_KEYRING_JSON` appears only in [`payment_auth_guard.py`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1277) and [`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md#L242) (no tests at `05ac51c` explicitly inject `CHECKOUT_SESSION_HMAC_KEYRING_JSON` or assert `CheckoutSessionTokenManager` prod fail-closed startup) |
| Railway Staging / external vaults | **Not accessible in session** | Railway MCP OAuth is deferred and browser DevTools was unattached; never copy a Staging/non-prod keyring into Production regardless |

**Conclusion:** No reusable production keyring exists in any inspected source. Generate a fresh, independent production secret.

### 4.2 Railway Service & Environment Scope
- **Requires `CHECKOUT_SESSION_HMAC_KEYRING_JSON` (Production):**
  - **Railway Project `BoonTrack` -> Environment `production` -> Service `boontrack-core`:** Boots `uvicorn app.main:app` ([`Dockerfile`](file:///c:/boontrack-core/Dockerfile), [`Procfile`](file:///c:/boontrack-core/Procfile)), where `RAILWAY_ENVIRONMENT=production` activates [`is_production_environment`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1145-L1152).
  - **Multi-worker / Multi-replica `boontrack-core` instances:** If `boontrack-core` scales horizontally or runs multiple Uvicorn workers, **all workers/replicas in the same service/environment must receive the identical `CHECKOUT_SESSION_HMAC_KEYRING_JSON`** so any worker can verify tokens issued by another.
- **Standalone / Non-FastAPI Services at `05ac51c` Verified NOT to Import `academy_routes`:**
  - [`run_bot.py`](file:///c:/boontrack-core/run_bot.py) — does not import `app.main` or `app.routes.academy_routes`.
  - [`subscription_reminder_worker.py`](file:///c:/boontrack-core/subscription_reminder_worker.py) & [`scripts/subscription_reminder_worker.py`](file:///c:/boontrack-core/scripts/subscription_reminder_worker.py) — do not import `app.main` or `app.routes.academy_routes`.
  - [`app/core/server.py`](file:///c:/boontrack-core/app/core/server.py) (`create_web_app()` aiohttp entrypoint) — does **not** call [`register_academy_routes`](file:///c:/boontrack-core/app/routes/academy_routes.py#L333) (`register_academy_routes` is invoked only in test suites at `05ac51c`).
- **Admin / One-off CLI Script Note:** [`scripts/generate_penny_invoice.py:L31`](file:///c:/boontrack-core/scripts/generate_penny_invoice.py#L31) imports `create_academy_invoice` from `app.routes.academy_routes`. If ever executed in an environment with `APP_ENV`/`ENVIRONMENT`/`RAILWAY_ENVIRONMENT`/`NODE_ENV` in `{"production", "prod", "live"}`, it will trigger `CheckoutSessionTokenManager()`.
- **Other Environments & Standby Compose Warning:**
  - **Railway Staging / Preview:** When `RAILWAY_ENVIRONMENT` is `staging` / preview (and `APP_ENV`, `ENVIRONMENT`, `NODE_ENV` are not `production`/`prod`/`live`), `CheckoutSessionTokenManager` falls back to [`_EPHEMERAL_DEV_CS_KEY_ID`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1290) and does not crash. If Staging explicitly configures a keyring (e.g., to test multi-worker persistence or rotation), use a **distinct staging-only key** (`cs_stg_202611_v1`), **never** the production secret.
  - **Docker Standby Compose ([`docker-compose.prod.yml`](file:///c:/boontrack-core/docker-compose.prod.yml), `05ac51c:L204–205`):** Sets `ENVIRONMENT=${ENVIRONMENT:-production}` alongside `RAILWAY_ENVIRONMENT=${RAILWAY_ENVIRONMENT:-standby}`. Because [`is_production_environment`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1148-L1151) checks `"APP_ENV"`, `"ENVIRONMENT"`, `"RAILWAY_ENVIRONMENT"`, and `"NODE_ENV"`, defaulting `ENVIRONMENT=production` activates the production guard even when `RAILWAY_ENVIRONMENT=standby`. Any `uvicorn app.main:app` container started from `docker-compose.prod.yml` with `ENVIRONMENT=production` would also need `CHECKOUT_SESSION_HMAC_KEYRING_JSON` injected in its host/compose env.

---

## 5. Secure Local Generation Procedure (Operator Runbook Only)

> **Security Rule:** Do **not** generate production keys inside agent chat, do **not** echo secrets to terminal scrollback/shell logs, and do **not** save production secrets into `.env` or any file inside the Git repository.

### Option A — Windows PowerShell (Direct to Clipboard, Zero Terminal Echo)
Execute locally in a private PowerShell terminal (never logged/shared):

```powershell
# 1. Generate minified single-line JSON straight into clipboard without printing to stdout
python -c 'import json, secrets; payload = {"cs_prod_202611_v1": {"secret": secrets.token_hex(32), "status": "ACTIVE"}}; print(json.dumps(payload, separators=(",", ":")))' | Set-Clipboard
```

1. Copy/save a backup of the value from clipboard into your **authorized encrypted password manager / secrets vault** (under Railway Production -> `boontrack-core` -> `CHECKOUT_SESSION_HMAC_KEYRING_JSON`) **before** clearing clipboard.
2. In **Railway Dashboard -> Project BoonTrack -> Production -> Service `boontrack-core` -> Variables**, add variable:
   - **Name:** `CHECKOUT_SESSION_HMAC_KEYRING_JSON`
   - **Value:** Paste directly using Raw/Value input (ensure **no leading/trailing quotes** around `{...}`).
3. Immediately clear your local clipboard:

```powershell
Set-Clipboard -Value $null
```

### Option B — Air-Gapped / Ephemeral Python Session (If Not Using Clipboard Pipe)
Run `python -I` interactively, write directly to your secret manager's CLI or encrypted vault, verify `len(secret) == 64`, never write to disk, and close the session without shell history persistence (`$env:PSReadLine` / `HISTFILE`).

---

## 6. Pre-Deployment Validation (Read-Only Sanity Check Before Saving/Deploying)

Before applying in Railway Production or triggering a redeploy (once CTO-approved), validate the operator-prepared value locally **without printing secrets** using a clipboard or stdin-fed Python check against the exact [`CheckoutSessionTokenManager`](file:///c:/boontrack-core/app/core/security/payment_auth_guard.py#L1368-L1431) rules:

### 6.1 Silent Non-Echo Validation Script (Operator Run via Clipboard / Stdin)
```powershell
# Reads candidate JSON from clipboard (or stdin), validates strict schema + APP_MASTER_KEY separation,
# prints ONLY boolean/length metadata — NEVER prints secrets.
Get-Clipboard | python -c '
import json, hmac, os, sys
raw = sys.stdin.read().strip()
data = json.loads(raw)
assert isinstance(data, dict) and len(data) >= 1, "Top-level JSON must be a non-empty object"
active_count = 0
master = os.environ.get("PROD_APP_MASTER_KEY_IF_CHECKED", "").strip()
for kid, meta in data.items():
    assert isinstance(kid, str) and kid.strip() and "." not in kid and ":" not in kid, f"Invalid key_id: {kid!r}"
    assert isinstance(meta, dict), f"Metadata for {kid} must be a JSON object"
    sec = str(meta.get("secret") or "").strip()
    st = str(meta.get("status") or "").strip().upper()
    assert len(sec) >= 32, f"Secret too short for {kid}: len={len(sec)}"
    assert not (master and hmac.compare_digest(sec, master)), f"Secret for {kid} reuses APP_MASTER_KEY"
    assert st in ("ACTIVE", "VERIFY_ONLY", "REVOKED"), f"Invalid status for {kid}: {st}"
    if st == "ACTIVE":
        active_count += 1
    print(f"OK key_id={kid} status={st} secret_len={len(sec)}")
assert active_count >= 1, "At least one ACTIVE key is required for POST /api/v1/academy/invoice"
print(f"VALIDATION PASSED: keys={len(data)} active={active_count} minified_bytes={len(raw)}")
'
```

### 6.2 Pre-Apply Checklist in Railway Dashboard
- [ ] Service/Environment confirmed: **`boontrack-core`** in **`production`** environment (and `RAILWAY_ENVIRONMENT` is `production`).
- [ ] Variable name exact: `CHECKOUT_SESSION_HMAC_KEYRING_JSON`.
- [ ] JSON is valid single-line JSON with `key_id = cs_prod_202611_v1`, `status = "ACTIVE"`, `len(secret) == 64` (256-bit hex), no `.` or `:` in `key_id`, and zero outer wrapping quotes.
- [ ] Secret does **not** match Production `APP_MASTER_KEY` (check against Railway Production `APP_MASTER_KEY`, not just local `.env`), `PAYMENT_INTERNAL_HMAC_KEYRING_JSON`, `PAYMENT_PROVENANCE_SIGNING_PRIVATE_KEYRING_JSON`, or `JWT_SECRET`.
- [ ] Verify whether Railway Production has `SUPABASE_URL` and `SUPABASE_ANON_KEY` (or `SUPABASE_KEY`) set (these are checked earlier at `05ac51c:L30–36` in [`app/main.py`](file:///c:/boontrack-core/app/main.py) before execution reaches `L100`).
- [ ] Local clipboard cleared (`Set-Clipboard -Value $null`) and secret recorded safely in encrypted vault.

---

## 7. Rollback Considerations

Consistent with the **Zero Insecure Revival Rule** ([`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md:L426-L438`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md#L426-L438)):
1. **Forbidden Rollback Actions:**
   - Do **not** patch out `CheckoutSessionTokenManager()`, disable `is_production_environment()`, force `RAILWAY_ENVIRONMENT` to non-prod in Production, or reuse `APP_MASTER_KEY`.
   - Do **not** revert `app/main.py` to stop enforcing `P0-D` checkout session protection or expose unauthenticated invoice polling.
2. **If Startup Still Fails After Setting `CHECKOUT_SESSION_HMAC_KEYRING_JSON`:**
   - **Malformed JSON (`Invalid JSON in CHECKOUT_SESSION_HMAC_KEYRING_JSON.`):** Fix variable quoting/formatting in Railway Dashboard Variables and redeploy/restart.
   - **Validation Error (`secret must be at least 32 characters` / `Invalid status` / `Invalid checkout session key_id`):** Fix only the JSON value in Railway Variables; no code change required.
   - **Accidental Reuse (`forbidden from reusing APP_MASTER_KEY`):** Generate a brand-new `secrets.token_hex(32)` key and replace the variable value.
   - **Secondary Missing Startup Variable:** Wait and inspect the new deploy log — because `app/main.py:L100` failed on import before subsequent lines, fix any newly revealed configuration variable via Railway Variables rather than rolling back security guards.
3. **Rollback During Future Key Rotations (Post-Recovery):**
   - If a newly rotated key (`cs_prod_202612_v1`) misbehaves or fails to propagate cleanly across workers, restore the previous `key_id` (`cs_prod_202611_v1`) back to `"ACTIVE"` (or keep as `"VERIFY_ONLY"`) in `CHECKOUT_SESSION_HMAC_KEYRING_JSON` without touching source code or weakening verification ([`PHASE-1-IMPLEMENTATION-PLAN-v1.1.md:L430-431`](file:///c:/boontrack-core/PHASE-1-IMPLEMENTATION-PLAN-v1.1.md#L430-L431)).

---

## 8. Post-Startup Verification Plan (Read-Only Checks After CTO Approval & Redeploy)

Once CTO approves adding `CHECKOUT_SESSION_HMAC_KEYRING_JSON` and redeploying `05ac51c907dd46d8213d29442edd1a54145a22d9`:

1. **Deployment & Boot Log Inspection (Railway Dashboard):**
   - Confirm deployment status reaches **ACTIVE / SUCCESS** (replacing crashed deployment).
   - Confirm startup logs show Uvicorn startup cleanly (`Uvicorn running on http://0.0.0.0:...`) and **zero** `PaymentConfigurationError`, `RuntimeError`, or module import tracebacks.
   - Verify no secrets or variable values appear in build/deploy logs.

2. **Safe Read-Only HTTP Endpoint Checks (`https://api.boontrack.com`):**
   - **Liveness ([`app/main.py`](file:///c:/boontrack-core/app/main.py), `05ac51c:L371–384`):**
     `GET https://api.boontrack.com/health` -> Expect `HTTP 200` with `{"status": "healthy", "service": "boontrack-core", ...}`.
   - **Readiness ([`app/main.py`](file:///c:/boontrack-core/app/main.py), `05ac51c:L387–452`):**
     `GET https://api.boontrack.com/ready` -> Expect `HTTP 200` with `{"status": "ready", "database": {"supabase": "active"}, ...}`.
   - **Academy Router Mounted & Non-Mutating ([`academy_routes.py:L75-92`](file:///c:/boontrack-core/app/routes/academy_routes.py#L75-L92)):**
     `GET https://api.boontrack.com/api/v1/academy/sku` -> Expect `HTTP 200` with `sku_id: "OB-BATCH1-249K"`.
   - **Anti-Enumeration Guard Active ([`academy_routes.py:L234-269`](file:///c:/boontrack-core/app/routes/academy_routes.py#L234-L269)):**
     `GET https://api.boontrack.com/api/v1/academy/invoice/BTA-NONEXISTENT-VERIFY` (no token) -> Expect `HTTP 404` `{"detail": "Invoice not found"}` with headers `Referrer-Policy: no-referrer` and `Cache-Control: no-store, no-cache, must-revalidate, private`.
   - *(Do not invoke `POST /api/v1/academy/invoice` against production unless explicitly authorized by the CTO for controlled synthetic smoke testing, as it writes to `orders` / `payment_intents` and `_ACADEMY_INVOICES`.)*

---

**STOPPING HERE:** Awaiting CTO review and explicit authorization before any Railway variable creation, service restart, or redeploy is performed.
