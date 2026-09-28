"""app/services/unified_conversation_service.py
Unified Conversation Engine (Storefront Webchat & Evolution WhatsApp Gateway).

Menjamin:
1. Engine deterministik terpadu antara Webchat (shop.boontrack.com/[slug]) dan WhatsApp (Evolution API).
2. 3 Static Welcome Buttons berbasis 6 Kategori Bisnis Resmi (PHYSICAL, FOOD, FIELD_SERVICE, PROFESSIONAL_SERVICE, DIGITAL, CREATOR_AGENCY).
3. Zero-Hallucination Safe Guard:
   - Data produk riil dari Supabase (tabel products & bookings).
   - Katalog kosong -> Pesan resmi & alihkan ke status CS unassigned.
   - Produk di luar database -> Respons sopan penolakan & trigger antrean CS unassigned.
   - Suhu LLM terkunci di temperature: 0.0 (deterministik murni).
"""

import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from app.services.onboarding_service import onboarding_service
from app.services.whatsapp_service import get_tenant_products_from_db
from app.services.rotary_routing_service import rotary_routing_service
from app.services.ai_engine import commerce_ai_engine

logger = logging.getLogger("UNIFIED_CONVERSATION_ENGINE")

# 6 Kategori Bisnis Resmi & 3 Tombol Statis Default
CATEGORY_WELCOME_BUTTONS: Dict[str, List[str]] = {
    "PHYSICAL": [
        "📦 Cek Katalog & Promo",
        "🚚 Cek Ongkir & Resi",
        "💬 Hubungi Live CS",
    ],
    "FOOD": [
        "🛵 Pesan Antar (Delivery)",
        "🥡 Ambil di Resto (Takeaway)",
        "📍 Lokasi & Jam Dapur",
    ],
    "FIELD_SERVICE": [
        "📅 Jadwalkan Servis/Teknisi",
        "💰 Tarif & Area Layanan",
        "🛠️ Konsultasi CS",
    ],
    "PROFESSIONAL_SERVICE": [
        "📝 Jadwal Konsultasi/Janji Temu",
        "📋 Portofolio & Brief",
        "🚗 Simulasi/Paket Layanan",
    ],
    "DIGITAL": [
        "⚡ Akses Download & Materi",
        "🔑 Kendala Akun & Lisensi",
        "📚 Kurikulum Produk",
    ],
    "CREATOR_AGENCY": [
        "📊 Rate Card & Paket Endorse",
        "📦 Kirim Brief/Sampel",
        "📅 Jadwal Live Talent",
    ],
}

EMPTY_CATALOG_MESSAGE = (
    "Halo! Katalog produk/layanan kami sedang disiapkan oleh admin. "
    "Ada yang bisa kami bantu secara langsung?"
)

UNKNOWN_PRODUCT_MESSAGE = (
    "Mohon maaf Kak, varian/produk tersebut belum tersedia di katalog kami. "
    "Pertanyaan Kakak kami teruskan ke tim admin ya."
)

GREETING_TRIGGERS = {
    "halo", "halo kak", "halo min", "hai", "hai kak", "hi", "pagi", "selamat pagi",
    "siang", "selamat siang", "sore", "selamat sore", "malam", "selamat malam",
    "assalamualaikum", "assalam", "permisi", "tes", "test", "ping", "p", "start",
    "menu", "bantuan", "info", "mulai", "greeting"
}

PRODUCT_INQUIRY_KEYWORDS = [
    "ada", "apakah ada", "punya", "jual", "ready", "apakah jual", "varian",
    "tersedia", "stok", "stock", "beli", "order", "mau cari", "nyari", "apakah menyediakan"
]


