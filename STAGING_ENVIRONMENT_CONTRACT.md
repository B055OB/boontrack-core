# STAGING ENVIRONMENT BOOTSTRAP CONTRACT (R1 REMEDIATION — REV 2)

- **Document Ref:** `CTO-P0-PHASE2B-STAGING-ENV-007A-REV2`
- **Repository:** `B055OB/boontrack-core` (`C:\boontrack-core`)
- **Verified Baseline:** `a82b6fdf76c043c9a3ee87f48c34062f05258437`
- **Scope:** Staging vs. Production Compose Separation, Required/Optional/Fail-Closed Env Inventory, JWT Realm/Issuer/Audience/Secret Isolation, Approved R2 Staging Bucket (`boontrack-staging-renders`), OnlineBoost Strict Holds (`true`) & Checkout Flag (`false`)
- **Posture:** **STRICT HOLD — DESIGN REVIEW REVISION** (Zero source/config mutation applied to tracked files, zero container boot, zero secret values printed/logged)

---

## 1. STAGING VS. PRODUCTION COMPOSE CONFIGURATION SEPARATION

To prevent environment drift and cross-environment contamination, Staging container orchestration is strictly separated into a dedicated `docker-compose.staging.yml` manifest rather than overloading `docker-compose.prod.yml`.

| Dimension | `docker-compose.staging.yml` (Dedicated Staging) | `docker-compose.prod.yml` (Production / Standby) | `docker-compose.yml` (Local Dev Only) |
| :--- | :--- | :--- | :--- |
| **Container Name** | `boontrack_staging_backend` | `boontrack_standby_backend` | `boontrack_backend` (+ `postgres`, `bot`, `metabase`, `waha`) |
| **Host Port Binding** | `127.0.0.1:${STAGING_PORT:-8001}:8000` | `127.0.0.1:${PORT:-8000}:8000` | `8000:8000` |
| **Runtime Environment** | `ENVIRONMENT=staging`, `APP_ENV=staging`, `RAILWAY_ENVIRONMENT=staging` | `ENVIRONMENT=production`, `APP_ENV=production`, `RAILWAY_ENVIRONMENT=${RAILWAY_ENVIRONMENT:-standby}` | Local development |
| **Supabase Project Ref** | `xkhqirhurnjqglmajghn` (`boontrack-staging-db`, `ap-southeast-1`) | `mpluzajlzpregmjwpjqr` (`boontrack-db` — **LOCKED**) | Local / Mock |
| **Supabase JWT Issuer** | `https://xkhqirhurnjqglmajghn.supabase.co/auth/v1` | `https://mpluzajlzpregmjwpjqr.supabase.co/auth/v1` | Ephemeral dev (`_is_dev_or_test()==True`) |
| **Cloudflare R2 Bucket** | `boontrack-staging-renders` (Approved APAC staging bucket) | `boontrack-media` (**LOCKED** production bucket) | Local mock fallback (`data/r2_mock_storage`) |
| **Xendit Gateway Mode** | `XENDIT_ENV=sandbox` (`xnd_development_...` key only) | `XENDIT_ENV=production` | Test placeholder |
| **Missing Mandatory Secret** | Hard Compose interpolation error (`${VAR:?error}`) + app fail-closed | Hard Compose interpolation error (`${VAR:?error}`) + app fail-closed | Dev fallback |
| **`ONLINEBOOST_ALUMNI_BROADCAST_HOLD`** | `"true"` (**Explicit Hard Lock**) | `"true"` (**Explicit Hard Lock**) | N/A |
| **`ONLINEBOOST_PAYMENT_STRICT_HOLD`** | `"true"` (**Explicit Hard Lock**) | `"true"` (**Explicit Hard Lock**) | N/A |
| **`FEATURE_ONLINEBOOST_CHECKOUT_ENABLED`** | `"false"` (**Explicit Disabled**) | `"false"` (**Explicit Disabled**) | N/A |

---

## 2. COMPLETE CLASSIFICATION: FAIL-CLOSED, REQUIRED & OPTIONAL ENVIRONMENT VARIABLES

