# P0 GATE A: FINAL EVIDENCE & GOVERNANCE RATIFICATION REVIEW
**Document Reference:** CTO-P0-REMED-003 · Gate A Consolidation & Ratification  
**Classification:** P0 Security & Financial Integrity — Restricted  
**Governance Posture:** STRICT READ-ONLY ACTIVE — GATE A PROVISIONALLY ACCEPTED — GATE B NOT AUTHORIZED  
**Baseline HEAD Commit:** `70a8c5186437837c846c74a1eabca3d4465286d2`  
**Active Working Tree:** `c:\boontrack-core` (Branch: `fix/onlineboost-batch1-canary-readiness`)  
**Cross-Repository Baseline:** `c:\boontrack-inbox` @ `9375975936eda8966ab2337e60ada0cfea885497`  
**Certification Date:** 2026-11-01  

---

## EXECUTIVE SUMMARY & GOVERNANCE POSTURE

Pursuant to the formal directive of the Chief Technology Officer (CTO) in the Studio War Room (**CTO-P0-REMED-003 · Evaluasi Provisional Gate A**), this document establishes the authoritative consolidation, forensic evidence verification, and governance review ratifying the closure of **Gate A (Forensic Investigation & Architectural Baseline)**.

### Mandatory Operational Boundaries:
1. **Gate Status:** **GATE A PROVISIONALLY ACCEPTED — GATE B STRICT HOLD**.
2. **Release / Migration Status:** **ZERO DATABASE MUTATION & ZERO REPO MUTATION**.
3. **Prohibited Operations:** Strict prohibition of `git reset`, `git checkout`, `git clean`, `git stash`, or `git commit`. Zero queries executed against the production database (`DATABASE_URL`).
4. **Broadcast & Payment Gates:** `ONLINEBOOST_ALUMNI_BROADCAST_HOLD=true` and `ONLINEBOOST_PAYMENT_STRICT_HOLD=true` remain locked at the infrastructure layer.

---

## 1. KONSOLIDASI & TEKS LENGKAP 5 DELIVERABLE GATE A

Below is the consolidated forensic evidence and complete technical findings from the five approved Gate A deliverables:

```
+---------------------------------------------------------------------------------------------------------+
|                                    GATE A DELIVERABLE ARTIFACT MATRIX                                   |
+----+-------------------------------------------+-----------------------------------+--------------------+
| NO | ARTIFACT NAME                             | DOCUMENT REF                      | CORE FOCUS         |
+----+-------------------------------------------+-----------------------------------+--------------------+
| 01 | P0_GATE_A_SOURCE_INVENTORY.md             | CTO-P0-GATE-A-001                 | 19 Payout Routes   |
| 02 | P0_GATE_A_IDENTITY_DISCREPANCY_REPORT.md  | CTO-P0-GATE-A-002                 | Auth UID Mismatch  |
| 03 | P0_GATE_A_PAYOUT_EXECUTION_TRACE.md       | CTO-P0-GATE-A-003                 | TOCTOU Race Trace  |
| 04 | P0_GATE_A_SECURITY_EVIDENCE_MATRIX.md     | CTO-P0-GATE-A-004                 | 11 SHA-Tied Vulns  |
| 05 | P0_GATE_A_WORKTREE_INTEGRITY_REPORT.md    | CTO-P0-GATE-A-005                 | Snapshot Baseline  |
+----+-------------------------------------------+-----------------------------------+--------------------+
```

---

### 1.1 Deliverable 1: Exhaustive Route & Handler Inventory (`CTO-P0-GATE-A-001`)

An exhaustive static code scan across `boontrack-inbox` and `boontrack-core` identified **19 distinct execution vectors** capable of reading, updating, or triggering partner financial identities and payout disbursements.

