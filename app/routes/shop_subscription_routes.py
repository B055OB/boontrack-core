import logging
import re
from datetime import datetime, timedelta
from aiohttp import web
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.services.whatsapp_service import get_supabase
from app.services.subscription_service import create_subscription_invoice, process_successful_subscription

logger = logging.getLogger("SHOP_SUBSCRIPTION_ROUTER")

# Router Aiohttp
shop_subscription_aiohttp_routes = web.RouteTableDef()

# Router FastAPI
shop_subscription_fastapi_router = APIRouter(prefix="/api/v1/shop/subscriptions", tags=["Shop Subscriptions"])


# --- Helper Sanitasi Slug ---
def sanitize_slug(slug: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9-]', '-', slug.strip().lower())
    return re.sub(r'-+', '-', cleaned).strip('-')


# --- Shared Check Slug Logic (Anti-Squatting Check) ---
async def check_slug_availability_logic(slug: str):
    clean_slug = sanitize_slug(slug)
    if not clean_slug or len(clean_slug) < 3:
        return {"available": False, "slug": "", "message": "Format slug toko minimal 3 karakter alfanumerik."}, 400

    supabase = get_supabase()
    if not supabase:
        return {"available": True, "slug": clean_slug, "message": "Nama toko siap digunakan."}, 200

    try:
        # 1. Cek di tabel utama merchants
        m_existing = supabase.table("merchants").select("id").eq("slug", clean_slug).execute()
        if m_existing.data and len(m_existing.data) > 0:
            return {
                "available": False,
                "slug": clean_slug,
                "message": f"Nama toko '{clean_slug}' sudah terdaftar, silakan pilih nama lain."
            }, 200

        # 2. Cek di tabel slug_reservations yang belum expired
        now_iso = datetime.utcnow().isoformat()
        r_existing = supabase.table("slug_reservations")\
            .select("id")\
            .eq("slug", clean_slug)\
            .eq("status", "RESERVED")\
            .gt("expires_at", now_iso)\
            .execute()

        if r_existing.data and len(r_existing.data) > 0:
            return {
                "available": False,
                "slug": clean_slug,
                "message": f"Nama toko '{clean_slug}' sedang direservasi calon merchant lain."
            }, 200

        return {
            "available": True,
            "slug": clean_slug,
            "message": "Nama toko tersedia! Silakan lanjutkan registrasi & pembayaran."
        }, 200
    except Exception as e:
        logger.error(f"[CHECK SLUG ERROR] {e}")
        return {"available": True, "slug": clean_slug, "message": "Nama toko siap digunakan."}, 200


# --- Shared Webhook Logic ---
async def handle_xendit_subscription_webhook_logic(payload: dict):
    status = str(payload.get("status", "")).upper()
    metadata = payload.get("metadata", {}) or {}
    external_id = str(payload.get("external_id", "") or payload.get("id", ""))
    
    if status == "PAID":
        tenant_slug = metadata.get("tenant_slug")

        if not tenant_slug and external_id.startswith("sub_"):
            parts = external_id.split("_")
            if len(parts) >= 2 and parts[1]:
                tenant_slug = sanitize_slug(parts[1])

        if not tenant_slug:
            logger.warning(f"[XENDIT WEBHOOK IGNORED] Tidak ada tenant_slug valid. Payload: {payload}")
            return {
                "status": "ignored",
                "reason": "Missing tenant_slug in metadata and external_id"
            }, 200

        plan_tier = metadata.get("plan_tier") or "growth"
        affiliate_id = metadata.get("affiliate_id")
        am_id = metadata.get("am_id")

        logger.info(f"[XENDIT WEBHOOK PROCESS] Mengaktifkan tenant: {tenant_slug}, Plan: {plan_tier}, Inv: {external_id}")

        result = await process_successful_subscription(
            tenant_slug=tenant_slug,
            plan_tier=plan_tier,
            xendit_invoice_id=external_id,
            affiliate_id=affiliate_id,
            am_id=am_id
        )
        return result, 200

    return {"status": "ignored", "reason": f"Invoice status is {status}"}, 200


