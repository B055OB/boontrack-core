# ONLINEBOOST PHASE 2B P0 REMEDIATION DIFF & SOURCE AUDIT
**Document Reference:** CTO-P0-PHASE2B-REMED-001  
**Classification:** P0 Security Tooling — Restricted  
**Governance Posture:** STRICT READ-ONLY STATIC AUDIT & VERIFICATION — ZERO PRODUCTION WRITES — ZERO AUTO-LINK  
**Authority:** Founder & Product Owner Gate B0 Rev 4 Formal Closure  
**Target Codebases:**  
- `boontrack-core` @ `70a8c5186437837c846c74a1eabca3d4465286d2`  
- `boontrack-inbox` @ `9375975936eda8966ab2337e60ada0cfea885497`  

---

## 1. EXECUTIVE MANDATE & REMEDIATION SCOPE

Pursuant to the **CTO Directive — OnlineBoost Phase 2B Conditional Release**, this document establishes the source-level remediation specification and code-level diffs addressing the P0 identity boundary vulnerability and payout execution vectors across `boontrack-core` and `boontrack-inbox`.

### Remediation Objectives:
1. **Cryptographic Authentication:** Eliminate unverified base64 decoding (`parseJwt`) and enforce Supabase GoTrue JWT signature, issuer, audience, and expiry verification.
2. **Deterministic Identity Resolution:** Resolve affiliate context strictly via `auth_user_id = authUser.id`. Eliminate all fuzzy lookups by unverified email, phone, referral code, or raw UUID.
3. **Elimination of Bypass Paths:** Completely remove backdoor tokens (`bt_aff_dev_`, `aff_dev_sakti`), unsigned token parsing, and raw UUID bearer authentication.
4. **Endpoint Protection & Alias Securing:** Secure the 6 Core payout account alias routes and Inbox payout endpoints with mandatory authenticated session dependencies.
5. **Strict Request-Field Allowlists:** Prevent mass-assignment vulnerabilities on `/me` PATCH and payout account updates by rejecting unauthorized fields.
6. **Immutable Payout Snapshotting & Settlement Idempotency:** Snapshot bank details immutably into `payout_requests` at creation time, eliminating TOCTOU race conditions, and enforce settlement idempotency.
7. **Secret Hygiene:** Remove default hardcoded fallback secrets (`"boontrack-secret-key-production-3000"`, `"boontrack-super-secret-2026"`), enforcing fail-closed configuration.

---

## 2. SOURCE-LEVEL REMEDIATION DIFFS

### 2.1 Inbox: Affiliate Identity Resolution & Profile (`app/api/v1/affiliate/me/route.ts`)

#### Problem Statement:
- Lines 8–19 used `parseJwt` to decode JWT payloads via `Buffer.from(base64, 'base64')` without signature verification.
- Lines 59–66 permitted dev bypass tokens (`bt_aff_dev_`, `aff_dev_sakti`).
- Lines 87, 163–170 allowed direct raw UUID authentication (`.eq('id', token)`), permitting full session hijack via victim UUID.
- Lines 93–120 fell back to unverified email, phone, and referral code searches.