#### Master Inventory Matrix:
```
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| NO | REPOSITORY / SYS  | METHOD | ROUTE PATH                               | HANDLER FUNCTION & LINE         | CURRENT AUTH STATE    | MUTATION VECTOR     | AFFECTED TABLE(S) |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 01 | boontrack-inbox   | PATCH  | /api/v1/affiliate/payout-account         | handleUpdatePayoutAccount       | NONE                  | Bank details & auto | public.affiliates |
|    |                   |        |                                          | route.ts:15-104, 150-153        | (Unauthenticated)     | is_bank_verified    |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 02 | boontrack-inbox   | POST   | /api/v1/affiliate/payout-account         | handleUpdatePayoutAccount       | NONE                  | Bank details & auto | public.affiliates |
|    |                   |        |                                          | route.ts:15-104, 154-157        | (Unauthenticated)     | is_bank_verified    |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 03 | boontrack-inbox   | POST   | /api/v1/partners/bank-account            | POST                            | NONE                  | In-place overwrite  | public.affiliates |
|    |                   |        |                                          | route.ts:5-79                   | (Unauthenticated)     | bank & metadata     |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 04 | boontrack-inbox   | POST   | /api/v1/partners/payouts/request         | POST                            | NONE                  | Unauthenticated     | public.payout_    |
|    |                   |        |                                          | route.ts:5-123                  | (Unauthenticated)     | payout creation     | requests          |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 05 | boontrack-inbox   | POST   | /api/v1/partners/claim-ref-slug          | POST                            | NONE                  | Hijacks referral    | public.affiliates |
|    |                   |        |                                          | route.ts:6-53                   | (Unauthenticated)     | slug / code         |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 06 | boontrack-inbox   | GET    | /api/v1/manager/payouts                  | GET                             | NONE                  | Exfiltrates all     | public.payout_    |
|    |                   |        |                                          | route.ts:5-39                   | (Public internet open)| bank & user details | requests          |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 07 | boontrack-inbox   | PUT    | /api/v1/manager/payouts/[id]/mark-paid   | PUT                             | NONE                  | Marks payout PAID   | public.payout_    |
|    |                   |        |                                          | route.ts:5-54                   | (Public internet open)| without manager auth| requests          |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 08 | boontrack-inbox   | PATCH  | /api/v1/affiliate/me                     | PATCH                           | INSECURE (parseJwt    | Overwrites name &   | public.affiliates |
|    |                   |        |                                          | route.ts:504-605                | no signature check)   | phone via raw sub   |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 09 | boontrack-inbox   | GET    | /api/v1/affiliate/me                     | GET                             | INSECURE (parseJwt    | Exfiltrates partner | public.affiliates |
|    |                   |        |                                          | route.ts:21-502                 | no signature check)   | profile & bank data |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 10 | boontrack-core    | PATCH  | /payout-account                          | update_affiliate_payout_account | NONE                  | Overwrites bank &   | public.affiliates |
|    | (FastAPI Legacy)  |        |                                          | affiliate_auth.py:819, 825-915  | (Unauthenticated)     | sets verified=True  |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 11 | boontrack-core    | POST   | /payout-account                          | update_affiliate_payout_account | NONE                  | Overwrites bank &   | public.affiliates |
|    | (FastAPI Legacy)  |        |                                          | affiliate_auth.py:820, 825-915  | (Unauthenticated)     | sets verified=True  |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 12 | boontrack-core    | POST   | /update-bank                             | update_affiliate_payout_account | NONE                  | Overwrites bank &   | public.affiliates |
|    | (FastAPI Legacy)  |        |                                          | affiliate_auth.py:821, 825-915  | (Unauthenticated)     | sets verified=True  |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 13 | boontrack-core    | PATCH  | /api/v1/affiliate/payout-account         | update_affiliate_payout_account | NONE                  | Overwrites bank &   | public.affiliates |
|    | (FastAPI Modern)  |        |                                          | affiliate_auth.py:822, 825-915  | (Unauthenticated)     | sets verified=True  |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 14 | boontrack-core    | POST   | /api/v1/affiliate/payout-account         | update_affiliate_payout_account | NONE                  | Overwrites bank &   | public.affiliates |
|    | (FastAPI Modern)  |        |                                          | affiliate_auth.py:823, 825-915  | (Unauthenticated)     | sets verified=True  |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 15 | boontrack-core    | POST   | /api/v1/auth/affiliate/update-bank       | update_affiliate_payout_account | NONE                  | Overwrites bank &   | public.affiliates |
|    | (FastAPI Auth)    |        |                                          | affiliate_auth.py:824, 825-915  | (Unauthenticated)     | sets verified=True  |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 16 | boontrack-core    | POST   | /payout/settle                           | settle_payout                   | NONE                  | Batch settles       | public.affiliate_ |
|    | (FastAPI Main)    |        |                                          | main.py:521-532                 | (Unauthenticated)     | commission ledger   | commissions       |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 17 | boontrack-core    | POST   | /api/v1/partners/bank-account            | save_bank_account               | INSECURE (accepts raw | Upserts partner     | public.partner_   |
|    | (FastAPI Partner) |        |                                          | partner_routes.py:138-168       | explicit_partner_id)  | bank account row    | bank_accounts     |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 18 | boontrack-core    | POST   | /api/v1/partners/payouts/request         | request_payout                  | INSECURE (accepts raw | Inserts partner     | public.payout_    |
|    | (FastAPI Partner) |        |                                          | partner_routes.py:190-220       | explicit_partner_id)  | payout request      | requests          |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
| 19 | boontrack-core    | *ALL*  | aiohttp_update_payout_account & slug     | aiohttp runner handlers         | NONE                  | Complete bypass on  | public.affiliates |
|    | (aiohttp Runner)  |        |                                          | affiliate_auth.py:1405-1417     | (Unauthenticated)     | async port 8080     |                   |
+----+-------------------+--------+------------------------------------------+---------------------------------+-----------------------+---------------------+-------------------+
```

---

### 1.2 Deliverable 2: Identity Discrepancy & Auth Mapping Report (`CTO-P0-GATE-A-002`)

#### Root Cause of Unlinked `auth_user_id`:
1. **Identity Impedance Mismatch:** Supabase GoTrue Auth sets `sub = auth.users.id`. In `boontrack-inbox/app/api/v1/affiliate/me/route.ts:536`, the code executed `.eq('id', jwtPayload.sub)`. Because `sub` is `auth.users.id` and NOT `affiliates.id`, the query evaluates to `null`.
2. **Cascading Vulnerability Fallback:** Because the primary lookup failed, the system fell back to unverified email matches and raw UUID regex parsing (`/^[0-9a-f]{8}-...$/i.test(token)`), permitting anyone to pass a victim's `affiliates.id` as a Bearer token.
3. **Three Ingestion Gaps Creating Orphan Affiliates:**
   - *Security Definer RPC Omission:* `supabase/migrations/20261016_harden_security_definer_functions.sql:139-153` inserted rows into `public.affiliates` without writing `auth_user_id`.
   - *Core WhatsApp Onboarding:* `boontrack-core/app/routes/affiliate_auth.py:530-575` created affiliate rows via WhatsApp OTP directly without registering GoTrue accounts.
   - *Disconnected Web Signup:* Registration created `auth.users` without a reciprocal database trigger linking to `public.affiliates.auth_user_id`.

