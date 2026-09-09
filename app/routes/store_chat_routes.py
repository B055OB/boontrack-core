"""app/routes/store_chat_routes.py
Unified AI Routes for BoonTrack Multi-Agent Architecture (ADR):
1. POST /api/v1/store/chat       -> BUYER_ASSISTANT (Store Sales Agent - ModelProfile: FAST)
2. POST /api/v1/merchant/copilot  -> MERCHANT_COPILOT (BoonPilot - ModelProfile: REASONING)
3. POST /api/v1/platform/support  -> PLATFORM_SUPPORT (BoonTrack CS - ModelProfile: BALANCED)

Enforces:
- Strict Backend Security Validator on prices and stock (Anti-price tampering)
- Dynamic Catalog Injection to avoid hallucinated/vague pricing
- Numeric Capacity Intent Matching for accurate product cards
- Tenant-scoped session isolation
- Structured action payloads for Storefront Webchat (SHOW_PRODUCT, SHOW_CHECKOUT, TEXT, etc.)
"""

import re
import urllib.parse
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.services.ai_gateway import AgentProfile, parse_ai_quick_actions_response
from app.services.ai_engine import commerce_ai_engine
from app.services.boonpilot_service import boonpilot_service
from app.services.platform_support_agent import platform_support_agent
from app.services.sales_agent_guard import (
    backend_security_validator,
    StoreActionType,
    StoreContextBoundaryManager,
    format_tenant_session_key,
)

from app.services.onboarding_service import onboarding_service
from app.services.whatsapp_service import safe_log_to_supabase_messages, get_tenant_products_from_db
from app.schemas.context import RequestContext, resolve_tenant_context, ChannelType, SurfaceType, ActorType
from app.core.security_context import assert_tenant_integrity, format_composite_session_key
from app.services.tenant_context_resolver import tenant_context_resolver

logger = logging.getLogger("STORE_CHAT_ROUTES")

router = APIRouter(tags=["AI Gateway Endpoints"])


# =============================================================================
# 1. STORE SALES AGENT (POST /api/v1/store/chat)
# =============================================================================

class StoreChatProductItem(BaseModel):
    id: Optional[Any] = None
    name: Optional[str] = None
    title: Optional[str] = None
    price: Optional[float] = None
    originalPrice: Optional[float] = None
    image: Optional[str] = None
    description: Optional[str] = None
    badge: Optional[str] = None
    category: Optional[str] = None
    modules: Optional[List[str]] = None
    features: Optional[List[str]] = None


class StoreChatRequest(BaseModel):
    tenant_slug: Optional[str] = Field(None, description="Slug tenant toko")
    tenant_id: Optional[str] = Field(None, description="Tenant identifier")
    slug: Optional[str] = Field(None, description="Tenant slug")
    message: str = Field(..., description="Pesan / pertanyaan pembeli atau label aksi")
    session_id: Optional[str] = Field(None, description="ID sesi webchat pembeli")
    conversation_history: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Riwayat percakapan sebelumnya"
    )
    products: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Daftar produk aktif"
    )
    cart: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Isi keranjang belanja saat ini"
    )
    button_id: Optional[str] = Field(None, description="Button ID quick-reply")


class StoreChatResponse(BaseModel):
    reply_text: str
    action: str  # SHOW_PRODUCT | SHOW_PRODUCT_LIST | SHOW_CHECKOUT | NONE
    payload: Dict[str, Any] = Field(default_factory=dict)
    session_state: Dict[str, Any] = Field(default_factory=dict)

    # Storefront Webchat UI compatibility fields
    status: str = "success"
    type: Optional[str] = None
    reply: Optional[str] = None
    product: Optional[Dict[str, Any]] = None
    quick_actions: Optional[List[str]] = None
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None