### 2.1 Category A — Boot-Time Fail-Closed Variables (Required at Module Import / Process Startup)

| Variable | Codebase Enforcement Reference | Default | Missing / Invalid Behavior at Boot | Staging Contract (Redacted) |
| :--- | :--- | :--- | :--- | :--- |
| `DATABASE_URL` | `app/core/server.py:23–28`, `app/core/database.py:95–97` | *None* | Raises `RuntimeError("[SECURITY FAIL-CLOSED] DATABASE_URL is mandatory...")` | `postgresql://...xkhqirhurnjqglmajghn...:6543/postgres` |
| `SUPABASE_URL` | `app/main.py:30–38`, `app/api/webhook_payment.py:13–20` | *None* | Raises `RuntimeError` at module import (`2.5s` connect / `5.0s` read timeout) | `https://xkhqirhurnjqglmajghn.supabase.co` |
| `SUPABASE_ANON_KEY` | `app/main.py:31–38`, `app/api/webhook_payment.py:14–20` | *None* | Raises `RuntimeError` if both `SUPABASE_ANON_KEY` and `SUPABASE_KEY` are unset | `<REDACTED_STG_SUPABASE_ANON_KEY>` (**!= `SERVICE_ROLE_KEY`**) |
| `SUPABASE_KEY` | `app/main.py:31`, `app/services/whatsapp_service.py:15` | Alias of `SUPABASE_ANON_KEY` | Raises `RuntimeError` if both `SUPABASE_ANON_KEY` and `SUPABASE_KEY` are unset | `<REDACTED_STG_SUPABASE_ANON_KEY>` |
| `EVOLUTION_API_KEY` | `app/services/whatsapp/evolution.py:34–41` | *None* | Raises `RuntimeError("EVOLUTION_API_KEY environment variable is missing")` | `<REDACTED_STG_EVOLUTION_API_KEY>` |
| `XENDIT_SECRET_KEY` | `app/services/xendit_service.py:33–36` | *None* | Raises `ValueError("[SECURITY FAIL-CLOSED] XENDIT_SECRET_KEY is mandatory...")` | `<REDACTED_STG_XENDIT_SANDBOX_KEY>` (`xnd_development_...`) |
| `XENDIT_CALLBACK_TOKEN` | `app/services/xendit_service.py:41–49`, `app/routes/xendit.py:706–730` | *None* | Raises `ValueError` at import; rejects webhook with `HTTP 403` via `hmac.compare_digest` | `<REDACTED_STG_XENDIT_CALLBACK_TOKEN>` |

### 2.2 Category B — Runtime Fail-Closed Variables (Required on Auth, Inter-Service, Storage & Hold Gates)