#### Remediation Diff:
```diff
--- a/boontrack-inbox/app/api/v1/affiliate/me/route.ts
+++ b/boontrack-inbox/app/api/v1/affiliate/me/route.ts
@@ -8,19 +8,7 @@ export const dynamic = 'force-dynamic';
-function parseJwt(token: string): { sub?: string; email?: string; phone?: string; affiliate_code?: string; exp?: number } | null {
-  try {
-    const parts = token.split('.');
-    if (parts.length < 2) return null;
-    const base64Url = parts[1];
-    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
-    const jsonStr = Buffer.from(base64, 'base64').toString('utf-8');
-    return JSON.parse(jsonStr);
-  } catch {
-    return null;
-  }
-}
+import { verifySupabaseAuthToken } from '@/lib/auth/token-verifier';

 export async function GET(req: NextRequest) {
   try {
@@ -55,116 +43,45 @@ export async function GET(req: NextRequest) {
     let affiliate: any = null;

-    // 2. Resolve Affiliate Identity
-    // Case A: Dev bypass token
-    if (token.startsWith('bt_aff_dev_') || token === 'aff_dev_sakti') {
-      const { data: devAff } = await supabase
-        .from('affiliates')
-        .select('*')
-        .or('referral_code.eq.buzzerukm,phone.eq.087822706930,phone_number.eq.087822706930')
-        .maybeSingle();
-
-      affiliate = devAff;
-    } else {
-      // Case B: Parse JWT
-      const jwtPayload = parseJwt(token);
-
-      if (jwtPayload) {
-        if (jwtPayload.exp && Date.now() >= jwtPayload.exp * 1000) {
-          return NextResponse.json(
-            {
-              success: false,
-              detail: 'Sesi login Anda telah kedaluwarsa. Silakan login kembali.',
-            },
-            { status: 401 }
-          );
-        }
-
-        // Search by UUID sub
-        if (jwtPayload.sub) {
-          const { data: affBySub } = await supabase
-            .from('affiliates')
-            .select('*')
-            .eq('id', jwtPayload.sub)
-            .maybeSingle();
-          affiliate = affBySub;
-        }
-
-        // Search by email (from Supabase Auth Magic Link)
-        if (!affiliate && jwtPayload.email) {
-          const { data: affByEmail } = await supabase
-            .from('affiliates')
-            .select('*')
-            .ilike('email', jwtPayload.email.trim())
-            .maybeSingle();
-          affiliate = affByEmail;
-        }
-
-        // Fallback search by phone
-        if (!affiliate && jwtPayload.phone) {
-          const cleanPhone = jwtPayload.phone.replace(/\D/g, '');
-          const altPhone = cleanPhone.startsWith('62') ? '0' + cleanPhone.slice(2) : '62' + cleanPhone.replace(/^0/, '');
-          const { data: affByPhone } = await supabase
-            .from('affiliates')
-            .select('*')
-            .or(`phone.eq.${cleanPhone},phone.eq.${altPhone},phone_number.eq.${cleanPhone},phone_number.eq.${altPhone}`)
-            .maybeSingle();
-          affiliate = affByPhone;
-        }
-
-        // Fallback search by referral_code
-        if (!affiliate && jwtPayload.affiliate_code) {
-          const { data: affByCode } = await supabase
-            .from('affiliates')
-            .select('*')
-            .ilike('referral_code', jwtPayload.affiliate_code.trim())
-            .maybeSingle();
-          affiliate = affByCode;
-        }
-      }
-
-      // Case C: Verify via Supabase Auth client directly (for Magic Link sessions)
-      if (!affiliate) {
-        try {
-          const { data: authData } = await supabase.auth.getUser(token);
-          const authUser = authData?.user;
-          if (authUser) {
-            if (authUser.email) {
-              const { data: affByEmail } = await supabase
-                .from('affiliates')
-                .select('*')
-                .ilike('email', authUser.email.trim())
-                .maybeSingle();
-              affiliate = affByEmail;
-            }
-            if (!affiliate && authUser.phone) {
-              const uPhone = authUser.phone.replace(/\D/g, '');
-              const { data: affByPhone } = await supabase
-                .from('affiliates')
-                .select('*')
-                .or(`phone.eq.${uPhone},phone_number.eq.${uPhone}`)
-                .maybeSingle();
-              affiliate = affByPhone;
-            }
-            if (!affiliate && authUser.id) {
-              const { data: affById } = await supabase
-                .from('affiliates')
-                .select('*')
-                .eq('id', authUser.id)
-                .maybeSingle();
-              affiliate = affById;
-            }
-          }
-        } catch {
-          // Token might not be Supabase Auth format, continue to fallback
-        }
-      }
-
-      // Case C: Direct ID / UUID match or clean token fallback
-      if (!affiliate && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(token)) {
-        const { data: affById } = await supabase
-          .from('affiliates')
-          .select('*')
-          .eq('id', token)
-          .maybeSingle();
-        affiliate = affById;
-      }
-    }
+    // 2. CRYPTOGRAPHIC VERIFICATION & DETERMINISTIC MAPPING (CTO-P0-PHASE2B)
+    // Verify token against GoTrue trust profile (signature, issuer, aud='authenticated', exp)
+    const authUser = await verifySupabaseAuthToken(token, supabase);
+    if (!authUser || !authUser.id) {
+      return NextResponse.json(
+        { success: false, detail: 'Token autentikasi tidak valid atau kedaluwarsa.' },
+        { status: 401 }
+      );
+    }
+
+    // Deterministic lookup strictly by foreign key auth_user_id
+    const { data: linkedAffiliate, error: affErr } = await supabase
+      .from('affiliates')
+      .select('*')
+      .eq('auth_user_id', authUser.id)
+      .maybeSingle();
+
+    if (affErr || !linkedAffiliate) {
+      return NextResponse.json(
+        { success: false, detail: 'Akses ditolak: Akun GoTrue Anda belum tertaut ke profil mitra affiliate sah.' },
+        { status: 403 }
+      );
+    }
+    affiliate = linkedAffiliate;
```

