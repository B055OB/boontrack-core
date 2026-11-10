# Security Contract Proposal: Tenant Ownership Mutation in Public Registration

**Repository:** `B055OB/boontrack-core`  
**Target Component:** `app/routes/auth_routes.py` (`handle_register_logic`)  
**Associated PR:** PR #28 (`security/upload-auth-hardening-issue-27`)  
**Associated Issue:** Issue #27  
**Date:** 2026-11-10  
**Classification:** Critical Trust Boundary / Stop Condition Triggered  

---

## 1. Vulnerability & Trust Boundary Audit Evidence

In accordance with the CTO Work Order directive, a comprehensive architectural inspection of the registration and authentication contract was conducted across:
- `handle_register_logic()` ([`app/routes/auth_routes.py`](file:///C:/boontrack-core/app/routes/auth_routes.py#L312-L356))
- `generate_session_jwt()` ([`app/routes/auth_routes.py`](file:///C:/boontrack-core/app/routes/auth_routes.py#L117-L132))
- `POST /api/v1/auth/register` and `POST /api/v1/auth/magic-link/register`
- `get_supabase()` ([`app/services/whatsapp/credentials.py`](file:///C:/boontrack-core/app/services/whatsapp/credentials.py#L21-L48))
- Table `merchants` conflict resolution semantics

### Required Audit Findings

| Investigation Vector | Finding | Evidence & Source Details |
| :--- | :--- | :--- |
| **Is registration public?** | **YES** | Both `POST /api/v1/auth/register` and `POST /api/v1/auth/magic-link/register` are registered as public endpoints accepting unauthenticated requests. |
| **Is email verified before session issuance?** | **NO** | `handle_register_logic` sends an asynchronous welcome notification (`send_merchant_welcome_email`), but immediately issues a signed JWT session via `generate_session_jwt` without awaiting email OTP or magic link confirmation. |
| **Can an existing slug be overwritten?** | **YES (Code Contract)** | Line 321–328 executes `supabase.table("merchants").upsert(..., on_conflict="slug")`. In PostgreSQL / Supabase, an upsert on conflicting `slug` executes `ON CONFLICT (slug) DO UPDATE`, which replaces `owner_email`, `owner_name`, `store_name`, and `status`. |
| **Which Supabase credential type is selected?** | **CONDITIONAL** | In `app/services/whatsapp/credentials.py`, `get_supabase()` selects `SUPABASE_SERVICE_ROLE_KEY` (which bypasses PostgreSQL Row-Level Security via `BYPASSRLS`) **if that environment variable is populated**; otherwise it falls back to `SUPABASE_ANON_KEY`. Production environment secret values have not been directly probed to avoid secret exposure. |
| **Does database policy prevent conflict updates?** | **CONDITIONAL / UNVERIFIED** | If the service role key is active in the environment, RLS is bypassed. If only the anon key is active, RLS applies. Live database triggers or policies have not been probed to respect production isolation. |
| **Does principal own matching merchant record?** | **ARCHITECTURAL VULNERABILITY** | An unverified registrant submitting an existing tenant's `tenant_slug` (e.g. `warung-kopi`) will overwrite `owner_email`. The upload membership validator (`validate_merchant_tenant_membership`) then queries `merchants` and finds `owner_email == registrant_email`, authorizing them as the tenant owner. |

> [!IMPORTANT]
> **Evidence Scope Notice:** Live production exploitability has NOT been verified against production infrastructure in compliance with safety guardrails (no live mutation or unauthorized probing). The findings above document an authoritative architectural code vulnerability in `handle_register_logic`.

---

## 2. Root Cause Analysis

Lines 321–328 of [`app/routes/auth_routes.py`](file:///C:/boontrack-core/app/routes/auth_routes.py#L321-L328):
```python
supabase.table("merchants").upsert({
    "slug": slug,
    "store_name": req.store_name or user_name,
    "owner_name": user_name,
    "owner_email": user_email,
    "owner_whatsapp": req.phone or "",
    "status": "ACTIVE",
}, on_conflict="slug").execute()
```

If an attacker calls `POST /api/v1/auth/register`:
```json
{
  "email": "attacker@evil.com",
  "name": "Attacker",
  "tenant_slug": "victim-store"
}
```
1. Under the upsert contract, the `merchants` record for `victim-store` has its `owner_email` overwritten to `"attacker@evil.com"`.
2. A valid signed session JWT is generated for `attacker@evil.com` bound to `victim-store`.
3. The upload membership validator (`validate_merchant_tenant_membership`) queries `merchants WHERE slug = 'victim-store' AND lower(owner_email) = 'attacker@evil.com'`, finds a match, and grants upload permissions.

---

## 3. Minimal Remediation Proposals (For CTO Approval)

In strict adherence to the **STOP CONDITION**, no global auth routes or registration semantics were silently modified in PR #28. The following three architectural options are submitted for CTO selection:

### Option A: Fail-Closed Slug Collision Check (Recommended Minimal Change)
Before persisting in `handle_register_logic`:
1. Query `merchants` by `slug`.
2. If row exists and `lower(owner_email) != user_email`:
   - Raise `HTTPException(status_code=409, detail="Tenant slug is already registered to another owner.")`.
3. Query active `slug_reservations` where `status = 'RESERVED'` and `expires_at > now()`.
   - If found and not owned by user: raise `HTTPException(status_code=409, detail="Tenant slug is reserved.")`.
4. If row exists and `lower(owner_email) == user_email`:
   - Treat as idempotent onboarding update or re-login.
5. If row does not exist:
   - Perform atomic `insert` (NOT upsert on conflict).

### Option B: Pure Insert with DB Unique Constraint Enforcement
Replace `upsert(..., on_conflict="slug")` with `insert(...)`:
- If `slug` exists, PostgreSQL throws a unique constraint violation (`23505`).
- Handler catches duplicate error and returns `HTTP 409 Conflict`.
- Guarantees zero overwrite capability at the database transaction boundary.

### Option C: Gated Activation via Magic Link / Email Verification
- Do not issue signed merchant session JWT in `handle_register_logic`.
- Registration only creates an unactivated merchant (`status = 'PENDING_VERIFICATION'`) and dispatches a magic link with OTP.
- The session JWT is ONLY issued upon calling `/api/v1/auth/magic-link/verify` with a valid cryptographic token.

---

## 4. Current State & Blast Radius
- The upload authorization gate (`authorize_tenant_upload`) is completely fail-closed and strictly verifies database membership against `cs_agents` and `merchants`.
- However, as long as `handle_register_logic` allows public upsert overwrites on `slug`, the provenance of the `merchants` row can be tampered with via the registration endpoint.
- **Action Required:** CTO review and formal directive on which option (A, B, or C) to apply in a dedicated auth-hardening PR.