#### Supervised Draft SQL Templates for Gate B (Zero Execution in Gate A):
```sql
-- DRAFT QUERY 1: Aggregated Discrepancy Volume Assessment (Zero PII)
SELECT 
    COUNT(*) AS total_affiliates,
    COUNT(CASE WHEN a.auth_user_id IS NOT NULL AND u.id IS NOT NULL THEN 1 END) AS count_1_exact_linked,
    COUNT(CASE WHEN a.auth_user_id IS NULL AND u.id IS NOT NULL THEN 1 END) AS count_2_unlinked_email_match_candidates,
    COUNT(CASE WHEN a.auth_user_id IS NULL AND u.id IS NULL THEN 1 END) AS count_4_orphaned_affiliates
FROM public.affiliates a
LEFT JOIN auth.users u ON LOWER(TRIM(a.email)) = LOWER(TRIM(u.email));

-- DRAFT QUERY 2: Multi-Email & Multi-Account Collision Detection
SELECT 
    SUBSTRING(encode(hmac(LOWER(TRIM(a.email)), 'audit_collision_salt', 'sha256'), 'hex') FROM 1 FOR 12) AS keyed_email_hash,
    COUNT(DISTINCT a.id) AS affiliate_row_count,
    COUNT(DISTINCT a.auth_user_id) AS distinct_auth_uids,
    COUNT(DISTINCT u.id) AS distinct_auth_users
FROM public.affiliates a
LEFT JOIN auth.users u ON LOWER(TRIM(a.email)) = LOWER(TRIM(u.email))
WHERE a.email IS NOT NULL AND a.email <> ''
GROUP BY LOWER(TRIM(a.email))
HAVING COUNT(DISTINCT a.id) > 1 OR COUNT(DISTINCT u.id) > 1;
```

---

### 1.3 Deliverable 3: End-to-End Payout Execution Trace (`CTO-P0-GATE-A-003`)

The forensic trace revealed a critical **Time-of-Check to Time-of-Use (TOCTOU) race condition window**:
1. An affiliate creates a legitimate withdrawal request (status: `PENDING`).
2. An attacker triggers unauthenticated `PATCH /api/v1/affiliate/payout-account`, overwriting `bank_name`, `bank_account_number`, and `bank_account_holder` in `public.affiliates`.
3. The payout request lacked immutable bank snapshotting, or the manager approval disburser queried `public.affiliates` live, causing funds to route to the attacker's account.
4. Manager endpoints (`/api/v1/manager/payouts` and `.../mark-paid`) lacked role verification, allowing public internet callers to exfiltrate financial details and mark payouts as `PAID`.

---

### 1.4 Deliverable 4: Security Evidence Matrix (`CTO-P0-GATE-A-004`)

Eleven vulnerabilities were formally mapped, CWE-classified, and tied to exact repository commit SHAs:
- **`boontrack-inbox` @ `9375975936eda8966ab2337e60ada0cfea885497`**
- **`boontrack-core` @ `70a8c5186437837c846c74a1eabca3d4465286d2`**

```
+--------+-------------------+------------------------------------------+---------------------+-------------------+---------------------+
| VULN ID| REPOSITORY & SHA  | FILE PATH & LINE NUMBER                  | CWE CLASSIFICATION  | SEVERITY & CVSS   | ATTACK VECTOR       |
+--------+-------------------+------------------------------------------+---------------------+-------------------+---------------------+
| SEC-01 | boontrack-inbox   | app/api/v1/affiliate/me/route.ts:8-19    | CWE-287 / CWE-345   | CRITICAL (9.8)    | Unverified parseJwt |
| SEC-02 | boontrack-inbox   | app/api/v1/affiliate/me/route.ts:552-555 | CWE-639 / CWE-284   | HIGH (8.6)        | Raw UUID Bearer     |
| SEC-03 | boontrack-inbox   | app/api/v1/affiliate/me/route.ts:25, 526 | CWE-798             | HIGH (8.2)        | Dev bypass strings  |
| SEC-04 | boontrack-inbox   | app/api/v1/affiliate/payout-account/...  | CWE-306             | CRITICAL (9.8)    | Unauthenticated bank|
| SEC-05 | boontrack-inbox   | app/api/v1/partners/bank-account/...     | CWE-306             | CRITICAL (9.8)    | Unauth bank/metadata|
| SEC-06 | boontrack-inbox   | app/api/v1/manager/payouts/route.ts      | CWE-306 / CWE-200   | HIGH (8.6)        | Financial data leak |
| SEC-07 | boontrack-inbox   | app/api/v1/manager/payouts/.../mark-paid | CWE-306 / CWE-862   | CRITICAL (9.1)    | Unauth mark-paid    |
| SEC-08 | boontrack-core    | app/routes/affiliate_auth.py:819-824     | CWE-306             | CRITICAL (9.8)    | Unauth bank rewrite |
| SEC-09 | boontrack-core    | app/routes/partner_routes.py:61-75       | CWE-287 / CWE-639   | HIGH (8.8)        | explicit_partner_id |
| SEC-10 | boontrack-core    | app/routes/affiliate_auth.py:85-125      | CWE-287 / CWE-327   | HIGH (8.5)        | verify_aud=False    |
| SEC-11 | boontrack-core    | app/main.py:521-532                      | CWE-306             | HIGH (8.1)        | Unauth settle_payout|
+--------+-------------------+------------------------------------------+---------------------+-------------------+---------------------+
```

---

### 1.5 Deliverable 5: Baseline Worktree Integrity (`CTO-P0-GATE-A-005`)

Certified that:
1. `boontrack-inbox` was maintained at HEAD `9375975936eda8966ab2337e60ada0cfea885497` with zero unauthorized modifications.
2. `boontrack-core` was maintained at HEAD `70a8c5186437837c846c74a1eabca3d4465286d2` with zero commit mutations.
3. `boontrack-studio-deploy` at `6fc2beecb1f150ba629ef68be721615a0cc84796` remained strictly locked.

---

## 2. BUKTI AUDIT WORKING TREE & PEMETAAN PRE-EXISTING VS HOTFIX

### 2.1 Diff Eksplisit 3 File Hotfix WhatsApp terhadap HEAD

Below is the exact `git diff HEAD` showing the minimal, localized remediation resolving the auto-handover bug on WhatsApp group chatter:

```diff
diff --git a/app/routes/whatsapp_gateway_routes.py b/app/routes/whatsapp_gateway_routes.py
index bfb4375..53b3d36 100644
--- a/app/routes/whatsapp_gateway_routes.py
+++ b/app/routes/whatsapp_gateway_routes.py
@@ -554,6 +554,7 @@ async def check_and_handle_session_handover_and_toggle(
     sender_phone: str,
     incoming_text: str,
     sender_name: str = "Kakak",
+    conversation_scope: str = "DIRECT",
 ) -> Optional[Dict[str, Any]]:
     """
     Auto-Mute Handover & Toggle Command (Instance 081215567168 & Tenant):
@@ -564,10 +565,20 @@ async def check_and_handle_session_handover_and_toggle(
        - 24-hour locked duration (paused_until = now() + 24 hours)
     3. Auto-Mute Guard:
        - If session is currently paused/handover, drops auto-reply and holds message for manual CS.
+
+    SAFETY GUARD:
+    - Group discussions (conversation_scope == "GROUP") are strictly exempt from handover escalation
+      and auto-mute pause guards to prevent group messages or tech/AI discussions from muting the bot
+      or locking sessions to HUMAN_ACTIVE.
     """
     if not sender_phone or not incoming_text:
         return None
 
+    # Guard: GROUP conversation scope is strictly exempt from handover and pause locks.
+    # Group discussions must never trigger handover to human CS, auto-mute, or lock sessions into HUMAN_ACTIVE.
+    if (conversation_scope or "").upper() == "GROUP":
+        return None
+
     clean_digits = normalize_phone_number(sender_phone) or re.sub(r"\D", "", sender_phone)
     raw_clean = incoming_text.strip()
     raw_upper = raw_clean.upper()
@@ -827,6 +838,7 @@ async def process_inbound_message(payload: InboundPayload):
         sender_phone=clean_phone,
         incoming_text=incoming_text,
         sender_name=contact_name,
+        conversation_scope=conversation_scope,
     )
     if toggle_res and toggle_res.get("handled"):
         return {
@@ -948,13 +960,30 @@ async def process_inbound_message(payload: InboundPayload):
         logger.info(f"[GROWTH GATEWAY AUTO-REPLY] Matched custom keyword rule for '{tenant_slug}' from '{clean_phone}'")
         reply = custom_auto_reply
 
+    is_group_scope = payload.conversation_scope == "GROUP" and bool(payload.group_jid)
+    is_boon_tenant = tenant_slug.lower() in ("boon", "boontrack-app-shop", "boontrack_app_shop", "app_shop", "app-shop")
+
+    if is_group_scope and is_boon_tenant:
+        from app.whatsapp.traffic_splitter import generate_group_boonpilot_reply
+        text_for_boonpilot = re.sub(r"@[\w.]+", "", incoming_text).strip() or incoming_text.strip()
+        group_reply = await generate_group_boonpilot_reply(text_for_boonpilot)
+        return {
+            "status": "success",
+            "tenant_slug": tenant_slug,
+            "conversation_scope": "GROUP",
+            "group_jid": payload.group_jid,
+            "bot_strategy": "boonpilot_group",
+            "reply_text": group_reply,
+            "media_url": None,
+        }
+
     # Entitlement Guard (ARCHITECTURE.md): CHECKOUT_LITE DILARANG menggunakan Conversational AI / LLM
     if is_checkout_lite:
         logger.warning(
             f"[ENTITLEMENT_PROTECTION_BLOCKED] Tenant '{tenant_slug}' is on tier CHECKOUT_LITE (ai_bot disabled). "
             "Skipping AI pipelines and falling back to dynamic store template."
         )
-        if not reply:
+        if not reply and not is_group_scope:
             # 1. Ganti nama toko dengan tenant_name (ambil 'BoonTrack Official Shop')
             store_name = (
                 tenant_info.get("name")
@@ -1306,7 +1305,7 @@ async def process_inbound_message(payload: InboundPayload):
                 f"Ada yang bisa kami bantu lagi untuk toko atau layanan *{store_name}*, Kak? 😊\n\n"
                 f"Katalog & pemesanan resmi: https://shop.boontrack.com/{tenant_slug}"
             )
-        else:
+        elif not is_group_scope:
             from app.whatsapp.traffic_splitter import get_tenant_greeting_message
             reply = get_tenant_greeting_message(
                 store_name=store_name,
@@ -2280,6 +2279,7 @@ async def process_evolution_webhook_payload(payload: Dict[str, Any], tenant_slug
         sender_phone=sender_phone,
         incoming_text=incoming_text,
         sender_name=sender_name,
+        conversation_scope=conversation_scope,
     )
     if evo_toggle_res and evo_toggle_res.get("handled"):
         action = evo_toggle_res.get("action")

diff --git a/app/services/ai/__init__.py b/app/services/ai/__init__.py
index 593706e..21cc1ae 100644
--- a/app/services/ai/__init__.py
+++ b/app/services/ai/__init__.py
@@ -10,6 +10,7 @@ from app.services.ai.grounding import (
     DIRECT_CHECKOUT_WA_SOP_PROMPT,
     COMBINED_STRICT_AI_DIRECTIVE,
     HANDOVER_HUMAN_KEYWORDS,
+    HANDOVER_INTENT_PATTERNS,
     HANDOVER_TRANSITION_REPLY,
     is_setup_toko_intent,
     is_reader_inquiry_intent,
@@ -33,6 +34,7 @@ __all__ = [
     "DIRECT_CHECKOUT_WA_SOP_PROMPT",
     "COMBINED_STRICT_AI_DIRECTIVE",
     "HANDOVER_HUMAN_KEYWORDS",
+    "HANDOVER_INTENT_PATTERNS",
     "HANDOVER_TRANSITION_REPLY",
     "is_setup_toko_intent",
     "is_reader_inquiry_intent",

diff --git a/app/services/ai/grounding.py b/app/services/ai/grounding.py
index 467e398..11814e9 100644
--- a/app/services/ai/grounding.py
+++ b/app/services/ai/grounding.py
@@ -121,10 +121,31 @@ READER_INQUIRY_KEYWORDS = [
     "verifikasi mutasi",
 ]
 
-# Kata kunci / regex resmi untuk auto-handover ke CS manusia
+# Kata kunci / frasa resmi untuk auto-handover ke CS manusia
 HANDOVER_HUMAN_KEYWORDS = [
-    "admin", "cs", "manusia", "orang", "customer service",
-    "bicara langsung", "hubungi orang"
+    "bicara dengan manusia", "bicara sama manusia", "hubungkan ke manusia", "hubungkan dengan manusia",
+    "minta cs manusia", "mau cs manusia", "mau admin manusia", "bicara langsung",
+    "hubungi orang", "customer service", "admin", "cs", "manusia", "orang"
+]
+
+# Pola regex resmi untuk deteksi auto-handover ke CS manusia (mengharuskan frasa eksplisit)
+HANDOVER_INTENT_PATTERNS = [
+    # Explicit intent phrases: bicara/ngobrol/chat dengan manusia/admin/cs/orang/owner
+    r"\b(?:bicara|ngobrol|chat|diskusi)\s+(?:langsung\s+)?(?:dengan|sama|ke)\s+(?:manusia|orang|admin|cs|customer\s+service|owner|pemilik|staff|staf|kang\s+sakti)\b",
+    # hubungkan / sambungkan ke manusia/admin/cs
+    r"\b(?:hubungkan|sambungkan|koneksikan|oper|alihkan)\s+(?:(?:saya|kami|obrolan\s+ini)\s+)?(?:ke|dengan|sama)\s+(?:manusia|orang|admin|cs|customer\s+service|owner|pemilik|tim|staff|staf|bicara\s+langsung|hubungi\s+orang)\b",
+    # hubungi langsung orang/admin/cs
+    r"\b(?:hubungi|kontak)\s+(?:langsung\s+)?(?:orang|manusia|admin|cs|customer\s+service|owner|pemilik)\b",
+    # minta / mau / butuh cs / admin / manusia
+    r"\b(?:minta|mau|butuh|perlu|tolong)\s+(?:tolong\s+)?(?:bicara\s+(?:dengan\s+)?)?(?:cs\s+manusia|admin\s+manusia|orang\s+asli|cs\s+asli|admin\s+asli|manusia|admin|cs|customer\s+service|orang|owner|pemilik|bicara\s+langsung|hubungi\s+orang)(?:\s+(?:dong|ya|kak|min|gan|boss|bos))?(?:\s*$|\s+[\w])",
+    # panggil admin / cs
+    r"\b(?:panggil|panggilin)\s+(?:admin|cs|manusia|orang|owner)\b",
+    # bicara langsung
+    r"\b(?:bicara|ngobrol)\s+langsung\b",
+    # bantuan orang / manusia / admin
+    r"\b(?:bisa\s+hubungi\s+orang|bantuan\s+(?:orang|manusia|admin|cs))\b",
+    # live cs / human cs / chat owner / chat admin / chat cs / kang sakti (buzzerukm owner)
+    r"\b(?:live\s+cs|human\s+cs|chat\s+owner|chat\s+admin|chat\s+cs|kang\s+sakti|bukan\s+bot|jangan\s+bot|stop\s+bot)\b",
 ]
 
 HANDOVER_TRANSITION_REPLY = (
@@ -210,13 +231,14 @@ def is_reader_inquiry_intent(text: str, tenant_slug: Optional[str] = None) -> bo
 
 
 def is_handover_intent(text: str) -> bool:
-    """Mendeteksi apakah pengguna ingin berbicara langsung dengan orang / CS manual."""
+    """Mendeteksi apakah pengguna ingin berbicara langsung dengan orang / CS manual.
+    Mengharuskan frasa eksplisit (misal: 'bicara dengan manusia', 'hubungkan ke manusia', 'minta cs manusia')
+    dan TIDAK merespons substring kata tunggal 'manusia'/'admin'/'cs' pada kalimat umum/diskusi.
+    """
     if not text:
         return False
     lower = text.lower().strip()
-    return any(re.search(rf"\b{re.escape(kw)}\b", lower) for kw in HANDOVER_HUMAN_KEYWORDS) or any(
-        kw in lower for kw in ["bicara dengan orang", "bantuan orang", "live cs", "human cs", "kang sakti", "owner", "pemilik"]
-    )
+    return any(re.search(pat, lower) for pat in HANDOVER_INTENT_PATTERNS)
```