# --- Pydantic Payload Schema ---
class CreateSubPayload(BaseModel):
    tenant_slug: str
    plan_tier: str = "growth"
    business_category: Optional[str] = "general"
    merchant_name: Optional[str] = "Owner"
    merchant_phone: Optional[str] = ""
    customer_email: Optional[str] = "merchant@boontrack.com"
    referral_code: Optional[str] = None
    affiliate_id: Optional[str] = None
    am_id: Optional[str] = None


# --- Shared Create Subscription & Merchant Persistence Logic ---
async def create_subscription_logic(payload: CreateSubPayload):
    clean_slug = sanitize_slug(payload.tenant_slug)
    supabase = get_supabase()

    if supabase:
        try:
            # 1. Kunci reservasi slug selama 24 jam
            supabase.table("slug_reservations").upsert({
                "slug": clean_slug,
                "reserved_by_phone": payload.merchant_phone or "",
                "status": "RESERVED",
                "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat()
            }, on_conflict="slug").execute()

            # 2. Catat / Update data calon merchant ke database
            supabase.table("merchants").upsert({
                "slug": clean_slug,
                "store_name": payload.merchant_name or clean_slug,
                "business_category": payload.business_category or "general",
                "owner_name": payload.merchant_name or "Owner",
                "owner_whatsapp": payload.merchant_phone or "",
                "owner_email": payload.customer_email or "merchant@boontrack.com",
                "status": "PENDING_PAYMENT",
                "plan_tier": payload.plan_tier.upper(),
                "referral_code": payload.referral_code or payload.affiliate_id,
                "is_otp_verified": True
            }, on_conflict="slug").execute()
        except Exception as e:
            logger.error(f"[MERCHANT REGISTRATION ERROR] Gagal menyimpan data merchant: {e}")

    # 3. Terbitkan invoice Xendit
    return await create_subscription_invoice(
        tenant_slug=clean_slug,
        plan_tier=payload.plan_tier,
        customer_email=payload.customer_email or "merchant@boontrack.com",
        affiliate_id=payload.referral_code or payload.affiliate_id,
        am_id=payload.am_id
    )


# --- Aiohttp Endpoints ---

@shop_subscription_aiohttp_routes.get("/api/v1/shop/subscriptions/check-slug/{slug}")
async def aiohttp_check_slug(request: web.Request) -> web.Response:
    slug = request.match_info.get("slug", "")
    res, status_code = await check_slug_availability_logic(slug)
    return web.json_response(res, status=status_code)


@shop_subscription_aiohttp_routes.post("/api/v1/shop/subscriptions/create")
async def aiohttp_create_sub(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        payload = CreateSubPayload(**body)
        res = await create_subscription_logic(payload)
        return web.json_response(res, status=200)
    except Exception as e:
        logger.error(f"[CREATE SUB ERROR] {e}")
        return web.json_response({"error": str(e)}, status=500)


@shop_subscription_aiohttp_routes.post("/api/v1/shop/subscriptions/webhook/xendit")
async def aiohttp_xendit_sub_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        res, status = await handle_xendit_subscription_webhook_logic(data)
        return web.json_response(res, status=status)
    except Exception as e:
        logger.error(f"[XENDIT SUB WEBHOOK ERROR] {e}")
        return web.json_response({"error": str(e)}, status=500)


def register_shop_subscription_routes(app: web.Application):
    app.add_routes(shop_subscription_aiohttp_routes)
    logger.info("[ROUTER] Shop Subscription & Commission routes registered (Aiohttp).")


# --- FastAPI Endpoints ---

@shop_subscription_fastapi_router.get("/check-slug/{slug}")
async def fastapi_check_slug(slug: str):
    res, _ = await check_slug_availability_logic(slug)
    return res


@shop_subscription_fastapi_router.post("/create")
async def fastapi_create_sub(payload: CreateSubPayload):
    return await create_subscription_logic(payload)


@shop_subscription_fastapi_router.post("/webhook/xendit")
async def fastapi_xendit_sub_webhook(payload: dict):
    res, _ = await handle_xendit_subscription_webhook_logic(payload)
    return res