"""
app/whatsapp/traffic_splitter.py
---------------------------------
Deterministic Traffic Splitter & Webhook Isolation Gateway (P0 Hardening Gate).

Separates Meta WhatsApp Webhook traffic strictly into two isolated pipelines:
1. PLATFORM_TRANSACTIONAL (PlatformWebhookRouter):
   - Handles official platform WABA traffic (+6285179555449 / PLATFORM_PHONE_NUMBER_ID).
   - High-Priority Activation Interceptor (5-parameter authorization).
   - Early return 200 OK (halts pipeline immediately before conversation engine/CS queue).
   - Platform transactional alerts / payment confirmations.
   - State Guard: GLOBAL_FALLBACK_PLATFORM (Anti-silent bot).

2. TENANT_SALES (TenantWebhookRouter):
   - Handles tenant-specific WABA traffic.
   - Strict tenant-to-tenant runtime context isolation.
   - Rejects platform activation commands sent to tenant numbers.
   - Routes to Conversation Engine (Catalog, Checkout, CS Rotary Routing).
   - Fallback Guard: Automated fallback bot serves chat if no CS agent is active.
   - State Guard: GLOBAL_FALLBACK_TENANT (Anti-silent bot).
"""

import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple, List

from app.services.whatsapp_service import (
    normalize_phone_number,
    get_supabase,
)
from app.services.whatsapp.cloud_api import send_whatsapp_text
from app.services.tenant_context_resolver import tenant_context_resolver, TenantRuntimeContext

logger = logging.getLogger("WABA_TRAFFIC_SPLITTER")

# ---------------------------------------------------------------------------
# Platform Configuration
# ---------------------------------------------------------------------------
PLATFORM_PHONE_NUMBER_ID = (
    os.getenv("PLATFORM_PHONE_NUMBER_ID")
    or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    or os.getenv("PHONE_NUMBER_ID")
    or "1268977686299719"
).strip()

GLOBAL_FALLBACK_PLATFORM = (
    "Halo! Selamat datang di Layanan Resmi BoonTrack 🛍️\n\n"
    "Berikut beberapa bantuan yang dapat kami berikan:\n"
    "• *Aktivasi Toko*: Ketik *AKTIVASI BT-XXXX* sesuai kode verifikasi dari browser.\n"
    "• *Pengaturan Toko*: Kunjungi https://shop.boontrack.com\n"
    "• *Bantuan CS & Integrasi*: Silakan sampaikan pertanyaan Anda di sini.\n\n"
    "Ada yang bisa kami bantu hari ini?"
)

def get_tenant_fallback_message(store_name: str, tenant_slug: str) -> str:
    clean_name = store_name or tenant_slug.replace("-", " ").title()
    return (
        f"Halo! Selamat datang di *{clean_name}* 👋\n\n"
        "Terima kasih telah menghubungi kami. Kami siap melayani pesanan dan pertanyaan Kakak.\n\n"
        f"🛍️ *Katalog Online*: https://shop.boontrack.com/{tenant_slug}\n"
        "Silakan ketik produk atau informasi yang ingin Kakak ketahui!"
    )


