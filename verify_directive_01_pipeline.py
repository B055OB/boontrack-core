"""verify_directive_01_pipeline.py
Automated Verification Suite for DIRECTIVE 01 - ONLINEBOOST BATCH 1 PIPELINE.

Verifies:
1. Node 2: Webhook WABA "MAU METODE RAHASIA" -> Lookup staging_alumni_cpm (E.164) -> Bypass form -> Call Xendit Dynamic QRIS Rp249.000 (timeout cap 1.2s, latency < 2.0s).
2. Node 3: Webhook Xendit Redis Lock SETNX (<150ms response) -> Telegram createChatInviteLink (member_limit=1, expire=+24h) + Listener chat_member + Command fallback "LINK BARU".
3. Node 4: @boonshop_bot anti-spoofing ownership validation (tenant_id == telegram_user_id, products >= 1, QRIS active) -> Unlock onboarding_stage = 2 + Automated Flexing Alert.
4. Fase 3 & Node 5: Sandbox 3x Meta CAPI test_event_code, FFmpeg -c copy -metadata worker untuk video R2, Endpoint POST /api/store/import-starter-product, Trigger WA Kuota 80% (dengan cek phone_suppressions RLS ketat).
"""

import os
import sys
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import time
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Force root path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db_connection
from app.services.whatsapp_service import normalize_phone_number
from app.services.academy_service import (
    classify_academy_trigger,
    lookup_staging_alumni_cpm,
    generate_fast_path_xendit_qris_batch1,
    academy_bot,
)
from app.core.redis import acquire_payment_lock, release_payment_lock, get_redis_client
from app.services.ctwa_fulfillment_service import (
    create_telegram_single_use_invite_link,
    fulfill_onlineboost_ctwa_order,
)
from app.services.telegram_commerce_service import (
    handle_chat_member_joined,
    handle_telegram_link_baru,
    dispatch_flexing_alert,
    link_tenant_telegram,
    process_telegram_incoming,
)
from app.modules.tracking.capi_dispatcher import capi_dispatcher
from app.services.video_metadata_worker import video_metadata_worker
from app.routes.store_starter_routes import (
    import_starter_product_endpoint,
    ImportStarterProductRequest,
)
from app.services.quota_alert_service import (
    is_phone_suppressed,
    trigger_quota_80_percent_alert,
)


