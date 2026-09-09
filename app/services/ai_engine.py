"""app/services/ai_engine.py
Dynamic Commerce AI Engine & Context Injection Service (100% Database-Driven).

Dynamically constructs store-bounded AI system prompts for multi-tenant ecosystem:
1. Injects Store Name, Business Vertical Category, and Tone of Voice from tenant settings.
2. Injects real catalog products/services with accurate pricing from database or metadata.
3. Completely agnostic and dynamic—no hardcoded tenant knowledge bases or specific store scripts.
"""

import logging
from typing import Dict, Any, List, Optional
from app.services.onboarding_service import onboarding_service
from app.services.ai_gateway import ai_gateway, AgentProfile
from app.services.sales_agent_guard import backend_security_validator

logger = logging.getLogger("COMMERCE_AI_ENGINE")

BOT_STRATEGY_DIRECTIVES: Dict[str, Dict[str, str]] = {
    "trust_builder": {
        "title": "Mode 'trust_builder' (Toko Baru / Bangun Kepercayaan)",
        "tone": "Konsultan ramah, penuh empati, edukatif, bersahabat, dan tidak memaksa",
        "instructions": (
            "ATURAN STRATEGI BOT PERSONA: 'trust_builder' (Toko Baru / Bangun Kepercayaan):\n"
            "- Gaya Bahasa: Konsultan ramah, empatik, edukatif, dan tidak memaksa.\n"
            "- Aturan:\n"
            "  * Jawab keraguan produk atau pertanyaan secara detail, mendalam, dan transparan.\n"
            "  * Pamerkan jaminan keamanan transaksi, garansi resmi toko, dan kepuasan pelanggan.\n"
            "  * Fokus membangun kepercayaan dan pemahaman prospek terlebih dahulu.\n"
            "- Kalimat Penutup: Tanyakan kenyamanan prospek (contoh: 'Apakah ada bagian dari layanan atau produk yang ingin Kakak tanyakan lebih detail?')."
        ),
    },
    "balanced": {
        "title": "Mode 'balanced' (Toko Berkembang - Default)",
        "tone": "Efisien, ramah, to-the-point",
        "instructions": (
            "ATURAN STRATEGI BOT PERSONA: 'balanced' (Toko Berkembang - Default):\n"
            "- Gaya Bahasa: Efisien, ramah, to-the-point.\n"
            "- Aturan:\n"
            "  * Jawab pertanyaan dalam 2-3 kalimat ringkas dan jelas.\n"
            "  * Jelaskan manfaat utama produk atau layanan secara padat.\n"
            "  * Beri 1 opsi CTA konfirmasi apakah prospek ingin mengamankan jadwal atau promo hari ini."
        ),
    },
    "hard_selling": {
        "title": "Mode 'hard_selling' (Toko Ramai / Fast-Track Checkout)",
        "tone": "Cepat, percaya diri, berorientasi transaksi langsung",
        "instructions": (
            "ATURAN STRATEGI BOT PERSONA: 'hard_selling' (Toko Ramai / Fast-Track Checkout):\n"
            "- Gaya Bahasa: Cepat, percaya diri, lugas, dan berorientasi transaksi langsung.\n"
            "- Aturan:\n"
            "  * Respon maksimal 1-2 kalimat singkat dan to-the-point.\n"
            "  * Langsung sodorkan rincian ringkas layanan/produk dan tegaskan status ready.\n"
            "  * Pangkas drop-off dengan menyodorkan opsi pembayaran instan (QRIS / Bayar di tempat)."
        ),
    }
}