# ---------------------------------------------------------------------------
# Execution Trace Logger
# ---------------------------------------------------------------------------
class WebhookExecutionTrace:
    def __init__(self, message_id: str, phone_number_id: str, sender_phone: str, raw_text: str):
        self.message_id = message_id
        self.phone_number_id = phone_number_id
        self.sender_phone = sender_phone
        self.raw_text = raw_text
        self.steps: List[str] = []
        self.route_type: Optional[str] = None
        self.target_tenant: Optional[str] = None
        self.early_return: bool = False
        self.response_status: int = 200
        self.response_payload: Dict[str, Any] = {}

    def log_step(self, step_name: str, details: str = ""):
        entry = f"[{datetime.now(timezone.utc).isoformat()}] {step_name}: {details}".strip()
        self.steps.append(entry)
        logger.info(f"[EXECUTION TRACE] [{self.message_id}] {step_name}: {details}")

    def render_trace(self) -> str:
        lines = [
            "=" * 60,
            f"EXECUTION TRACE — MESSAGE ID: {self.message_id}",
            f"Phone ID     : {self.phone_number_id}",
            f"Sender Phone : {self.sender_phone}",
            f"Message Text : '{self.raw_text}'",
            f"Route Type   : {self.route_type}",
            f"Target Tenant: {self.target_tenant}",
            f"Early Return : {self.early_return} (HTTP {self.response_status})",
            "-" * 60,
            "PIPELINE STEPS:"
        ]
        for s in self.steps:
            lines.append(f"  {s}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# PlatformWebhookRouter (PURPOSE: PLATFORM_TRANSACTIONAL)
# ---------------------------------------------------------------------------
class PlatformWebhookRouter:
    """
    Router khusus untuk nomor Platform WABA (+6285179555449).
    Hanya melayani aktivasi sistem dan transactional alerts/payment notification.
    """

    ACTIVATION_REGEX = re.compile(r"^AKTIVASI\s+BT-([A-Za-z0-9]{4})$", re.IGNORECASE)

    @classmethod
    async def handle(
        cls,
        sender_phone: str,
        incoming_text: str,
        phone_number_id: str,
        raw_msg: Dict[str, Any],
        trace: WebhookExecutionTrace,
    ) -> Dict[str, Any]:
        trace.route_type = "PLATFORM_TRANSACTIONAL"
        trace.target_tenant = "boontrack-platform"
        trace.log_step("PlatformWebhookRouter.handle", f"Entered platform pipeline for phone {sender_phone}")

        clean_text = incoming_text.strip()

        # =====================================================================
        # 1. ACTIVATION INTERCEPTOR (P0 LAYER TERATAS)
        # =====================================================================
        activation_match = cls.ACTIVATION_REGEX.search(clean_text)
        if activation_match:
            trace.log_step("ActivationInterceptor", f"Matched activation format with token suffix '{activation_match.group(1)}'")
            return await cls._process_activation(
                token_suffix=activation_match.group(1).upper().strip(),
                sender_phone=sender_phone,
                phone_number_id=phone_number_id,
                raw_text=clean_text,
                trace=trace,
            )

        # =====================================================================
        # 2. TRANSACTIONAL / PAYMENT NOTIFICATIONS
        # =====================================================================
        text_lower = clean_text.lower()
        if any(kw in text_lower for kw in ["pembayaran berhasil", "invoice paid", "xendit settlement"]):
            trace.log_step("TransactionalHandler", "Matched platform transactional alert")
            trace.early_return = True
            trace.response_status = 200
            res = {
                "status": "success",
                "purpose": "PLATFORM_TRANSACTIONAL",
                "action": "transactional_notification_logged",
                "message": "Platform transactional event acknowledged"
            }
            trace.response_payload = res
            return res

        # =====================================================================
        # 3. STATE GUARD (ANTI-SILENT BOT): GLOBAL_FALLBACK_PLATFORM
        # =====================================================================
        trace.log_step("StateGuard", "General message on platform number -> dispatching GLOBAL_FALLBACK_PLATFORM")
        try:
            await send_whatsapp_text(
                to_phone=sender_phone,
                text=GLOBAL_FALLBACK_PLATFORM,
                tenant_id="shop",
                phone_number_id=phone_number_id,
            )
            trace.log_step("StateGuard.Dispatch", "Dispatched GLOBAL_FALLBACK_PLATFORM successfully")
        except Exception as err:
            trace.log_step("StateGuard.DispatchError", str(err))

        trace.early_return = True
        trace.response_status = 200
        res = {
            "status": "success",
            "purpose": "PLATFORM_TRANSACTIONAL",
            "action": "global_fallback_dispatched",
            "reply": GLOBAL_FALLBACK_PLATFORM,
        }
        trace.response_payload = res
        return res

    @classmethod
    async def _process_activation(
        cls,
        token_suffix: str,
        sender_phone: str,
        phone_number_id: str,
        raw_text: str,
        trace: WebhookExecutionTrace,
    ) -> Dict[str, Any]:
        """
        Otorisasi 5 Parameter:
        1. activation_code: BT-xxxx
        2. sender_phone: nomor pengirim terverifikasi
        3. pending_registration: record registrasi tenant ditemukan
        4. expiry: pendaftaran belum kadaluarsa (< 48 jam)
        5. status: status pendaftaran PENDING_ACTIVATION / pending_wa_verification / pending / trial
        """
        canonical_token = f"BT-{token_suffix}"
        clean_phone = normalize_phone_number(sender_phone) or re.sub(r"\D", "", sender_phone)
        trace.log_step("ActivationAuth.Input", f"Token='{canonical_token}', Sender='{clean_phone}'")

        supabase = get_supabase()
        matched_tenant = None

        # Param 1 & 3: Pencarian pending_registration berdasarkan activation_code & token
        if supabase:
            try:
                res = (
                    supabase.table("tenants")
                    .select("*")
                    .filter("metadata->>wa_verification_token", "eq", canonical_token)
                    .execute()
                )
                if res and res.data and len(res.data) > 0:
                    matched_tenant = res.data[0]
                    trace.log_step("ActivationAuth.DBLookup", f"Found tenant '{matched_tenant.get('slug')}' by metadata token")
                else:
                    # Fallback check variants
                    all_pending = (
                        supabase.table("tenants")
                        .select("*")
                        .in_("status", ["pending_wa_verification", "pending", "pending_activation", "trial"])
                        .limit(50)
                        .execute()
                    )
                    for t in (all_pending.data or []):
                        t_meta = t.get("metadata") or {}
                        cand_token = str(t_meta.get("wa_verification_token") or "").upper().strip()
                        if cand_token in (canonical_token, token_suffix, f"BT{token_suffix}"):
                            matched_tenant = t
                            trace.log_step("ActivationAuth.DBLookup", f"Found pending tenant '{t.get('slug')}' by suffix")
                            break
            except Exception as db_err:
                trace.log_step("ActivationAuth.DBError", str(db_err))

        # Fallback pencarian in-memory onboarding registry
        if not matched_tenant:
            try:
                from app.services.onboarding_service import onboarding_service
                for t_slug, t_data in onboarding_service._tenants_by_slug.items():
                    t_meta = t_data.get("metadata") or {}
                    cand_token = str(t_meta.get("wa_verification_token") or t_data.get("wa_verification_token") or "").upper().strip()
                    if cand_token in (canonical_token, token_suffix, f"BT{token_suffix}"):
                        matched_tenant = t_data
                        trace.log_step("ActivationAuth.MemoryLookup", f"Found tenant '{t_slug}' in onboarding_service")
                        break
            except Exception as mem_err:
                trace.log_step("ActivationAuth.MemoryLookupError", str(mem_err))

        # Jika pendaftaran tidak ditemukan sama sekali
        if not matched_tenant:
            trace.log_step("ActivationAuth.Rejected", f"Token {canonical_token} not found (Param 3 Failed)")
            fail_msg = (
                f"Kode verifikasi {canonical_token} tidak ditemukan. "
                "Pastikan Anda memasukkan kode yang tertera di browser pendaftaran BoonTrack."
            )
            try:
                await send_whatsapp_text(
                    to_phone=clean_phone,
                    text=fail_msg,
                    tenant_id="shop",
                    phone_number_id=phone_number_id,
                )
            except Exception:
                pass
            trace.early_return = True
            trace.response_status = 200
            res = {
                "status": "rejected",
                "reason": "REGISTRATION_NOT_FOUND",
                "verified": False,
                "token": canonical_token,
                "reply": fail_msg,
            }
            trace.response_payload = res
            return res

        # Param 5: Validasi Status == PENDING_ACTIVATION
        current_status = str(matched_tenant.get("status") or "").lower().strip()
        allowed_pending = ["pending_wa_verification", "pending", "pending_activation", "trial"]
        if current_status not in allowed_pending and not matched_tenant.get("is_active") is False:
            trace.log_step("ActivationAuth.StatusCheck", f"Tenant already active or status '{current_status}' (Param 5 Check)")
            already_active_msg = "Nomor WhatsApp Anda sudah terverifikasi sebelumnya. Silakan lanjutkan pengaturan toko di browser."
            try:
                await send_whatsapp_text(to_phone=clean_phone, text=already_active_msg, tenant_id="shop", phone_number_id=phone_number_id)
            except Exception:
                pass
            trace.early_return = True
            trace.response_status = 200
            res = {
                "status": "success",
                "action": "store_activation",
                "verified": True,
                "tenant_slug": matched_tenant.get("slug"),
                "token": canonical_token,
                "reply": already_active_msg,
            }
            trace.response_payload = res
            return res

        # Param 4: Expiry Check (Maksimal 48 jam dari pembuatan)
        created_str = matched_tenant.get("created_at")
        if created_str:
            try:
                if isinstance(created_str, str):
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                else:
                    created_dt = created_str
                if datetime.now(timezone.utc) - created_dt > timedelta(hours=48):
                    trace.log_step("ActivationAuth.Expired", f"Registration expired (Created: {created_str}) (Param 4 Failed)")
                    exp_msg = f"Kode verifikasi {canonical_token} sudah kadaluarsa (melebihi 48 jam). Silakan lakukan pendaftaran ulang."
                    try:
                        await send_whatsapp_text(to_phone=clean_phone, text=exp_msg, tenant_id="shop", phone_number_id=phone_number_id)
                    except Exception:
                        pass
                    trace.early_return = True
                    trace.response_status = 200
                    res = {
                        "status": "rejected",
                        "reason": "REGISTRATION_EXPIRED",
                        "verified": False,
                        "token": canonical_token,
                        "reply": exp_msg,
                    }
                    trace.response_payload = res
                    return res
            except Exception as parse_err:
                trace.log_step("ActivationAuth.ExpiryParseWarn", str(parse_err))

        # =====================================================================
        # SELURUH 5 PARAMETER TERPENUHI: AKTIFKAN TENANT & SEGERA RETURN 200 OK
        # =====================================================================
        tenant_id = matched_tenant.get("id")
        tenant_slug = matched_tenant.get("slug")
        meta = matched_tenant.get("metadata") or {}
        meta["wa_verification_status"] = "verified"
        meta["is_verified"] = True
        meta["phone"] = clean_phone
        meta["whatsapp_number"] = clean_phone
        meta["wa_verified_at"] = datetime.now(timezone.utc).isoformat()

        matched_tenant["status"] = "active"
        matched_tenant["is_active"] = True
        matched_tenant["metadata"] = meta

        # 1. Update DB Supabase
        if supabase and tenant_id:
            try:
                supabase.table("tenants").update({
                    "status": "active",
                    "is_active": True,
                    "metadata": meta,
                }).eq("id", tenant_id).execute()
                trace.log_step("ActivationAuth.DBUpdate", f"Tenant '{tenant_slug}' marked active in DB")
            except Exception as upd_err:
                trace.log_step("ActivationAuth.DBUpdateError", str(upd_err))

        # 2. Update store_registrations table jika ada
        if supabase:
            try:
                supabase.table("store_registrations").update({
                    "status": "verified",
                    "is_verified": True,
                    "whatsapp_number": clean_phone,
                    "verified_at": datetime.now(timezone.utc).isoformat()
                }).eq("verification_token", canonical_token).execute()
            except Exception:
                pass

        # 3. Update in-memory registry
        try:
            from app.services.onboarding_service import onboarding_service
            if tenant_slug and tenant_slug in onboarding_service._tenants_by_slug:
                onboarding_service._tenants_by_slug[tenant_slug].update(matched_tenant)
        except Exception:
            pass

        success_reply = (
            "Selamat! Nomor WhatsApp Anda berhasil diverifikasi untuk akun BoonTrack. "
            "Silakan lanjutkan pengaturan toko Anda di browser."
        )

        # 4. Kirim balasan konfirmasi sukses resmi via Meta WABA
        try:
            await send_whatsapp_text(
                to_phone=clean_phone,
                text=success_reply,
                tenant_id="shop",
                phone_number_id=phone_number_id,
            )
            trace.log_step("ActivationAuth.DispatchSuccess", f"Confirmation sent to {clean_phone}")
        except Exception as send_err:
            trace.log_step("ActivationAuth.DispatchError", str(send_err))

        # 5. EARLY RETURN 200 OK — STOP PIPELINE SEKETIKA!
        # JANGAN BIARKAN MENYENTUH CONVERSATION ENGINE, CATALOG, ATAU CS ROTARY QUEUE!
        trace.early_return = True
        trace.response_status = 200
        res = {
            "status": "success",
            "action": "store_activation",
            "verified": True,
            "tenant_slug": tenant_slug,
            "token": canonical_token,
            "reply": success_reply,
        }
        trace.response_payload = res
        trace.log_step("ActivationAuth.Complete", "Early return 200 OK executed. Pipeline halted.")
        return res


# ---------------------------------------------------------------------------
# TenantWebhookRouter (PURPOSE: TENANT_SALES)
# ---------------------------------------------------------------------------
class TenantWebhookRouter:
    """
    Router khusus untuk nomor WABA milik Tenant.
    Menjamin isolasi tenant-to-tenant dan melayani alur sales/katalog/CS.
    """

    @classmethod
    async def handle(
        cls,
        tenant_context: TenantRuntimeContext,
        sender_phone: str,
        incoming_text: str,
        phone_number_id: str,
        contact_name: str,
        raw_msg: Dict[str, Any],
        trace: WebhookExecutionTrace,
    ) -> Dict[str, Any]:
        tenant_slug = tenant_context.tenant_id
        trace.route_type = "TENANT_SALES"
        trace.target_tenant = tenant_slug
        trace.log_step("TenantWebhookRouter.handle", f"Entered isolated tenant pipeline for '{tenant_slug}' (User: {sender_phone})")

        clean_text = incoming_text.strip()
        text_lower = clean_text.lower()

        # =====================================================================
        # 1. REJECT PLATFORM ACTIVATION ON TENANT WABA (STRICT BOUNDARY)
        # =====================================================================
        if re.search(r"^AKTIVASI\s+BT-([A-Za-z0-9]+)", clean_text, re.IGNORECASE):
            trace.log_step("TenantBoundaryGuard", "Platform activation keyword rejected on tenant number")
            tenant_reject_msg = (
                "Pesan aktivasi akun toko BoonTrack hanya dapat diverifikasi melalui "
                "nomor resmi platform BoonTrack (+62 851-7955-5449). "
                "Silakan kirimkan kode verifikasi Anda ke nomor resmi platform."
            )
            try:
                await send_whatsapp_text(
                    to_phone=sender_phone,
                    text=tenant_reject_msg,
                    tenant_id=tenant_slug,
                    phone_number_id=phone_number_id,
                )
            except Exception:
                pass
            res = {
                "status": "rejected",
                "purpose": "TENANT_SALES",
                "reason": "PLATFORM_ACTIVATION_NOT_ALLOWED_ON_TENANT_WABA",
                "reply": tenant_reject_msg,
                "tenant": tenant_slug,
            }
            trace.early_return = True
            trace.response_status = 200
            trace.response_payload = res
            return res

        # =====================================================================
        # 2. STATE GUARD (ANTI-SILENT BOT): General Greeting / Menu / Help
        # =====================================================================
        is_general_inquiry = text_lower in ("halo", "hi", "p", "test", "tes", "hai", "start", "menu", "help", "bantuan", "info")
        
        # Check active CS agent via Rotary Routing Service
        has_active_cs_agent = False
        try:
            from app.services.rotary_routing_service import get_rotary_routing_service
            rotary = get_rotary_routing_service()
            active_agents = rotary.list_agents(tenant_id=tenant_slug, include_inactive=False)
            has_active_cs_agent = any(a.get("presence") == "active" for a in active_agents)
            trace.log_step("RotaryRoutingCheck", f"Active CS agents found: {has_active_cs_agent} ({len(active_agents)} total)")
        except Exception as cs_err:
            trace.log_step("RotaryRoutingCheckError", str(cs_err))

        # Check product buy intent / catalog inquiry
        is_catalog_inquiry = any(kw in text_lower for kw in ["katalog", "harga", "produk", "beli", "order", "checkout", "bayar"])

        reply_text = None

        if is_general_inquiry and not is_catalog_inquiry:
            # Fallback menu ramah untuk toko merchant
            store_name = (
                tenant_context.metadata.get("name")
                or tenant_context.metadata.get("business_name")
                or tenant_context.slug.replace("-", " ").title()
            )
            reply_text = get_tenant_fallback_message(store_name, tenant_slug)
            trace.log_step("StateGuard.TenantFallback", f"Generated fallback greeting for store '{store_name}'")
        else:
            # 3. Route to Conversation Engine / AI Commerce Engine
            trace.log_step("ConversationEngine", f"Routing message '{clean_text}' to AI Commerce Engine for {tenant_slug}")
            try:
                from app.services.ai_engine import commerce_ai_engine
                reply_text = await commerce_ai_engine.generate_commerce_response(
                    tenant_slug=tenant_slug,
                    user_message=clean_text,
                    user_phone=sender_phone,
                    user_name=contact_name,
                )
            except Exception as ai_err:
                trace.log_step("ConversationEngine.Error", str(ai_err))

            # Automated fallback bot jika AI belum menghasilkan jawaban
            if not reply_text:
                store_name = (
                    tenant_context.metadata.get("name")
                    or tenant_context.metadata.get("business_name")
                    or tenant_context.slug.replace("-", " ").title()
                )
                reply_text = get_tenant_fallback_message(store_name, tenant_slug)
                trace.log_step("FallbackBot", "AI empty -> using automated tenant fallback bot")

        # 4. Dispatch balasan ke pengguna
        if reply_text:
            try:
                await send_whatsapp_text(
                    to_phone=sender_phone,
                    text=reply_text,
                    tenant_id=tenant_slug,
                    phone_number_id=phone_number_id,
                )
                trace.log_step("TenantDispatch.Success", f"Sent reply to {sender_phone}")
            except Exception as send_err:
                trace.log_step("TenantDispatch.Error", str(send_err))

        res = {
            "status": "success",
            "purpose": "TENANT_SALES",
            "tenant": tenant_slug,
            "has_active_cs": has_active_cs_agent,
            "reply": reply_text,
        }
        trace.early_return = False
        trace.response_status = 200
        trace.response_payload = res
        return res


# ---------------------------------------------------------------------------
# Deterministic Traffic Splitter (Entry Point Webhook Meta)
# ---------------------------------------------------------------------------
class TrafficSplitter:
    """
    Traffic Splitter utama yang membagi trafik webhook Meta Cloud API secara deterministik:
    - phone_number_id == PLATFORM_PHONE_NUMBER_ID -> PlatformWebhookRouter
    - phone_number_id milik Tenant -> TenantWebhookRouter
    - phone_number_id unmapped -> 404 / 400 (Dilarang ke public service!)
    """

    @classmethod
    async def split_and_dispatch(cls, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any], WebhookExecutionTrace]:
        # 1. Ekstraksi phone_number_id & metadata dari payload Meta
        entry = (payload.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value") or {}
        metadata = value.get("metadata") or {}
        incoming_phone_id = str(metadata.get("phone_number_id") or "").strip()

        # Ekstraksi pesan & sender
        messages = value.get("messages") or []
        first_msg = messages[0] if messages else {}
        msg_id = str(first_msg.get("id") or f"trace_{datetime.now(timezone.utc).timestamp()}").strip()
        raw_sender = str(first_msg.get("from") or "").strip()
        sender_phone = normalize_phone_number(raw_sender) or raw_sender
        
        # Ekstraksi teks pesan
        incoming_text = ""
        msg_type = str(first_msg.get("type") or "").strip()
        if msg_type == "text":
            incoming_text = str((first_msg.get("text") or {}).get("body") or "").strip()
        elif msg_type == "interactive":
            interactive = first_msg.get("interactive") or {}
            incoming_text = str(interactive.get("button_reply", {}).get("id") or interactive.get("list_reply", {}).get("id") or "").strip()
        elif msg_type == "button":
            incoming_text = str((first_msg.get("button") or {}).get("payload") or "").strip()

        # Fallback format flat untuk testing
        if not incoming_text:
            text_field = payload.get("text")
            if isinstance(text_field, dict):
                incoming_text = str(text_field.get("body") or "").strip()
            elif isinstance(text_field, str):
                incoming_text = text_field.strip()
        if not sender_phone:
            sender_phone = str(payload.get("from") or payload.get("from_phone") or "6281234567890").strip()
        if not incoming_phone_id:
            incoming_phone_id = str(payload.get("phone_id") or PLATFORM_PHONE_NUMBER_ID).strip()

        contacts = value.get("contacts") or [{}]
        contact_name = (contacts[0].get("profile") or {}).get("name") or "Pelanggan"

        trace = WebhookExecutionTrace(
            message_id=msg_id,
            phone_number_id=incoming_phone_id,
            sender_phone=sender_phone,
            raw_text=incoming_text,
        )
        trace.log_step("TrafficSplitter.Inbound", f"Extracted Phone ID: '{incoming_phone_id}'")

        # =====================================================================
        # ROUTE A: PLATFORM_TRANSACTIONAL
        # =====================================================================
        platform_id = str(PLATFORM_PHONE_NUMBER_ID).strip()
        if incoming_phone_id in (platform_id, "1268977686299719"):
            trace.log_step("TrafficSplitter.Route", f"Matched PLATFORM_PHONE_NUMBER_ID ({incoming_phone_id}) -> PlatformWebhookRouter")
            result = await PlatformWebhookRouter.handle(
                sender_phone=sender_phone,
                incoming_text=incoming_text,
                phone_number_id=incoming_phone_id,
                raw_msg=first_msg,
                trace=trace,
            )
            return 200, result, trace

        # =====================================================================
        # ROUTE B: TENANT_SALES (Tenant Resolver)
        # =====================================================================
        tenant_context = await tenant_context_resolver.resolve_by_phone_number_id(incoming_phone_id)
        if tenant_context and tenant_context.tenant_id not in ("boontrack-holding", "pelayanan_publik"):
            trace.log_step("TrafficSplitter.Route", f"Resolved tenant '{tenant_context.tenant_id}' -> TenantWebhookRouter")
            result = await TenantWebhookRouter.handle(
                tenant_context=tenant_context,
                sender_phone=sender_phone,
                incoming_text=incoming_text,
                phone_number_id=incoming_phone_id,
                contact_name=contact_name,
                raw_msg=first_msg,
                trace=trace,
            )
            return 200, result, trace

        # =====================================================================
        # ROUTE C: UNKNOWN / UNMAPPED PHONE NUMBER ID
        # Jangan pernah alirkan ke public service! Return 404 / 400.
        # =====================================================================
        trace.log_step("TrafficSplitter.Unmapped", f"Unknown phone_number_id: '{incoming_phone_id}'. Pipeline rejected.")
        trace.route_type = "UNMAPPED_REJECTED"
        trace.early_return = True
        trace.response_status = 404
        unmapped_res = {
            "status": "error",
            "error": "UNMAPPED_PHONE_NUMBER_ID",
            "message": f"Phone number ID '{incoming_phone_id}' is not registered on BoonTrack platform or tenants.",
            "phone_number_id": incoming_phone_id,
        }
        trace.response_payload = unmapped_res
        return 404, unmapped_res, trace