| Variable | Codebase Reference | Default in Code | Missing / Invalid Behavior (`ENVIRONMENT=staging`) | Staging Contract (Redacted) |
| :--- | :--- | :--- | :--- | :--- |
| `ENVIRONMENT`, `APP_ENV`, `RAILWAY_ENVIRONMENT` | `jwt_secret.py:52–54`, `inter_service_auth.py:83` | `"production"` / `"standby"` | `_is_dev_or_test()` returns `False` for `"staging"`, disabling ephemeral secrets & enforcing replay guard | `"staging"` |
| `JWT_SECRET` | `app/core/jwt_secret.py:58–70` | *None* (`staging`/`prod`) | Raises `RuntimeError("JWT_SECRET is not configured...")`; blocks `_COMPROMISED_SECRETS` (`L63–64`) | `<REDACTED_STG_CORE_JWT_SECRET_64B>` |
| `SUPABASE_JWT_SECRET` | `app/core/jwt_secret.py:73–85` | *None* (`staging`/`prod`) | Raises `RuntimeError("SUPABASE_JWT_SECRET is not configured...")`; blocks `_COMPROMISED_SECRETS` (`L78–79`) | `<REDACTED_STG_SUPABASE_JWT_SECRET>` |
| `CORE_JWT_ISSUER` | `app/core/jwt_secret.py:88–90, 281–286` | `"boontrack-core"` | Rejects `"core"` realm token with `ValueError` -> `HTTP 401` on missing/mismatched `iss` | `"boontrack-core"` |
| `CORE_JWT_AUDIENCE` | `app/core/jwt_secret.py:92–94, 288–300` | `"boontrack-core"` | Rejects `"core"` realm token with `ValueError` -> `HTTP 401` on missing/mismatched `aud` | `"boontrack-core"` |
| `SUPABASE_JWT_ISSUER` | `app/core/jwt_secret.py:96–104, 281–286` | `<SUPABASE_URL>/auth/v1` | Rejects `"supabase"` realm token with `ValueError` -> `HTTP 401` on missing/mismatched `iss` | `"https://xkhqirhurnjqglmajghn.supabase.co/auth/v1"` |
| `SUPABASE_JWT_AUDIENCE` | `app/core/jwt_secret.py:106–107, 288–300` | `"authenticated"` | Rejects `"supabase"` realm token with `ValueError` -> `HTTP 401` on missing/mismatched `aud` | `"authenticated"` |
| `INTERNAL_MAGIC_SECRET` | `app/core/jwt_secret.py:305–310`, `auth_routes.py:285`, `magic_login.py:21` | `None` | `get_internal_magic_secret()` returns `None` -> endpoints reject with `HTTP 403 Forbidden` | `<REDACTED_STG_INTERNAL_MAGIC_SECRET_64B>` |
| `BOONTRACK_HMAC_SECRET` | `app/core/security/inter_service_auth.py:171–180, 402–415` | *None* | Raises `ValueError("CRITICAL_SECURITY_ERROR: BOONTRACK_HMAC_SECRET ... is missing")` -> `HTTP 401` | `<REDACTED_STG_BOONTRACK_HMAC_SECRET_64B>` |
| `STRICT_REPLAY_GUARD` | `app/core/security/inter_service_auth.py:80–85` | `""` (enabled in prod/stg) | When `"true"`, Redis outage during HMAC nonce check aborts with `HTTP 503 Service Unavailable` | `"true"` |
| `REDIS_URL` | `app/core/redis.py:18–46`, `inter_service_auth.py:67` | `"redis://localhost:6379/0"` | Required for replay nonce store (`STRICT_REPLAY_GUARD=true`) -> `HTTP 503` if unreachable | `<REDACTED_STG_REDIS_URL>` |
| `SUPABASE_SERVICE_ROLE_KEY` | `app/main.py:51–66`, `app/api/webhook_payment.py:29–39` | `""` | Raises `RuntimeError` when privileged admin/webhook helper is invoked without key | `<REDACTED_STG_SUPABASE_SERVICE_ROLE_KEY>` |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | `app/services/storage/r2.py:53–55, 111`, `r2_storage_service.py:9–11` | `""` | `R2Client` raises `RuntimeError("[R2 FAIL-CLOSED] Credentials missing...")` (`r2.py:111`) | `56303bb13200d0980da8695adcf08550` + `<REDACTED_STG_R2_KEYS>` |
| `R2_BUCKET_NAME` | `app/services/storage/r2.py:56`, `r2_storage_service.py:12` | `"boontrack-media"` | Must be overridden to `"boontrack-staging-renders"` in staging to prevent prod bucket access | `"boontrack-staging-renders"` |
| `ONLINEBOOST_ALUMNI_BROADCAST_HOLD` | `app/services/meta_waba_service.py:437–471` | `"true"` | Fail-closed unless explicitly `"false"`/`"0"`/`"off"`/`"no"`; holds alumni broadcasts (`0` sent) | `"true"` (**MANDATORY EXPLICIT HOLD**) |
| `ONLINEBOOST_PAYMENT_STRICT_HOLD` | `app/services/academy_service.py:1010–1025, 2513` | `"true"` | Fail-closed unless explicitly `"false"`/`"0"`/`"off"`/`"no"`; blocks live QRIS/invoice creation | `"true"` (**MANDATORY EXPLICIT HOLD**) |
| `FEATURE_ONLINEBOOST_CHECKOUT_ENABLED` | `ONLINEBOOST_PHASE2B_RELEASE_READINESS.md:118` | `"false"` | Checkout killswitch; diverts checkout to static hold fallback when `"false"` | `"false"` (**MANDATORY EXPLICIT FALSE**) |