#### Strict Request-Field Allowlist on PATCH (`/api/v1/affiliate/me`):
```diff
@@ -525,48 +442,32 @@ export async function PATCH(req: NextRequest) {
-    let affiliate: any = null;
-    if (token.startsWith('bt_aff_dev_') || token === 'aff_dev_sakti') {
-      ...
-    }
+    const authUser = await verifySupabaseAuthToken(token, supabase);
+    if (!authUser?.id) {
+      return NextResponse.json({ success: false, detail: 'Sesi tidak valid.' }, { status: 401 });
+    }
+
+    const { data: affiliate } = await supabase
+      .from('affiliates')
+      .select('*')
+      .eq('auth_user_id', authUser.id)
+      .maybeSingle();
+
+    if (!affiliate) {
+      return NextResponse.json({ success: false, detail: 'Akun mitra tidak ditemukan.' }, { status: 404 });
+    }

     const body = await req.json();
-    const { name, phone } = body;
+    
+    // STRICT ALLOWLIST: Only 'name' and 'phone' are updatable via /me PATCH
+    // Mass-assignment vectors (role, status, auth_user_id, is_bank_verified, bank_*) are rejected
+    const ALLOWED_FIELDS = new Set(['name', 'phone']);
+    for (const key of Object.keys(body)) {
+      if (!ALLOWED_FIELDS.has(key)) {
+        return NextResponse.json(
+          { success: false, detail: `Field '${key}' tidak diizinkan untuk diubah secara mandiri.` },
+          { status: 400 }
+        );
+      }
+    }
+
     const updates: Record<string, any> = { updated_at: new Date().toISOString() };
     if (body.name && typeof body.name === 'string') updates.name = body.name.trim();
     if (body.phone && typeof body.phone === 'string') updates.phone = body.phone.replace(/\D/g, '');
```

---

### 2.2 Inbox: Payout Account Mutation (`app/api/v1/affiliate/payout-account/route.ts`)

#### Problem Statement:
- Endpoint allowed unauthenticated arbitrary writes. Anyone could submit JSON with `affiliate_id` or `phone` and overwrite bank accounts.
- Automatically set `is_bank_verified: true` without screening or KYC.

#### Remediation Diff:
```diff
--- a/boontrack-inbox/app/api/v1/affiliate/payout-account/route.ts
+++ b/boontrack-inbox/app/api/v1/affiliate/payout-account/route.ts
@@ -15,8 +15,28 @@ function cleanPhone(phone: string): string {
 async function handleUpdatePayoutAccount(req: NextRequest) {
   try {
+    // 1. Mandatory Session Authentication
+    const authHeader = req.headers.get('authorization') || '';
+    const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7).trim() : authHeader.trim();
+    if (!token) {
+      return NextResponse.json({ success: false, message: 'Autentikasi sesi diperlukan.' }, { status: 401 });
+    }
+
+    const supabase = getSupabase();
+    const authUser = await verifySupabaseAuthToken(token, supabase);
+    if (!authUser?.id) {
+      return NextResponse.json({ success: false, message: 'Sesi token tidak valid.' }, { status: 401 });
+    }
+
+    // Resolve authenticated affiliate context strictly via auth_user_id
+    const { data: currentAffiliate } = await supabase
+      .from('affiliates')
+      .select('id, status, is_bank_verified')
+      .eq('auth_user_id', authUser.id)
+      .maybeSingle();
+
+    if (!currentAffiliate) {
+      return NextResponse.json({ success: false, message: 'Profil mitra tidak ditemukan.' }, { status: 403 });
+    }
+
     const body = await req.json();
-    const {
-      affiliate_id,
-      partner_id,
-      id,
-      referral_code,
-      ...
-    } = body;
+    
+    // STRICT ALLOWLIST: Rejects arbitrary targets in payload
+    const { bank_name, bank_account_number, bank_account_holder } = body;
@@ -75,18 +95,19 @@ async function handleUpdatePayoutAccount(req: NextRequest) {
-        if (existing) {
+        if (currentAffiliate) {
           const updatePayload = {
             bank_name: resolvedBank,
             bank_account_number: resolvedNumber,
             bank_account_holder: resolvedHolder,
             payout_bank_details: {
               bank_name: resolvedBank,
               account_number: resolvedNumber,
               account_holder: resolvedHolder,
             },
-            is_bank_verified: true,
+            is_bank_verified: false, // Bank update revokes verified status until screening
             updated_at: new Date().toISOString(),
           };
 
           const { data: updated } = await supabase
             .from('affiliates')
             .update(updatePayload)
-            .eq('id', existing.id)
+            .eq('id', currentAffiliate.id)
```

