import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from app.services.whatsapp_service import get_supabase
from app.services.affiliate_service import allocate_upgrade_commission, affiliate_service

logger = logging.getLogger("SUBSCRIPTION_SERVICE")

# 1. Mapping Harga Paket Langganan SaaS Toko (PLAN_PRICING)
PLAN_PRICING = {
    # 0. Checkout Lite -> CHECKOUT_LITE (Rp 59.000 / bln)
    "checkout_lite": 59000,
    "checkoutlite": 59000,
    "lite": 59000,

    # 3 Official Plan Tiers
    # 1. Solo / Starter -> STARTER (Rp 199.000 / bln)
    "starter": 199000,
    "solo": 199000,
    "solo_trial": 199000,

    # 2. Ads Performance -> PRO_SCALE (Rp 299.000 / bln)
    "ads_performance": 299000,
    "pro_scale": 299000,
    "proscale": 299000,
    "growth_tracking": 299000,

    # 3. Team Scale -> ENTERPRISE (Rp 499.000 / bln)
    "team_scale": 499000,
    "enterprise": 499000,
    "scale": 499000,

    # Backward Compatibility
    "growth": 199000,
    "free": 0,
}

# Alias for backward compatibility
TIER_PRICING = PLAN_PRICING


def normalize_tier_name(tier_name: Optional[str]) -> str:
    """Mengonversi nama tier ke canonical tier resmi: CHECKOUT_LITE, STARTER, PRO_SCALE, ENTERPRISE, atau FREE."""
    if not tier_name:
        return "FREE"
    clean = str(tier_name).strip().lower().replace("-", "_").replace(" ", "_")
    if clean in ("free", "none", "null", ""):
        return "FREE"
    if any(k in clean for k in ("checkout", "lite")):
        return "CHECKOUT_LITE"
    if any(k in clean for k in ("enterprise", "team", "scale")) and "pro" not in clean:
        return "ENTERPRISE"
    if any(k in clean for k in ("pro", "ads", "performance")):
        return "PRO_SCALE"
    if any(k in clean for k in ("starter", "solo", "growth")):
        return "STARTER"
    return clean.upper()


def get_tier_base_price(tier_name: str) -> int:
    """Mendapatkan harga dasar bulanan paket langganan resmi."""
    canonical = normalize_tier_name(tier_name)
    if canonical == "CHECKOUT_LITE":
        return 59000
    if canonical == "ENTERPRISE":
        return 499000
    if canonical == "PRO_SCALE":
        return 299000
    if canonical == "STARTER":
        return 199000
    if canonical == "FREE":
        return 0
    return get_plan_pricing(canonical.lower())


class ProrationResult(dict):
    """
    Struktur data hasil kalkulasi prorata yang mewarisi dict standar
    dan mendukung pemanggilan 'await' secara langsung (dual sync/async).
    """
    def __await__(self):
        async def _coro():
            return self
        return _coro().__await__()


def _lookup_tenant_subscription_data(tenant_id_or_slug: str):
    """Mencari data tier, status, dan masa berlaku langganan tenant dari database."""
    import uuid
    clean_key = str(tenant_id_or_slug or "").strip()
    db_tier = None
    db_status = None
    db_valid_until = None

    supabase = get_supabase()
    if supabase and clean_key:
        try:
            # 1. Cari di tabel tenants berdasarkan slug atau id
            t_res = supabase.table("tenants").select("id, slug, tier, status, subscription_ends_at, trial_ends_at, metadata").eq("slug", clean_key).execute()
            if not t_res.data:
                try:
                    uuid.UUID(clean_key)
                    t_res = supabase.table("tenants").select("id, slug, tier, status, subscription_ends_at, trial_ends_at, metadata").eq("id", clean_key).execute()
                except Exception:
                    pass

            if t_res and t_res.data:
                row = t_res.data[0]
                meta = row.get("metadata") or {}
                db_tier = row.get("tier") or meta.get("plan_tier") or meta.get("tier")
                db_status = row.get("status")
                db_valid_until = row.get("subscription_ends_at") or meta.get("subscription_ends_at") or row.get("trial_ends_at")

            # 2. Cari di tabel merchants jika belum lengkap
            if not db_tier or not db_valid_until:
                m_res = supabase.table("merchants").select("plan_tier, status, active_until").eq("slug", clean_key).execute()
                if m_res and m_res.data:
                    m_row = m_res.data[0]
                    db_tier = db_tier or m_row.get("plan_tier")
                    db_status = db_status or m_row.get("status")
                    db_valid_until = db_valid_until or m_row.get("active_until")

            # 3. Cari di tabel shop_subscriptions jika ada subscription aktif
            if not db_valid_until:
                s_res = supabase.table("shop_subscriptions").select("plan_tier, status, current_period_end").eq("tenant_slug", clean_key).eq("status", "ACTIVE").order("created_at", desc=True).limit(1).execute()
                if s_res and s_res.data:
                    s_row = s_res.data[0]
                    db_tier = db_tier or s_row.get("plan_tier")
                    db_valid_until = s_row.get("current_period_end")
        except Exception as err:
            logger.warning(f"[LOOKUP TENANT PRORATION ERROR] {err}")

    # Fallback default
    if not db_tier:
        db_tier = "FREE"
    if not db_status:
        db_status = "TRIAL"

    return db_tier, db_status, db_valid_until


