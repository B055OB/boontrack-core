"""app/services/onboarding_service.py
Merchant Provisioning & Self-Onboarding Service.

Executes atomic database transactions to provision:
1. Tenant entity (with indexed affiliate_ref).
2. Initial Product catalog item linked to tenant.
3. Merchant Payout disbursement details linked to tenant.
4. Auto-registration into the active runtime tenant registry.
"""

import re
import uuid
import logging
import hashlib
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from uuid import UUID, uuid4

from sqlalchemy import select
from app.models.tenant import Tenant, TenantTier, OnboardingMode, TenantPayout
from app.models.catalog import Product, ProductType, LicenseStatus
from app.schemas.onboarding_schema import TenantOnboardRequest
from app.configs.templates import COMMERCE_TEMPLATE, RETAIL_D2C_TEMPLATE, get_commerce_template
from app.core.tenant_loader import (
    LOADED_CONFIG_TENANTS,
    TENANT_REGISTRY,
    TenantConfig,
)
from app.schemas.tenant_config import (
    TenantIdentity,
    TenantStatus,
    TenantPersona,
    TenantMenuConfig,
)
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("ONBOARDING_SERVICE")


class TenantSlugAlreadyExistsError(ValueError):
    """Raised when a tenant with the requested slug is already registered."""
    pass


def slugify(text: str) -> str:
    """Transforms arbitrary text into a clean URL-safe slug."""
    clean = text.lower().strip()
    clean = re.sub(r"[^\w\s-]", "", clean)
    clean = re.sub(r"[\s_-]+", "-", clean)
    return clean.strip("-")


def sanitize_product_slug(raw_slug: str, fallback_title: str = "") -> str:
    """
    Sanitasi slug salespage produk:
    - Lowercase
    - Strip karakter aneh / non-alfanumerik
    - Ganti spasi, underscore, titik, dan slash menjadi tanda minus '-'
    - Gabungkan tanda '-' berurutan dan strip leading/trailing minus.
    """
    source = str(raw_slug or "").strip()
    if not source:
        source = str(fallback_title or "").strip()
    if not source:
        source = "product"

    # Lowercase & strip whitespace
    slug = source.lower().strip()
    # Ganti pemisah (spasi, underscore, titik, slash) menjadi minus '-'
    slug = re.sub(r"[\s_./\\]+", "-", slug)
    # Hapus semua karakter yang bukan alfanumerik atau '-'
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Satukan minus berulang
    slug = re.sub(r"-+", "-", slug)
    # Strip minus di awal atau akhir
    slug = slug.strip("-")

    return slug or "product"