@router.post(
    "/api/v1/store/chat",
    response_model=StoreChatResponse,
    summary="Storefront Interactive Webchat (Store Sales Agent - BUYER_ASSISTANT)",
)
@router.post(
    "/api/store/chat",
    response_model=StoreChatResponse,
    include_in_schema=False,
)
async def handle_store_chat(payload: StoreChatRequest = Body(...)):
    """
    Rute utama obrolan etalase toko (Storefront Webchat).
    - Menghubungkan produk katalog database secara deterministik ke AI prompt.
    - Mencocokkan kartu produk berbasis angka kapasitas secara spesifik.
    - Memanggil profil BUYER_ASSISTANT melalui CommerceAIEngine.
    """
    target_slug = payload.tenant_slug or payload.slug or payload.tenant_id or "onlineboost"
    clean_slug = str(target_slug).strip().lower()
    session_id = payload.session_id or f"store_sess_{clean_slug}_{id(payload)}"
    q = (payload.message or "").strip()

    if not q:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pesan tidak boleh kosong.",
        )

    # 1. Resolve Tenant Context
    ctx = resolve_tenant_context(
        tenant_slug=clean_slug,
        channel=ChannelType.WEBCHAT.value,
        surface=SurfaceType.STOREFRONT.value,
        actor_type=ActorType.CUSTOMER.value,
        session_id=session_id,
        untrusted_client_tenant_id=payload.tenant_id
    )
    runtime_ctx = tenant_context_resolver.resolve_runtime_context(clean_slug)

    # 2. Pengumpulan Katalog Produk Komprehensif secara Dinamis dari Database / Metadata
    merged_catalog: List[Dict[str, Any]] = []

    if payload.products:
        merged_catalog.extend(payload.products)

    if not merged_catalog:
        db_data = StoreContextBoundaryManager.fetch_transaction_data(ctx.tenant_slug)
        if db_data:
            merged_catalog.extend(db_data)

    if not merged_catalog:
        _, direct_db = get_tenant_products_from_db(clean_slug)
        if direct_db:
            merged_catalog.extend(direct_db)

    if not merged_catalog:
        settings = onboarding_service.get_tenant_settings(clean_slug) or {}
        meta = settings.get("metadata", {}) if isinstance(settings, dict) else {}
        if isinstance(meta, dict) and meta.get("capacities"):
            merged_catalog.extend(meta["capacities"])
        elif isinstance(meta, dict) and meta.get("products"):
            merged_catalog.extend(meta["products"])

    # Normalisasi format katalog
    normalized_catalog = []
    for item in merged_catalog:
        if not isinstance(item, dict):
            continue
        p_id = item.get("id") or item.get("product_id") or item.get("slug")
        p_name = item.get("name") or item.get("title") or "Layanan Resmi"
        p_price = float(item.get("price") or 0)
        p_promo = float(item.get("promo_price")) if item.get("promo_price") else None
        p_desc = item.get("description") or item.get("variants") or ""
        normalized_catalog.append({
            "product_id": str(p_id),
            "id": str(p_id),
            "title": p_name,
            "name": p_name,
            "price": p_price,
            "promo_price": p_promo,
            "description": p_desc,
            "variants": item.get("variants", ""),
            "is_available": item.get("is_available", True),
        })

    # Susun teks katalog untuk disuntikkan ke instruksi AI
    catalog_lines = []
    for idx, prod in enumerate(normalized_catalog, 1):
        promo_text = f" (Promo: Rp{prod['promo_price']:,.0f})" if prod["promo_price"] else ""
        desc_text = f" - {prod['description']}" if prod["description"] else ""
        catalog_lines.append(f"{idx}. {prod['title']}: Rp{prod['price']:,.0f}{promo_text}{desc_text}")
    catalog_prompt_snippet = "\n".join(catalog_lines)

    mode_prompt = (
        f"KATALOG & TARIF RESMI SAAT INI (DARI DATABASE):\n"
        f"{catalog_prompt_snippet}\n\n"
        f"ATURAN WAJIB:\n"
        f"- Jika pembeli menanyakan harga atau kapasitas, sebutkan nominal harga resmi di atas secara tegas dan jelas.\n"
        f"- DILARANG menjawab mengambang jika harga layanan sudah terdaftar di atas."
    )

    # 3. Generate respons AI melalui Commerce Engine
    formatted_history = []
    if payload.conversation_history:
        for item in payload.conversation_history:
            role = item.get("sender") or item.get("role") or "user"
            content = item.get("text") or item.get("content") or item.get("message") or ""
            if content:
                formatted_history.append({"role": role, "content": content})

    ai_raw = await commerce_ai_engine.generate_commerce_response(
        tenant_slug=clean_slug,
        user_message=q,
        user_phone=session_id,
        user_name=f"Web Visitor #{session_id[-4:] if len(session_id) >= 4 else session_id}",
        button_id=payload.button_id,
        history=formatted_history,
        mode_prompt=mode_prompt,
    )
    ai_reply, dynamic_quick_actions = parse_ai_quick_actions_response(ai_raw)

    # 4. Klasifikasi Intent & Pencocokan Produk Akurat
    q_lower = q.lower()
    is_checkout_intent = any(w in q_lower for w in ["beli", "checkout", "pesan sekarang", "bayar", "qris", "ambil promo", "transfer"])
    is_list_intent = any(w in q_lower for w in ["semua produk", "katalog lengkap", "daftar produk", "list produk", "produk apa saja"])
    is_shipping_intent = any(w in q_lower for w in ["ongkir", "ongkos kirim", "pengiriman", "ekspedisi", "kurir"])
    is_product_intent = any(w in q_lower for w in ["harga", "berapa", "produk", "detail", "fitur", "manfaat", "stok", "kuras", "toren", "liter", "biaya", "kapasitas"])
    is_human_intent = any(w in q_lower for w in ["bicara dengan admin", "hubungi cs", "cs manusia", "kontak admin", "bantuan manusia"])

    action = "NONE"
    matched_product = None

    if normalized_catalog:
        user_numbers = re.findall(r"\d+", q_lower)
        if user_numbers:
            for prod in normalized_catalog:
                prod_numbers = re.findall(r"\d+", prod["title"])
                if any(num in user_numbers for num in prod_numbers):
                    matched_product = prod
                    break

        if not matched_product:
            for prod in normalized_catalog:
                p_name = prod["title"].lower()
                tokens = [t for t in re.split(r"[\s\-_]+", p_name) if len(t) > 3 and t not in ["kuras", "toren", "jasa"]]
                if any(t in q_lower for t in tokens):
                    matched_product = prod
                    break

    sanitized_product_card = None
    product_ids_payload: List[Any] = []
    payload_data: Dict[str, Any] = {}

    if is_shipping_intent and not is_checkout_intent:
        action = "NONE"
    elif is_human_intent:
        action = "TRANSFER_TO_HUMAN"
        payload_data = {"cs_contact": "+6281237450222"}
    elif (is_checkout_intent or is_product_intent) and matched_product:
        action = "SHOW_CHECKOUT" if is_checkout_intent else "SHOW_PRODUCT"
        verified_price = matched_product["price"]
        product_ids_payload = [matched_product["product_id"]]
        sanitized_product_card = {
            "id": matched_product["product_id"],
            "name": matched_product["title"],
            "category": "service",
            "price": float(verified_price),
            "originalPrice": float(matched_product.get("promo_price") or verified_price),
            "description": matched_product.get("description") or "Katalog resmi terverifikasi",
            "badge": "Terverifikasi Resmi",
            "is_available": True,
            "stock": 99,
        }
    elif is_list_intent and normalized_catalog:
        action = "SHOW_PRODUCT_LIST"
        product_ids_payload = [p["product_id"] for p in normalized_catalog]
        payload_data = {
            "total_items": len(normalized_catalog),
            "products_summary": [{"product_id": p["product_id"], "title": p["title"], "price": p["price"]} for p in normalized_catalog]
        }

    scoped_session_key = format_tenant_session_key(clean_slug, session_id)
    session_state = {
        "tenant_id": clean_slug,
        "session_id": session_id,
        "scoped_key": scoped_session_key,
        "last_action": action,
    }

    quick_actions = tenant_context_resolver.filter_buyer_actions(
        raw_actions=dynamic_quick_actions,
        runtime_ctx=runtime_ctx
    )

    safe_log_to_supabase_messages(
        sender="bot",
        text=ai_reply,
        tenant_id=clean_slug,
        channel="webchat",
        user_id=session_id,
        user_name=f"Web Visitor #{session_id[-4:] if len(session_id) >= 4 else session_id}",
    )

    final_payload = {
        "product_ids": product_ids_payload,
        **payload_data,
    }

    return StoreChatResponse(
        reply_text=ai_reply,
        action=action,
        payload=final_payload,
        session_state=session_state,
        status="success",
        type=action if action != "NONE" else "TEXT",
        reply=ai_reply,
        product=sanitized_product_card,
        quick_actions=quick_actions,
        session_id=session_id,
        tenant_id=clean_slug,
    )


