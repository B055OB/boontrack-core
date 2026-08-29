"""app/services/ai_engine.py
Dynamic Commerce AI Engine & Context Injection Service.

Dynamically constructs store-bounded AI system prompts for COMMERCE_TEMPLATE tenants:
1. Injects Store Name, Business Vertical Category, and Tone of Voice.
2. Injects real catalog products with accurate pricing, variants, bundling promos, and digital asset URLs.
3. Enforces strict negative context boundaries: rejects irrelevant topics (gym schedules, civil registration, KTP, etc.).
"""

import logging
from typing import Dict, Any, List, Optional
from app.services.onboarding_service import onboarding_service
from app.services.ai_gateway import ai_gateway

logger = logging.getLogger("COMMERCE_AI_ENGINE")


class CommerceAIEngine:
    """Universal AI Engine for Multi-Tenant Commerce with Dynamic Prompt Injection."""

    def __init__(self, ai_service=None):
        self.ai_service = ai_service or ai_gateway

    def build_commerce_system_prompt(self, tenant_slug: str) -> str:
        """Constructs a hyper-focused system prompt bounded strictly to the merchant's catalog."""
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
        if not details:
            # Fallback generic commerce prompt
            return (
                f"Kamu adalah asisten resmi untuk toko online '{tenant_slug}'.\n"
                "Jawab pertanyaan pelanggan dengan ramah, sopan, dan to-the-point seputar produk kami.\n"
                "Tolak pertanyaan di luar produk toko kami dengan sopan."
            )

        tenant = details.get("tenant", {})
        persona = details.get("persona", {})
        products = details.get("products", [])

        store_name = tenant.get("name", tenant_slug)
        vertical = tenant.get("vertical", "COMMERCE")
        tone = persona.get("tone", "Edukatif & Expert, ramah, to-the-point")
        welcome = persona.get("welcome_message", f"Selamat datang di {store_name}!")

        # 1. Format Daftar Produk Riil
        product_lines: List[str] = []
        if products:
            for idx, p in enumerate(products, 1):
                title = p.get("title", f"Produk {idx}")
                price = p.get("price", 0)
                desc = p.get("description") or "Katalog resmi berkualitas tinggi"
                p_type = p.get("product_type", "DIGITAL_FILE")
                asset_ref = p.get("asset_reference", "digital_access")

                # Promo bundling & digital asset delivery note
                if "DIGITAL" in str(p_type).upper():
                    delivery_note = f"Materi digital instan: https://{tenant_slug}.boontrack.com/assets/{asset_ref}"
                    bundling_note = "Promo Bundling: Beli 2 gratis template bonus eksklusif"
                else:
                    delivery_note = "Pengiriman kurir kilat 1-3 hari kerja ke seluruh Indonesia"
                    bundling_note = "Promo Bundling: Pembelian paket bundling diskon 10%"

                product_lines.append(
                    f"{idx}. {title}\n"
                    f"   - Harga: Rp{float(price):,.0f}\n"
                    f"   - Deskripsi: {desc}\n"
                    f"   - Varian / Spesifikasi: Standard Resmi ({p_type})\n"
                    f"   - {bundling_note}\n"
                    f"   - Info Pengiriman: {delivery_note}"
                )
            catalog_text = "\n\n".join(product_lines)
        else:
            catalog_text = (
                f"1. Paket Layanan {store_name}\n"
                f"   - Harga: Rp50,000\n"
                f"   - Deskripsi: Solusi layanan berkualitas langsung dari {store_name}\n"
                f"   - Info Pengiriman: Konfirmasi instan via WhatsApp"
            )

        # 2. Assembling System Prompt dengan Negative Context Boundaries
        prompt = (
            f"Kamu adalah asisten resmi untuk toko '{store_name}' ({vertical}).\n"
            f"Tone of Voice: {tone}.\n\n"
            f"INFORMASI TOKO:\n"
            f"- Nama Toko: {store_name}\n"
            f"- Kategori Vertikal: {vertical}\n"
            f"- Sapaan Pembuka: {welcome}\n\n"
            f"KATALOG PRODUK RIIL YANG TERSEDIA:\n"
            f"{catalog_text}\n\n"
            f"PANDUAN & CARA PEMESANAN:\n"
            f"- Pelanggan dapat memesan produk langsung melalui chat ini.\n"
            f"- Pembayaran didukung via QRIS (BCA, Mandiri, BRI, DANA, GoPay, OVO, ShopeePay) dengan verifikasi otomatis.\n"
            f"- Berikan penjelasan produk yang edukatif, profesional, dan meyakinkan pelanggan.\n\n"
            f"BATASAN TOPIK & INTEGRITAS TOKO (STRICT NEGATIVE BOUNDARIES):\n"
            f"1. Kamu HANYA melayani seputar produk, pemesanan, dan layanan resmi dari {store_name} ({vertical}).\n"
            f"2. JANGAN PERNAH membahas, memberikan jadwal, atau melayani topik:\n"
            f"   - Fasilitas gym, keanggotaan fitness, atau turnstile gate Atmosfitnes.\n"
            f"   - Layanan publik kelurahan, pengurusan KTP/SKU/bansos, surat pengantar nikah, atau Balé Pananggeuhan.\n"
            f"   - Bimbingan ibadah/riyadhoh Om Budi atau konsultasi karir umum.\n"
            f"3. Jika pelanggan bertanya tentang topik di luar katalog dan layanan {store_name}, tolak dengan sopan dan arahkan kembali ke produk toko:\n"
            f"   Contoh: 'Mohon maaf Kakak, saya asisten resmi {store_name}. Saya khusus melayani seputar produk dan pesanan di {store_name}. Ada produk kami yang ingin Kakak tanyakan?'"
        )
        return prompt

    def is_product_info_trigger(self, message: str, button_id: Optional[str] = None) -> bool:
        """Detects whether incoming message or button payload requests product/catalog details."""
        clean_btn = str(button_id or "").strip().upper()
        clean_text = str(message or "").strip().lower()

        btn_triggers = [
            "INFO_PRODUK", "DETAIL_PRODUK", "INFO_PAKET", "ORDER_PRODUK",
            "LIHAT_PRODUK", "INFO_CATALOG", "PRODUK_DETAIL"
        ]
        if clean_btn in btn_triggers or any(clean_btn.startswith(prefix) for prefix in ["INFO_", "DETAIL_"]):
            return True

        text_triggers = [
            "info produk", "detail produk", "info paket", "detail paket",
            "lihat produk", "katalog produk", "informasi produk", "penjelasan produk",
            "produk apa saja", "daftar produk"
        ]
        return any(trigger in clean_text for trigger in text_triggers)

    def build_internal_product_query(self, details: Dict[str, Any], product_index: int = 0) -> str:
        """Constructs an internal LLM query for comprehensive, persuasive product explanation."""
        products = details.get("products", [])
        tenant = details.get("tenant", {})
        store_name = tenant.get("name", "Toko")

        if products and len(products) > product_index:
            p = products[product_index]
            product_name = p.get("title", "Produk Unggulan")
            price = f"Rp{float(p.get('price', 0)):,.0f}"
            variants = p.get("product_type", "Standard Resmi")
            materials = p.get("description", "Materi dan silabus lengkap siap pakai")
            p_type = str(variants).upper()
            if "DIGITAL" in p_type:
                promo = "Beli 2 gratis template bonus eksklusif"
            else:
                promo = "Diskon paket bundling 10% untuk pemesanan hari ini"
        else:
            product_name = f"Paket Layanan {store_name}"
            price = "Rp50,000"
            variants = "Standard Resmi"
            materials = "Layanan langsung terintegrasi"
            promo = "Diskon paket bundling spesial pelanggan baru"

        return (
            f"Jelaskan secara lengkap, menarik, dan luwes mengenai produk {product_name} "
            f"dengan harga {price}, varian/opsi {variants}, materi/silabus {materials}, "
            f"serta promo bundling {promo} sesuai persona toko."
        )

    async def generate_commerce_response(
        self,
        tenant_slug: str,
        user_message: str,
        user_phone: str = "",
        user_name: str = "",
        button_id: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Generates contextual AI completion using the dynamically injected commerce prompt.
        
        If a quick-reply button payload or 'Info Produk' trigger is received, routes through
        an internal LLM prompt describing the product comprehensively.
        Incorporates conversation history for multi-turn conversational context.
        """
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
        system_prompt = self.build_commerce_system_prompt(tenant_slug)
        clean_msg = (user_message or "").strip()

        # Incorporate multi-turn conversation history into system prompt
        if history and isinstance(history, list):
            formatted_turns = []
            for turn in history[-8:]:
                role = turn.get("role") or turn.get("sender") or "User"
                content = turn.get("content") or turn.get("text") or turn.get("message") or ""
                if content:
                    formatted_turns.append(f"{str(role).capitalize()}: {content}")
            if formatted_turns:
                history_str = "\n\nRIWAYAT PERCAKAPAN SEBELUMNYA:\n" + "\n".join(formatted_turns)
                system_prompt = f"{system_prompt}{history_str}"

        # Check if button click or product info request
        is_info_request = self.is_product_info_trigger(clean_msg, button_id)
        if is_info_request:
            query_to_llm = self.build_internal_product_query(details)
            logger.info(
                f"[{tenant_slug}] Routed quick-reply button payload '{button_id or clean_msg}' to internal LLM query: {query_to_llm}"
            )
        else:
            query_to_llm = clean_msg

        try:
            response = await self.ai_service.generate(
                user_message=query_to_llm,
                system_prompt=system_prompt,
                context={
                    "tenant_slug": tenant_slug,
                    "phone": user_phone,
                    "name": user_name or "Kakak",
                    "button_id": button_id,
                    "has_history": bool(history),
                },
            )
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.warning(f"[{tenant_slug}] AI generation error, falling back: {e}")

        # Non-static Conversational Fallback Response:
        store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug
        products = details.get("products", [])

        if products:
            p = products[0]
            title = p.get("title", "Produk Unggulan")
            price = f"Rp{float(p.get('price', 0)):,.0f}"
            desc = p.get("description", "Materi dan silabus lengkap siap pakai")
            p_type = p.get("product_type", "Standard Resmi")
            promo = "Beli 2 gratis template bonus eksklusif / diskon bundling spesial"
            return (
                f"Halo Kakak! Di *{store_name}*, kami menyediakan *{title}* seharga {price} ({p_type}).\n\n"
                f"📚 *Materi & Silabus:* {desc}\n"
                f"🎁 *Promo Bundling:* {promo}\n\n"
                f"Apakah ada yang ingin Kakak tanyakan lebih detail, atau ingin langsung memesan via QRIS otomatis?"
            )

        return (
            f"Halo Kakak! Selamat datang di *{store_name}*. "
            f"Ada yang bisa kami bantu seputar produk dan katalog kami hari ini?"
        )


# Singleton
commerce_ai_engine = CommerceAIEngine()