### 2.3 Category C — Required Operational & Cryptographic Variables, and Category D — Optional Integrations

| Category | Variable(s) | Codebase Reference | Default / Behavior | Staging Contract |
| :--- | :--- | :--- | :--- | :--- |
| **Category C (Required Operational)** | `APP_MASTER_KEY`, `APP_SECRET_KEY`, `PII_HASH_SALT` | `app/core/security.py:6–8`, `.env.example:63–64` | Envelope encryption, Fernet bot token encryption (`encrypt_bot_token`), PII hashing | `<REDACTED_STG_CRYPTO_KEYS_32B>` |
| **Category C (Required Operational)** | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `app/core/config.py:18–55`, `scripts/init_test_postgres_schema.py:14–32` | Discrete DB params used by catalog & RLS verification scripts | Staging DB (`xkhqirhurnjqglmajghn`) discrete params |
| **Category C (Required Operational)** | `PORT`, `PYTHON_VERSION`, `XENDIT_ENV`, `XENDIT_API_URL` | `Dockerfile:1`, `.env.example:15–16, 70–71` | Uvicorn container port `8000`, `python:3.11-slim`, Xendit sandbox mode | `8000` (host `8001`), `3.11`, `sandbox` |
| **Category D (Optional Integrations)** | `EVOLUTION_API_URL`, `META_WABA_*`, `WHATSAPP_*`, `RESEND_API_KEY`, `BITESHIP_API_KEY`, `TELEGRAM_*`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `DUITKU_*`, `SHOP_URL`, `DASHBOARD_URL`, `FRONTEND_URL`, `R2_PUBLIC_DOMAIN` | `meta_waba_service.py:68–74`, `biteship_adapter.py`, `auth_routes.py:41`, `r2.py:58` | WABA outbound fails closed if phone ID/token missing (`meta_waba_service.py:474`); Biteship uses mock tracking `BITESHIP-AUTO-{id}` when key empty (`checkout_shipping_service.py:333`) | Sandbox / optional staging keys |

---

## 3. JWT REALM, ISSUER, AUDIENCE & SECRET ISOLATION VALIDATION

All JWT and inter-service token operations are centralized in `app/core/jwt_secret.py:1–310` and `app/core/security/inter_service_auth.py:1–185`.

| Cryptographic Realm | Secret Env Variable & Resolver | Algorithm | Required Issuer (`iss`) | Required Audience (`aud`) | Active Callers in Codebase | Cross-Realm & Compromise Controls |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Realm 1: `"core"`** | `JWT_SECRET` via `get_jwt_secret()` (`jwt_secret.py:58–70`) | `HS256` (`L43, L235`) | `CORE_JWT_ISSUER` (`"boontrack-core"`, `L88–90, L285`) | `CORE_JWT_AUDIENCE` (`"boontrack-core"`, `L92–94, L293`) | `auth_routes.py:131`, `affiliate_auth.py:47, 70, 115, 562, 725, 1249`, `partner_routes.py:123`, `partner_service.py:52` | Rejects `"supabase"` tokens; rejects `_COMPROMISED_SECRETS`; requires `exp`, `iss`, `aud` (`L270–301`) |
| **Realm 2: `"supabase"`** | `SUPABASE_JWT_SECRET` via `get_supabase_jwt_secret()` (`jwt_secret.py:73–85`) | `HS256` (`L43, L235`) | `SUPABASE_JWT_ISSUER` (`"https://xkhqirhurnjqglmajghn.supabase.co/auth/v1"`, `L96–104`) | `SUPABASE_JWT_AUDIENCE` (`"authenticated"`, `L106–107`) | `verify_jwt_token_strict(..., realm="supabase")` (`jwt_secret.py:121–128, 195–302`) | Strictly isolated from `JWT_SECRET`; rejects `"core"` tokens; binds `iss` to Staging Supabase ref `xkhqirhurnjqglmajghn` |
| **Internal Magic Link** | `INTERNAL_MAGIC_SECRET` via `get_internal_magic_secret()` (`jwt_secret.py:305–310`) | Constant-time equality | N/A (Header secret) | Internal magic login | `auth_routes.py:285`, `app/api/endpoints/magic_login.py:21` | Returns `None` if unset or in `_COMPROMISED_SECRETS` -> callers return `HTTP 403 Forbidden` |
| **Inter-Service HMAC** | `BOONTRACK_HMAC_SECRET` via `_get_hmac_secret()` (`inter_service_auth.py:171–180`) | `HMAC-SHA256` + Redis Nonce | `X-BoonTrack-Timestamp` (`300s` window) | `X-BoonTrack-Nonce` (`STRICT_REPLAY_GUARD=true`) | `inter_service_auth.py:402–415` | Disjoint from `JWT_SECRET`; raises `ValueError` -> `HTTP 401` if unset; `HTTP 503` if Redis down |