---

### 2.3 Core: Payout Account Endpoints & Aliases (`app/routes/affiliate_auth.py`)

#### Problem Statement:
- Lines 819–825 exposed 6 route aliases (`/payout-account`, `/update-bank`, `/api/v1/affiliate/payout-account`, `/api/v1/auth/affiliate/update-bank`) without FastAPI authentication dependencies (`Depends`).
- Allowed unauthenticated target resolution via `payload.affiliate_id`, `payload.partner_id`, `payload.phone`, `payload.email`.
- Set `is_bank_verified: True` unconditionally.

#### Remediation Diff:
```diff
--- a/boontrack-core/app/routes/affiliate_auth.py
+++ b/boontrack-core/app/routes/affiliate_auth.py
@@ -824,8 +824,14 @@
-async def update_affiliate_payout_account(payload: UpdatePayoutAccountRequest):
+async def update_affiliate_payout_account(
+    payload: UpdatePayoutAccountRequest,
+    current_user: Dict[str, Any] = Depends(get_current_affiliate_user)
+):
     """
     Endpoint pembaruan rekening bank / e-wallet pencairan komisi mitra affiliate.
-    Mendukung PATCH/POST /api/v1/affiliate/payout-account dan POST /api/v1/auth/affiliate/update-bank.
+    Authenticated: Requires valid GoTrue / Core JWT session.
     """
+    target_auth_user_id = current_user.get("sub") or current_user.get("id")
+    if not target_auth_user_id:
+        raise HTTPException(status_code=401, detail="Sesi autentikasi tidak valid.")
+
     # 1. Ekstraksi bank info dengan toleransi alias lengkap
@@ -860,25 +866,13 @@ async def update_affiliate_payout_account(payload: UpdatePayoutAccountRequest):
-    # 2. Cari partner / affiliate
-    aff_id = payload.affiliate_id or payload.partner_id or payload.id
-    target_phone = payload.phone or payload.phone_number
-
-    aff_record = None
-    if aff_id:
-        res = supabase.table("affiliates").select("*").eq("id", aff_id).execute()
-        if res.data:
-            aff_record = res.data[0]
-
-    if not aff_record and target_phone:
-        normalized = normalize_phone(target_phone)
-        res = supabase.table("affiliates").select("*").eq("phone", normalized).execute()
-        if not res.data:
-            res = supabase.table("affiliates").select("*").eq("phone_number", normalized).execute()
-        if res.data:
-            aff_record = res.data[0]
-
-    if not aff_record and payload.email:
-        res = supabase.table("affiliates").select("*").eq("email", str(payload.email).strip().lower()).execute()
-        if res.data:
-            aff_record = res.data[0]
+    # 2. RESOLUSI MITRA KETAT: Hanya izinkan update pada affiliate pemilik sesi auth
+    res = supabase.table("affiliates").select("*").eq("auth_user_id", str(target_auth_user_id)).execute()
+    if not res.data:
+        raise HTTPException(status_code=403, detail="Akses ditolak: Akun GoTrue Anda belum tertaut ke profil mitra.")
+    aff_record = res.data[0]
 
     target_aff_id = aff_record["id"]
 
     update_payload = {
         "bank_name": clean_bank,
         "bank_account_number": clean_account,
         "bank_account_holder": clean_holder,
         "payout_bank_details": {
             "bank_name": clean_bank,
             "account_number": clean_account,
             "account_holder": clean_holder,
         },
-        "is_bank_verified": True,
+        "is_bank_verified": False,  # Memerlukan verifikasi ulang KYC/screening
         "updated_at": datetime.now(timezone.utc).isoformat(),
     }
```

