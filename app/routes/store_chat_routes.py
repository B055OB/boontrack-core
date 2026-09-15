"""app/routes/store_chat_routes.py
State Machine + Local FAQ Interceptor + Dynamic Database-Driven Storefront Chat.
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
    StoreContextBoundaryManager,
    format_tenant_session_key,
)

from app.services.onboarding_service import onboarding_service
from app.services.whatsapp_service import safe_log_to_supabase_messages, get_tenant_products_from_db
from app.schemas.context import RequestContext, resolve_tenant_context, ChannelType, SurfaceType, ActorType
from app.core.security_context import assert_tenant_integrity
from app.services.tenant_context_resolver import tenant_context_resolver

logger = logging.getLogger("STORE_CHAT_ROUTES")
router = APIRouter(tags=["AI Gateway Endpoints"])

class StoreChatRequest(BaseModel):
    tenant_slug: Optional[str] = Field(None, description="Slug tenant toko")
    tenant_id: Optional[str] = Field(None, description="Tenant identifier")
    slug: Optional[str] = Field(None, description="Tenant slug")
    message: str = Field(..., description="Pesan / pertanyaan pembeli atau label aksi")
    session_id: Optional[str] = Field(None, description="ID sesi webchat pembeli")
    conversation_history: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    products: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    cart: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    button_id: Optional[str] = Field(None, description="Button ID quick-reply")

class StoreChatResponse(BaseModel):
    reply_text: str
    action: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    session_state: Dict[str, Any] = Field(default_factory=dict)
    status: str = "success"
    type: Optional[str] = None
    reply: Optional[str] = None
    product: Optional[Dict[str, Any]] = None
    quick_actions: Optional[List[str]] = None
    session_id: Optional[str] = None
    tenant_id: Optional[str] = None


@router.post("/api/v1/store/chat", response_model=StoreChatResponse)
@router.post("/api/store/chat", response_model=StoreChatResponse, include_in_schema=False)
async def handle_store_chat(payload: StoreChatRequest = Body(...)):
    target_slug = payload.tenant_slug or payload.slug or payload.tenant_id or "onlineboost"
    clean_slug = str(target_slug).strip().lower()
    session_id = payload.session_id or f"store_sess_{clean_slug}_{id(payload)}"
    q = (payload.message or "").strip()
    q_lower = q.lower()

    if not q:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pesan tidak boleh kosong.")

    # Ambil konfigurasi dinamis dari database/metadata tenant
    settings = onboarding_service.get_tenant_settings(clean_slug) or {}
    meta = settings.get("metadata", {}) if isinstance(settings, dict) else {}
    persona = settings.get("persona", {}) if isinstance(settings, dict) else {}
    
    # Ambil template respons dari dashboard
    welcome_msg = persona.get("welcome_message") or "Halo! Ada yang bisa kami bantu?"
    qris_closing = meta.get("qris_closing_template") or "Terima kasih Kak, pembayaran bisa via scan QRIS resmi setelah pekerjaan beres ya."
    cod_closing = meta.get("cod_closing_template") or "Terima kasih Kak, pembayaran tunai dibayarkan langsung ke teknisi setelah selesai."
    faqs = meta.get("faqs", []) # Daftar FAQ custom dari dashboard

    # Tarik katalog produk/kapasitas dari database
    merged_catalog = []
    if payload.products:
        merged_catalog.extend(payload.products)
    if not merged_catalog:
        db_data = StoreContextBoundaryManager.fetch_transaction_data(clean_slug)
        if db_data:
            merged_catalog.extend(db_data)
    if not merged_catalog:
        _, direct_db = get_tenant_products_from_db(clean_slug)
        if direct_db:
            merged_catalog.extend(direct_db)
    if not merged_catalog and isinstance(meta, dict) and meta.get("capacities"):
        merged_catalog.extend(meta["capacities"])

    normalized_catalog = []
    for item in merged_catalog:
        if not isinstance(item, dict):
            continue
        p_id = item.get("id") or item.get("product_id") or item.get("slug")
        p_name = item.get("name") or item.get("title") or "Layanan"
        p_price = float(item.get("price") or 0)
        p_promo = float(item.get("promo_price")) if item.get("promo_price") else None
        normalized_catalog.append({
            "product_id": str(p_id),
            "title": p_name,
            "price": p_price,
            "promo_price": p_promo,
            "description": item.get("description", "")
        })

    from app.services.unified_conversation_service import (
        unified_conversation_engine,
        get_welcome_buttons_for_category,
        normalize_business_category,
        EMPTY_CATALOG_MESSAGE,
        UNKNOWN_PRODUCT_MESSAGE,
    )
    from app.services.rotary_routing_service import rotary_routing_service

    business_category = normalize_business_category(settings.get("tenant", {}).get("category") or settings.get("tenant", {}).get("vertical") or "PHYSICAL")
    welcome_buttons = get_welcome_buttons_for_category(business_category)

    # ZERO-HALLUCINATION SAFE GUARD 1: Katalog Kosong
    if not normalized_catalog:
        rotary_routing_service.ensure_conversation_and_mark_unassigned(
            tenant_id=clean_slug,
            phone_or_session=session_id,
            reason="EMPTY_CATALOG_HANDOVER"
        )
        safe_log_to_supabase_messages(
            sender="bot", text=EMPTY_CATALOG_MESSAGE, tenant_id=clean_slug, channel="webchat", user_id=session_id
        )
        return StoreChatResponse(
            reply_text=EMPTY_CATALOG_MESSAGE,
            action="CS_HANDOVER",
            payload={"product_ids": []},
            session_state={"tenant_id": clean_slug, "session_id": session_id},
            status="success",
            type="TEXT",
            reply=EMPTY_CATALOG_MESSAGE,
            quick_actions=welcome_buttons,
            session_id=session_id,
            tenant_id=clean_slug,
        )

    # ZERO-HALLUCINATION SAFE GUARD 2: Pertanyaan Produk di Luar Database
    is_unknown, queried_item = unified_conversation_engine.detect_unlisted_product_inquiry(q, normalized_catalog)
    if is_unknown:
        rotary_routing_service.ensure_conversation_and_mark_unassigned(
            tenant_id=clean_slug,
            phone_or_session=session_id,
            reason=f"UNKNOWN_PRODUCT_QUERY: {queried_item}"
        )
        safe_log_to_supabase_messages(
            sender="bot", text=UNKNOWN_PRODUCT_MESSAGE, tenant_id=clean_slug, channel="webchat", user_id=session_id
        )
        return StoreChatResponse(
            reply_text=UNKNOWN_PRODUCT_MESSAGE,
            action="CS_HANDOVER",
            payload={"product_ids": [p["product_id"] for p in normalized_catalog]},
            session_state={"tenant_id": clean_slug, "session_id": session_id},
            status="success",
            type="TEXT",
            reply=UNKNOWN_PRODUCT_MESSAGE,
            quick_actions=welcome_buttons,
            session_id=session_id,
            tenant_id=clean_slug,
        )

    # Greeting Awal
    if unified_conversation_engine.is_initial_greeting(q, payload.conversation_history) or payload.button_id == "START_GREETING":
        greeting_text = (
            f"{welcome_msg}\n\n"
            f"Silakan pilih menu cepat berikut untuk memulai:\n"
            f"1. {welcome_buttons[0]}\n"
            f"2. {welcome_buttons[1]}\n"
            f"3. {welcome_buttons[2]}"
        )
        safe_log_to_supabase_messages(
            sender="bot", text=greeting_text, tenant_id=clean_slug, channel="webchat", user_id=session_id
        )
        return StoreChatResponse(
            reply_text=greeting_text,
            action="SHOW_MENU",
            payload={"product_ids": [p["product_id"] for p in normalized_catalog]},
            session_state={"tenant_id": clean_slug, "session_id": session_id},
            status="success",
            type="TEXT",
            reply=greeting_text,
            quick_actions=welcome_buttons,
            session_id=session_id,
            tenant_id=clean_slug,
        )

    # 1. CEK LOCAL FAQ INTERCEPTOR (Hemat Biaya LLM)
    matched_faq_answer = None
    for faq in faqs:
        keyword = str(faq.get("keyword", "")).lower()
        question = str(faq.get("question", "")).lower()
        if (keyword and keyword in q_lower) or (question and any(w in q_lower for w in question.split() if len(w) > 3)):
            matched_faq_answer = faq.get("answer")
            break

    if matched_faq_answer:
        ai_reply = f"{matched_faq_answer}\n\nAda hal lain yang ingin ditanyakan?"
        action = "NONE"
        quick_actions = welcome_buttons
    else:
        # 2. STATE MACHINE FUNNEL (Self-Service Rules)
        user_numbers = re.findall(r"\d+", q_lower)
        matched_product = None
        
        if user_numbers:
            for prod in normalized_catalog:
                prod_nums = re.findall(r"\d+", prod["title"])
                if any(num in user_numbers for num in prod_nums):
                    matched_product = prod
                    break

        is_checkout_intent = any(w in q_lower for w in ["beli", "checkout", "pesan", "qris", "tunai", "bayar"])
        is_pikir_dulu = any(w in q_lower for w in ["pikir", "nanti", "belum", "terima kasih", "makasih"])

        if matched_product:
            price_display = f"Rp{matched_product['price']:,.0f}"
            promo_display = f" (Promo: Rp{matched_product['promo_price']:,.0f})" if matched_product['promo_price'] else ""
            ai_reply = (
                f"Untuk pilihan {matched_product['title']}, biaya jasanya adalah *{price_display}{promo_display}*.\n\n"
                f"Bagaimana Kak, ingin dilanjutkan untuk pemesanan sekarang?"
            )
            action = "SHOW_PRODUCT"
            quick_actions = ["Ya, Lanjut Pesan / Booking", "Pikir-pikir Dulu"]
        elif is_pikir_dulu:
            ai_reply = "Baik, terima kasih banyak Kak atas informasinya. Kalau nanti berminat, silakan kontak kami kembali ya. Sehat selalu! 😊"
            action = "NONE"
            quick_actions = welcome_buttons
        elif any(w in q_lower for w in ["lanjut", "pesan", "booking", "mau"]):
            ai_reply = "Baik Kak! Silakan pilih metode pembayaran yang diinginkan (dibayar setelah pengerjaan beres / 0% fee QRIS):"
            action = "SHOW_CHECKOUT"
            quick_actions = ["Scan QRIS Mandiri", "Bayar di Tempat (Tunai)"]
        elif any(w in q_lower for w in ["qris", "scan"]):
            ai_reply = f"{qris_closing}\n\nBerikut rincian jadwal kunjungan teknisi ke lokasi Anda:"
            action = "SHOW_CHECKOUT"
            quick_actions = ["Konfirmasi Jadwal", "Hubungi Admin WA"]
        elif any(w in q_lower for w in ["tunai", "tempat"]):
            ai_reply = f"{cod_closing}\n\nBerikut rincian jadwal kunjungan teknisi ke lokasi Anda:"
            action = "SHOW_CHECKOUT"
            quick_actions = ["Konfirmasi Jadwal", "Hubungi Admin WA"]
        else:
            # 3. LLM BACKUP FALLBACK Deterministik
            engine_res = await unified_conversation_engine.process_chat(
                tenant_slug=clean_slug,
                message=q,
                sender_id=session_id,
                sender_name="Visitor",
                channel="webchat",
                history=payload.conversation_history,
                button_id=payload.button_id,
            )
            ai_reply = engine_res.get("reply", "")
            quick_actions = engine_res.get("quick_actions") or welcome_buttons
            action = engine_res.get("action", "NONE")

    # Log pesan & kembalikan respons terstruktur
    safe_log_to_supabase_messages(
        sender="bot", text=ai_reply, tenant_id=clean_slug, channel="webchat", user_id=session_id
    )

    return StoreChatResponse(
        reply_text=ai_reply,
        action=action,
        payload={"product_ids": [p["product_id"] for p in normalized_catalog]},
        session_state={"tenant_id": clean_slug, "session_id": session_id},
        status="success",
        type=action if action != "NONE" else "TEXT",
        reply=ai_reply,
        quick_actions=quick_actions,
        session_id=session_id,
        tenant_id=clean_slug,
    )

# Placeholder rute pendukung lainnya (Copilot & Support) tetap dipertahankan sesuai struktur file.