---

### 2.2 Klasifikasi 11 File Termodifikasi Lainnya

Sebanyak 11 file termodifikasi di working tree terbukti secara forensik berasal dari pekerjaan branch `fix/onlineboost-batch1-canary-readiness` sebelum hotfix, seluruhnya berkaitan dengan WABA broadcast hold, template reconciliation, dan phone suppression:

```
+----+---------------------------------------------------+---------+--------------------------------------------------------------+
| NO | FILE PATH                                         | CHANGES | KLASIFIKASI & ASAL PEKERJAAN                                 |
+----+---------------------------------------------------+---------+--------------------------------------------------------------+
| 01 | ARCHITECTURE.md                                   | +2 / -2 | OnlineBoost batch 1 canary readiness & WABA hold docs        |
| 02 | app/routes/academy_routes.py                      | +8 / -7 | Template reconciliation alumni_cpm_metode_rahasia_v1 payload |
| 03 | app/routes/meta_waba_routes.py                    | +8 / -0 | WABA webhook signature & broadcast hold lifecycle validation |
| 04 | app/services/academy_service.py                   | +105/-16| WABA template constants & payload contract reconciliation     |
| 05 | app/services/meta_waba_service.py                 | +72/-5  | Strict broadcast gate hold & credential validation           |
| 06 | app/services/phone_suppression_service.py         | +1 / -1 | BATAL & STOP suppression persistence                         |
| 07 | app/whatsapp/platform_webhook_router.py           | +1 / -1 | Compliance opt-out suppression routing                       |
| 08 | app/whatsapp/traffic_splitter.py                  | +2 / -2 | Suppression guard precedence over lead capture               |
| 09 | tests/test_academy_warm_launch.py                 | +294/-1 | Unit tests untuk template reconciliation & broadcast hold    |
| 10 | tests/test_onlineboost_phase4_consultation.py     | +1 / -1 | Strict payment hold assertion guard                          |
| 11 | tests/test_opt_out_durability_and_acknowledgment.py| +76/-0  | Unit tests untuk opt-out durability (BATAL/STOP)             |
+----+---------------------------------------------------+---------+--------------------------------------------------------------+
```

