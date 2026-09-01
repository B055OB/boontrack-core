import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("SUBSCRIPTION_SERVICE")

TIER_PRICING = {
    "growth": 199000,
    "pro_scale": 499000
}


async def create_subscription_invoice(
    tenant_slug: str,
    plan_tier: str,
    customer_email: str = "merchant@boontrack.com",
    affiliate_id: Optional[str] = None,
    am_id: Optional[str] = None
) -> Dict[str, Any]:
    """Membuat invoice langganan Xendit Sandbox untuk paket SaaS toko."""
    import httpx
    
    clean_slug = str(tenant_slug).strip().lower()
    clean_tier = str(plan_tier).strip().lower()
    amount = TIER_PRICING.get(clean_tier, 199000)
    
    xendit_secret_key = os.getenv("XENDIT_SECRET_KEY", "xnd_development_dummy_key_2026")
    external_id = f"sub_{clean_slug}_{clean_tier}_{int(datetime.now().timestamp())}"
    
    payload = {
        "external_id": external_id,
        "amount": amount,
        "payer_email": customer_email,
        "description": f"Subscription BoonTrack Shop ({clean_tier.upper()}) - Store: {clean_slug}",
        "invoice_duration": 86400,
        "currency": "IDR",
        "metadata": {
            "type": "SUBSCRIPTION",
            "tenant_slug": clean_slug,
            "plan_tier": clean_tier,
            "affiliate_id": affiliate_id,
            "am_id": am_id
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
                "amount": amount,
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
        "amount": amount,
        "invoice_url": invoice_url,
        "external_id": external_id
    }


async def process_successful_subscription(
    tenant_slug: str,
    plan_tier: str,
    xendit_invoice_id: str,
    affiliate_id: Optional[str] = None,
    am_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    1. Membagi split komisi sub-ledger 25% - 5% (atau 30% direct AM) - 70% Platform.
    2. Eksekusi state transition merchant: PENDING_PAYMENT -> PAID -> ACTIVE.
    3. Provisioning default config tenant & audit log.
    """
    clean_slug = str(tenant_slug).strip().lower()
    clean_tier = str(plan_tier).strip().lower()
    gross_amount = TIER_PRICING.get(clean_tier, 199000)
    
    # Aturan Pembagian Komisi
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
    period_end = now + timedelta(days=30)

    # 1. Update status tabel shop_subscriptions
    sub_res = supabase.table("shop_subscriptions").insert({
        "tenant_slug": clean_slug,
        "plan_tier": clean_tier,
        "amount": gross_amount,
        "status": "ACTIVE",
        "xendit_invoice_id": xendit_invoice_id,
        "current_period_start": now.isoformat(),
        "current_period_end": period_end.isoformat()
    }).execute()

    sub_id = sub_res.data[0]["id"] if sub_res.data else None

    # 2. Catat rincian komisi ke ledger
    if sub_id:
        try:
            supabase.table("shop_commission_ledger").insert({
                "subscription_id": sub_id,
                "tenant_slug": clean_slug,
                "gross_amount": gross_amount,
                "affiliate_id": affiliate_id,
                "affiliate_amount": affiliate_share,
                "am_id": am_id,
                "am_amount": am_share,
                "platform_net_amount": platform_net,
                "disbursement_status": "PENDING"
            }).execute()
        except Exception as ledger_err:
            logger.warning(f"[COMMISSION LEDGER ERROR] {ledger_err}")

    # 3. State Transition: Aktivasi Merchant & Reservasi Slug
    try:
        m_res = supabase.table("merchants").update({
            "status": "ACTIVE",
            "active_until": period_end.isoformat(),
            "plan_tier": clean_tier.upper(),
            "updated_at": now.isoformat()
        }).eq("slug", clean_slug).execute()

        merchant_id = m_res.data[0]["id"] if m_res.data else None

        # Klaim slug resmi
        supabase.table("slug_reservations").update({
            "status": "CLAIMED",
            "updated_at": now.isoformat()
        }).eq("slug", clean_slug).execute()

        # Provisioning konfigurasi dasar tenant toko
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
            supabase.table("merchant_audit_logs").insert({
                "merchant_id": merchant_id,
                "actor_type": "XENDIT_WEBHOOK",
                "event_name": "MERCHANT_AUTO_PROVISIONED",
                "status": "SUCCESS",
                "payload": {
                    "tenant_slug": clean_slug,
                    "plan_tier": clean_tier,
                    "invoice_id": xendit_invoice_id,
                    "affiliate_id": affiliate_id,
                    "am_id": am_id
                }
            }).execute()

        logger.info(f"[PROVISIONING SUCCESS] Toko '{clean_slug}' resmi aktif hingga {period_end.isoformat()}.")
    except Exception as prov_err:
        logger.error(f"[PROVISIONING ERROR] Gagal aktivasi tenant {clean_slug}: {prov_err}")

    return {
        "status": "success",
        "tenant_slug": clean_slug,
        "plan_tier": clean_tier,
        "gross_amount": gross_amount,
        "split_ledger": {
            "affiliate_share": affiliate_share,
            "am_share": am_share,
            "platform_net_70_percent": platform_net
        }
    }