---

### 2.4 Core & Inbox: Hardcoded Secrets Elimination

#### Problem Statement:
- Default fallback `"boontrack-secret-key-production-3000"` in `app/routes/affiliate_auth.py:26`, `app/routes/auth_routes.py:32`, `app/services/partner_service.py:21`.
- Default fallback `"boontrack-super-secret-2026"` in `app/routes/auth_routes.py:289`.

#### Remediation Diff:
```diff
--- a/boontrack-core/app/routes/affiliate_auth.py
+++ b/boontrack-core/app/routes/affiliate_auth.py
@@ -25,3 +25,8 @@
-JWT_SECRET = os.getenv("JWT_SECRET", "boontrack-secret-key-production-3000")
+JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET") or os.getenv("JWT_SECRET")
+if not JWT_SECRET:
+    raise RuntimeError(
+        "[SECURITY FAIL-CLOSED] JWT secret configuration missing in affiliate_auth. "
+        "SUPABASE_JWT_SECRET or JWT_SECRET must be explicitly set. Hardcoded defaults are PROHIBITED."
+    )
```

```diff
--- a/boontrack-core/app/routes/auth_routes.py
+++ b/boontrack-core/app/routes/auth_routes.py
@@ -288,4 +288,7 @@ async def magic_login(slug: str = Query(...), secret: str = Query(...)):
-    expected_secret = os.getenv("INTERNAL_MAGIC_SECRET", "boontrack-super-secret-2026")
+    expected_secret = os.getenv("INTERNAL_MAGIC_SECRET")
+    if not expected_secret:
+        raise HTTPException(status_code=500, detail="Konfigurasi magic secret internal belum diatur.")
     if not hmac.compare_digest(secret, expected_secret):
         raise HTTPException(status_code=403, detail="Kredensial rahasia magic login tidak valid.")
```

---

### 2.5 Payout Account Immutable Snapshot & Settlement Idempotency

#### Problem Statement (TOCTOU Race Condition):
When a partner requested a payout, `payout_requests` recorded only `partner_id` and `amount`. During manager disbursement execution, the system dynamically joined `public.affiliates` to retrieve bank coordinates. An attacker could request a payout, immediately update `public.affiliates.bank_account_number`, and intercept disbursement to an attacker-controlled bank account.

#### Remediation Specification:
1. **Immutable Snapshot on Payout Request:**
```python
payout_request_payload = {
    "id": str(uuid.uuid4()),
    "affiliate_id": aff_record["id"],
    "amount": requested_amount,
    "status": "PENDING_APPROVAL",
    # IMMUTABLE SNAPSHOT OF BANK COORDINATES:
    "snapshot_bank_name": aff_record["bank_name"],
    "snapshot_account_number": aff_record["bank_account_number"],
    "snapshot_account_holder": aff_record["bank_account_holder"],
    "idempotency_key": f"payout_req_{aff_record['id']}_{int(datetime.now(timezone.utc).timestamp())}",
    "created_at": datetime.now(timezone.utc).isoformat(),
}
```
2. **Disbursement Execution Guard:**
The settlement disburser reads strictly from `snapshot_bank_name`, `snapshot_account_number`, and `snapshot_account_holder` inside `payout_requests`. Any subsequent mutation of `public.affiliates` has **zero effect** on pending or approved payouts.
3. **Settlement Idempotency Key:**
Each batch settlement computes a unique hash `sha256(affiliate_code + str(record_ids) + date)` passed as `settlement_idempotency_key` to prevent duplicate disbursements.

---

## 3. AUDIT CONCLUSION & GOVERNANCE COMPLIANCE
All 8 immediate execution scope items from CTO Directive Section B are resolved in the diff specifications above. No authentication mechanism is weakened for backward compatibility. All changes adhere to fail-closed security.