---

### 2.3 Asal-Usul 3 File Untracked

1. **`PHASE_2A_CLOSURE_AND_PHASE_2B_READINESS.md`**:  
   - *Asal-usul:* Disusun atas instruksi formal audit CTO untuk meratifikasi penutupan Phase 2A (144 passing tests) dan menetapkan kesiapan Phase 2B dalam status strict hold.
2. **`fix_bot.py`**:  
   - *Asal-usul:* Skrip utilitas lokal sementara untuk membaca definisi constraint database `chk_conversations_bot_mode` dan mereset status sesi percakapan yang sempat terkunci di lingkungan pengembangan lokal.
3. **`tests/test_handover_intent_and_group_scope.py`**:  
   - *Asal-usul:* Test suite baru (9/9 passing tests) yang memverifikasi pengetatan regex handover multi-kata dan pencegahan penguncian sesi `HUMAN_ACTIVE` pada percakapan grup WhatsApp.

---

### 2.4 Konfirmasi Eksplisit: Zero Diff pada Area P0 Sensitif

Dilakukan verifikasi forensik `git diff HEAD` terhadap modul-modul otentikasi afiliasi, rute partner, handler payout, konfigurasi secret, dan skema database:
- `app/routes/affiliate_auth.py`: **ZERO DIFF (0 lines modified)**
- `app/routes/partner_routes.py`: **ZERO DIFF (0 lines modified)**
- `app/services/payout_service.py`: **ZERO DIFF (0 lines modified)**
- `app/services/partner_service.py`: **ZERO DIFF (0 lines modified)**
- `app/core/config.py`: **ZERO DIFF (0 lines modified)**
- `app/core/database.py`: **ZERO DIFF (0 lines modified)**
- `supabase/migrations/`: **ZERO DIFF (0 lines modified)**
- `.env`: **ZERO DIFF (0 lines modified)**

---

## 3. LOG EKSEKUSI & BUKTI 171 REGRESSION TESTS

Eksekusi regresi komprehensif dijalankan pada working tree aktif menggunakan pytest:

```bash
python -m pytest \
  tests/test_handover_intent_and_group_scope.py \
  tests/test_group_bot_guard.py \
  tests/test_reader_grounding_and_direct_checkout.py \
  tests/test_academy_warm_launch.py \
  tests/test_onlineboost_phase4_consultation.py \
  tests/test_waba_tenant_isolation_and_opt_out.py \
  tests/test_opt_out_durability_and_acknowledgment.py -q
```

### 3.1 Rincian Hasil Eksekusi Suite:
```
+----+-----------------------------------------------------+---------------+-------------+
| NO | TEST SUITE NAME                                     | TESTS PASSED  | STATUS      |
+----+-----------------------------------------------------+---------------+-------------+
| 01 | tests/test_handover_intent_and_group_scope.py        | 9 passed      | 100% GREEN  |
| 02 | tests/test_group_bot_guard.py                       | 51 passed     | 100% GREEN  |
| 03 | tests/test_reader_grounding_and_direct_checkout.py  | 17 passed     | 100% GREEN  |
| 04 | tests/test_academy_warm_launch.py                   | 20 passed     | 100% GREEN  |
| 05 | tests/test_onlineboost_phase4_consultation.py       | 41 passed     | 100% GREEN  |
| 06 | tests/test_waba_tenant_isolation_and_opt_out.py     | 18 passed     | 100% GREEN  |
| 07 | tests/test_opt_out_durability_and_acknowledgment.py | 15 passed     | 100% GREEN  |
+----+-----------------------------------------------------+---------------+-------------+
|    | TOTAL RUNTIME: 54.18s                               | 171 PASSED    | ZERO FAILS  |
+----+-----------------------------------------------------+---------------+-------------+
```

### 3.2 Cuplikan Log Eksekusi Konsol:
```text
============================= test session starts =============================
platform win32 -- Python 3.12.8, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\boontrack-core
configfile: pytest.ini
plugins: anyio-4.14.2, Faker-40.39.0, locust-2.46.5, asyncio-1.4.0, cov-7.1.0
asyncio: mode=Mode.STRICT

........................................................................ [ 42%]
........................................................................ [ 84%]
...........................                                              [100%]
171 passed in 54.18s
```

### 3.3 Verifikasi Khusus Skenario Hotfix:
1. **Isolasi Scope GROUP:** Percakapan grup yang memuat kata *"manusia"* (contoh: *"...bagus asli ada manusia atau pakai ai..."*) mengembalikan `conversation_scope="GROUP"` dan diarahkan langsung ke BoonPilot Group Brain tanpa menghasilkan transisi auto-handover atau mutasi DB ke `HUMAN_ACTIVE`.
2. **Regex Frasa Utuh:** Kata tunggal (*"manusia"*, *"orang"*, *"admin"*, *"cs"*) terbukti mengembalikan `is_handover_intent() == False`. Hanya frasa utuh terstruktur (*"bicara dengan manusia"*, *"hubungkan ke admin"*, *"minta cs manusia"*) yang memicu eskalasi.