def calculate_upgrade_proration(
    tenant_id: str,
    target_tier: str,
    current_tier: Optional[str] = None,
    valid_until: Optional[Any] = None,
    status: Optional[str] = None,
    now: Optional[datetime] = None
) -> ProrationResult:
    """
    Kalkulasi resmi upgrade prorata paket SaaS BoonTrack Core.
    
    Aturan Bisnis:
    - Jika status == 'TRIAL' atau tier in ['FREE', None]:
      * days_remaining = 0
      * credit = 0
      * final_amount = target_tier_price (durasi 30 hari penuh)
    - Jika tenant aktif berbayar (misal STARTER Rp 199.000):
      * days_remaining = max(0, (valid_until - now).days)
      * credit = round((days_remaining / 30) * old_tier_price)
      * new_cost = round((days_remaining / 30) * target_tier_price)
      * upgrade_amount = max(10000, new_cost - credit) # minimal transaksi gateway
    - Return dict berisi:
      {
        "current_tier": ...,
        "target_tier": ...,
        "days_remaining": ...,
        "credit_amount": credit,
        "new_tier_cost": new_cost,
        "final_upgrade_amount": upgrade_amount,
        "new_valid_until": valid_until (tetap)
      }
    """
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    clean_tenant = str(tenant_id or "").strip()

    # 1. Lookup ke DB jika parameter tidak diberikan secara eksplisit
    if current_tier is None or status is None or valid_until is None:
        db_tier, db_status, db_valid_until = _lookup_tenant_subscription_data(clean_tenant)
        if current_tier is None:
            current_tier = db_tier
        if status is None:
            status = db_status
        if valid_until is None:
            valid_until = db_valid_until

    target_tier_canon = normalize_tier_name(target_tier)
    target_tier_price = get_tier_base_price(target_tier_canon)

    current_tier_canon = normalize_tier_name(current_tier)
    old_tier_price = get_tier_base_price(current_tier_canon)

    status_clean = str(status or "TRIAL").strip().upper()
    is_trial_or_free = (
        status_clean in ("TRIAL", "INACTIVE", "EXPIRED", "PENDING_PAYMENT", "")
        or current_tier_canon in ("FREE", "NONE", None)
        or valid_until is None
    )

    if is_trial_or_free:
        days_remaining = 0
        credit = 0
        new_cost = target_tier_price
        upgrade_amount = target_tier_price
        new_valid_until = (now_dt + timedelta(days=30)).isoformat()
    else:
        # Parse valid_until
        valid_until_dt = None
        valid_until_str = ""
        if isinstance(valid_until, datetime):
            valid_until_dt = valid_until if valid_until.tzinfo else valid_until.replace(tzinfo=timezone.utc)
            valid_until_str = valid_until_dt.isoformat()
        elif isinstance(valid_until, str):
            valid_until_str = valid_until
            try:
                dt = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
                valid_until_dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                valid_until_dt = None

        if not valid_until_dt:
            days_remaining = 0
            credit = 0
            new_cost = target_tier_price
            upgrade_amount = target_tier_price
            new_valid_until = (now_dt + timedelta(days=30)).isoformat()
        else:
            days_remaining = max(0, (valid_until_dt - now_dt).days)
            if days_remaining <= 0:
                days_remaining = 0
                credit = 0
                new_cost = target_tier_price
                upgrade_amount = target_tier_price
                new_valid_until = (now_dt + timedelta(days=30)).isoformat()
            else:
                credit = round((days_remaining / 30.0) * old_tier_price)
                new_cost = round((days_remaining / 30.0) * target_tier_price)
                upgrade_amount = max(10000, new_cost - credit)
                new_valid_until = valid_until_str

    result_dict = {
        "current_tier": current_tier_canon,
        "target_tier": target_tier_canon,
        "days_remaining": days_remaining,
        "credit_amount": credit,
        "new_tier_cost": new_cost,
        "final_upgrade_amount": upgrade_amount,
        "new_valid_until": new_valid_until
    }
    return ProrationResult(result_dict)