def normalize_business_category(category_input: Optional[str]) -> str:
    """Normalisasi string kategori ke 6 kategori kanonikal."""
    raw = str(category_input or "").strip().upper()
    if not raw:
        return "PHYSICAL"

    if any(k in raw for k in ("FOOD", "FNB", "CULINARY", "RESTO", "KULINER", "MAKANAN", "MINUMAN", "DAPUR")):
        return "FOOD"
    if any(k in raw for k in ("FIELD_SERVICE", "FIELD", "SERVICE_FIELD", "TOREN", "TEKNISI", "SERVIS", "REPARASI", "AC", "SEDOT")):
        return "FIELD_SERVICE"
    if any(k in raw for k in ("PROFESSIONAL_SERVICE", "PRO_SERVICE", "PROFESSIONAL", "CONSULTANT", "KONSULTAN", "AGENCY_PRO", "LEGAL", "KLINIK", "DOKTER")):
        return "PROFESSIONAL_SERVICE"
    if any(k in raw for k in ("DIGITAL", "DIGITAL_PRODUCT", "COURSE", "EBOOK", "SOFTWARE", "SAAS", "LICENSE", "LISENSI", "KELAS", "MASTERCLASS")):
        return "DIGITAL"
    if any(k in raw for k in ("CREATOR_AGENCY", "CREATOR", "TALENT", "ENDORSE", "INFLUENCER", "KOL", "UGC", "MANAGEMENT")):
        return "CREATOR_AGENCY"
    if any(k in raw for k in ("PHYSICAL", "PHYSICAL_RETAIL", "RETAIL", "COMMERCE", "PRODUK", "FASHION", "SKINCARE", "HERBAL")):
        return "PHYSICAL"

    return "PHYSICAL"


def get_welcome_buttons_for_category(category: str) -> List[str]:
    """Mengambil 3 welcome buttons statis sesuai kategori bisnis (returns isolated list copy)."""
    canon_cat = normalize_business_category(category)
    return list(CATEGORY_WELCOME_BUTTONS.get(canon_cat, CATEGORY_WELCOME_BUTTONS["PHYSICAL"]))