1. **Zero Cross-Realm Fallback (`jwt_secret.py:110–131, 238–242`):** `get_jwt_trust_profile(realm)` resolves strictly one profile (`"core"` or `"supabase"`) and raises `ValueError(f"Unsupported JWT realm: {realm}")` for any other value. `verify_jwt_token_strict` never retries signature verification with the alternate realm's secret.
2. **Staging Non-Dev Enforcement (`jwt_secret.py:37, 49–55`):** `_DEV_ENV_NAMES = {"dev", "development", "local", "test", "testing"}` excludes `"staging"`. When `ENVIRONMENT=staging` and `APP_ENV=staging` (outside `pytest`), `_is_dev_or_test()` returns `False`, forcing `get_jwt_secret()` and `get_supabase_jwt_secret()` to raise `RuntimeError` if either secret is missing.
3. **Compromised Static Secret Ban (`jwt_secret.py:38–41, 63–64, 78–79, 308–309`):** `_COMPROMISED_SECRETS = {"boontrack-secret-key-production-3000", "boontrack-super-secret-2026"}` is unconditionally blocked across all environments.
4. **Secret Disjointness & Zero-Exposure Invariant:** `JWT_SECRET != SUPABASE_JWT_SECRET != BOONTRACK_HMAC_SECRET != INTERNAL_MAGIC_SECRET`, and all Staging secrets are independently generated and disjoint from Production secrets. Zero raw secret values, prefixes/suffixes, or live secret hashes may ever be printed or logged.

---

## 4. R2 STAGING BUCKET VERIFICATION AGAINST APPROVED INFRASTRUCTURE

Cross-checking `boontrack-core` (`app/services/storage/r2.py:53–56` and `app/services/r2_storage_service.py:9–13`) against the approved infrastructure specification (`docs/production-readiness/12_STAGING_ENVIRONMENT_PREPARATION.md:38, 222` and `13_R2_PROVISIONING_AND_PREDEPLOYMENT_VERIFICATION.md:8, 43–55`):

| Storage Parameter | Approved Infrastructure Spec (`12_*.md` & `13_*.md`) | Production Value (LOCKED) | Verified Staging Contract for `boontrack-core` |
| :--- | :--- | :--- | :--- |
| **Cloudflare Account ID (`R2_ACCOUNT_ID`)** | `56303bb13200d0980da8695adcf08550` | `56303bb13200d0980da8695adcf08550` | `56303bb13200d0980da8695adcf08550` |
| **Bucket Name (`R2_BUCKET_NAME`)** | **`boontrack-staging-renders`** (APAC Jurisdiction) | `boontrack-media` (and legacy `boontrack-documents`) | **`boontrack-staging-renders`** (Overrides `r2.py:56` & `r2_storage_service.py:12` defaults) |
| **Public Access & `r2.dev`** | Disabled (`0` custom domains; private access only) | `assets.boontrack.com` | Private presigned S3 URLs (`generate_presigned_download_url`); `r2.dev` disabled |
| **CORS & Lifecycle Policy** | Origin `https://staging-studio.boontrack.com` (`GET/HEAD`); `auto-purge-after-7-days` on `renders/staging/` | Production storefront origins | Verified active in Cloudflare R2; staging API credentials rotated & scoped to staging |