class CommerceAIEngine:
    """Universal AI Engine for Multi-Tenant Commerce & Services with 100% Dynamic Database Prompt Injection."""

    def __init__(self, ai_service=None):
        self.ai_service = ai_service or ai_gateway

    def build_commerce_system_prompt(self, tenant_slug: str, bot_strategy: Optional[str] = None) -> str:
        """Constructs a hyper-focused system prompt dynamically pulled entirely from tenant database settings."""
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
        tenant = details.get("tenant", {}) if details else {}
        persona = details.get("persona", {}) if details else {}
        ai_k = details.get("ai_knowledge", {}) if details else {}
        meta = details.get("metadata", {}) if details else {}
        products = details.get("products", []) if details else []

        if not products:
            try:
                from app.services.whatsapp_service import get_tenant_products_from_db
                _, db_prods = get_tenant_products_from_db(tenant_slug)
                if db_prods:
                    products = db_prods
            except Exception:
                pass

        # Jika produk kosong di root, cek metadata.capacities atau settings database
        if not products and isinstance(meta, dict) and meta.get("capacities"):
            products = meta["capacities"]

        # Resolve Strategy
        strategy_key = (
            bot_strategy
            or tenant.get("bot_strategy")
            or persona.get("bot_strategy")
            or ai_k.get("bot_strategy")
            or "trust_builder"
        ).lower().strip()
        if strategy_key not in BOT_STRATEGY_DIRECTIVES:
            strategy_key = "trust_builder"

        strategy_info = BOT_STRATEGY_DIRECTIVES[strategy_key]
        strategy_rules = strategy_info["instructions"]

        store_name = tenant.get("name", tenant_slug)
        vertical = tenant.get("vertical", "COMMERCE")
        
        # 100% Dynamic from Database Dashboard Settings
        welcome = persona.get("welcome_message") or ai_k.get("welcome_message") or f"Halo! Selamat datang di {store_name}. Ada yang bisa saya bantu?"
        assistant_name = (
            persona.get("assistant_name")
            or persona.get("ai_name")
            or ai_k.get("ai_name")
            or ai_k.get("assistant_name")
            or f"Asisten {store_name}"
        )
        tone = persona.get("tone") or ai_k.get("tone") or "Ramah, solutif, dan profesional"
        custom_system_prompt = persona.get("system_prompt") or ai_k.get("system_prompt") or tenant.get("system_prompt")

        # Format Daftar Produk / Layanan / Tarif Riil dari Database
        product_lines: List[str] = []
        if products:
            for idx, p in enumerate(products, 1):
                title = p.get("title") or p.get("name") or f"Layanan {idx}"
                price = p.get("promo_price") or p.get("price") or 0
                desc = p.get("description") or p.get("variants") or "Layanan resmi terverifikasi"
                promo_suffix = f" (Promo: Rp{float(p.get('promo_price')):,.0f})" if p.get("promo_price") else ""
                product_lines.append(f"{idx}. {title} - Rp{float(price):,.0f}{promo_suffix} | {desc}")
            catalog_text = "\n".join(product_lines)
        else:
            catalog_text = f"1. Layanan Utama {store_name}"

        # Jika merchant mengatur custom system prompt di dashboard
        if custom_system_prompt and custom_system_prompt.strip() and not custom_system_prompt.startswith("Kamu adalah asisten resmi"):
            return (
                f"{custom_system_prompt.strip()}\n\n"
                f"{strategy_rules}\n\n"
                f"IDENTITAS ASISTEN & TOKO:\n"
                f"- Nama Asisten AI: {assistant_name}\n"
                f"- Nama Toko / Merchant: {store_name} ({vertical})\n"
                f"- Gaya Komunikasi / Tone: {tone}\n"
                f"- Sapaan Pembuka Wajib: {welcome}\n\n"
                f"KATALOG & TARIF RESMI (DARI DATABASE):\n"
                f"{catalog_text}\n"
            )

        prompt = (
            f"Anda adalah {assistant_name}, Sales Closer dan Konsultan profesional untuk '{store_name}' ({vertical}).\n"
            f"Gaya Komunikasi: {strategy_info['tone']} ({tone}), luwes, ramah, dan solutif seperti manusia.\n\n"
            f"INFORMASI TOKO:\n"
            f"- Nama Toko: {store_name}\n"
            f"- Nama Asisten AI: {assistant_name}\n"
            f"- Sapaan Pembuka Wajib: {welcome}\n\n"
            f"{strategy_rules}\n\n"
            f"KATALOG & TARIF RESMI DARI DATABASE (JANGAN MENGARANG HARGA LAIN):\n"
            f"{catalog_text}\n\n"
            f"ATURAN MUTLAK:\n"
            f"1. Dilarang mengarang harga atau layanan di luar daftar tarif database di atas.\n"
            f"2. Jika ada pertanyaan teknis di luar alur, jawab singkat dan tarik kembali pelanggan ke alur transaksi.\n"
            f"3. Respon WAJIB berupa JSON Object dengan struktur:\n"
            f'{{\n  "reply": "<teks balasan kepada calon pembeli>",\n  "quick_actions": ["<aksi 1>", "<aksi 2>"]\n}}\n'
        )
        return prompt

    def is_product_info_trigger(self, message: str, button_id: Optional[str] = None) -> bool:
        """Detects whether incoming message requests catalog or pricing details."""
        clean_btn = str(button_id or "").strip().upper()
        clean_text = str(message or "").strip().lower()

        if clean_btn.startswith("INFO_") or clean_btn.startswith("DETAIL_"):
            return True

        text_triggers = [
            "info produk", "detail produk", "info layanan", "daftar tarif",
            "katalog", "harga", "berapa", "kapasitas", "layanan apa saja"
        ]
        return any(trigger in clean_text for trigger in text_triggers)

    async def generate_commerce_response(
        self,
        tenant_slug: str,
        user_message: str,
        user_phone: str = "",
        user_name: str = "",
        button_id: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        bot_strategy: Optional[str] = None,
        mode_prompt: Optional[str] = None,
    ) -> str:
        """Generates contextual AI completion using 100% dynamic database-driven system prompt."""
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
        tenant = details.get("tenant", {}) if details else {}
        persona = details.get("persona", {}) if details else {}

        strategy_key = (
            bot_strategy
            or tenant.get("bot_strategy")
            or persona.get("bot_strategy")
            or "trust_builder"
        ).lower().strip()
        if strategy_key not in BOT_STRATEGY_DIRECTIVES:
            strategy_key = "trust_builder"

        system_prompt = self.build_commerce_system_prompt(tenant_slug, bot_strategy=strategy_key)
        if mode_prompt:
            system_prompt = f"{mode_prompt}\n\n{system_prompt}"

        clean_msg = (user_message or "").strip()

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

        query_to_llm = clean_msg

        try:
            if hasattr(self.ai_service, "generate_for_agent"):
                response = await self.ai_service.generate_for_agent(
                    agent_profile=AgentProfile.BUYER_ASSISTANT,
                    user_message=query_to_llm,
                    system_prompt=system_prompt,
                    context={
                        "tenant_slug": tenant_slug,
                        "phone": user_phone,
                        "name": user_name or "Kakak",
                        "button_id": button_id,
                        "has_history": bool(history),
                        "bot_strategy": strategy_key,
                    },
                )
            else:
                response = await self.ai_service.generate(
                    user_message=query_to_llm,
                    system_prompt=system_prompt,
                    context={
                        "tenant_slug": tenant_slug,
                        "phone": user_phone,
                        "name": user_name or "Kakak",
                        "button_id": button_id,
                        "has_history": bool(history),
                        "bot_strategy": strategy_key,
                    },
                )
            if response and response.strip():
                from app.services.whatsapp_service import sanitize_whatsapp_message_text
                return sanitize_whatsapp_message_text(response.strip())
        except Exception as e:
            logger.warning(f"[{tenant_slug}] AI generation error, falling back: {e}")

        # Fallback dinamis murni mengambil sapaan dari database tenant bersangkutan
        ai_k = details.get("ai_knowledge", {}) if details else {}
        fallback_welcome = persona.get("welcome_message") or ai_k.get("welcome_message") or f"Halo! Selamat datang di {tenant.get('name', tenant_slug)}. Ada yang bisa saya bantu?"
        return fallback_welcome

    async def validate_store_action(
        self,
        tenant_id_or_slug: str,
        action: Dict[str, Any],
    ) -> Dict[str, Any]:
        """ADR Security Guard: Validates and sanitizes store sales actions strictly against real DB."""
        return await backend_security_validator.validate_and_sanitize_action(
            tenant_id=tenant_id_or_slug,
            proposed_action=action,
        )


# Singleton
commerce_ai_engine = CommerceAIEngine()