class UnifiedConversationEngine:
    """
    Engine Percakapan Terpadu & Deterministik untuk Seluruh Channel (Webchat & WhatsApp).
    """

    @staticmethod
    def is_initial_greeting(message: str, history: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Mendeteksi apakah percakapan merupakan sapaan awal pembuka."""
        clean_msg = re.sub(r"[^\w\s]", "", message.lower()).strip()
        if not clean_msg:
            return True
        if clean_msg in GREETING_TRIGGERS:
            return True
        # Jika belum ada riwayat obrolan dan pesan pendek (< 15 karakter)
        if not history and len(clean_msg) <= 12 and any(clean_msg.startswith(g) for g in ["halo", "hai", "hi", "selamat"]):
            return True
        return False

    @staticmethod
    def detect_unlisted_product_inquiry(message: str, catalog: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        """
        Mendeteksi jika pelanggan menanyakan produk/varian tertentu yang TIDAK ada di katalog riil.
        Returns: (is_unknown_inquiry, candidate_query)
        """
        if not catalog:
            return False, None

        clean_text = message.lower().strip()
        # Jika pertanyaan umum menanyakan produk/katalog yang tersedia, jangan anggap unlisted product
        if any(g in clean_text for g in ["apa saja", "apa ja", "daftar produk", "katalog", "list produk", "semua produk", "produk apa", "tanya produk", "produk yang tersedia"]):
            return False, None

        has_inquiry_intent = any(re.search(rf"\b{re.escape(kw)}\b", clean_text) for kw in PRODUCT_INQUIRY_KEYWORDS)
        if not has_inquiry_intent:
            return False, None

        # Kumpulkan seluruh kata kunci produk yang ada di database
        catalog_tokens = set()
        for item in catalog:
            title = str(item.get("title") or item.get("name") or "").lower()
            desc = str(item.get("description") or "").lower()
            # Tokenize title & desc
            tokens = re.findall(r"\b[a-z0-9_-]{3,}\b", title + " " + desc)
            catalog_tokens.update(tokens)

        # Cari token dalam pertanyaan user yang mengindikasikan nama objek/produk
        user_words = [w for w in re.findall(r"\b[a-z0-9_-]{3,}\b", clean_text) if w not in {
            "apakah", "ada", "punya", "jual", "ready", "kak", "min", "saya", "mau",
            "cari", "tolong", "bisa", "berapa", "harga", "untuk", "dan", "atau",
            "yang", "ini", "itu", "nya", "apakah", "kami", "dong", "gan", "sis", "stok",
            "halo", "tanya", "produk", "layanan", "jasa", "apa", "saja", "tersedia", "katalog", "daftar"
        }]

        # Jika user menyebutkan kata benda/produk spesifik (>= 1 kata)
        if user_words:
            # Hitung apakah ada token yang cocok dengan katalog
            matches = [w for w in user_words if w in catalog_tokens]
            # Jika user menanyakan produk spesifik dan sama sekali tidak ada yang match di katalog
            if not matches:
                return True, " ".join(user_words)

        return False, None

    async def process_chat(
        self,
        tenant_slug: str,
        message: str,
        sender_id: str,
        sender_name: str = "Pelanggan",
        channel: str = "webchat",
        history: Optional[List[Dict[str, Any]]] = None,
        button_id: Optional[str] = None,
        image_base64: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Memproses pesan secara deterministik:
        1. Resolve profile tenant & kategori bisnis.
        2. Ambil data produk riil dari Supabase.
        3. Validasi greeting awal -> Kembalikan sapaan resmi + 3 tombol statis.
        4. Guardrail katalog kosong -> Respon resmi & mutasi ke status unassigned.
        5. Guardrail produk di luar database -> Respon penolakan & mutasi ke status unassigned.
        6. Interceptor tombol cepat & booking jasa.
        7. LLM inference deterministik (temperature: 0.0) / Multimodal visual pipeline.
        """
        clean_slug = str(tenant_slug or "").strip().lower()
        if not clean_slug:
            return {"reply_text": "Halo! Silakan hubungi admin toko melalui tautan resmi kami.", "buttons": []}
        q = (message or "").strip()
        if image_base64 and (not q or q == "[Gambar diterima]"):
            q = "Tolong analisa gambar ini sesuai konteks toko."
        q_lower = q.lower()

        from app.services.whatsapp_service import normalize_phone_number, get_supabase
        clean_phone = normalize_phone_number(sender_id) if any(c.isdigit() for c in str(sender_id)) else str(sender_id)
        supabase = get_supabase()

        # Step 0: Inbound Message Drop saat Paused / Handover to Human
        if supabase and clean_phone:
            try:
                s_res = (
                    supabase.from_("conversation_sessions")
                    .select("id, current_state, is_paused, paused_until")
                    .eq("tenant_id", clean_slug)
                    .eq("user_identifier", clean_phone)
                    .maybe_single()
                    .execute()
                )
                if s_res and s_res.data:
                    s_data = s_res.data
                    is_state_paused = s_data.get("current_state") in ("HANDOVER_TO_HUMAN", "PAUSED")
                    is_flag_paused = bool(s_data.get("is_paused"))
                    p_until = s_data.get("paused_until")
                    is_active_pause = False
                    if is_state_paused or is_flag_paused:
                        if p_until:
                            try:
                                p_dt = datetime.fromisoformat(str(p_until).replace("Z", "+00:00"))
                                if p_dt > datetime.now(timezone.utc):
                                    is_active_pause = True
                            except Exception:
                                is_active_pause = True
                        else:
                            is_active_pause = True

                    if is_active_pause:
                        logger.info(
                            f"[UNIFIED CONVERSATION ENGINE] Sesi untuk '{clean_phone}' (tenant='{clean_slug}') "
                            f"sedang dalam status HANDOVER_TO_HUMAN/PAUSED hingga {p_until}. "
                            "DROP inbound message agar owner/CS manusia membalas manual."
                        )
                        return {
                            "success": True,
                            "reply": None,
                            "reply_text": None,
                            "tenant_slug": clean_slug,
                            "business_category": "DIGITAL",
                            "action": "DROP_PAUSED",
                            "bot_paused": True,
                            "current_state": "HANDOVER_TO_HUMAN",
                            "type": "NONE",
                            "unassigned_triggered": False,
                        }
            except Exception as _chk_err:
                logger.warning(f"[SESSION_PAUSE_CHECK_WARN] {_chk_err}")

        # 1. Resolve Tenant Profile & Kategori Bisnis
        details = onboarding_service.get_tenant_details_by_slug(clean_slug) or {}
        tenant_obj = details.get("tenant", {}) if details else {}
        persona = details.get("persona", {}) if details else {}
        ai_k = details.get("ai_knowledge", {}) if details else {}

        raw_category = tenant_obj.get("category") or tenant_obj.get("vertical") or details.get("category") or "PHYSICAL"
        business_category = normalize_business_category(raw_category)
        welcome_buttons = get_welcome_buttons_for_category(business_category)

        store_name = tenant_obj.get("name") or clean_slug.replace("-", " ").title()
        tenant_meta = tenant_obj.get("metadata") or {}
        if not isinstance(tenant_meta, dict):
            tenant_meta = {}

        from app.whatsapp.traffic_splitter import get_tenant_greeting_message
        welcome_msg = get_tenant_greeting_message(
            store_name=store_name,
            tenant_slug=clean_slug,
            tenant_meta=tenant_meta,
        )

        # 1.5. HANDOVER ESCALATION INTERCEPTOR (Pilihan '2', chat langsung dengan owner / Kang Sakti / CS)
        clean_q = re.sub(r"[^\w\s]", "", q_lower).strip()

        # Guard: Jika user sedang dalam sesi memilih nomor produk di katalog (misal pilih produk #2), jangan cegat sebagai handover
        is_in_product_menu = False
        try:
            from app.services.whatsapp_menu_flow_service import whatsapp_menu_flow_service
            menu_sess = whatsapp_menu_flow_service.get_session(clean_slug, clean_phone)
            if menu_sess and menu_sess.current_state in ("selecting_product", "viewing_product", "viewing_testimonials"):
                is_in_product_menu = True
        except Exception:
            pass

        has_explicit_owner_kw = any(
            kw in q_lower for kw in [
                "ngobrol dengan", "bicara dengan", "chat dengan", "kang sakti",
                "owner", "pemilik", "admin", "live cs", "hubungi cs", "chat cs",
                "manusia", "human cs", "staf", "bantuan admin", "tanya kang sakti",
                "ngobrol santai"
            ]
        )
        is_digit_2_handover = (
            not is_in_product_menu and (
                clean_q in ("2", "2.", "dua", "opsi 2", "pilihan 2", "nomor 2", "no 2", "chat langsung", "chat owner")
                or q_lower.startswith("2 ")
            )
        )
        is_handover_intent = has_explicit_owner_kw or is_digit_2_handover

        if is_handover_intent:
            logger.info(f"[HANDOVER_TO_HUMAN] Detected escalation intent from '{clean_phone}' for tenant '{clean_slug}': '{q[:60]}'")

            # 1. Pesan konfirmasi transisi CUKUP SATU KALI SAJA
            if "kang sakti" in q_lower or clean_slug == "buzzerukm":
                handover_msg = (
                    "Baik Kak, pesan Kakak sudah kami teruskan langsung ke Kang Sakti. "
                    "Asisten bot kami jeda sejenak agar Kang Sakti dapat langsung membalas chat Kakak secara manual ya. Terima kasih! 🙏"
                )
            else:
                handover_msg = (
                    f"Baik Kak, pesan Kakak sudah kami teruskan ke tim admin / owner *{store_name}*. "
                    "Asisten bot kami jeda sejenak agar tim kami dapat langsung membalas chat Kakak secara manual ya. Terima kasih! 🙏"
                )

            # 2. Kunci State Session: HANDOVER_TO_HUMAN, is_paused = True, paused_until = now() + 24 hours
            now_dt = datetime.now(timezone.utc)
            paused_until_dt = now_dt + timedelta(hours=24)
            session_payload = {
                "tenant_id": clean_slug,
                "session_id": f"wa_{clean_slug}_{clean_phone}",
                "channel": channel.upper(),
                "user_identifier": clean_phone,
                "current_state": "HANDOVER_TO_HUMAN",
                "is_paused": True,
                "paused_until": paused_until_dt.isoformat(),
                "updated_at": now_dt.isoformat(),
                "metadata": {
                    "paused_reason": "HUMAN_HANDOVER",
                    "paused_at": now_dt.isoformat(),
                    "trigger_text": q[:100],
                },
            }
            if supabase and clean_phone:
                try:
                    ex = supabase.from_("conversation_sessions").select("id").eq("tenant_id", clean_slug).eq("user_identifier", clean_phone).maybe_single().execute()
                    if ex and ex.data:
                        supabase.from_("conversation_sessions").update(session_payload).eq("id", ex.data["id"]).execute()
                    else:
                        supabase.from_("conversation_sessions").insert(session_payload).execute()
                except Exception as _upsert_err:
                    logger.warning(f"[SESSION_UPSERT_WARN] {_upsert_err}")

            # 3. Mark unassigned & update Postgres conversations table
            try:
                rotary_routing_service.ensure_conversation_and_mark_unassigned(
                    tenant_id=clean_slug,
                    phone_or_session=clean_phone,
                    contact_name=sender_name,
                    reason=f"HANDOVER_TO_HUMAN: {q[:60]}"
                )
                conn = rotary_routing_service._get_connection()
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET bot_paused = TRUE, bot_mode = 'HUMAN_ACTIVE', updated_at = NOW()
                        WHERE tenant_id = %s AND (phone_number = %s OR phone_number LIKE %s);
                        """,
                        (clean_slug, clean_phone, f"%{clean_phone[-8:]}")
                    )
                    conn.commit()
                conn.close()
            except Exception as _rr_err:
                logger.warning(f"[ROTARY_HANDOVER_WARN] {_rr_err}")

            return {
                "success": True,
                "reply": handover_msg,
                "reply_text": handover_msg,
                "tenant_slug": clean_slug,
                "business_category": business_category,
                "quick_actions": [],
                "action": "HANDOVER_TO_HUMAN",
                "bot_paused": True,
                "current_state": "HANDOVER_TO_HUMAN",
                "type": "TEXT",
                "unassigned_triggered": True,
            }

        # 2. Ambil Katalog Produk Riil dari Database Supabase
        db_name, catalog = get_tenant_products_from_db(clean_slug)
        if not catalog and details.get("products"):
            catalog = details.get("products", [])
        if db_name and not tenant_obj.get("name"):
            store_name = db_name

        # 3. Handle Greeting Awal / Percakapan Baru (hanya untuk teks murni tanpa gambar)
        is_greeting = not bool(image_base64) and (self.is_initial_greeting(q, history) or (button_id == "START_GREETING"))
        if is_greeting:
            has_embedded_options = any(w in welcome_msg.lower() for w in ["balas 1", "balas \"1\"", "balas '1'", "1.", "1 -", "opsi 1"])
            if has_embedded_options or not welcome_buttons:
                greeting_text = welcome_msg
            else:
                greeting_text = (
                    f"{welcome_msg}\n\n"
                    f"Silakan pilih menu cepat berikut untuk memulai:\n"
                    f"1. {welcome_buttons[0]}\n"
                    f"2. {welcome_buttons[1]}\n"
                    f"3. {welcome_buttons[2]}"
                )
            return {
                "success": True,
                "reply": greeting_text,
                "reply_text": greeting_text,
                "tenant_slug": clean_slug,
                "business_category": business_category,
                "quick_actions": welcome_buttons,
                "action": "SHOW_MENU",
                "type": "TEXT",
                "unassigned_triggered": False,
            }

        # 4. ZERO-HALLUCINATION SAFE GUARD 1: Katalog Kosong
        if not catalog or len(catalog) == 0:
            logger.info(f"[Zero-Hallucination Safe Guard] Tenant '{clean_slug}' has empty catalog. Handing over to unassigned CS queue.")
            # Alihkan tiket percakapan ke status CS 'unassigned' di tabel conversations
            rotary_routing_service.ensure_conversation_and_mark_unassigned(
                tenant_id=clean_slug,
                phone_or_session=sender_id,
                contact_name=sender_name,
                reason="EMPTY_CATALOG_HANDOVER"
            )
            return {
                "success": True,
                "reply": EMPTY_CATALOG_MESSAGE,
                "reply_text": EMPTY_CATALOG_MESSAGE,
                "tenant_slug": clean_slug,
                "business_category": business_category,
                "quick_actions": welcome_buttons,
                "action": "CS_HANDOVER",
                "type": "TEXT",
                "unassigned_triggered": True,
            }

        # 5. ZERO-HALLUCINATION SAFE GUARD 2: Pertanyaan Produk di Luar Database (hanya untuk teks murni tanpa gambar)
        if not image_base64:
            is_unknown, queried_item = self.detect_unlisted_product_inquiry(q, catalog)
            if is_unknown:
                logger.info(
                    f"[Zero-Hallucination Safe Guard] User inquired about unknown product '{queried_item}' "
                    f"not in database for '{clean_slug}'. Triggering unassigned CS queue."
                )
                rotary_routing_service.ensure_conversation_and_mark_unassigned(
                    tenant_id=clean_slug,
                    phone_or_session=sender_id,
                    contact_name=sender_name,
                    reason=f"UNKNOWN_PRODUCT_QUERY: {queried_item}"
                )
                return {
                    "success": True,
                    "reply": UNKNOWN_PRODUCT_MESSAGE,
                    "reply_text": UNKNOWN_PRODUCT_MESSAGE,
                    "tenant_slug": clean_slug,
                    "business_category": business_category,
                    "quick_actions": welcome_buttons,
                    "action": "CS_HANDOVER",
                    "type": "TEXT",
                    "unassigned_triggered": True,
                }

        # 6. Interceptor Cek Katalog / Tombol Statis Relevan
        if any(w in q_lower for w in ["cek katalog", "katalog", "daftar promo", "daftar harga", "menu", "tarif"]):
            catalog_lines = []
            for idx, p in enumerate(catalog[:8], 1):
                p_title = p.get("title") or p.get("name") or f"Item {idx}"
                p_price = float(p.get("promo_price") or p.get("price") or 0)
                promo_txt = f" (Promo: Rp{p_price:,.0f})" if p.get("promo_price") else ""
                p_slug = str(p.get("slug") or p.get("id") or "").strip()
                p_url = f"https://shop.boontrack.com/{clean_slug}/p/{p_slug}" if p_slug else f"https://shop.boontrack.com/{clean_slug}"
                catalog_lines.append(f"{idx}. {p_title} - Rp{p_price:,.0f}{promo_txt}\n   Link Checkout: {p_url}")
            
            catalog_summary = "\n\n".join(catalog_lines)
            reply = (
                f"Berikut daftar produk & layanan resmi *{store_name}*:\n\n"
                f"{catalog_summary}\n\n"
                f"🌐 Toko Resmi: https://shop.boontrack.com/{clean_slug}\n\n"
                f"Ada item yang ingin Kakak tanyakan lebih lanjut atau langsung dipesan?"
            )
            return {
                "success": True,
                "reply": reply,
                "reply_text": reply,
                "tenant_slug": clean_slug,
                "business_category": business_category,
                "quick_actions": welcome_buttons,
                "action": "SHOW_CATALOG",
                "type": "TEXT",
                "unassigned_triggered": False,
            }

        if any(w in q_lower for w in ["live cs", "hubungi cs", "chat cs", "admin"]):
            rotary_routing_service.ensure_conversation_and_mark_unassigned(
                tenant_id=clean_slug,
                phone_or_session=sender_id,
                contact_name=sender_name,
                reason="USER_REQUESTED_LIVE_CS"
            )
            cs_reply = "Pesan Kakak sudah kami teruskan ke antrean Tim Live CS. Mohon ditunggu sebentar ya Kak, CS kami akan segera merespons."
            return {
                "success": True,
                "reply": cs_reply,
                "reply_text": cs_reply,
                "tenant_slug": clean_slug,
                "business_category": business_category,
                "quick_actions": welcome_buttons,
                "action": "CS_HANDOVER",
                "type": "TEXT",
                "unassigned_triggered": True,
            }

        # 7. Entitlement Guard (ARCHITECTURE.md): CHECKOUT_LITE dilarang keras eksekusi LLM
        tenant_tier = str(tenant_obj.get("tier") or "").strip().upper()
        if (
            tenant_tier == "CHECKOUT_LITE"
            or "checkout_lite" in clean_slug
            or "checkout-lite" in clean_slug
        ):
            logger.warning(
                f"[ENTITLEMENT_PROTECTION_BLOCKED] Tenant '{clean_slug}' is on tier CHECKOUT_LITE. "
                "Skipping LLM execution in unified_conversation_engine."
            )
            from app.whatsapp.traffic_splitter import get_tenant_greeting_message
            static_reply = get_tenant_greeting_message(
                store_name=store_name,
                tenant_slug=clean_slug,
                tenant_meta=tenant_meta,
            )
            return {
                "success": True,
                "reply": static_reply,
                "reply_text": static_reply,
                "tenant_slug": clean_slug,
                "business_category": business_category,
                "quick_actions": welcome_buttons,
                "action": "CS_HANDOVER",
                "type": "TEXT",
                "unassigned_triggered": True,
            }

        # 7. Eksekusi LLM Deterministik (temperature: 0.0) via CommerceAIEngine
        llm_reply = await commerce_ai_engine.generate_commerce_response(
            tenant_slug=clean_slug,
            user_message=q,
            user_phone=sender_id,
            user_name=sender_name,
            button_id=button_id,
            history=history,
            image_base64=image_base64,
            mime_type=mime_type,
        )

        return {
            "success": True,
            "reply": llm_reply,
            "reply_text": llm_reply,
            "tenant_slug": clean_slug,
            "business_category": business_category,
            "quick_actions": welcome_buttons,
            "action": "NONE",
            "type": "TEXT",
            "unassigned_triggered": False,
        }


# Singleton Engine Instance
unified_conversation_engine = UnifiedConversationEngine()