---

## 5. ONLINEBOOST STRICT HOLDS & CHECKOUT FEATURE GATE ENFORCEMENT

| Governance Gate Variable | Required Staging & Prod Value | Codebase Enforcement Location | Verified Runtime Behavior |
| :--- | :--- | :--- | :--- |
| `ONLINEBOOST_ALUMNI_BROADCAST_HOLD` | **`"true"`** (Explicit) | `app/services/meta_waba_service.py:437–471` | Blocks outbound broadcast templates `alumni_cpm_metode` and `alumni_cpm_metode_rahasia_v1`; records `status="HELD"`, `reason="ONLINEBOOST_ALUMNI_BROADCAST_HOLD_ACTIVE"`, `sent=0`. |
| `ONLINEBOOST_PAYMENT_STRICT_HOLD` | **`"true"`** (Explicit) | `app/services/academy_service.py:1010–1025, 2513` | Blocks live QRIS / Xendit invoice creation in OnlineBoost consultation & CTWA flows unless explicitly `"false"`. |
| `FEATURE_ONLINEBOOST_CHECKOUT_ENABLED` | **`"false"`** (Explicit) | `ONLINEBOOST_PHASE2B_RELEASE_READINESS.md:118` | Keeps OnlineBoost checkout killswitch disabled (`"false"`). |

---

## 6. ISOLATED PROPOSED PATCHES FOR CTO REVIEW (`PATCH-R1-A` .. `PATCH-R1-C`)

### 6.1 `PATCH-R1-A` — Dedicated Staging Compose File (`docker-compose.staging.yml` [NEW])