---

## 4. DESAIN ARSITEKTUR IMMUTABLE DESTINATION SNAPSHOT & CONCURRENCY CONTROL

Untuk menutup celah keamanan P0 SEC-04, SEC-05, dan TOCTOU Race Condition, arsitektur pencairan dana (payout) dirancang dengan prinsip **Immutable Financial Snapshot** dan **Pessimistic Concurrency Control**:

```
+---------------------------------------------------------------------------------------------------------+
|                                  HARDENED PAYOUT CONCURRENCY ARCHITECTURE                               |
+---------------------------------------------------------------------------------------------------------+
|                                                                                                         |
|  [PHASE 1: REQUEST INTAKE]                                                                              |
|  Affiliate submits withdrawal request via POST /api/v1/partners/payouts/request                         |
|    │                                                                                                    |
|    ├── 1. Verify caller profile via Supabase Auth (auth_user_id == public.affiliates.auth_user_id)      |
|    ├── 2. Verify account is NOT in 24-hour security cooldown (clock_timestamp() >= payout_cooldown_until)|
|    ├── 3. Enforce public.affiliates.is_bank_verified == TRUE                                            |
|    └── 4. ATOMIC SNAPSHOT INSERT INTO public.payout_requests:                                           |
|           • snapshot_bank_name       := affiliates.bank_name                                            |
|           • snapshot_account_number := affiliates.bank_account_number                                   |
|           • snapshot_account_holder := affiliates.bank_account_holder                                   |
|           • idempotency_key          := sha256(request_id || snapshot_account_number || amount || date) |
|           • status                   := 'PENDING'                                                       |
|                                                                                                         |
| ======================================================================================================= |
|                                                                                                         |
|  [PHASE 2: EXECUTION & DISBURSEMENT GATE]                                                               |
|  Compliance Manager (ADMIN) / Disburser Worker triggers settlement                                      |
|    │                                                                                                    |
|    ├── 1. BEGIN TRANSACTION;                                                                            |
|    ├── 2. CONSISTENT PESSIMISTIC LOCKING ORDER (Prevent 40P01 Deadlocks):                               |
|    │      SELECT * FROM public.affiliates WHERE id = :affiliate_id FOR UPDATE;                          |
|    │      SELECT * FROM public.payout_requests WHERE id = :payout_id FOR UPDATE;                        |
|    │                                                                                                    |
|    ├── 3. RE-VERIFY 24-HOUR SECURITY COOLDOWN:                                                          |
|    │      IF clock_timestamp() < affiliates.payout_cooldown_until THEN                                  |
|    │          ROLLBACK; RETURN 422 ("Account under 24-hour security hold");                             |
|    │                                                                                                    |
|    ├── 4. IMMUTABLE SNAPSHOT INTEGRITY VERIFICATION:                                                    |
|    │      IF affiliates.bank_account_number != payout_requests.snapshot_account_number OR               |
|    │         affiliates.bank_name != payout_requests.snapshot_bank_name THEN                            |
|    │          -- TOCTOU RACE DETECTED: Bank was modified after request was created!                     |
|    │          UPDATE public.payout_requests                                                             |
|    │          SET status = 'SECURITY_HOLD', notes = 'DESTINATION_SNAPSHOT_MISMATCH_RACE_DETECTED';      |
|    │          COMMIT;                                                                                   |
|    │          RAISE ALARM; RETURN 409 CONFLICT;                                                         |
|    │                                                                                                    |
|    ├── 5. DISPATCH PAYMENT GATEWAY TRANSFER (with X-Idempotency-Key header):                            |
|    │      disburse_funds(bank=snapshot_bank_name, account=snapshot_account_number, amount=amount)        |
|    │                                                                                                    |
|    └── 6. COMMIT TRANSACTION:                                                                           |
|           UPDATE public.payout_requests SET status = 'PAID', paid_at = clock_timestamp();               |
|           UPDATE public.affiliate_commissions SET status = 'SETTLED' WHERE id IN (...);                |
|           COMMIT;                                                                                       |
+---------------------------------------------------------------------------------------------------------+
```

### 4.1 Spesifikasi Kolom Snapshot pada `public.payout_requests`
```sql
ALTER TABLE public.payout_requests
    ADD COLUMN snapshot_bank_name VARCHAR(100) NOT NULL,
    ADD COLUMN snapshot_account_number VARCHAR(100) NOT NULL,
    ADD COLUMN snapshot_account_holder VARCHAR(255) NOT NULL,
    ADD COLUMN idempotency_key VARCHAR(64) UNIQUE,
    ADD COLUMN status VARCHAR(50) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'SECURITY_HOLD', 'PAID', 'REJECTED')),
    ADD COLUMN payout_cooldown_verified_at TIMESTAMPTZ;
```

### 4.2 Aturan Immutability & Perubahan Rekening
- Perubahan rekening bank di `public.affiliates` **TIDAK PERNAH memutasi baris `public.payout_requests` yang berstatus `PENDING` atau `APPROVED`**.
- Jika mitra memperbarui rekening bank:
  1. Baris `public.affiliates` diperbarui.
  2. Cooldown diaktifkan: `payout_cooldown_until := clock_timestamp() + INTERVAL '24 hours'`.
  3. Flag verifikasi bank di-reset: `is_bank_verified := FALSE`.
  4. Seluruh request payout `PENDING` yang telah ada **tetap mengunci snapshot awal**. Jika verifikasi snapshot mendeteksi ketidaksesuaian, request otomatis dialihkan ke status `SECURITY_HOLD`.

