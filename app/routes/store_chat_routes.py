"""app/routes/store_chat_routes.py
Unified AI Routes for BoonTrack Multi-Agent Architecture (ADR):
1. POST /api/v1/store/chat       -> BUYER_ASSISTANT (Store Sales Agent - ModelProfile: FAST)
2. POST /api/v1/merchant/copilot  -> MERCHANT_COPILOT (BoonPilot - ModelProfile: REASONING)
3. POST /api/v1/platform/support  -> PLATFORM_SUPPORT (BoonTrack CS - ModelProfile: BALANCED)

Enforces:
- Strict Backend Security Validator on prices and stock (Anti-price tampering)
- Tenant-scoped session isolation
- Structured action payloads for Storefront Webchat (SHOW_PRODUCT, SHOW_CHECKOUT, TEXT, etc.)
"""

import re
import urllib.parse
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, status, Body
from pydantic import BaseModel, Field

from app.services.ai_gateway import AgentProfile
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
from app.services.whatsapp_service import safe_log_to_supabase_messages

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
    tenant_slug: Optional[str] = Field(None, description="Slug tenant toko (e.g. 'onlineboost')")
    tenant_id: Optional[str] = Field(None, description="Tenant identifier")
    slug: Optional[str] = Field(None, description="Tenant slug")
    message: str = Field(..., description="Pesan / pertanyaan pembeli atau label aksi")
    session_id: Optional[str] = Field(None, description="ID sesi webchat pembeli")
    conversation_history: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Riwayat percakapan sebelumnya [{'sender': 'user'|'bot', 'text': '...'}]"
    )
    products: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Daftar produk aktif (opsional jika ingin di-override dari frontend)"
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
    - Memanggil profil BUYER_ASSISTANT melalui CommerceAIEngine (ModelProfile: FAST).
    - Memverifikasi kepatuhan batas keamanan & stok database via BackendSecurityValidator.
    - Format response standar: reply_text, action, payload (product_ids), session_state.
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

    # 1. Ambil katalog produk riil langsung dari database PostgreSQL tenant
    db_catalog = StoreContextBoundaryManager.fetch_transaction_data(clean_slug)
    
    # 2. Generate respons AI dari Commerce Engine (BUYER_ASSISTANT profile)
    formatted_history = []
    if payload.conversation_history:
        for item in payload.conversation_history:
            role = item.get("sender") or item.get("role") or "user"
            content = item.get("text") or item.get("content") or item.get("message") or ""
            if content:
                formatted_history.append({"role": role, "content": content})

    ai_reply = await commerce_ai_engine.generate_commerce_response(
        tenant_slug=clean_slug,
        user_message=q,
        user_phone=session_id,
        user_name=f"Web Visitor #{session_id[-4:] if len(session_id) >= 4 else session_id}",
        button_id=payload.button_id,
        history=formatted_history,
    )

    # 3. Klasifikasi Intent Aksi Storefront
    q_lower = q.lower()
    is_checkout_intent = any(w in q_lower for w in ["beli", "checkout", "pesan sekarang", "bayar", "qris", "ambil promo", "transfer"])
    is_list_intent = any(w in q_lower for w in ["semua produk", "katalog lengkap", "daftar produk", "list produk", "produk apa saja"])
    is_product_intent = any(w in q_lower for w in ["harga", "berapa", "produk", "detail", "fitur", "manfaat", "stok", "ongkir", "materi", "silabus"])
    is_human_intent = any(w in q_lower for w in ["bicara dengan admin", "hubungi cs", "cs manusia", "kontak admin", "bantuan manusia"])

    action = "NONE"
    matched_product = None

    if db_catalog:
        for prod in db_catalog:
            prod_title = str(prod.get("title", "")).lower()
            prod_slug = str(prod.get("slug", "")).lower()
            if any(part in q_lower for part in prod_title.split() if len(part) > 2) or prod_slug in q_lower:
                matched_product = prod
                break
        if not matched_product and (is_product_intent or is_checkout_intent) and not is_list_intent:
            matched_product = db_catalog[0]

    # 4. Validasi Keamanan Backend & Stok Database Riil
    sanitized_product_card = None
    product_ids_payload: List[Any] = []

    if is_human_intent:
        action = "TRANSFER_TO_HUMAN"
        action_res = await backend_security_validator.validate_and_sanitize_action(
            tenant_id=clean_slug,
            proposed_action={"action_type": StoreActionType.TRANSFER_TO_HUMAN.value}
        )
        if action_res.get("is_valid") and action_res.get("sanitized_payload"):
            payload_data = action_res["sanitized_payload"]
        else:
            payload_data = {"cs_contact": "+6281237450222"}

    elif is_checkout_intent and matched_product:
        # Validasi stok & ID produk di database
        action_res = await backend_security_validator.validate_and_sanitize_action(
            tenant_id=clean_slug,
            proposed_action={
                "action_type": StoreActionType.SHOW_CHECKOUT.value,
                "product_id": matched_product.get("product_id"),
                "product_slug": matched_product.get("slug"),
                "price": matched_product.get("price"),
            }
        )
        if action_res.get("is_valid") and action_res.get("sanitized_payload"):
            action = "SHOW_CHECKOUT"
            payload_data = action_res["sanitized_payload"]
            verified_price = payload_data["verified_price"]
            product_ids_payload = [matched_product.get("product_id")]
            sanitized_product_card = {
                "id": matched_product.get("product_id") or matched_product.get("slug"),
                "name": matched_product.get("title"),
                "category": matched_product.get("product_type") or "digital",
                "price": float(verified_price),
                "originalPrice": float(verified_price * 1.35) if verified_price > 0 else 0,
                "description": matched_product.get("description") or "Katalog resmi terverifikasi",
                "badge": "Terverifikasi Resmi",
                "is_available": True,
                "stock": payload_data.get("stock_available", 99),
                "checkout_url": payload_data.get("checkout_url"),
            }
        else:
            # Produk out of stock atau ID tidak valid di DB
            action = "NONE"
            product_ids_payload = [matched_product.get("product_id")]
            ai_reply = action_res.get("message") or f"Mohon maaf, stok untuk '{matched_product['title']}' saat ini habis."
            payload_data = {"error": action_res.get("error_code", "OUT_OF_STOCK")}

    elif is_list_intent and db_catalog:
        action = "SHOW_PRODUCT_LIST"
        product_ids_payload = [p.get("product_id") for p in db_catalog]
        payload_data = {
            "total_items": len(db_catalog),
            "products_summary": [{"product_id": p.get("product_id"), "title": p.get("title"), "price": p.get("price")} for p in db_catalog]
        }

    elif is_product_intent and matched_product:
        action_res = await backend_security_validator.validate_and_sanitize_action(
            tenant_id=clean_slug,
            proposed_action={
                "action_type": StoreActionType.SHOW_PRODUCT.value,
                "product_id": matched_product.get("product_id"),
                "product_slug": matched_product.get("slug"),
                "price": matched_product.get("price"),
            }
        )
        if action_res.get("is_valid") and action_res.get("sanitized_payload"):
            action = "SHOW_PRODUCT"
            payload_data = action_res["sanitized_payload"]
            verified_price = payload_data["verified_price"]
            product_ids_payload = [matched_product.get("product_id")]
            sanitized_product_card = {
                "id": matched_product.get("product_id") or matched_product.get("slug"),
                "name": matched_product.get("title"),
                "category": matched_product.get("product_type") or "digital",
                "price": float(verified_price),
                "originalPrice": float(verified_price * 1.35) if verified_price > 0 else 0,
                "description": matched_product.get("description") or "Katalog resmi terverifikasi",
                "badge": "Terverifikasi Resmi",
                "is_available": matched_product.get("is_available", True),
                "stock": payload_data.get("stock_available", 99),
                "checkout_url": payload_data.get("checkout_url"),
            }
        else:
            action = "NONE"
            product_ids_payload = [matched_product.get("product_id")]
            payload_data = {"error": action_res.get("error_code")}
    else:
        action = "NONE"
        payload_data = {}

    # Scoped tenant session state
    scoped_session_key = format_tenant_session_key(clean_slug, session_id)
    session_state = {
        "tenant_id": clean_slug,
        "session_id": session_id,
        "scoped_key": scoped_session_key,
        "last_action": action,
    }

    # 5. Siapkan Quick Actions responsif
    quick_actions = [
        "Lihat Rekomendasi Terlaris",
        "Tanya Detail Promo & Garansi",
        "Cara Pembayaran QRIS",
        "Hubungi WhatsApp",
    ]
    if action == "SHOW_PRODUCT":
        quick_actions = ["Langsung Checkout QRIS", "Apakah Ada Garansi?", "Cek Katalog Lengkap"]
    elif action == "SHOW_CHECKOUT":
        quick_actions = ["Cek Produk Lain", "Detail Garansi", "Bantuan WhatsApp"]

    # Catat pesan ke database
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
        # Storefront Webchat backward-compatibility
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
    type: str = "TEXT"  # TEXT | ACTION_PROPOSAL
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
    summary="Merchant Copilot Assistant (MERCHANT_COPILOT - BoonPilot)",
)
@router.post(
    "/api/merchant/copilot",
    response_model=MerchantCopilotResponse,
    include_in_schema=False,
)
async def handle_merchant_copilot(payload: MerchantCopilotRequest = Body(...)):
    """
    Rute utama Merchant Copilot (BoonPilot).
    - Memanggil profil MERCHANT_COPILOT (ModelProfile: REASONING).
    - Query-only tools: Laporan omset & ROAS, monitoring stok menipis, status WhatsApp Automation.
    - Data mutation tools: Menghasilkan Action Proposal dengan TTL 10 menit (Human-in-the-Loop).
    """
    clean_slug = str(payload.tenant_slug or "onlineboost").strip().lower()
    session_id = payload.session_id or f"copilot_sess_{clean_slug}_{id(payload)}"
    q = (payload.message or "").strip()

    if not q:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pesan tidak boleh kosong.",
        )

    # Format history turn
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
        "Cek status otomatisasi WhatsApp",
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
    type: str = "TEXT"  # TEXT | ESCALATE_WA
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
    """
    Rute layanan pelanggan & CS resmi platform BoonTrack.
    - Memanggil profil PLATFORM_SUPPORT (ModelProfile: BALANCED).
    - Panduan integrasi WhatsApp (Baileys vs Meta WABA), dynamic QRIS, payout affiliate, logistik Biteship.
    - Menyertakan eskalasi langsung ke CS WhatsApp resmi (+6281237450222) untuk isu mendesak.
    """
    target_tenant = payload.tenant_slug or payload.tenant_id or "boontrack-platform"
    clean_tenant = str(target_tenant).strip().lower()
    session_id = payload.session_id or f"support_sess_{clean_tenant}_{id(payload)}"
    q = (payload.message or "").strip()

    if not q:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pesan tidak boleh kosong.",
        )

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
        "Tanya Program Kemitraan Mitra & Payout",
        "Hubungi Live Support WA (+6281237450222)",
    ]

    support_reply = result.get("reply", "")
    action_str = "ESCALATE_WA" if needs_escalation else "NONE"
    return PlatformSupportResponse(
        status="success",
        type="ESCALATE_WA" if needs_escalation else "TEXT",
        action=action_str,
        reply=support_reply,
        reply_text=support_reply,
        category=payload.category or "general",
        escalation_url=escalation_url,
        quick_actions=quick_actions,
        session_id=session_id,
        tenant_id=clean_tenant,
    )