def get_plan_pricing(plan_tier: str, amount: Optional[int] = None) -> int:
    """
    Menghitung harga paket langganan secara deterministik:
    1. Mencocokkan plan_tier ke PLAN_PRICING (case-insensitive, strip whitespace & hyphen/underscore).
    2. Jika tier tidak ada di dict tapi amount eksplisit valid (> 0) dikirim dari request, gunakan amount.
    3. Default fallback: 199000 (Solo / Growth).
    """
    clean_tier = str(plan_tier).strip().lower().replace("-", "_").replace(" ", "_")
    if clean_tier in PLAN_PRICING:
        return PLAN_PRICING[clean_tier]
    if amount and isinstance(amount, (int, float)) and amount > 0:
        return int(amount)
    return 199000


async def create_subscription_invoice(
    tenant_slug: str,
    plan_tier: str,
    customer_email: str = "merchant@boontrack.com",
    affiliate_id: Optional[str] = None,
    am_id: Optional[str] = None,
    amount: Optional[int] = None,
    is_upgrade: bool = False,
    proration_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Membuat invoice langganan Xendit Sandbox untuk paket SaaS toko (mendukung mode Upgrade Prorata)."""
    import httpx
    
    clean_slug = str(tenant_slug).strip().lower()
    clean_tier = str(plan_tier).strip().lower().replace("-", "_").replace(" ", "_")
    canonical_tier = normalize_tier_name(clean_tier)

    # Kalkulasi prorata jika mode upgrade
    if is_upgrade:
        if not proration_data:
            proration_data = calculate_upgrade_proration(clean_slug, canonical_tier)
        final_amount = amount or proration_data.get("final_upgrade_amount") or get_plan_pricing(clean_tier, amount)
    else:
        final_amount = get_plan_pricing(clean_tier, amount)
    
    xendit_secret_key = os.getenv("XENDIT_SECRET_KEY", "xnd_development_dummy_key_2026")
    prefix_ext = "sub_upgrade" if is_upgrade else "sub"
    external_id = f"{prefix_ext}_{clean_slug}_{clean_tier}_{int(datetime.now().timestamp())}"
    desc = (
        f"Upgrade Proration BoonTrack Shop ({canonical_tier}) - Store: {clean_slug}"
        if is_upgrade else
        f"Subscription BoonTrack Shop ({clean_tier.upper()}) - Store: {clean_slug}"
    )
    
    payload = {
        "external_id": external_id,
        "amount": final_amount,
        "payer_email": customer_email,
        "description": desc,
        "invoice_duration": 86400,
        "currency": "IDR",
        "payment_methods": ["QRIS"],
        "metadata": {
            "type": "SUBSCRIPTION_UPGRADE" if is_upgrade else "SUBSCRIPTION",
            "is_upgrade": is_upgrade,
            "tenant_slug": clean_slug,
            "plan_tier": clean_tier,
            "target_tier": canonical_tier,
            "affiliate_id": affiliate_id,
            "am_id": am_id,
            "amount": final_amount,
            "new_valid_until": proration_data.get("new_valid_until") if proration_data else None,
            "credit_amount": proration_data.get("credit_amount") if proration_data else 0,
            "days_remaining": proration_data.get("days_remaining") if proration_data else 0
        }
    }
    
    invoice_url = f"https://checkout-staging.xendit.co/web/{external_id}"
    invoice_id = external_id
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.xendit.co/v2/invoices",
                json=payload,
                auth=(xendit_secret_key, "")
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                invoice_url = data.get("invoice_url", invoice_url)
                invoice_id = data.get("id", invoice_id)
    except Exception as err:
        logger.warning(f"[XENDIT SUB API FALLBACK] {err}")
        
    # Catat draft langganan pending ke database
    supabase = get_supabase()
    if supabase:
        try:
            supabase.table("shop_subscriptions").insert({
                "tenant_slug": clean_slug,
                "plan_tier": clean_tier,
                "amount": final_amount,
                "status": "PENDING",
                "xendit_invoice_id": invoice_id,
                "xendit_external_id": external_id
            }).execute()
        except Exception as db_err:
            logger.warning(f"[DB SUB PENDING ERROR] {db_err}")
            
    return {
        "status": "success",
        "tenant_slug": clean_slug,
        "plan_tier": clean_tier,
        "amount": final_amount,
        "is_upgrade": is_upgrade,
        "proration": proration_data if is_upgrade else None,
        "invoice_url": invoice_url,
        "external_id": external_id
    }


async def process_successful_subscription(
    tenant_slug: str,
    plan_tier: str,
    xendit_invoice_id: str,
    affiliate_id: Optional[str] = None,
    am_id: Optional[str] = None,
    paid_amount: Optional[int] = None,
    is_upgrade: bool = False,
    target_valid_until: Optional[str] = None
) -> Dict[str, Any]:
    """
    1. Membagi split komisi sub-ledger 25% - 5% (atau 30% direct AM) - 70% Platform.
    2. Eksekusi state transition merchant: PENDING_PAYMENT -> PAID -> ACTIVE / UPGRADED.
    3. Jika mode upgrade prorata: Mengupdate kolom plan_tier menjadi target_tier TANPA memajukan valid_until.
    4. Provisioning default config tenant, audit log, dan structured trace log.
    """
    clean_slug = str(tenant_slug).strip().lower()
    clean_tier = str(plan_tier).strip().lower().replace("-", "_").replace(" ", "_")
    canonical_plan_tier = normalize_tier_name(clean_tier)
    if paid_amount and isinstance(paid_amount, (int, float)) and paid_amount > 0:
        gross_amount = int(paid_amount)
    else:
        gross_amount = get_plan_pricing(clean_tier, paid_amount)
    
    # Aturan Pembagian Komisi & Strict Zero Financial Leakage Guardrail
    if is_upgrade:
        from app.services.affiliate_service import affiliate_service
        comm_alloc = await affiliate_service.allocate_upgrade_commission(
            tenant_id=clean_slug,
            invoice_id=xendit_invoice_id,
            amount_paid=gross_amount,
            affiliate_id=affiliate_id,
            am_id=am_id
        )
        if comm_alloc.get("status") == "success":
            affiliate_share = comm_alloc.get("direct_commission", 0)
            am_share = comm_alloc.get("override_commission", 0)
        else:
            # ORGANIC_NO_AFFILIATE: 100% Platform Revenue (Komisi = Rp 0)
            affiliate_share = 0
            am_share = 0
        platform_net = gross_amount - affiliate_share - am_share
    else:
        # Aturan Pembagian Komisi Standar untuk Langganan Baru
        if am_id and not affiliate_id:
            affiliate_share = 0
            am_share = int(gross_amount * 0.30)
        elif affiliate_id:
            affiliate_share = int(gross_amount * 0.25)
            am_share = int(gross_amount * 0.05) if am_id else 0
        else:
            affiliate_share = 0
            am_share = 0
        platform_net = gross_amount - affiliate_share - am_share

    supabase = get_supabase()
    if not supabase:
        return {"status": "error", "message": "Supabase connection unavailable"}

    now = datetime.now(timezone.utc)

    # 1. Tentukan batas akhir masa aktif (Preserved Billing Cycle jika upgrade prorata)
    if is_upgrade:
        existing_ends_at = target_valid_until
        if not existing_ends_at:
            try:
                t_check = supabase.table("tenants").select("subscription_ends_at, metadata").eq("slug", clean_slug).execute()
                if t_check.data:
                    existing_ends_at = t_check.data[0].get("subscription_ends_at") or (t_check.data[0].get("metadata") or {}).get("subscription_ends_at")
            except Exception:
                pass
        if not existing_ends_at:
            try:
                m_check = supabase.table("merchants").select("active_until").eq("slug", clean_slug).execute()
                if m_check.data:
                    existing_ends_at = m_check.data[0].get("active_until")
            except Exception:
                pass

        period_end_str = existing_ends_at or (now + timedelta(days=30)).isoformat()
    else:
        period_end = now + timedelta(days=30)
        period_end_str = period_end.isoformat()

    # 2. Update status tabel shop_subscriptions
    sub_res = supabase.table("shop_subscriptions").insert({
        "tenant_slug": clean_slug,
        "plan_tier": clean_tier,
        "amount": gross_amount,
        "status": "ACTIVE",
        "xendit_invoice_id": xendit_invoice_id,
        "current_period_start": now.isoformat(),
        "current_period_end": period_end_str
    }).execute()

    sub_id = sub_res.data[0]["id"] if sub_res.data else None

    # 3. Catat rincian komisi ke ledger jika ada komisi diterbitkan
    if sub_id and (not is_upgrade or (affiliate_share > 0 or am_share > 0)):
        try:
            supabase.table("shop_commission_ledger").insert({
                "subscription_id": sub_id,
                "tenant_slug": clean_slug,
                "gross_amount": gross_amount,
                "affiliate_id": affiliate_id if affiliate_share > 0 else None,
                "affiliate_amount": affiliate_share,
                "am_id": am_id if am_share > 0 else None,
                "am_amount": am_share,
                "platform_net_amount": platform_net,
                "disbursement_status": "PENDING"
            }).execute()
        except Exception as ledger_err:
            logger.warning(f"[COMMISSION LEDGER ERROR] {ledger_err}")

    # Canonical 3 tier mapping:
    db_tier = canonical_plan_tier

    # 4. State Transition: Aktivasi / Upgrade Merchant & Sinkronisasi Tenant
    try:
        m_update: Dict[str, Any] = {
            "status": "ACTIVE",
            "plan_tier": db_tier,
            "updated_at": now.isoformat()
        }
        if not is_upgrade:
            m_update["active_until"] = period_end_str
        elif target_valid_until:
            m_update["active_until"] = target_valid_until

        m_res = supabase.table("merchants").update(m_update).eq("slug", clean_slug).execute()

        # Sinkronisasi ke tabel tenants (single source of truth frontend)
        try:
            t_res = supabase.table("tenants").select("metadata, subscription_ends_at").eq("slug", clean_slug).execute()
            meta = (t_res.data[0].get("metadata") or {}) if t_res.data else {}
            meta["plan_tier"] = canonical_plan_tier
            meta["tier"] = db_tier
            meta["subscription_ends_at"] = period_end_str
            if "capabilities" not in meta:
                meta["capabilities"] = {}
            meta["capabilities"]["inbox"] = (db_tier == "ENTERPRISE")
            meta["capabilities"]["seats"] = 10 if db_tier == "ENTERPRISE" else (5 if db_tier == "PRO_SCALE" else 1)
            meta["capabilities"]["omnichannel"] = (db_tier in ("PRO_SCALE", "ENTERPRISE"))
            meta["capabilities"]["ai_closing"] = (db_tier in ("PRO_SCALE", "ENTERPRISE"))
            meta["capabilities"]["ads_tracking"] = (db_tier in ("PRO_SCALE", "ENTERPRISE"))

            supabase.table("tenants").update({
                "tier": db_tier,
                "status": "active",
                "subscription_ends_at": period_end_str,
                "metadata": meta
            }).eq("slug", clean_slug).execute()
        except Exception as t_sync_err:
            logger.warning(f"[TENANT TABLE SYNC NOTE] {t_sync_err}")

        # Sinkronisasi ke PostgreSQL jika sync engine tersedia
        try:
            from app.routes.entitlement_routes import _sync_engine
            from sqlalchemy import text
            if _sync_engine:
                with _sync_engine.begin() as conn:
                    conn.execute(text("UPDATE tenants SET tier = :tier WHERE slug = :slug"), {"tier": db_tier, "slug": clean_slug})
                    conn.execute(text("""
                        INSERT INTO tenant_entitlements (tenant_slug, plan_id, max_seats, ai_closing_enabled, updated_at)
                        VALUES (:slug, :plan_id, :seats, :ai_closing, NOW())
                        ON CONFLICT (tenant_slug) DO UPDATE 
                        SET plan_id = :plan_id, max_seats = :seats, ai_closing_enabled = :ai_closing, updated_at = NOW()
                    """), {
                        "slug": clean_slug,
                        "plan_id": db_tier.lower(),
                        "seats": 10 if db_tier == "ENTERPRISE" else (5 if db_tier == "PRO_SCALE" else 1),
                        "ai_closing": db_tier in ("PRO_SCALE", "ENTERPRISE")
                    })
        except Exception as pg_sync_err:
            logger.debug(f"[POSTGRES ENTITLE SYNC NOTE] {pg_sync_err}")

        merchant_id = m_res.data[0]["id"] if m_res.data else None

        # Klaim slug resmi
        supabase.table("slug_reservations").update({
            "status": "CLAIMED",
            "updated_at": now.isoformat()
        }).eq("slug", clean_slug).execute()

        # Provisioning konfigurasi dasar tenant toko jika belum ada
        if merchant_id:
            supabase.table("tenant_configs").upsert({
                "merchant_id": merchant_id,
                "store_title": clean_slug.replace("-", " ").title(),
                "timezone": "Asia/Jakarta",
                "currency": "IDR",
                "bot_persona": "friendly_cs",
                "auto_qris_enabled": True,
                "updated_at": now.isoformat()
            }, on_conflict="merchant_id").execute()

            # Catat Audit Log Sukses
            event_name = "MERCHANT_TIER_UPGRADED" if is_upgrade else "MERCHANT_AUTO_PROVISIONED"
            supabase.table("merchant_audit_logs").insert({
                "merchant_id": merchant_id,
                "actor_type": "XENDIT_WEBHOOK",
                "event_name": event_name,
                "status": "SUCCESS",
                "payload": {
                    "tenant_slug": clean_slug,
                    "plan_tier": clean_tier,
                    "canonical_tier": canonical_plan_tier,
                    "is_upgrade": is_upgrade,
                    "valid_until": period_end_str,
                    "invoice_id": xendit_invoice_id,
                    "affiliate_id": affiliate_id,
                    "am_id": am_id
                }
            }).execute()

        # Structured Observability Trace Log (P1 Standard)
        try:
            from app.core.tracing import log_structured_event
            log_structured_event(
                service="subscription_service",
                event_type="SUBSCRIPTION_UPGRADED" if is_upgrade else "SUBSCRIPTION_ACTIVATED",
                entity_type="subscription",
                entity_id=xendit_invoice_id,
                tenant_id=clean_slug,
                provider="xendit",
                status="SUCCESS",
                extra_metadata={
                    "plan_tier": canonical_plan_tier,
                    "is_upgrade": is_upgrade,
                    "gross_amount": gross_amount,
                    "valid_until": period_end_str
                }
            )
        except Exception as trace_err:
            logger.debug(f"[TRACING SUBSCRIPTION NOTE] {trace_err}")

        action_desc = "diupgrade ke tier" if is_upgrade else "resmi aktif hingga"
        logger.info(f"[SUBSCRIPTION SUCCESS] Toko '{clean_slug}' {action_desc} {canonical_plan_tier} (Valid Until: {period_end_str}).")
    except Exception as prov_err:
        logger.error(f"[PROVISIONING ERROR] Gagal proses langganan tenant {clean_slug}: {prov_err}")

    return {
        "status": "success",
        "tenant_slug": clean_slug,
        "plan_tier": clean_tier,
        "canonical_tier": canonical_plan_tier,
        "is_upgrade": is_upgrade,
        "valid_until": period_end_str,
        "gross_amount": gross_amount,
        "split_ledger": {
            "affiliate_share": affiliate_share,
            "am_share": am_share,
            "platform_net_70_percent": platform_net
        }
    }