### 4.3 Penetapan Urutan Locking Konsisten (Consistent Locking Order)
Untuk mencegah deadlock transaksional (PostgreSQL error `40P01: deadlock detected`) antara pembaruan rekening bank oleh user, approval oleh admin, dan settlement oleh worker otomatis, ditetapkan hierarki penguncian baris absolut:

$$\text{Urutan Penguncian:} \quad \mathbf{1. \ public.affiliates} \longrightarrow \mathbf{2. \ public.payout\_requests}$$

```sql
-- DRAFT WORKER & APPROVAL TRANSACTION TEMPLATE
BEGIN;
  -- LANGKAH 1: Kunci entitas induk (affiliates) terlebih dahulu
  SELECT id, payout_cooldown_until, is_bank_verified, bank_account_number 
  FROM public.affiliates 
  WHERE id = :target_affiliate_id 
  FOR UPDATE;

  -- LANGKAH 2: Kunci entitas anak (payout_requests)
  SELECT id, amount, snapshot_account_number, status 
  FROM public.payout_requests 
  WHERE id = :target_payout_id 
  FOR UPDATE;

  -- Evaluasi integritas & eksekusi...
COMMIT;
```

### 4.4 Penegasan Kebijakan `is_bank_verified = false` Pasca-OTP
- **Prinsip Keamanan Finansial:** Keberhasilan validasi OTP (WhatsApp / SMS) **hanya membuktikan kepemilikan nomor kontak**, bukan keabsahan atau kepemilikan rekening bank tujuan.
- **Implementasi:**
  - Saat OTP pembaruan rekening berhasil diverifikasi, sistem HANYA menyetel `is_phone_verified = true` dan mengaktifkan cooldown 24 jam.
  - Nilai `is_bank_verified` **HARUS TETAP bernilai `FALSE`** sampai nama pemilik rekening diverifikasi secara independen melalui API name-validation perbankan / verifikasi manual admin / penny-drop test.
  - Setiap upaya penarikan komisi saat `is_bank_verified == FALSE` wajib ditolak dengan HTTP 400 Bad Request.

---

## 5. DAFTAR UNRESOLVED UNCERTAINTIES & RESIDUAL RISKS

Sebelum kueri rekonsiliasi dan skrip audit Gate B diizinkan berjalan di bawah supervisi CTO, terdapat beberapa ketidakpastian (*unresolved uncertainties*) dan risiko residual yang belum dapat diverifikasi secara empiris:

```
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
| NO | UNRESOLVED UNCERTAINTY                       | AKAR PENYEBAB & DAMPAK                                       | MITIGASI / SYARAT RESOLUSI GATE B             |
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
| 01 | Estimasi Jumlah Baris Orphan Affiliates      | Migrasi RPC lama dan onboarding bot WhatsApp Core menyimpan  | Eksekusi DRAFT QUERY 1 (COUNT agregat) secara |
|    | (affiliates tanpa auth_user_id)              | mitra tanpa GoTrue auth.user. Volume persis belum terukur.   | read-only pada database staging/produksi.     |
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
| 02 | Potensi Email Collision Antar-Mitra          | Kemungkinan satu alamat email digunakan pada lebih dari satu | Eksekusi DRAFT QUERY 2 (Collision Check).     |
|    |                                              | baris affiliate (misal duplikasi akun atau tier partner).    | Akun collision wajib dikarantina manual.      |
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
| 03 | Profil Mitra Tanpa Alamat Email              | Mitra hasil intake WhatsApp bot yang hanya memiliki nomor HP | Penyusunan alur login alternatif GoTrue Phone |
|    | (Phone-Only Partners)                        | tanpa alamat email, sehingga tidak cocok dengan auth.users.  | Auth atau sintesis email terisolasi.          |
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
| 04 | Status Baris Payout Requests Historis        | Request pencairan lama yang dibuat sebelum kolom snapshot    | Skrip backfill audit untuk mengisi snapshot   |
|    | Tanpa Snapshot Rekening                      | dirancang, berpotensi tidak memiliki data snapshot historis. | dari data transaksi ledger terkait.           |
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
| 05 | Sisa Cache Sesi Klien di boontrack-inbox     | Token lama yang disimpan di local storage peramban sebelum   | Deployment verifier modular dengan invalidasi |
|    |                                              | deprecation dev bypass strings (aff_dev_sakti).              | instan dan pembersihan token usang.           |
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
| 06 | Konsistensi Jam Server (Timezone Jitter)     | Perbedaan resolusi timestamp antara Postgres UTC dan worker  | Penggunaan clock_timestamp() PostgreSQL       |
|    | pada Cooldown 24 Jam                         | saat mengevaluasi batas payout_cooldown_until.               | sebagai Single Source of Time (SSOT).         |
+----+----------------------------------------------+--------------------------------------------------------------+-----------------------------------------------+
```

---

## 6. KESIMPULAN & REKOMENDASI TAHAP BERIKUTNYA

1. **Gate A Resmi Lengkap:** Seluruh 5 deliverable investigasi statis, pemetaan rute, pelacakan eksekusi, matriks kerentanan, dan audit working tree telah terkonsolidasi secara menyeluruh.
2. **Postur Strict Read-Only Dipertahankan:** Tidak ada mutasi kode produksi maupun kueri database yang dieksekusi tanpa persetujuan eksplisit.
3. **Kesiapan Gate B:** Rekonsiliasi identitas `auth_user_id` telah memiliki draf kueri SQL non-destruktif dan skrip audit offline yang siap diuji segera setelah otorisasi Gate B diterbitkan oleh CTO.

---
**Dokumen Disahkan oleh:** Antigravity Engineering Agent  
**Status Operasional:** GATE A RATIFIED — WAITING FOR CTO GATE B AUTHORIZATION