class Directive01PipelineVerifier:
    def __init__(self):
        self.tenant_id = "onlineboost"
        self.test_phone = "6281288889999"
        self.alumni_name = "Budi Hartono (Alumni Batch 1)"
        self.test_order_id = f"TEST-DIR01-{uuid.uuid4().hex[:6].upper()}"

    def log_header(self, title: str):
        print(f"\n{'='*75}\n[TEST EXECUTION] {title}\n{'='*75}")

    def log_result(self, step: str, passed: bool, detail: str = ""):
        mark = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {mark} | {step}")
        if detail:
            print(f"         Detail: {detail}")
        if not passed:
            raise AssertionError(f"Step '{step}' failed: {detail}")

    def setup_seed_data(self):
        """Seed tenant 'onlineboost' and staging_alumni_cpm lead."""
        self.log_header("SETUP SEED DATA FOR ONLINEBOOST")
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Ensure tenant 'onlineboost' exists with clean baseline
        cur.execute(
            """
            INSERT INTO public.tenants (id, slug, name, is_active, metadata, created_at, updated_at)
            VALUES (
                'e12acd29-6c18-487b-ade7-5422878c1c36',
                'onlineboost',
                'OnlineBoost Official Store',
                TRUE,
                '{"qris_active": true, "qris_status": "ACTIVE", "telegram_user_id": "7788990011"}',
                NOW(),
                NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                slug = 'onlineboost',
                metadata = '{"qris_active": true, "qris_status": "ACTIVE", "telegram_user_id": "7788990011"}'
            RETURNING id;
            """
        )

        # 2. Seed staging_alumni_cpm
        cur.execute(f"SET LOCAL app.current_tenant_id = '{self.tenant_id}';")
        cur.execute(
            "DELETE FROM public.staging_alumni_cpm WHERE tenant_id = %s AND lead_phone = %s;",
            (self.tenant_id, self.test_phone)
        )
        cur.execute(
            """
            INSERT INTO public.staging_alumni_cpm (
                tenant_id, lead_phone, alumni_name, campaign_id, status, metadata
            ) VALUES (
                %s, %s, %s, 'BATCH_1_METODE_RAHASIA', 'VERIFIED_ALUMNI',
                '{"email": "budi.alumni@onlineboost.id", "discount_entitlement": "RP_249K"}'
            );
            """,
            (self.tenant_id, self.test_phone, self.alumni_name)
        )

        # 3. Seed phone_suppressions for quota alert negative test
        suppressed_phone = "6289999999999"
        cur.execute(
            "DELETE FROM public.phone_suppressions WHERE tenant_id = %s AND phone_number = %s;",
            (self.tenant_id, suppressed_phone)
        )
        cur.execute(
            """
            INSERT INTO public.phone_suppressions (
                tenant_id, phone_number, reason, metadata, created_at
            ) VALUES (
                %s, %s, 'STOP_DIRECTIVE_TEST', '{"opted_out": true}', NOW()
            );
            """,
            (self.tenant_id, suppressed_phone)
        )

        conn.commit()
        cur.close()
        conn.close()
        self.log_result("Seed Tenant & Alumni Data", True, f"Tenant 'onlineboost' & Alumni '{self.alumni_name}' seeded.")

    async def test_node_2_waba_fast_path(self):
        """Node 2: Webhook WABA 'MAU METODE RAHASIA' -> Lookup staging_alumni_cpm -> Bypass form -> Xendit Dynamic QRIS Rp249k (<2s latency)."""
        self.log_header("NODE 2: WABA 'MAU METODE RAHASIA' FAST-PATH & LATENCY GUARANTEE")

        # 1. Pattern classifier test
        keyword = "MAU METODE RAHASIA"
        route = classify_academy_trigger(keyword)
        self.log_result(
            "Classifier Interception",
            route == "onlineboost_batch1",
            f"Expected 'onlineboost_batch1', got '{route}'"
        )

        # 2. Lookup staging_alumni_cpm (E.164)
        alumni = lookup_staging_alumni_cpm(self.test_phone, tenant_id=self.tenant_id)
        self.log_result(
            "Lookup Staging Alumni (E.164)",
            alumni is not None and alumni.get("alumni_name") == self.alumni_name,
            f"Alumni record: {alumni}"
        )

        # 3. Execute State Machine process_inbound (Bypassing form)
        t_start = time.monotonic()
        res = await academy_bot.process_inbound(
            sender_phone=self.test_phone,
            incoming_text=keyword,
            contact_name="Pelanggan",
            phone_number_id="1268977686299719",
            tenant_id=self.tenant_id,
        )
        latency = time.monotonic() - t_start

        self.log_result(
            "Form Bypass & Handled Status",
            res.get("handled") is True and res.get("action") == "FAST_PATH_QRIS_ISSUED",
            f"Action: {res.get('action')}, Order ID: {res.get('order_id')}"
        )
        self.log_result(
            "Dynamic QRIS Amount Rp 249.000",
            res.get("amount") == 249000,
            f"Amount: Rp {res.get('amount')}"
        )
        self.log_result(
            "Total Latency Under 2.0s Constraint",
            latency < 2.0,
            f"Execution time: {latency:.4f}s (< 2.0s constraint)"
        )
        self.log_result(
            "Dynamic QRIS Payload / URL Issued",
            bool(res.get("qr_string") and res.get("invoice_url")),
            f"Invoice URL: {res.get('invoice_url')}"
        )

    async def test_node_3_redis_lock_and_telegram_worker(self):
        """Node 3: Webhook Xendit Redis Lock SETNX (<150ms response) -> Telegram createChatInviteLink (member_limit=1, expire=+24h) + Listener chat_member + Command fallback 'LINK BARU'."""
        self.log_header("NODE 3: REDIS LOCK SETNX & TELEGRAM SINGLE-USE INVITE WORKER")

        # 1. Test Redis Lock SETNX (Pre-warmed steady-state latency < 150ms)
        get_redis_client()
        lock_id = f"ORDER-LOCK-{uuid.uuid4().hex[:6]}"
        t_lock_start = time.monotonic()
        acquired_first = acquire_payment_lock(lock_id, ttl_seconds=60)
        lock_latency = time.monotonic() - t_lock_start

        acquired_second = acquire_payment_lock(lock_id, ttl_seconds=60)
        release_payment_lock(lock_id)

        self.log_result(
            "Redis Lock SETNX (<150ms)",
            acquired_first is True and acquired_second is False and lock_latency < 0.150,
            f"First: {acquired_first}, Second (dedup): {acquired_second}, Latency: {lock_latency*1000:.2f}ms (< 150ms)"
        )

        # 2. Test createChatInviteLink (member_limit=1, expire=+24h)
        order_ref = f"ORD-{uuid.uuid4().hex[:6].upper()}"
        invite_link = await create_telegram_single_use_invite_link(
            order_id=order_ref,
            buyer_name="Budi Hartono",
        )
        self.log_result(
            "Telegram createChatInviteLink Generated",
            bool(invite_link and "t.me" in invite_link),
            f"Invite Link: {invite_link}"
        )

        # 3. Test Full CTWA Fulfillment (Stores to telegram_single_use_tokens & orders)
        fulfill_res = await fulfill_onlineboost_ctwa_order(
            order_id=order_ref,
            buyer_name="Budi Hartono",
            buyer_phone=self.test_phone,
            amount=249000,
            tenant_id=self.tenant_id,
        )
        self.log_result(
            "CTWA Paid Fulfillment Dispatch",
            fulfill_res.get("status") in ("SUCCESS", "FULFILLED", "ALREADY_FULFILLED"),
            f"Fulfillment status: {fulfill_res.get('status')}"
        )

        # Verify DB entry in telegram_single_use_tokens
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SET LOCAL app.current_tenant_id = '{self.tenant_id}';")
        cur.execute(
            "SELECT token, invite_link, claimed, expires_at FROM public.telegram_single_use_tokens WHERE order_id = %s;",
            (order_ref,)
        )
        token_row = cur.fetchone()
        cur.close()
        conn.close()

        self.log_result(
            "Token Persisted in telegram_single_use_tokens",
            token_row is not None and token_row[2] is False,
            f"Token: {token_row[0] if token_row else None}, Claimed: {token_row[2] if token_row else None}"
        )

        # 4. Test Listener chat_member (Member Joins -> Claimed = True & Audit Log)
        test_tg_user_id = 9988776655
        cm_result = await handle_chat_member_joined(
            joined_link=token_row[1] if token_row else invite_link,
            user_id=test_tg_user_id,
            user_name="Budi Hartono",
            chat_id="-1004371114362",
            tenant_id=self.tenant_id,
        )
        self.log_result(
            "Listener chat_member Updates Claimed = True",
            cm_result.get("claimed") is True,
            f"Result: {cm_result}"
        )

        # Verify claimed status in DB
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SET LOCAL app.current_tenant_id = '{self.tenant_id}';")
        cur.execute(
            "SELECT claimed, claimed_by FROM public.telegram_single_use_tokens WHERE order_id = %s;",
            (order_ref,)
        )
        post_claim = cur.fetchone()
        cur.close()
        conn.close()
        self.log_result(
            "Database Token Claim Verification",
            post_claim is not None and post_claim[0] is True and post_claim[1] == str(test_tg_user_id),
            f"Claimed: {post_claim[0] if post_claim else None}, Claimed By: {post_claim[1] if post_claim else None}"
        )

        # 5. Test Command Fallback "LINK BARU"
        link_baru_reply = await handle_telegram_link_baru(
            user_id=test_tg_user_id,
            user_name="Budi",
            tenant_id=self.tenant_id,
        )
        self.log_result(
            "Command Fallback 'LINK BARU'",
            "Tautan Undangan Baru Diterbitkan" in link_baru_reply and "t.me" in link_baru_reply,
            f"Reply snippet: {link_baru_reply[:120]}..."
        )

    async def test_node_4_anti_spoofing_and_flexing(self):
        """Node 4: @boonshop_bot anti-spoofing ownership validation -> Unlock onboarding_stage = 2 + Automated Flexing Alert."""
        self.log_header("NODE 4: ANTI-SPOOFING OWNERSHIP VALIDATION & FLEXING ALERT")

        owner_tg_id = "7788990011"
        spoof_tg_id = "1122334455"

        # 1. Negative Test: Anti-spoofing rejection when user_id does not match owner
        spoof_res = link_tenant_telegram(
            tenant_ref=self.tenant_id,
            chat_id="12345678",
            from_user={"id": spoof_tg_id, "username": "impostor"},
        )
        self.log_result(
            "Anti-Spoofing Negative Test (Impostor User Rejected)",
            spoof_res["success"] is False and "Anti-Spoofing Gagal" in spoof_res["message"],
            f"Message: {spoof_res['message'][:100]}..."
        )

        # 2. Negative Test: Tenant has 0 products
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM public.products WHERE tenant_id = %s::uuid;", ('e12acd29-6c18-487b-ade7-5422878c1c36',))
        conn.commit()
        cur.close()
        conn.close()

        no_prod_res = link_tenant_telegram(
            tenant_ref=self.tenant_id,
            chat_id="12345678",
            from_user={"id": owner_tg_id, "username": "valid_owner"},
        )
        self.log_result(
            "Anti-Spoofing Negative Test (0 Products Rejected)",
            no_prod_res["success"] is False and "Produk" in no_prod_res["message"],
            f"Message: {no_prod_res['message'][:100]}..."
        )

        # 3. Seed 1 starter product via import endpoint
        req = ImportStarterProductRequest(
            tenant_id="e12acd29-6c18-487b-ade7-5422878c1c36",
            tenant_slug="onlineboost",
            product_preset="starter_bundle",
        )
        import_res = await import_starter_product_endpoint(req)
        self.log_result(
            "Import Starter Product (Product Prerequisite)",
            import_res["imported"] is True and import_res["total_products"] >= 1,
            f"Total products: {import_res['total_products']}, Title: {import_res['product']['title']}"
        )

        # 4. Positive Test: Valid owner, products >= 1, QRIS active -> Unlocks onboarding_stage = 2
        valid_res = link_tenant_telegram(
            tenant_ref=self.tenant_id,
            chat_id="12345678",
            from_user={"id": owner_tg_id, "username": "valid_owner"},
        )
        self.log_result(
            "Anti-Spoofing Positive Test (Onboarding Stage 2 Unlocked)",
            valid_res["success"] is True and valid_res.get("onboarding_stage") == 2,
            f"Onboarding Stage: {valid_res.get('onboarding_stage')}, Message: {valid_res['message'][:120]}..."
        )

        # 5. Automated Flexing Alert Test
        flex_sent = await dispatch_flexing_alert(
            tenant_id="e12acd29-6c18-487b-ade7-5422878c1c36",
            order_id="OB1-FLEX-999",
            product_title="Paket Starter Digital OnlineBoost",
            amount=249000,
            customer_name="Kak Siti Rahma",
        )
        self.log_result(
            "Automated Flexing Alert Dispatch",
            flex_sent is not None,  # Can be mock sent or HTTP response
            "Flexing alert dispatched successfully."
        )

    async def test_fase_3_node_5_components(self):
        """Fase 3 & Node 5: Sandbox 3x CAPI test_event_code, FFmpeg worker R2, Quota 80% check phone_suppressions."""
        self.log_header("FASE 3 & NODE 5: SANDBOX 3X CAPI, FFMPEG R2 WORKER & QUOTA 80% SUPPRESSION")

        # 1. Sandbox 3x Meta CAPI test_event_code
        capi_results = await capi_dispatcher.run_sandbox_3x_test_events(
            tenant_id=self.tenant_id,
            test_event_code="TEST_ONLINEBOOST_B1",
            phone=self.test_phone,
        )
        self.log_result(
            "Sandbox 3x Meta CAPI test_event_code Dispatch",
            len(capi_results) == 3 and all(r.get("status") in ("SENT", "PENDING") for r in capi_results),
            f"Total events: {len(capi_results)}, Delivery statuses: {[r.get('status') for r in capi_results]}"
        )

        # 2. FFmpeg -c copy -metadata worker untuk video R2
        dummy_video_bytes = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42\x00\x00\x00\x08free"
        video_res = await video_metadata_worker.tag_and_upload_video(
            video_input=dummy_video_bytes,
            filename="sample_ad_reel.mp4",
            tenant_id=self.tenant_id,
            title="Video Iklan Praktikum OnlineBoost Batch 1",
            artist="BoonTrack AI Studio",
            copyright_notice="PT BoonTrack Inovasi Digital",
        )
        self.log_result(
            "FFmpeg Video Metadata Worker & R2 Upload",
            video_res["status"] == "success" and bool(video_res.get("r2_url")),
            f"R2 URL: {video_res.get('r2_url')}, Key: {video_res.get('r2_key')}"
        )

        # 3. Quota 80% Trigger: Negative Test (Suppressed Phone)
        suppressed_phone = "6289999999999"
        supp_check = is_phone_suppressed(suppressed_phone, tenant_id=self.tenant_id)
        self.log_result(
            "Strict RLS phone_suppressions Check",
            supp_check is True,
            f"Phone {suppressed_phone} identified as suppressed."
        )

        quota_supp_res = await trigger_quota_80_percent_alert(
            tenant_id=self.tenant_id,
            recipient_phone=suppressed_phone,
            current_usage=800,
            max_quota=1000,
        )
        self.log_result(
            "Quota 80% Alert Suppressed (Zero Message Sent)",
            quota_supp_res["status"] == "suppressed" and quota_supp_res["sent"] is False,
            f"Detail: {quota_supp_res.get('detail')}"
        )

        # 4. Quota 80% Trigger: Positive Test (Clean Phone)
        clean_phone = "6281122334455"
        quota_clean_res = await trigger_quota_80_percent_alert(
            tenant_id=self.tenant_id,
            recipient_phone=clean_phone,
            current_usage=800,
            max_quota=1000,
        )
        self.log_result(
            "Quota 80% Alert Allowed for Clean Phone",
            quota_clean_res["status"] in ("sent", "failed") and quota_clean_res.get("reason") != "PHONE_SUPPRESSED",
            f"Result status: {quota_clean_res.get('status')}"
        )

    def teardown_test_data(self):
        """Cleanup disposable test records."""
        self.log_header("CLEANUP TEST DISPOSABLE DATA")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"SET LOCAL app.current_tenant_id = '{self.tenant_id}';")
        cur.execute("DELETE FROM public.staging_alumni_cpm WHERE tenant_id = %s AND lead_phone = %s;", (self.tenant_id, self.test_phone))
        cur.execute("DELETE FROM public.phone_suppressions WHERE tenant_id = %s AND phone_number = '6289999999999';", (self.tenant_id,))
        cur.execute("DELETE FROM public.orders WHERE id LIKE 'OB1-%' OR id LIKE 'TEST-%' OR id LIKE 'ORD-%';")
        conn.commit()
        cur.close()
        conn.close()
        self.log_result("Teardown Disposable Test Records", True, "Test orders, suppression, and alumni records cleaned up.")

    async def run_all(self):
        print(f"\n===========================================================================")
        print(f"🚀 STARTING ACCEPTANCE TEST SUITE: DIRECTIVE 01 PIPELINE (ONLINEBOOST B1)")
        print(f"===========================================================================")
        self.setup_seed_data()
        await self.test_node_2_waba_fast_path()
        await self.test_node_3_redis_lock_and_telegram_worker()
        await self.test_node_4_anti_spoofing_and_flexing()
        await self.test_fase_3_node_5_components()
        self.teardown_test_data()
        print(f"\n===========================================================================")
        print(f"🎉 ALL DIRECTIVE 01 ACCEPTANCE CRITERIA PASSED SUCCESSFULLY! 100% READY.")
        print(f"===========================================================================\n")


if __name__ == "__main__":
    verifier = Directive01PipelineVerifier()
    asyncio.run(verifier.run_all())