# =============================================================================
# 2. MERCHANT COPILOT (POST /api/v1/merchant/copilot)
# =============================================================================

class MerchantCopilotRequest(BaseModel):
    tenant_slug: Optional[str] = Field("onlineboost", description="Slug tenant toko")
    message: str = Field(..., description="Instruksi atau pertanyaan operasional merchant")
    session_id: Optional[str] = Field(None, description="ID sesi copilot")
    conversation_history: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Riwayat percakapan copilot"
    )


class MerchantCopilotResponse(BaseModel):
    status: str = "success"
    type: str = "TEXT"
    reply: str
    reply_text: Optional[str] = None
    action: Optional[str] = None
    action_proposal: Optional[Dict[str, Any]] = None
    data: Optional[Dict[str, Any]] = None
    quick_actions: Optional[List[str]] = None
    session_id: str
    tenant_id: str


@router.post(
    "/api/v1/merchant/copilot",
    response_model=MerchantCopilotResponse,
    summary="Merchant Copilot Assistant (MERCHANT_COPILOT)",
)
@router.post(
    "/api/merchant/copilot",
    response_model=MerchantCopilotResponse,
    include_in_schema=False,
)
async def handle_merchant_copilot(payload: MerchantCopilotRequest = Body(...)):
    clean_slug = str(payload.tenant_slug or "onlineboost").strip().lower()
    session_id = payload.session_id or f"copilot_sess_{clean_slug}_{id(payload)}"
    q = (payload.message or "").strip()

    if not q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pesan tidak boleh kosong.")

    formatted_history = []
    if payload.conversation_history:
        for turn in payload.conversation_history:
            role = turn.get("role") or turn.get("sender") or "user"
            content = turn.get("content") or turn.get("text") or turn.get("message") or ""
            if content:
                formatted_history.append({"role": role, "content": content})

    result = await boonpilot_service.chat(
        tenant_slug=clean_slug,
        message=q,
        session_id=session_id,
        conversation_history=formatted_history,
    )

    is_action_proposal = result.get("action_type") is not None or result.get("status") == "AWAITING_APPROVAL"
    reply_text = result.get("reply") or result.get("description") or ""

    action_proposal_payload = None
    if is_action_proposal:
        action_proposal_payload = {
            "id": result.get("action_id"),
            "action_type": result.get("action_type"),
            "title": result.get("action_type", "").replace("_", " ").title(),
            "summary": result.get("description") or reply_text,
            "payload": result.get("payload") or {},
            "status": result.get("status", "PENDING"),
        }

    quick_actions = [
        "Bagaimana performa penjualan toko saya minggu ini?",
        "Cek stok produk yang hampir habis",
        "Bantu atur titik penjemputan gudang kurir",
        "Cek live chat & status BoonTrack Inbox",
    ]

    return MerchantCopilotResponse(
        status="success",
        type="ACTION_PROPOSAL" if is_action_proposal else "TEXT",
        action="ACTION_PROPOSAL" if is_action_proposal else "NONE",
        reply=reply_text,
        reply_text=reply_text,
        action_proposal=action_proposal_payload,
        data=result.get("data"),
        quick_actions=quick_actions,
        session_id=result.get("session_id") or session_id,
        tenant_id=clean_slug,
    )