def ensure_unique_product_slug(
    desired_slug: str,
    tenant_id_or_slug: str,
    current_product_id: Optional[str] = None,
    existing_products: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Memastikan slug produk unik per-tenant agar tidak bentrok dengan produk lain.
    Jika slug sudah digunakan oleh produk lain dalam tenant yang sama,
    secara otomatis menambahkan suffix numerik (-2, -3, dst).
    """
    used_slugs = set()

    # 1. Cek dari koleksi produk in-memory tenant
    if existing_products:
        for p in existing_products:
            p_id = str(p.get("id") or "")
            p_slug = str(p.get("slug") or "").strip().lower()
            if p_slug and (not current_product_id or p_id != str(current_product_id)):
                used_slugs.add(p_slug)

    # 2. Cek dari Supabase DB jika terhubung
    try:
        supabase = get_supabase()
        if supabase and tenant_id_or_slug:
            t_key = str(tenant_id_or_slug).strip()
            res = supabase.table("products").select("id, slug").or_(
                f"tenant_id.eq.{t_key},tenant_slug.eq.{t_key}"
            ).execute()
            if res and res.data:
                for row in res.data:
                    r_id = str(row.get("id") or "")
                    r_slug = str(row.get("slug") or "").strip().lower()
                    if r_slug and (not current_product_id or r_id != str(current_product_id)):
                        used_slugs.add(r_slug)
    except Exception as db_err:
        logger.debug(f"[ensure_unique_product_slug DB check note]: {db_err}")

    if desired_slug not in used_slugs:
        return desired_slug

    counter = 2
    candidate = f"{desired_slug}-{counter}"
    while candidate in used_slugs:
        counter += 1
        candidate = f"{desired_slug}-{counter}"

    return candidate



# Tiers yang mendapat akses fitur advanced (CAPI, Reader, Ads Tracking)
_ADVANCED_TIERS = {"ADS_PERFORMANCE", "PRO_SCALE", "TEAM_SCALE", "ENTERPRISE"}


def _build_feature_flags(tier: str, metadata_features: dict) -> dict:
    """Build feature flags dict secara deterministik berdasarkan tier tenant.

    Urutan prioritas:
    1. Jika metadata_features sudah terisi (dari DB), gunakan nilai tersebut.
    2. Jika kosong, fallback ke mapping tier bawaan.

    Args:
        tier             : Nilai tier tenant (mis. "ADS_PERFORMANCE", "STARTER")
        metadata_features: Dict features dari row["metadata"]["features"] (bisa kosong {})

    Returns:
        Dict feature flags dengan keys:
            has_capi, has_reader, ads_tracking, multi_cs
    """
    tier_upper = (tier or "STARTER").upper().strip()
    is_advanced = tier_upper in _ADVANCED_TIERS

    defaults = {
        "has_capi": is_advanced,
        "has_reader": is_advanced,
        "ads_tracking": is_advanced,
        "multi_cs": tier_upper in ("TEAM_SCALE", "ENTERPRISE"),
    }

    if not metadata_features:
        return defaults

    # Metadata override — nilai eksplisit dari DB menang atas default tier
    return {
        "has_capi": metadata_features.get("has_capi", defaults["has_capi"]),
        "has_reader": metadata_features.get("has_reader", defaults["has_reader"]),
        "ads_tracking": metadata_features.get("ads_tracking", defaults["ads_tracking"]),
        "multi_cs": metadata_features.get("multi_cs", defaults["multi_cs"]),
    }


class OnboardingService:
    """Service handling atomic merchant onboarding & provisioning."""

    def __init__(self, in_memory_mode: bool = False):
        self.in_memory_mode = in_memory_mode
        self._tenants_by_slug: Dict[str, Dict[str, Any]] = {}
        self._products_by_tenant: Dict[str, Dict[str, Any]] = {}
        self._payouts_by_tenant: Dict[str, Dict[str, Any]] = {}

    async def _identity_exists(self, phone_hash: str, device_fp_hash: str | None) -> bool:
        """Check if a phone or device fingerprint hash already exists in tenant_identities."""
        supabase = get_supabase()
        if not supabase:
            return False
        try:
            if device_fp_hash:
                filters = f"phone_hash.eq.{phone_hash},device_fingerprint_hash.eq.{device_fp_hash}"
                res = supabase.table("tenant_identities").select("id").or_(filters).execute()
            else:
                res = supabase.table("tenant_identities").select("id").eq("phone_hash", phone_hash).execute()
            return bool(res and res.data)
        except Exception as e:
            logger.warning(f"[OnboardingService] Identity existence check failed: {e}")
            return False

    async def _setup_tenant_entitlements_and_identity(self, tenant_id: str, plan_code: str, phone_hash: Optional[str], device_fp_hash: Optional[str]) -> None:
        """Insert identity record and copy entitlements from plan_entitlements to tenant_entitlements."""
        supabase = get_supabase()
        if not supabase:
            return
        # Insert identity if phone_hash is present
        if phone_hash:
            identity_payload: Dict[str, Any] = {
                "tenant_id": tenant_id,
                "phone_hash": phone_hash,
            }
            if device_fp_hash:
                identity_payload["device_fingerprint_hash"] = device_fp_hash
            try:
                supabase.table("tenant_identities").insert(identity_payload).execute()
            except Exception as e:
                logger.warning(f"[OnboardingService] Failed to insert tenant identity: {e}")
        # Copy entitlements
        try:
            ent_res = supabase.table("plan_entitlements").select("*").eq("plan_code", plan_code).execute()
        except Exception as e:
            logger.warning(f"[OnboardingService] Failed to fetch plan entitlements: {e}")
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        entitlements_to_insert = []
        if ent_res and ent_res.data:
            for row in ent_res.data:
                tenant_ent = {
                    "tenant_id": tenant_id,
                    "feature_code": row.get("feature_code"),
                    "status": "trial" if plan_code == "SOLO_TRIAL" else "active",
                    "starts_at": now_iso,
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat() if plan_code == "SOLO_TRIAL" else None,
                }
                entitlements_to_insert.append(tenant_ent)
        if entitlements_to_insert:
            try:
                supabase.table("tenant_entitlements").insert(entitlements_to_insert).execute()
            except Exception as e:
                logger.warning(f"[OnboardingService] Failed to insert tenant entitlements: {e}")


    async def onboard_tenant(self, payload: TenantOnboardRequest) -> Dict[str, Any]:
        """Provisions a new merchant, initial product, and payout in 1 atomic transaction, with reverse‑trial and anti‑abuse logic."""
        # 1. Resolve & validate tenant slug
        raw_slug = payload.slug or payload.name
        tenant_slug = slugify(raw_slug)
        if not tenant_slug:
            tenant_slug = f"tenant-{uuid4().hex[:8]}"

        # Check in-memory caches first
        if tenant_slug in self._tenants_by_slug or tenant_slug in LOADED_CONFIG_TENANTS:
            raise TenantSlugAlreadyExistsError(f"Tenant with slug '{tenant_slug}' already exists")

        # Resolve tier (Strict ARCHITECTURE.md: Free Trial & Promo default to PRO_SCALE / Ads Performance)
        tier_str = payload.tier.upper().replace("-", "_").replace(" ", "_")
        if tier_str in ("ADS_PERFORMANCE", "PROSCALE", "PRO_SCALE", "TRIAL", "FREE_TRIAL"):
            tier_enum = TenantTier.PRO_SCALE
        elif tier_str in ("TEAM_SCALE", "ENTERPRISE", "CUSTOM_ENTERPRISE"):
            tier_enum = TenantTier.ENTERPRISE
        elif tier_str in TenantTier.__members__:
            tier_enum = TenantTier[tier_str]
        else:
            tier_enum = TenantTier.PRO_SCALE

        # Resolve template & alias (RETAIL_D2C_TEMPLATE -> COMMERCE_TEMPLATE)
        raw_template = (payload.template or "COMMERCE_TEMPLATE").strip()
        if raw_template.upper() in ("RETAIL_D2C_TEMPLATE", "COMMERCE_TEMPLATE"):
            template_name = "COMMERCE_TEMPLATE"
        else:
            template_name = raw_template

        # Resolve onboarding mode (Default: SELF_SERVICE)
        raw_mode = (payload.onboarding_mode or "SELF_SERVICE").upper().strip()
        mode_enum = OnboardingMode[raw_mode] if raw_mode in OnboardingMode.__members__ else OnboardingMode.SELF_SERVICE

        # Resolve dynamic vertical parameters from generic COMMERCE_TEMPLATE
        vert_config = get_commerce_template(payload.vertical or "DIGITAL_PRODUCTS")

        # Resolve product slug
        # Resolve product slug (fresh 0 products if no product provided)
        has_initial_product = bool(payload.product and getattr(payload.product, "title", None))
        prod_slug = (
            (payload.product.slug or slugify(payload.product.title) or f"prod-{uuid4().hex[:6]}")
            if has_initial_product
            else None
        )

        # Generate official WABA activation token & code
        wa_verification_token = f"BT-{uuid4().hex[:4].upper()}"
        activation_code = f"AKTIVASI {wa_verification_token}"

        # Compute hashes for anti‑abuse
        phone_raw = payload.phone or payload.admin_phone
        phone_hash = hashlib.sha256(phone_raw.encode()).hexdigest() if phone_raw else None
        device_fp_hash = hashlib.sha256(payload.device_fingerprint.encode()).hexdigest() if payload.device_fingerprint else None

        # Determine initial plan based on existing identity (Ads Performance 7-Day Trial)
        is_duplicate = await self._identity_exists(phone_hash, device_fp_hash) if phone_hash else False
        plan_code = "FREE" if is_duplicate else "ADS_PERF"
        logger.info(f"[OnboardingService] Assigned plan '{plan_code}' for tenant '{tenant_slug}' (duplicate={is_duplicate})")

        tenant_id = uuid4()
        product_id = uuid4() if has_initial_product else None
        payout_id = uuid4() if (payload.payout and getattr(payload.payout, "account_number", None)) else None
        now = datetime.now(timezone.utc)

        # 2. Execute 1 Atomic Database Transaction via SQLAlchemy (if DB configured)
        db_executed = False
        try:
            from app.core.server import async_session
            async with async_session() as session:
                async with session.begin():
                    # Check slug collision in DB
                    existing_stmt = select(Tenant).where(Tenant.slug == tenant_slug)
                    existing_tenant = (await session.execute(existing_stmt)).scalar_one_or_none()
                    if existing_tenant:
                        raise TenantSlugAlreadyExistsError(f"Tenant with slug '{tenant_slug}' already exists")

                    # 1. Insert Tenant with onboarding_mode and template
                    tenant_record = Tenant(
                        id=tenant_id,
                        name=payload.name,
                        slug=tenant_slug,
                        tier=tier_enum,
                        onboarding_mode=mode_enum,
                        template=template_name,
                        affiliate_ref=payload.affiliate_ref,
                        is_active=False,
                        created_at=now,
                    )
                    session.add(tenant_record)
                    await session.flush()

                    # 2. Insert Initial Product (ONLY IF EXPLICITLY PROVIDED AND VALID)
                    # Clean State Invariant: Jangan suntikkan produk mock/dummy ke toko produksi baru
                    is_mock_item = bool(
                        payload.product.title.strip().lower() in ("produk uji coba", "tes produk", "sample product", "dummy product", payload.name.strip().lower())
                        or "uji coba" in payload.product.title.lower()
                    ) if has_initial_product else False
                    if has_initial_product and not is_mock_item:
                        product_type_val = (
                            ProductType[payload.product.product_type.upper()]
                            if payload.product.product_type.upper() in ProductType.__members__
                            else ProductType.DIGITAL_FILE
                        )
                        product_record = Product(
                            id=product_id,
                            tenant_id=tenant_record.id,
                            title=payload.product.title,
                            slug=prod_slug,
                            description=payload.product.description,
                            price=Decimal(str(payload.product.price)),
                            product_type=product_type_val,
                            license_status=LicenseStatus.OFFICIAL,
                            asset_reference=payload.product.asset_reference or "default_asset_v1",
                            is_available=payload.product.is_available,
                            created_at=now,
                        )
                        session.add(product_record)

                    # 3. Insert Tenant Payout (ONLY IF PROVIDED)
                    if payload.payout and getattr(payload.payout, "account_number", None):
                        payout_record = TenantPayout(
                            id=payout_id,
                            tenant_id=tenant_record.id,
                            bank_name=(payload.payout.bank_name or "BCA").upper(),
                            account_number=payload.payout.account_number,
                            account_holder=payload.payout.account_holder,
                            payout_email=payload.payout.payout_email or payload.admin_email,
                            is_verified=False,
                            created_at=now,
                        )
                        session.add(payout_record)

                    db_executed = True
                    logger.info(f"[Onboarding DB] Atomic transaction committed for tenant '{tenant_slug}' (ID: {tenant_id})")
        except TenantSlugAlreadyExistsError:
            raise
        except Exception as db_err:
            if not self.in_memory_mode:
                logger.warning(f"[Onboarding DB Note] Fallback to isolated memory provisioning: {db_err}")

        # 3. Save to In-Memory Repositories for instant access and testing
        tenant_dict = {
            "id": str(tenant_id),
            "name": payload.name,
            "slug": tenant_slug,
            "tier": tier_enum.value,
            "template": template_name,
            "vertical": (payload.vertical or vert_config["vertical"]).upper(),
            "onboarding_mode": mode_enum.value,
            "affiliate_ref": payload.affiliate_ref,
            "admin_email": payload.admin_email,
            "admin_phone": payload.admin_phone,
            "is_active": False,
            "status": "pending_wa_verification",
            "activation_code": activation_code,
            "wa_verification_token": wa_verification_token,
            "created_at": now.isoformat(),
            "metadata": {
                "template": template_name,
                "onboarding_mode": mode_enum.value,
                "vertical": (payload.vertical or vert_config["vertical"]).upper(),
                "wa_verification_token": wa_verification_token,
                "activation_code": activation_code,
                "wa_verification_status": "pending",
                "is_verified": False,
                "is_bot_active": True,
                "bot_paused": False,
                "payment_settings": {
                    "qris_raw": None,
                    "qris": None,
                    "is_qris_active": True,
                    "provider": "SELLER_NATIVE_QRIS",
                },
                "payment_config": {
                    "mode": "SELLER_NATIVE_QRIS",
                    "provider": "SELLER_NATIVE_QRIS",
                    "enable_qris": True,
                    "unique_code_system": "DOWNWARD",
                },
                "bot_persona": {
                    "tone": "ramah, profesional, solutif",
                    "rule": "ZERO_URL_HALLUCINATION",
                    "lead_collection": "NATIVE_STATE_MACHINE",
                },
            },
        }
        product_dict = None
        if has_initial_product:
            product_dict = {
                "id": str(product_id),
                "tenant_id": str(tenant_id),
                "title": payload.product.title,
                "slug": prod_slug,
                "category": getattr(payload.product, "category", None) or "Digital Course",
                "description": payload.product.description,
                "price": float(payload.product.price),
                "product_type": payload.product.product_type,
                "asset_reference": payload.product.asset_reference or "default_asset_v1",
                "is_available": payload.product.is_available,
                "created_at": now.isoformat(),
            }

        payout_dict = None
        if payload.payout and getattr(payload.payout, "account_number", None):
            payout_dict = {
                "id": str(payout_id),
                "tenant_id": str(tenant_id),
                "bank_name": (payload.payout.bank_name or "BCA").upper(),
                "account_number": payload.payout.account_number,
                "account_holder": payload.payout.account_holder,
                "payout_email": payload.payout.payout_email or payload.admin_email,
                "is_verified": False,
                "created_at": now.isoformat(),
            }

        self._tenants_by_slug[tenant_slug] = tenant_dict
        self._products_by_tenant[str(tenant_id)] = [product_dict] if product_dict else []
        self._payouts_by_tenant[str(tenant_id)] = payout_dict or {}

        # 4. Auto-register in global runtime tenant configs
        try:
            new_config = TenantConfig(
                identity=TenantIdentity(
                    tenant_id=tenant_slug,
                    name=payload.name,
                    slug=tenant_slug,
                    status=TenantStatus.ACTIVE,
                    description=(payload.product.description if has_initial_product else None) or f"Store {payload.name} ({vert_config['name']})",
                ),
                persona=TenantPersona(
                    system_prompt=f"Kamu adalah asisten resmi untuk toko {payload.name}. {vert_config['system_prompt_addon']}",
                    tone="ramah, profesional, solutif",
                    welcome_message=f"Selamat datang di {payload.name}! Ada yang bisa kami bantu hari ini?",
                ),
                menu_config=TenantMenuConfig(
                    keywords=vert_config.get("menu_keywords", {}),
                ),
            )
            LOADED_CONFIG_TENANTS[tenant_slug] = new_config
            TENANT_REGISTRY[tenant_slug] = {
                "name": payload.name,
                "module": "app.modules.commerce.router",
                "routes_attr": "commerce_routes",
                "description": f"Merchant Store {payload.name}",
                "enabled": True,
            }
            logger.info(f"[Onboarding Registry] Registered '{tenant_slug}' into active runtime loader")
        except Exception as reg_err:
            logger.warning(f"[Onboarding Registry Note] Runtime config registration warning: {reg_err}")

                # 4b. Sync Tenant Record to Supabase 'tenants' table
        try:
            supabase = get_supabase()
            if supabase:
                trial_period_end = (now + timedelta(days=7)).isoformat()
                supabase.table("tenants").upsert({
                    "id": str(tenant_id),
                    "name": payload.name,
                    "slug": tenant_slug,
                    "tier": tier_enum.value,
                    "trial_ends_at": trial_period_end,
                    "subscription_ends_at": trial_period_end,
                    "created_at": now.isoformat(),
                    "is_active": False,
                    "status": "pending_wa_verification",
                    "metadata": {
                        "template": template_name,
                        "onboarding_mode": mode_enum.value,
                        "vertical": (payload.vertical or vert_config["vertical"]).upper(),
                        "tier": tier_enum.value,
                        "plan_tier": tier_enum.value,
                        "selected_plan": "Ads Performance Trial" if tier_enum == TenantTier.PRO_SCALE else ("Team Scale" if tier_enum == TenantTier.ENTERPRISE else "Paket Solo"),
                        "subscription_status": "trial" if tier_enum == TenantTier.PRO_SCALE else "active",
                        "is_trial": True if tier_enum == TenantTier.PRO_SCALE else False,
                        "trial_days": 7 if tier_enum == TenantTier.PRO_SCALE else 0,
                        "trial_ends_at": trial_period_end if tier_enum == TenantTier.PRO_SCALE else None,
                        "subscription_ends_at": trial_period_end,
                        "wa_verification_token": wa_verification_token,
                        "activation_code": activation_code,
                        "wa_verification_status": "pending",
                        "is_verified": False,
                        "products": [],
                        "product": None,
                        "is_bot_active": True,
                        "bot_paused": False,
                        "payment_settings": {
                            "qris_raw": None,
                            "qris": None,
                            "is_qris_active": True,
                            "provider": "SELLER_NATIVE_QRIS",
                        },
                        "payment_config": {
                            "mode": "SELLER_NATIVE_QRIS",
                            "provider": "SELLER_NATIVE_QRIS",
                            "enable_qris": True,
                            "unique_code_system": "DOWNWARD",
                        },
                        "bot_persona": {
                            "tone": "ramah, profesional, solutif",
                            "rule": "ZERO_URL_HALLUCINATION",
                            "lead_collection": "NATIVE_STATE_MACHINE",
                        },
                    }
                }, on_conflict="slug").execute()
                logger.info(f"[OnboardingService] Synced tenant '{tenant_slug}' (trial_ends_at: {trial_period_end}) to Supabase")
        except Exception as sb_err:
            logger.warning(f"[OnboardingService Supabase tenant sync warning]: {sb_err}")

        # 5. Setup entitlements and identity based on plan
        try:
            await self._setup_tenant_entitlements_and_identity(
                tenant_id=str(tenant_id),
                plan_code=plan_code,
                phone_hash=phone_hash,
                device_fp_hash=device_fp_hash,
            )
        except Exception as e:
            logger.warning(f"[OnboardingService] Entitlement setup failed: {e}")

        products_list = [product_dict] if product_dict else []
        return {
            "status": "SUCCESS",
            "message": "Tenant onboarded successfully",
            "tenant_id": str(tenant_id),
            "tenant": tenant_dict,
            "product": product_dict,
            "products": products_list,
            "payout": payout_dict,
            "activation_code": activation_code,
            "wa_verification_token": wa_verification_token,
        }

    def get_activation_token_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Retrieves or generates WABA activation token for tenant."""
        clean_slug = slugify(slug)
        tenant_dict = self._tenants_by_slug.get(clean_slug)
        if not tenant_dict:
            details = self.get_tenant_details_by_slug(clean_slug)
            if details and details.get("tenant"):
                tenant_dict = details["tenant"]

        if not tenant_dict:
            return None

        meta = tenant_dict.get("metadata") or {}
        token = tenant_dict.get("wa_verification_token") or meta.get("wa_verification_token")
        if not token:
            token = f"BT-{uuid4().hex[:4].upper()}"
            tenant_dict["wa_verification_token"] = token
            if "metadata" not in tenant_dict:
                tenant_dict["metadata"] = {}
            tenant_dict["metadata"]["wa_verification_token"] = token

        act_code = tenant_dict.get("activation_code") or meta.get("activation_code") or f"AKTIVASI {token}"
        tenant_dict["activation_code"] = act_code
        if "metadata" in tenant_dict:
            tenant_dict["metadata"]["activation_code"] = act_code

        return {
            "status": "SUCCESS",
            "slug": clean_slug,
            "activation_code": act_code,
            "wa_verification_token": token,
            "is_active": tenant_dict.get("is_active", False),
        }

    def get_tenant_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Finds tenant record by slug."""
        return self._tenants_by_slug.get(slug)

    def get_latest_commerce_tenant(self) -> Optional[str]:
        """Returns the slug of the latest registered active COMMERCE_TEMPLATE tenant."""
        # 1. Check in-memory reverse order
        for slug, t_data in reversed(list(self._tenants_by_slug.items())):
            if t_data.get("template") == "COMMERCE_TEMPLATE" and t_data.get("is_active"):
                return slug

        # 2. Check LOADED_CONFIG_TENANTS for dynamic commerce tenants
        for slug in reversed(list(LOADED_CONFIG_TENANTS.keys())):
            if slug in ("atmosfitnes", "career", "boontrack-career", "bale_pananggeuhan", "pelayanan_publik"):
                continue
            return slug

        return "digicorn"

    def get_tenant_details_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Finds full tenant profile, real products list, payout details, and persona configuration."""
        raw_slug = str(slug or "").strip().lower()
        if raw_slug in ("52967979-4760-4cea-b686-cdbdb389c0e1", "app_shop_v1", "app-shop-v1", "app_shop", "app-shop", "boon", "boontrack-app-shop", "boontrack_app_shop"):
            clean_slug = "boon"
        else:
            clean_slug = slugify(raw_slug)

        cfg = LOADED_CONFIG_TENANTS.get(clean_slug)
        tenant_dict = self._tenants_by_slug.get(clean_slug)

        if not tenant_dict and clean_slug == "boon":
            tenant_dict = {
                "id": "52967979-4760-4cea-b686-cdbdb389c0e1",
                "name": "BoonTrack Official Shop",
                "slug": "boon",
                "tier": "ENTERPRISE",
                "features": _build_feature_flags("ENTERPRISE", {}),
                "template": "APP_SHOP",
                "vertical": "DIGITAL",
                "onboarding_mode": "SELF_SERVICE",
                "affiliate_ref": None,
                "admin_email": None,
                "admin_phone": "081215567168",
                "is_active": True,
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "tenant_type": "APP_SHOP_V1",
                    "runtime": "shared_core",
                    "version": "1.0",
                    "name": "BoonTrack Official Shop",
                    "tenant_name": "BoonTrack Official Shop",
                    "tenant_id": "52967979-4760-4cea-b686-cdbdb389c0e1",
                    "storefront_url": "https://shop.boontrack.com/boon",
                    "gateway_endpoint": "https://gateway.boontrack.com",
                    "whatsapp_instance": "boontrack-app-shop",
                    "phone": "081215567168",
                },
                "persona": {
                    "system_prompt": "Kamu adalah asisten resmi untuk toko BoonTrack Official Shop.",
                    "tone": "Edukatif & Expert, ramah, to-the-point",
                    "welcome_message": "Selamat datang di BoonTrack Official Shop! Ada yang bisa kami bantu?",
                    "default_fallback_message": "Mohon maaf, layanan sedang memproses antrean pesan lain.",
                    "assistant_name": "BoonTrack Official Shop Assistant",
                    "ai_name": "BoonTrack Official Shop Assistant",
                    "bot_strategy": "trust_builder",
                },
                "ai_knowledge": {
                    "ai_name": "BoonTrack Official Shop Assistant",
                    "assistant_name": "BoonTrack Official Shop Assistant",
                    "system_prompt": "Kamu adalah asisten resmi untuk toko BoonTrack Official Shop.",
                    "tone": "Edukatif & Expert, ramah, to-the-point",
                    "bot_strategy": "trust_builder",
                    "faq": [],
                },
            }
            self._tenants_by_slug["boon"] = tenant_dict
            self._tenants_by_slug["52967979-4760-4cea-b686-cdbdb389c0e1"] = tenant_dict

        if not tenant_dict:
            if cfg:
                _cfg_tier = getattr(cfg, "tier", None) or getattr(getattr(cfg, "billing", None), "tier", None) or "STARTER"
                tenant_dict = {
                    "id": str(uuid4()),
                    "name": cfg.identity.name,
                    "slug": clean_slug,
                    "tier": _cfg_tier,
                    "features": _build_feature_flags(_cfg_tier, {}),
                    "template": "COMMERCE_TEMPLATE",
                    "vertical": "DIGITAL_PRODUCTS",
                    "onboarding_mode": "SELF_SERVICE",
                    "affiliate_ref": None,
                    "admin_email": None,
                    "admin_phone": None,
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                supabase = get_supabase()
                if supabase:
                    try:
                        res = supabase.table("tenants").select("*").eq("slug", clean_slug).execute()
                        if (not res or not res.data) and ("-" in raw_slug and len(raw_slug) == 36):
                            res = supabase.table("tenants").select("*").eq("id", raw_slug).execute()
                        if res and res.data:
                            row = res.data[0]
                            db_slug = str(row.get("slug") or "").strip().lower()
                            if db_slug:
                                clean_slug = db_slug
                            _row_tier = row.get("tier") or "STARTER"
                            _row_meta = row.get("metadata") or {}
                            _row_features = _row_meta.get("features") or {}
                            _trial_end = row.get("trial_ends_at") or _row_meta.get("trial_ends_at")
                            _sub_end = row.get("subscription_ends_at") or _row_meta.get("subscription_ends_at")
                            resolved_name = row.get("name") or _row_meta.get("name") or _row_meta.get("tenant_name")
                            if not resolved_name or resolved_name == "52967979-4760-4cea-b686-cdbdb389c0e1" or clean_slug == "boon":
                                resolved_name = "BoonTrack Official Shop" if clean_slug == "boon" else (resolved_name or clean_slug.replace("-", " ").title())
                            tenant_dict = {
                                "id": str(row.get("id") or clean_slug),
                                "name": resolved_name,
                                "slug": clean_slug,
                                "tier": _row_tier,
                                "features": _build_feature_flags(_row_tier, _row_features),
                                "template": "COMMERCE_TEMPLATE",
                                "vertical": row.get("category", "COMMERCE"),
                                "trial_ends_at": _trial_end,
                                "subscription_ends_at": _sub_end or _trial_end,
                                "is_active": row.get("is_active") if row.get("is_active") is not None else False,
                                "status": row.get("status", "pending_wa_verification"),
                                "created_at": row.get("created_at") or datetime.now(timezone.utc).isoformat(),
                            }
                    except Exception as e:
                        logger.debug(f"[OnboardingService Supabase lookup note] {e}")

                if not tenant_dict:
                    t_name = "BoonTrack Official Shop" if clean_slug == "boon" else clean_slug.replace("-", " ").title()
                    tenant_dict = {
                        "id": "52967979-4760-4cea-b686-cdbdb389c0e1" if clean_slug == "boon" else str(uuid4()),
                        "name": t_name,
                        "slug": clean_slug,
                        "tier": "STARTER",
                        "features": _build_feature_flags("STARTER", {}),
                        "template": "COMMERCE_TEMPLATE",
                        "vertical": "COMMERCE",
                        "onboarding_mode": "SELF_SERVICE",
                        "affiliate_ref": None,
                        "is_active": True,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
            self._tenants_by_slug[clean_slug] = tenant_dict

        t_id = tenant_dict.get("id")
        products = []
        if t_id and t_id in self._products_by_tenant:
            p_data = self._products_by_tenant[t_id]
            if isinstance(p_data, list):
                products.extend(p_data)
            else:
                products.append(p_data)

        payout = self._payouts_by_tenant.get(t_id, {}) if t_id else {}

        if tenant_dict.get("persona"):
            persona = dict(tenant_dict["persona"])
        elif cfg:
            persona = {
                "system_prompt": cfg.persona.system_prompt,
                "tone": cfg.persona.tone,
                "welcome_message": cfg.persona.welcome_message,
                "default_fallback_message": cfg.persona.default_fallback_message,
                "assistant_name": f"{cfg.identity.name} Assistant",
                "ai_name": f"{cfg.identity.name} Assistant",
            }
        else:
            persona = {
                "system_prompt": f"Kamu adalah asisten resmi untuk toko {tenant_dict['name']}.",
                "tone": "Edukatif & Expert, ramah, to-the-point",
                "welcome_message": f"Selamat datang di {tenant_dict['name']}! Ada yang bisa kami bantu?",
                "default_fallback_message": "Mohon maaf, layanan sedang memproses antrean pesan lain.",
                "assistant_name": f"{tenant_dict['name']} Assistant",
                "ai_name": f"{tenant_dict['name']} Assistant",
            }

        # Check Supabase tenants table to load custom system_prompt, AI Persona, tier & features
        supabase = get_supabase()
        if supabase:
            try:
                res = supabase.table("tenants").select("*").eq("slug", clean_slug).execute()
                if res and res.data:
                    row = res.data[0]
                    meta = row.get("metadata") or {}
                    ai_k = meta.get("ai_knowledge") or {}
                    p_meta = meta.get("persona") or {}

                    # --- Dynamic tier & feature flags ---
                    if "is_active" in row and row.get("is_active") is not None:
                        tenant_dict["is_active"] = row["is_active"]
                    if "status" in row and row.get("status") is not None:
                        tenant_dict["status"] = row["status"]
                    live_tier = row.get("tier") or tenant_dict.get("tier") or "STARTER"
                    live_features_raw = meta.get("features") or {}
                    live_features = _build_feature_flags(live_tier, live_features_raw)
                    tenant_dict["tier"] = live_tier
                    tenant_dict["features"] = live_features
                    # ------------------------------------

                    for k in ("qris_image_url", "qris_url", "qris_string", "logo_url", "avatar_url", "banner_url", "payout", "payment_methods", "bank_accounts"):
                        if k in meta and meta[k] is not None and k not in tenant_dict:
                            tenant_dict[k] = meta[k]

                    sys_prompt = ai_k.get("system_prompt") or p_meta.get("system_prompt")
                    ai_name = (
                        ai_k.get("ai_name")
                        or ai_k.get("assistant_name")
                        or p_meta.get("ai_name")
                        or p_meta.get("assistant_name")
                    )
                    tone = ai_k.get("tone") or p_meta.get("tone")
                    bot_strategy_val = (
                        meta.get("bot_strategy")
                        or p_meta.get("bot_strategy")
                        or ai_k.get("bot_strategy")
                        or row.get("bot_strategy")
                        or tenant_dict.get("bot_strategy")
                        or "trust_builder"
                    )

                    if sys_prompt:
                        persona["system_prompt"] = sys_prompt
                    if ai_name:
                        persona["assistant_name"] = ai_name
                        persona["ai_name"] = ai_name
                    if tone:
                        persona["tone"] = tone
                    persona["bot_strategy"] = bot_strategy_val
                    tenant_dict["bot_strategy"] = bot_strategy_val

                    tenant_dict["persona"] = persona
                    tenant_dict["ai_knowledge"] = {
                        "ai_name": ai_name or persona.get("assistant_name"),
                        "assistant_name": ai_name or persona.get("assistant_name"),
                        "system_prompt": sys_prompt or persona.get("system_prompt", ""),
                        "tone": tone or persona.get("tone", "casual"),
                        "bot_strategy": bot_strategy_val,
                        "faq": ai_k.get("faq") or [],
                    }

                    tenant_dict["metadata"] = meta

                    # Fallback: jika products masih kosong, baca dari tenants.metadata -> 'products'
                    if not products:
                        meta_prods = meta.get("products")
                        if meta_prods and isinstance(meta_prods, list):
                            products = [p for p in meta_prods if p and isinstance(p, dict)]
                            if t_id:
                                self._products_by_tenant[t_id] = products
                        elif meta.get("product") and isinstance(meta["product"], dict):
                            products = [meta["product"]]
                            if t_id:
                                self._products_by_tenant[t_id] = products
            except Exception as db_err:
                logger.debug(f"[OnboardingService Supabase detail lookup note] {db_err}")

        # Ensure bot_strategy is present in persona and tenant
        final_strategy = tenant_dict.get("bot_strategy") or persona.get("bot_strategy") or "trust_builder"
        persona["bot_strategy"] = final_strategy
        tenant_dict["bot_strategy"] = final_strategy

        # Ensure tier & features always present in final tenant_dict
        if "tier" not in tenant_dict:
            tenant_dict["tier"] = "STARTER"
        if "features" not in tenant_dict:
            tenant_dict["features"] = _build_feature_flags(tenant_dict["tier"], {})

        return {
            "status": "success",
            "tenant": tenant_dict,
            "tier": tenant_dict["tier"],
            "features": tenant_dict["features"],
            "products": products,
            "payout": payout,
            "persona": persona,
            "ai_knowledge": tenant_dict.get("ai_knowledge") or {
                "ai_name": persona.get("ai_name") or f"{tenant_dict.get('name', clean_slug)} Assistant",
                "system_prompt": persona.get("system_prompt", ""),
                "tone": persona.get("tone", "casual"),
                "bot_strategy": final_strategy,
            }
        }

    def get_tenant_settings(self, slug: str) -> Optional[Dict[str, Any]]:
        """Retrieves store settings, trust badges, persona, payout, products list, and FAQ."""
        clean_slug = slugify(slug)
        details = self.get_tenant_details_by_slug(clean_slug)
        if not details:
            return None

        tenant = details.get("tenant", {})
        persona = details.get("persona", {})
        ai_knowledge = details.get("ai_knowledge", {})
        payout = details.get("payout", {})
        products = details.get("products", [])

        faq = tenant.get("faq") or []
        trust_badges = tenant.get("trust_badges") or []
        delivery_url = tenant.get("delivery_url") or (
            products[0].get("delivery_url") if (products and len(products) > 0 and products[0].get("delivery_url")) else None
        )

        return {
            "status": "success",
            "tenant": {
                **tenant,
                "public_description": tenant.get("public_description") or (products[0].get("description") if products else "Toko Resmi Terverifikasi"),
                "trust_badges": trust_badges,
                "delivery_url": delivery_url,
                "qris_image_url": tenant.get("qris_image_url") or tenant.get("qris_url"),
                "qris_url": tenant.get("qris_url") or tenant.get("qris_image_url"),
                "qris_string": tenant.get("qris_string"),
                "logo_url": tenant.get("logo_url"),
                "avatar_url": tenant.get("avatar_url"),
                "banner_url": tenant.get("banner_url"),
            },
            "persona": persona,
            "ai_knowledge": ai_knowledge,
            "payout": tenant.get("payout") or payout,
            "products": products,
            "faq": faq,
        }

    def update_tenant_settings(self, slug: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Updates store metadata, public description, persona bot, and auto-delivery URL.
        
        Syncs updates directly to LOADED_CONFIG_TENANTS, TENANT_REGISTRY, and Supabase DB.
        """
        clean_slug = slugify(slug)
        details = self.get_tenant_details_by_slug(clean_slug)
        if not details:
            return None

        tenant = details["tenant"]
        t_id = tenant.get("id")

        if "name" in updates:
            tenant["name"] = updates["name"]
        if "public_description" in updates:
            tenant["public_description"] = updates["public_description"]
        if "trust_badges" in updates:
            tenant["trust_badges"] = updates["trust_badges"]
        if "delivery_url" in updates:
            tenant["delivery_url"] = updates["delivery_url"]
        if "faq" in updates:
            tenant["faq"] = updates["faq"]

        # Support QRIS, branding, payout, and auto_replies fields in tenant profile
        for key in (
            "qris_image_url", "qris_url", "qris_string",
            "logo_url", "avatar_url", "banner_url",
            "payout", "payment_methods", "bank_accounts", "auto_replies"
        ):
            if key in updates and updates[key] is not None:
                tenant[key] = updates[key]
        if "qris_image_url" in tenant and not tenant.get("qris_url"):
            tenant["qris_url"] = tenant["qris_image_url"]
        if "qris_url" in tenant and not tenant.get("qris_image_url"):
            tenant["qris_image_url"] = tenant["qris_url"]

        # Extract AI & Persona updates
        sys_prompt = (
            updates.get("system_prompt")
            or (updates.get("persona") or {}).get("system_prompt")
            or (updates.get("ai_knowledge") or {}).get("system_prompt")
        )
        ai_name = (
            updates.get("assistant_name")
            or updates.get("ai_name")
            or (updates.get("persona") or {}).get("assistant_name")
            or (updates.get("persona") or {}).get("ai_name")
            or (updates.get("ai_knowledge") or {}).get("ai_name")
            or (updates.get("ai_knowledge") or {}).get("assistant_name")
        )
        tone = (
            (updates.get("persona") or {}).get("tone")
            or (updates.get("ai_knowledge") or {}).get("tone")
        )
        bot_strat = (
            updates.get("bot_strategy")
            or (updates.get("persona") or {}).get("bot_strategy")
            or (updates.get("ai_knowledge") or {}).get("bot_strategy")
        )

        p_dict = tenant.setdefault("persona", {})
        if sys_prompt:
            p_dict["system_prompt"] = sys_prompt
        if ai_name:
            p_dict["assistant_name"] = ai_name
            p_dict["ai_name"] = ai_name
        if tone:
            p_dict["tone"] = tone
        if bot_strat:
            p_dict["bot_strategy"] = bot_strat

        ai_dict = tenant.setdefault("ai_knowledge", {})
        if sys_prompt:
            ai_dict["system_prompt"] = sys_prompt
        if ai_name:
            ai_dict["ai_name"] = ai_name
            ai_dict["assistant_name"] = ai_name
        if tone:
            ai_dict["tone"] = tone
        if bot_strat:
            ai_dict["bot_strategy"] = bot_strat

        if bot_strat:
            tenant["bot_strategy"] = bot_strat

        self._tenants_by_slug[clean_slug] = tenant

        # Sync to LOADED_CONFIG_TENANTS
        cfg = LOADED_CONFIG_TENANTS.get(clean_slug)
        if cfg:
            if sys_prompt:
                cfg.persona.system_prompt = sys_prompt
            if tone:
                cfg.persona.tone = tone
            if bot_strat and hasattr(cfg.persona, "bot_strategy"):
                cfg.persona.bot_strategy = bot_strat
            if "name" in updates:
                cfg.identity.name = updates["name"]
            if "public_description" in updates:
                cfg.identity.description = updates["public_description"]

        if clean_slug in TENANT_REGISTRY and "name" in updates:
            TENANT_REGISTRY[clean_slug]["name"] = updates["name"]

        # Persist directly to Supabase tenants table
        supabase = get_supabase()
        if supabase:
            try:
                res = supabase.table("tenants").select("*").eq("slug", clean_slug).execute()
                existing = res.data[0] if res.data else None
                existing_meta = existing.get("metadata", {}) if existing else {}

                updated_meta = {
                    **existing_meta,
                    "bot_strategy": bot_strat or existing_meta.get("bot_strategy") or tenant.get("bot_strategy", "trust_builder"),
                    "ai_knowledge": {
                        **existing_meta.get("ai_knowledge", {}),
                        **(updates.get("ai_knowledge") or {}),
                        **({"system_prompt": sys_prompt} if sys_prompt else {}),
                        **({"ai_name": ai_name, "assistant_name": ai_name} if ai_name else {}),
                        **({"tone": tone} if tone else {}),
                        **({"bot_strategy": bot_strat} if bot_strat else {}),
                    },
                    "persona": {
                        **existing_meta.get("persona", {}),
                        **(updates.get("persona") or {}),
                        **({"system_prompt": sys_prompt} if sys_prompt else {}),
                        **({"assistant_name": ai_name, "ai_name": ai_name} if ai_name else {}),
                        **({"tone": tone} if tone else {}),
                        **({"bot_strategy": bot_strat} if bot_strat else {}),
                    }
                }
                for key in (
                    "qris_image_url", "qris_url", "qris_string",
                    "logo_url", "avatar_url", "banner_url",
                    "payout", "payment_methods", "bank_accounts", "auto_replies"
                ):
                    if key in tenant and tenant[key] is not None:
                        updated_meta[key] = tenant[key]

                upsert_payload = {
                    "slug": clean_slug,
                    "name": updates.get("name") or (existing.get("name") if existing else tenant.get("name", clean_slug)),
                    "metadata": updated_meta,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                if bot_strat:
                    upsert_payload["bot_strategy"] = bot_strat
                supabase.table("tenants").upsert(upsert_payload).execute()
                logger.info(f"[OnboardingService] Synced AI Persona & Store Profile ('{clean_slug}') to Supabase")
            except Exception as e:
                logger.debug(f"[OnboardingService Supabase sync note] {e}")

        return self.get_tenant_settings(clean_slug)

    def upsert_tenant_product(self, slug: str, product_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Adds or updates a product in tenant catalog, synced with live runtime and database."""
        clean_slug = slugify(slug)
        details = self.get_tenant_details_by_slug(clean_slug)
        if not details:
            return None

        tenant = details["tenant"]
        t_id = str(tenant.get("id"))

        existing_products = self._products_by_tenant.get(t_id)
        if not isinstance(existing_products, list):
            existing_products = [existing_products] if existing_products else []

        prod_id = str(product_data.get("id") or uuid4())
        prod_title = str(product_data.get("title") or "New Product").strip()

        # 1. Sanitasi dan Unikalisasi Slug
        raw_slug = product_data.get("slug") or prod_title
        base_slug = sanitize_product_slug(raw_slug, fallback_title=prod_title)
        prod_slug = ensure_unique_product_slug(
            desired_slug=base_slug,
            tenant_id_or_slug=t_id or clean_slug,
            current_product_id=prod_id,
            existing_products=existing_products
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        new_prod = {
            "id": prod_id,
            "tenant_id": t_id,
            "title": prod_title,
            "slug": prod_slug,
            "category": product_data.get("category", "Digital Course"),
            "price": float(product_data.get("price", 0)),
            "promo_price": float(product_data.get("promo_price")) if product_data.get("promo_price") is not None else None,
            "description": product_data.get("description", ""),
            "product_type": product_data.get("product_type", "DIGITAL_COURSE"),
            "delivery_url": product_data.get("delivery_url") or None,
            "asset_reference": product_data.get("asset_reference") or prod_slug,
            "is_available": product_data.get("is_available", True),
            "image": product_data.get("image") or product_data.get("primary_image") or "",
            "images": product_data.get("images") or [],
            "stock": int(product_data.get("stock", 0)) if product_data.get("stock") is not None else 0,
            "updated_at": now_iso,
        }

        updated = False
        for idx, p in enumerate(existing_products):
            if str(p.get("id")) == prod_id:
                existing_products[idx] = {**p, **new_prod}
                new_prod = existing_products[idx]
                updated = True
                break

        if not updated:
            new_prod["created_at"] = now_iso
            existing_products.append(new_prod)

        self._products_by_tenant[t_id] = existing_products

        # 2. Sinkronkan ke Supabase table 'products'
        supabase = get_supabase()
        if supabase:
            try:
                db_payload = {
                    "id": prod_id,
                    "tenant_id": t_id,
                    "tenant_slug": clean_slug,
                    "title": prod_title,
                    "slug": prod_slug,
                    "price": new_prod["price"],
                    "promo_price": new_prod["promo_price"],
                    "category": new_prod["category"],
                    "description": new_prod["description"],
                    "product_type": new_prod["product_type"],
                    "delivery_url": new_prod["delivery_url"],
                    "asset_reference": new_prod["asset_reference"],
                    "is_available": new_prod["is_available"],
                    "updated_at": now_iso,
                }
                update_res = supabase.table("products").update(db_payload).eq("id", prod_id).execute()
                if not update_res.data:
                    supabase.table("products").upsert(db_payload).execute()
                logger.info(f"[OnboardingService] Synced product '{prod_title}' (slug: {prod_slug}) to Supabase DB")
            except Exception as db_err:
                logger.debug(f"[OnboardingService product db sync note]: {db_err}")

        return new_prod

    def get_tenant_products(self, slug: str) -> Optional[list]:
        """Returns all products in tenant catalog, including category field."""
        clean_slug = slugify(slug)
        details = self.get_tenant_details_by_slug(clean_slug)
        if not details:
            return None
        t_id = str(details["tenant"].get("id"))
        prods = self._products_by_tenant.get(t_id, [])
        if not isinstance(prods, list):
            prods = [prods] if prods else []

        supabase = get_supabase()

        # 1. Jika in-memory kosong, coba ambil dari tabel products di Supabase
        if not prods and supabase and t_id:
            try:
                p_res = supabase.table("products").select("*").eq("tenant_id", t_id).execute()
                if p_res and p_res.data:
                    prods = p_res.data
                    self._products_by_tenant[t_id] = prods
            except Exception as db_err:
                logger.debug(f"[get_tenant_products db fetch note]: {db_err}")

        # 2. Fallback: jika tabel products kosong, baca fallback produk dari kolom JSONB tenants.metadata -> 'products'
        if not prods:
            tenant_meta = details.get("tenant", {}).get("metadata") or {}
            meta_prods = tenant_meta.get("products")

            if not meta_prods and supabase:
                try:
                    t_res = supabase.table("tenants").select("metadata").eq("slug", clean_slug).execute()
                    if t_res and t_res.data and t_res.data[0].get("metadata"):
                        meta_prods = t_res.data[0]["metadata"].get("products")
                except Exception as meta_err:
                    logger.debug(f"[get_tenant_products metadata query note]: {meta_err}")

            if meta_prods and isinstance(meta_prods, list):
                prods = [p for p in meta_prods if p and isinstance(p, dict)]
                self._products_by_tenant[t_id] = prods
            elif tenant_meta.get("product") and isinstance(tenant_meta["product"], dict):
                prods = [tenant_meta["product"]]
                self._products_by_tenant[t_id] = prods

        return prods

    def clear_state(self) -> None:
        """Clears in-memory state for test isolation."""
        for slug in list(self._tenants_by_slug.keys()):
            LOADED_CONFIG_TENANTS.pop(slug, None)
            TENANT_REGISTRY.pop(slug, None)
        self._tenants_by_slug.clear()
        self._products_by_tenant.clear()
        self._payouts_by_tenant.clear()


# Global Singleton
onboarding_service = OnboardingService()