```diff
--- /dev/null
+++ b/docker-compose.staging.yml
@@ -0,0 +1,52 @@
+services:
+  backend:
+    build:
+      context: .
+      dockerfile: Dockerfile
+    container_name: boontrack_staging_backend
+    restart: unless-stopped
+    command: uvicorn app.main:app --host 0.0.0.0 --port 8000
+    ports:
+      - "127.0.0.1:${STAGING_PORT:-8001}:8000"
+    environment:
+      - PYTHONPATH=/app
+      - PORT=8000
+      - ENVIRONMENT=staging
+      - APP_ENV=staging
+      - RAILWAY_ENVIRONMENT=staging
+      # Tier 1: Boot-Time Fail-Closed Variables (Staging Ref: xkhqirhurnjqglmajghn)
+      - DATABASE_URL=${DATABASE_URL:?DATABASE_URL is mandatory for staging}
+      - SUPABASE_URL=${SUPABASE_URL:?SUPABASE_URL is mandatory for staging}
+      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY:?SUPABASE_ANON_KEY is mandatory for staging}
+      - SUPABASE_KEY=${SUPABASE_KEY:-${SUPABASE_ANON_KEY}}
+      - SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is mandatory}
+      - EVOLUTION_API_KEY=${EVOLUTION_API_KEY:?EVOLUTION_API_KEY is mandatory for staging}
+      - XENDIT_SECRET_KEY=${XENDIT_SECRET_KEY:?XENDIT_SECRET_KEY is mandatory for staging}
+      - XENDIT_CALLBACK_TOKEN=${XENDIT_CALLBACK_TOKEN:?XENDIT_CALLBACK_TOKEN is mandatory for staging}
+      - XENDIT_ENV=sandbox
+      # Tier 2: Cryptographic Realm & Inter-Service Fail-Closed Variables
+      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET is mandatory for staging}
+      - CORE_JWT_ISSUER=${CORE_JWT_ISSUER:-boontrack-core}
+      - CORE_JWT_AUDIENCE=${CORE_JWT_AUDIENCE:-boontrack-core}
+      - SUPABASE_JWT_SECRET=${SUPABASE_JWT_SECRET:?SUPABASE_JWT_SECRET is mandatory for staging}
+      - SUPABASE_JWT_ISSUER=${SUPABASE_JWT_ISSUER:-https://xkhqirhurnjqglmajghn.supabase.co/auth/v1}
+      - SUPABASE_JWT_AUDIENCE=${SUPABASE_JWT_AUDIENCE:-authenticated}
+      - INTERNAL_MAGIC_SECRET=${INTERNAL_MAGIC_SECRET:?INTERNAL_MAGIC_SECRET is mandatory}
+      - BOONTRACK_HMAC_SECRET=${BOONTRACK_HMAC_SECRET:?BOONTRACK_HMAC_SECRET is mandatory}
+      - STRICT_REPLAY_GUARD=true
+      - REDIS_URL=${REDIS_URL:?REDIS_URL is mandatory for staging replay guard}
+      - APP_MASTER_KEY=${APP_MASTER_KEY:?APP_MASTER_KEY is mandatory}
+      - APP_SECRET_KEY=${APP_SECRET_KEY:?APP_SECRET_KEY is mandatory}
+      - PII_HASH_SALT=${PII_HASH_SALT:?PII_HASH_SALT is mandatory}
+      # Approved Cloudflare R2 Staging Bucket (boontrack-staging-renders)
+      - R2_ACCOUNT_ID=${R2_ACCOUNT_ID:?R2_ACCOUNT_ID is mandatory}
+      - R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID is mandatory}
+      - R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY is mandatory}
+      - R2_BUCKET_NAME=boontrack-staging-renders
+      # Mandatory OnlineBoost Strict Hold Gates (Explicitly Locked)
+      - ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true
+      - ONLINEBOOST_PAYMENT_STRICT_HOLD=true
+      - FEATURE_ONLINEBOOST_CHECKOUT_ENABLED=false
+    healthcheck:
+      test: ["CMD", "python", "-c", "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).getcode() == 200 else 1)"]
+      interval: 10s
+      timeout: 5s
+      retries: 3
+      start_period: 10s
```

### 6.2 `PATCH-R1-B` — Production Compose Hardening (`docker-compose.prod.yml`)

```diff
--- a/docker-compose.prod.yml
+++ b/docker-compose.prod.yml
@@ -26,13 +26,29 @@ services:
       - XENDIT_CALLBACK_TOKEN=${XENDIT_CALLBACK_TOKEN}
-      - BOONTRACK_HMAC_SECRET=${BOONTRACK_HMAC_SECRET:-}
+      - BOONTRACK_HMAC_SECRET=${BOONTRACK_HMAC_SECRET:?BOONTRACK_HMAC_SECRET is mandatory}
+      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET is mandatory}
+      - SUPABASE_JWT_SECRET=${SUPABASE_JWT_SECRET:?SUPABASE_JWT_SECRET is mandatory}
+      - CORE_JWT_ISSUER=${CORE_JWT_ISSUER:-boontrack-core}
+      - CORE_JWT_AUDIENCE=${CORE_JWT_AUDIENCE:-boontrack-core}
+      - SUPABASE_JWT_ISSUER=${SUPABASE_JWT_ISSUER:-https://mpluzajlzpregmjwpjqr.supabase.co/auth/v1}
+      - SUPABASE_JWT_AUDIENCE=${SUPABASE_JWT_AUDIENCE:-authenticated}
+      - INTERNAL_MAGIC_SECRET=${INTERNAL_MAGIC_SECRET:?INTERNAL_MAGIC_SECRET is mandatory}
+      - APP_MASTER_KEY=${APP_MASTER_KEY:?APP_MASTER_KEY is mandatory}
+      - APP_SECRET_KEY=${APP_SECRET_KEY:?APP_SECRET_KEY is mandatory}
+      - PII_HASH_SALT=${PII_HASH_SALT:?PII_HASH_SALT is mandatory}
       - ENVIRONMENT=${ENVIRONMENT:-production}
+      - APP_ENV=${APP_ENV:-production}
       - RAILWAY_ENVIRONMENT=${RAILWAY_ENVIRONMENT:-standby}
+      - STRICT_REPLAY_GUARD=true
+      - ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true
+      - ONLINEBOOST_PAYMENT_STRICT_HOLD=true
+      - FEATURE_ONLINEBOOST_CHECKOUT_ENABLED=false
       - REDIS_URL=${REDIS_URL:-}
       - META_WABA_PHONE_NUMBER_ID=${META_WABA_PHONE_NUMBER_ID:-}
       - WHATSAPP_VERIFY_TOKEN=${WHATSAPP_VERIFY_TOKEN:-}
       - EVOLUTION_API_URL=${EVOLUTION_API_URL:-}
       - RESEND_API_KEY=${RESEND_API_KEY:-}
       - R2_ACCESS_KEY_ID=${R2_ACCESS_KEY_ID:-}
       - R2_SECRET_ACCESS_KEY=${R2_SECRET_ACCESS_KEY:-}
       - R2_ACCOUNT_ID=${R2_ACCOUNT_ID:-}
+      - R2_BUCKET_NAME=${R2_BUCKET_NAME:-boontrack-media}
```

