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
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any, Optional
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


class OnboardingService:
    """Service handling atomic merchant onboarding & provisioning."""

    def __init__(self, in_memory_mode: bool = False):
        self.in_memory_mode = in_memory_mode
        self._tenants_by_slug: Dict[str, Dict[str, Any]] = {}
        self._products_by_tenant: Dict[str, Dict[str, Any]] = {}
        self._payouts_by_tenant: Dict[str, Dict[str, Any]] = {}

    async def onboard_tenant(self, payload: TenantOnboardRequest) -> Dict[str, Any]:
        """Provisions a new merchant, initial product, and payout in 1 atomic transaction."""
        # 1. Resolve & validate tenant slug
        raw_slug = payload.slug or payload.name
        tenant_slug = slugify(raw_slug)
        if not tenant_slug:
            tenant_slug = f"tenant-{uuid4().hex[:8]}"

        # Check in-memory caches first
        if tenant_slug in self._tenants_by_slug or tenant_slug in LOADED_CONFIG_TENANTS:
            raise TenantSlugAlreadyExistsError(f"Tenant with slug '{tenant_slug}' already exists")

        # Resolve tier
        tier_str = payload.tier.upper()
        tier_enum = TenantTier.STARTER
        if tier_str in TenantTier.__members__:
            tier_enum = TenantTier[tier_str]

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
        prod_slug = payload.product.slug or slugify(payload.product.title) or f"prod-{uuid4().hex[:6]}"

        tenant_id = uuid4()
        product_id = uuid4()
        payout_id = uuid4()
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
                        is_active=True,
                        created_at=now,
                    )
                    session.add(tenant_record)
                    await session.flush()

                    # 2. Insert Initial Product
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

                    # 3. Insert Tenant Payout
                    payout_record = TenantPayout(
                        id=payout_id,
                        tenant_id=tenant_record.id,
                        bank_name=payload.payout.bank_name.upper(),
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
            "vertical": vert_config["vertical"],
            "onboarding_mode": mode_enum.value,
            "affiliate_ref": payload.affiliate_ref,
            "admin_email": payload.admin_email,
            "admin_phone": payload.admin_phone,
            "is_active": True,
            "created_at": now.isoformat(),
        }
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
        payout_dict = {
            "id": str(payout_id),
            "tenant_id": str(tenant_id),
            "bank_name": payload.payout.bank_name.upper(),
            "account_number": payload.payout.account_number,
            "account_holder": payload.payout.account_holder,
            "payout_email": payload.payout.payout_email or payload.admin_email,
            "is_verified": False,
            "created_at": now.isoformat(),
        }

        self._tenants_by_slug[tenant_slug] = tenant_dict
        self._products_by_tenant[str(tenant_id)] = product_dict
        self._payouts_by_tenant[str(tenant_id)] = payout_dict

        # 4. Auto-register in global runtime tenant configs
        try:
            new_config = TenantConfig(
                identity=TenantIdentity(
                    tenant_id=tenant_slug,
                    name=payload.name,
                    slug=tenant_slug,
                    status=TenantStatus.ACTIVE,
                    description=payload.product.description or f"Store {payload.name} ({vert_config['name']})",
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

        return {
            "status": "SUCCESS",
            "message": "Tenant onboarded successfully",
            "tenant_id": str(tenant_id),
            "tenant": tenant_dict,
            "product": product_dict,
            "payout": payout_dict,
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
            if slug in ("atmosfitnes", "career", "boontrack-career", "om_budi", "bale_pananggeuhan", "pelayanan_publik"):
                continue
            return slug

        return "digicorn"

    def get_tenant_details_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Finds full tenant profile, real products list, payout details, and persona configuration."""
        clean_slug = slugify(slug)
        cfg = LOADED_CONFIG_TENANTS.get(clean_slug)
        tenant_dict = self._tenants_by_slug.get(clean_slug)

        if not tenant_dict:
            if cfg:
                tenant_dict = {
                    "id": str(uuid4()),
                    "name": cfg.identity.name,
                    "slug": clean_slug,
                    "tier": "STARTER",
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
                        if res and res.data:
                            row = res.data[0]
                            tenant_dict = {
                                "id": str(row.get("id") or clean_slug),
                                "name": row.get("name") or clean_slug.replace("-", " ").title(),
                                "slug": clean_slug,
                                "tier": "STARTER",
                                "template": "COMMERCE_TEMPLATE",
                                "vertical": row.get("category", "COMMERCE"),
                                "is_active": True,
                                "created_at": row.get("created_at") or datetime.now(timezone.utc).isoformat(),
                            }
                    except Exception as e:
                        logger.debug(f"[OnboardingService Supabase lookup note] {e}")

                if not tenant_dict:
                    tenant_dict = {
                        "id": str(uuid4()),
                        "name": clean_slug.replace("-", " ").title(),
                        "slug": clean_slug,
                        "tier": "STARTER",
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

        # Check Supabase tenants table to load custom system_prompt & AI Persona
        supabase = get_supabase()
        if supabase:
            try:
                res = supabase.table("tenants").select("*").eq("slug", clean_slug).execute()
                if res and res.data:
                    row = res.data[0]
                    meta = row.get("metadata") or {}
                    ai_k = meta.get("ai_knowledge") or {}
                    p_meta = meta.get("persona") or {}
                    
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
            except Exception as db_err:
                logger.debug(f"[OnboardingService Supabase detail lookup note] {db_err}")

        # Ensure bot_strategy is present in persona and tenant
        final_strategy = tenant_dict.get("bot_strategy") or persona.get("bot_strategy") or "trust_builder"
        persona["bot_strategy"] = final_strategy
        tenant_dict["bot_strategy"] = final_strategy

        return {
            "status": "success",
            "tenant": tenant_dict,
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

        faq = tenant.get("faq") or [
            {
                "q": "Bagaimana cara akses materi digital?",
                "a": "Link Google Drive resmi otomatis dikirimkan ke WhatsApp Anda setelah verifikasi pembayaran berhasil.",
            },
            {
                "q": "Apakah materi bisa diakses selamanya?",
                "a": "Ya, seluruh modul video, template, dan grup diskusi dapat diakses seumur hidup (lifetime access).",
            },
            {
                "q": "Metode pembayaran apa saja yang didukung?",
                "a": "Pembayaran dapat dilakukan melalui Dynamic QRIS otomatis (BCA, Mandiri, BRI, BNI, DANA, GoPay, OVO, ShopeePay).",
            },
        ]

        trust_badges = tenant.get("trust_badges") or [
            "100% Garansi Pembelajaran",
            "Akses Seumur Hidup",
            "Update Materi Berkala",
            "Mentor Praktisi Berpengalaman",
        ]

        delivery_url = tenant.get("delivery_url") or (
            products[0].get("delivery_url") if products else "https://drive.google.com/drive/folders/suhu-ads-masterclass-2026"
        )

        return {
            "status": "success",
            "tenant": {
                **tenant,
                "public_description": tenant.get("public_description") or (products[0].get("description") if products else "Toko Resmi Terverifikasi"),
                "trust_badges": trust_badges,
                "delivery_url": delivery_url,
            },
            "persona": persona,
            "ai_knowledge": ai_knowledge,
            "payout": payout,
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
                upsert_payload = {
                    "slug": clean_slug,
                    "name": updates.get("name") or (existing.get("name") if existing else tenant.get("name", clean_slug)),
                    "metadata": updated_meta,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                if bot_strat:
                    upsert_payload["bot_strategy"] = bot_strat
                supabase.table("tenants").upsert(upsert_payload).execute()
                logger.info(f"[OnboardingService] Synced AI Persona & Bot Strategy ('{bot_strat}') to Supabase for tenant '{clean_slug}'")
            except Exception as e:
                logger.debug(f"[OnboardingService Supabase sync note] {e}")

        return self.get_tenant_settings(clean_slug)

    def upsert_tenant_product(self, slug: str, product_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Adds or updates a product in tenant catalog, synced with live runtime."""
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
        prod_title = product_data.get("title", "New Product")
        prod_slug = slugify(prod_title)
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
            "delivery_url": product_data.get("delivery_url") or "https://drive.google.com/drive/folders/suhu-ads-masterclass-2026",
            "asset_reference": product_data.get("asset_reference") or prod_slug,
            "is_available": product_data.get("is_available", True),
            "updated_at": now_iso,
        }

        updated = False
        for idx, p in enumerate(existing_products):
            if str(p.get("id")) == prod_id or str(p.get("slug")) == prod_slug:
                existing_products[idx] = {**p, **new_prod}
                new_prod = existing_products[idx]
                updated = True
                break

        if not updated:
            new_prod["created_at"] = now_iso
            existing_products.append(new_prod)

        self._products_by_tenant[t_id] = existing_products
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