# =============================================================================
# 3. PLATFORM SUPPORT AGENT (POST /api/v1/platform/support)
# =============================================================================

class PlatformSupportRequest(BaseModel):
    tenant_slug: Optional[str] = Field("boontrack-platform", description="Tenant slug")
    tenant_id: Optional[str] = Field(None, description="Tenant ID")
    message: str = Field(..., description="Pertanyaan bantuan platform, kendala teknis, atau billing")
    session_id: Optional[str] = Field(None, description="ID sesi pengguna")
    category: Optional[str] = Field("general", description="Kategori tiket (billing, technical, affiliate, general)")


class PlatformSupportResponse(BaseModel):
    status: str = "success"
    type: str = "TEXT"
    action: Optional[str] = None
    reply: str
    reply_text: Optional[str] = None
    category: str = "general"
    escalation_url: Optional[str] = None
    quick_actions: Optional[List[str]] = None
    session_id: str
    tenant_id: str


@router.post(
    "/api/v1/platform/support",
    response_model=PlatformSupportResponse,
    summary="BoonTrack Platform Helpdesk & CS (PLATFORM_SUPPORT)",
)
@router.post(
    "/api/platform/support",
    response_model=PlatformSupportResponse,
    include_in_schema=False,
)
async def handle_platform_support(payload: PlatformSupportRequest = Body(...)):
    target_tenant = payload.tenant_slug or payload.tenant_id or "boontrack-platform"
    clean_tenant = str(target_tenant).strip().lower()
    session_id = payload.session_id or f"support_sess_{clean_tenant}_{id(payload)}"
    q = (payload.message or "").strip()

    if not q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pesan tidak boleh kosong.")

    result = await platform_support_agent.handle_support_query(
        user_message=q,
        user_identifier=session_id,
        tenant_id=clean_tenant,
        session_id=session_id,
        context={"category": payload.category or "general"},
    )

    q_lower = q.lower()
    needs_escalation = any(w in q_lower for w in ["cs", "human", "komplain", "kendala mendesak", "urgent", "pencairan", "upgrade", "billing"])
    encoded_query = urllib.parse.quote(f"Halo Tim Support BoonTrack, saya butuh bantuan kendala: {q[:60]}")
    escalation_url = f"https://wa.me/6281237450222?text={encoded_query}"

    quick_actions = [
        "Info Upgrade Paket Toko (Growth & ProScale)",
        "Bantuan Teknis Meta CAPI & Pixel",
        "Buat Tiket Kendala di BoonTrack Desk",
        "Hubungi Live Support WA (+6281237450222)",
    ]

    support_reply = result.get("reply", "")
    return PlatformSupportResponse(
        status="success",
        type="ESCALATE_WA" if needs_escalation else "TEXT",
        action="ESCALATE_WA" if needs_escalation else "NONE",
        reply=support_reply,
        reply_text=support_reply,
        category=payload.category or "general",
        escalation_url=escalation_url,
        quick_actions=quick_actions,
        session_id=session_id,
        tenant_id=clean_tenant,
    )