### 6.3 `PATCH-R1-C` — Environment Contract Template (`.env.example`)

```diff
--- a/.env.example
+++ b/.env.example
@@ -12,5 +12,12 @@ SUPABASE_KEY="test_secret_placeholder_supabase_key"
 SUPABASE_ANON_KEY="test_secret_placeholder_supabase_anon_key"
+SUPABASE_SERVICE_ROLE_KEY="test_secret_placeholder_supabase_service_role_key"
 
 # --- SERVER & RUNTIME ---
 PORT="8080"
-PYTHON_VERSION="3.10.13"
+PYTHON_VERSION="3.11"
+ENVIRONMENT="staging"
+APP_ENV="staging"
+RAILWAY_ENVIRONMENT="staging"
+ONLINEBOOST_ALUMNI_BROADCAST_HOLD="true"
+ONLINEBOOST_PAYMENT_STRICT_HOLD="true"
+FEATURE_ONLINEBOOST_CHECKOUT_ENABLED="false"
+STRICT_REPLAY_GUARD="true"
 BACKEND_URL="http://localhost:8000/api/v1/search"
@@ -63,3 +70,17 @@ WHATSAPP_VERIFY_TOKEN="test_secret_placeholder_verify_token"
 APP_MASTER_KEY="test_secret_placeholder_master_key_32bytes_len!"
+APP_SECRET_KEY="test_secret_placeholder_app_secret_key_32bytes!"
 PII_HASH_SALT="test_secret_placeholder_pii_salt"
+JWT_SECRET="test_secret_placeholder_core_jwt_secret_minimum_32_bytes"
+CORE_JWT_ISSUER="boontrack-core"
+CORE_JWT_AUDIENCE="boontrack-core"
+SUPABASE_JWT_SECRET="test_secret_placeholder_supabase_jwt_secret_isolated"
+SUPABASE_JWT_ISSUER="https://xkhqirhurnjqglmajghn.supabase.co/auth/v1"
+SUPABASE_JWT_AUDIENCE="authenticated"
+INTERNAL_MAGIC_SECRET="test_secret_placeholder_internal_magic_secret_32bytes"
+BOONTRACK_HMAC_SECRET="test_secret_placeholder_inter_service_hmac_secret_32bytes"
+REDIS_URL="redis://localhost:6379/0"
+R2_ACCOUNT_ID="56303bb13200d0980da8695adcf08550"
+R2_ACCESS_KEY_ID="test_secret_placeholder_r2_access_key_id"
+R2_SECRET_ACCESS_KEY="test_secret_placeholder_r2_secret_access_key"
+R2_BUCKET_NAME="boontrack-staging-renders"
```


