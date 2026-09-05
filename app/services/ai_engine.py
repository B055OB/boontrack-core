"""app/services/ai_engine.py
Dynamic Commerce AI Engine & Context Injection Service.

Dynamically constructs store-bounded AI system prompts for multi-tenant ecosystem:
1. Injects Store Name, Business Vertical Category, and Tone of Voice.
2. Injects real catalog products with accurate pricing, variants, bundling promos, and digital asset URLs.
3. Expanded knowledge bases for vertical tenants (suhu-ads-masterclass, atmosfitnes, bale_pananggeuhan).
4. High-Conversion Sales Closer Persona: Luwes, ramah, solutif, anti-robotik, berorientasi closing cepat via QRIS.
5. Enforces strict context boundaries and intelligent multi-turn responses.
"""

import logging
from typing import Dict, Any, List, Optional
from app.services.onboarding_service import onboarding_service
from app.services.ai_gateway import ai_gateway, AgentProfile, ModelProfile
from app.services.sales_agent_guard import (
    StoreContextBoundaryManager,
    backend_security_validator,
    format_tenant_session_key,
    tenant_session_store,
    StoreActionType,
    ALLOWED_STORE_ACTIONS,
)

logger = logging.getLogger("COMMERCE_AI_ENGINE")

EXPANDED_TENANT_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "suhu-ads-masterclass": {
        "title": "Suhu Ads Masterclass 2026",
        "vertical": "DIGITAL_PRODUCTS",
        "curriculum": [
            "Modul 1: Riset Winning Audience & Bedah Pixel Meta Ads (Event tracking, Custom & Lookalike Audience, CAPI setup)",
            "Modul 2: Struktur Campaign CBO vs ABO & Scaling Strategy (Budgeting & Ad Sets, Horizontal & Vertical Scaling)",
            "Modul 3: Funneling, Creative Hook & Copywriting Konversi Tinggi (Video hooks, AIDA framework, LP Optimization)",
            "Bonus: Template Dashboard Budgeting & Akses Grup Diskusi Eksklusif (Notion spreadsheet, private Telegram VIP)",
        ],
        "delivery_url": "https://drive.google.com/drive/folders/suhu-ads-masterclass-2026",
    },
    "onlineboost": {
        "title": "Onlineboost Masterclass & Digital Products",
        "vertical": "DIGITAL_PRODUCTS",
        "curriculum": [
            "Modul 1: Riset Winning Audience & Bedah Pixel Meta Ads (Event tracking, Custom & Lookalike Audience, CAPI setup)",
            "Modul 2: Struktur Campaign CBO vs ABO & Scaling Strategy (Budgeting & Ad Sets, Horizontal & Vertical Scaling)",
            "Modul 3: Funneling, Creative Hook & Copywriting Konversi Tinggi (Video hooks, AIDA framework, LP Optimization)",
            "Bonus: Template Dashboard Budgeting & Akses Grup Diskusi Eksklusif (Notion spreadsheet, private Telegram VIP)",
        ],
        "delivery_url": "https://drive.google.com/drive/folders/suhu-ads-masterclass-2026",
    },
    "atmosfitnes": {
        "title": "Prima Fit Gym (Atmosfitnes)",
        "vertical": "FITNESS & GYM",
        "packages": [
            "1. Gym Basic: Rp150.000 / bulan (Akses alat beban & cardio)",
            "2. Zumba & Studio Class: Rp200.000 / bulan (Akses kelas zumba, aerobik, yoga)",
            "3. Gym Premium: Rp250.000 / bulan (Gym + Kelas Studio + Locker)",
            "4. All Access VIP: Rp350.000 / bulan (Unlimited Gym, Studio, Sauna, Smart Gate NFC)",
            "5. Personal Training: Rp800.000 / 10 sesi (1-on-1 Certified Trainer)",
        ],
        "facilities": "Peralatan beban lengkap (Free weights, Machines, Cardio treadmill), Studio Zumba & Aerobik ber-AC, Locker room, Shower air hangat, Turnstile IoT smart access.",
        "schedule": "Zumba Class: Selasa & Kamis 19:00 WIB, Sabtu 08:30 WIB. Gym buka: Senin - Sabtu 06:00 - 22:00 WIB, Minggu 07:00 - 20:00 WIB.",
        "location": "Kompleks Olahraga Prima Fit, Jl. Cihampelas No. 88, Bandung",
        "payment_info": "Pembayaran instan via Dynamic QRIS (BCA, Mandiri, BRI, BNI, DANA, GoPay, OVO, ShopeePay). QRIS dibuat otomatis dan akses turnstile langsung aktif.",
    },
    "bale_pananggeuhan": {
        "title": "Balé Pananggeuhan",
        "vertical": "PUBLIC_SERVICES",
        "services": [
            "1. Pengaduan Fasilitas Umum: Jalan rusak, lampu PJU padam, drainase/banjir, sampah liar.",
            "2. Layanan Administrasi Kependudukan: Syarat KTP rusak/hilang, KK, Surat Keterangan Usaha (SKU), pengantar nikah N1-N4 ke KUA.",
            "3. Bantuan Sosial: Cek status bansos DTKS, PKH, sembako, dan beasiswa.",
        ],
        "operating_hours": "Senin - Jumat: 08:00 - 16:00 WIB, Pelaporan online 24/7 via WhatsApp",
    }
}

BOT_STRATEGY_DIRECTIVES: Dict[str, Dict[str, str]] = {
    "trust_builder": {
        "title": "Mode 'trust_builder' (Toko Baru / Bangun Kepercayaan)",
        "tone": "Konsultan ramah, penuh empati, edukatif, bersahabat, dan tidak memaksa",
        "instructions": (
            "ATURAN STRATEGI BOT PERSONA: 'trust_builder' (Toko Baru / Bangun Kepercayaan):\n"
            "- Gaya Bahasa: Konsultan ramah, empatik, edukatif, dan tidak memaksa.\n"
            "- Aturan:\n"
            "  * Jawab keraguan produk atau pertanyaan secara detail, mendalam, dan transparan.\n"
            "  * Pamerkan jaminan keamanan transaksi, garansi resmi toko, kepuasan pelanggan, dan komitmen pengiriman yang rapi serta aman.\n"
            "  * Fokus membangun kepercayaan dan pemahaman prospek terlebih dahulu.\n"
            "- Pantangan: JANGAN langsung kirim link pembayaran jika prospek baru tanya-tanya umum.\n"
            "- Alur: Arahkan untuk diskusi interaktif sampai prospek merasa yakin dan secara eksplisit ingin membeli.\n"
            "- Kalimat Penutup: Tanyakan kenyamanan prospek (contoh: 'Apakah ada bagian dari materi atau produk yang ingin Kakak tanyakan lebih detail?')."
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
            "  * Jelaskan manfaat utama (key value proposition) produk secara padat.\n"
            "  * Beri 1 opsi CTA konfirmasi apakah prospek ingin mengamankan stok atau promo hari ini.\n"
            "- Kalimat Penutup: 'Apakah Kakak ingin saya bantu amankan stok promonya sekarang?'"
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
            "  * Langsung sodorkan rincian ringkas produk dan tegaskan status stok ready / akses langsung aktif.\n"
            "  * Pangkas drop-off dengan menyodorkan CTA link checkout / pembayaran instan tanpa bertele-tele.\n"
            "- Kalimat Penutup: 'Stok ready, mau saya buatkan kode QRIS pembayarannya sekarang Kak?'"
        ),
    }
}


class CommerceAIEngine:
    """Universal AI Engine for Multi-Tenant Commerce & Ecosystem with Dynamic Prompt Injection."""

    def __init__(self, ai_service=None):
        self.ai_service = ai_service or ai_gateway

    def build_commerce_system_prompt(self, tenant_slug: str, bot_strategy: Optional[str] = None) -> str:
        """Constructs a hyper-focused system prompt bounded strictly to the merchant's catalog or knowledge base."""
        # 1. Khusus Tenant Atmosfitnes Gym
        if tenant_slug == "atmosfitnes":
            gym_kb = EXPANDED_TENANT_KNOWLEDGE.get("atmosfitnes", {})
            pkgs_str = "\n".join([f"- {p}" for p in gym_kb.get("packages", [])])
            return (
                "Anda adalah partner fitness dan Sales Closer profesional untuk Prima Fit Gym (Atmosfitnes).\n"
                "Gaya Komunikasi: Ramah, santai, energik, luwes seperti manusia, tidak kaku atau robotik.\n\n"
                "INFORMASI GYM & FASILITAS:\n"
                f"- Nama Gym: {gym_kb.get('title', 'Prima Fit Gym (Atmosfitnes)')}\n"
                f"- Lokasi: {gym_kb.get('location')}\n"
                f"- Jam Operasional & Jadwal: {gym_kb.get('schedule')}\n"
                f"- Fasilitas: {gym_kb.get('facilities')}\n\n"
                "PAKET MEMBERSHIP & KELAS RESMI:\n"
                f"{pkgs_str}\n\n"
                "PANDUAN KOMUNIKASI & CLOSING:\n"
                "- Jawab setiap pertanyaan atau obrolan santai calon member secara luwes, hangat, dan solutif (maksimal 3-4 kalimat).\n"
                "- Jika calon member bertanya tentang paket, kelas zumba, atau harga, jelaskan dengan jelas lalu ajak amankan slot: 'Mau saya buatkan kode QRIS pembayarannya sekarang Kak?'\n"
                "- Pembayaran didukung via Dynamic QRIS instan dan kartu/akses turnstile gate langsung aktif otomatis setelah bayar."
            )

        # 2. Khusus Tenant Bale Pananggeuhan
        if tenant_slug in ("bale_pananggeuhan", "bale-pananggeuhan"):
            bale_kb = EXPANDED_TENANT_KNOWLEDGE.get("bale_pananggeuhan", {})
            svcs_str = "\n".join([f"- {s}" for s in bale_kb.get("services", [])])
            return (
                "Kamu adalah asisten resmi layanan aspirasi dan pengaduan Balé Pananggeuhan (Layanan Publik Jawa Barat).\n"
                "Gaya Komunikasi: Sopan, mengayomi, solutif, dan informatif.\n\n"
                "LAYANAN DAN PENGADUAN RESMI:\n"
                f"{svcs_str}\n"
                f"- Jam Operasional: {bale_kb.get('operating_hours')}\n\n"
                "PANDUAN:\n"
                "- Bantu warga mencatat aduan fasilitas umum atau memberikan persyaratan administrasi kependudukan (KTP, SKU, N1-N4, Bansos DTKS) secara runtut dan jelas."
            )

        # 3. Dynamic Commerce Tenant Prompt
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
        tenant = details.get("tenant", {}) if details else {}
        persona = details.get("persona", {}) if details else {}
        ai_k = details.get("ai_knowledge", {}) if details else {}
        products = details.get("products", []) if details else []

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

        if not details:
            if strategy_key == "hard_selling":
                closing_q = "Stok ready! Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
            elif strategy_key == "balanced":
                closing_q = "Mau saya bantu amankan stok promonya sekarang Kak?"
            else:
                closing_q = "Apakah ada yang ingin Kakak tanyakan lebih detail mengenai produk kami?"
            return (
                f"Anda adalah Sales Closer dan konsultan produk profesional untuk '{tenant_slug}'.\n"
                f"{strategy_rules}\n\n"
                f"Jawab sesuai persona di atas, lalu akhiri dengan: '{closing_q}'"
            )

        tenant = details.get("tenant", {})
        persona = details.get("persona", {})
        ai_k = details.get("ai_knowledge", {})
        products = details.get("products", [])

        store_name = tenant.get("name", tenant_slug)
        vertical = tenant.get("vertical", "COMMERCE")
        tone = persona.get("tone") or ai_k.get("tone") or "Edukatif & Expert, ramah, to-the-point, high conversion closer"
        welcome = persona.get("welcome_message", f"Selamat datang di {store_name}!")
        assistant_name = (
            persona.get("assistant_name")
            or persona.get("ai_name")
            or ai_k.get("ai_name")
            or ai_k.get("assistant_name")
            or f"Asisten {store_name}"
        )
        custom_system_prompt = (
            persona.get("system_prompt")
            or ai_k.get("system_prompt")
            or tenant.get("system_prompt")
        )

        # Format Daftar Produk Riil
        product_lines: List[str] = []
        if products:
            for idx, p in enumerate(products, 1):
                title = p.get("title", f"Produk {idx}")
                price = p.get("price", 0)
                desc = p.get("description") or "Katalog resmi berkualitas tinggi"
                p_type = p.get("product_type", "DIGITAL_FILE")
                asset_ref = p.get("asset_reference", "digital_access")

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

        # Knowledge Base Kurikulum Khusus
        kb = EXPANDED_TENANT_KNOWLEDGE.get(tenant_slug, {})
        curriculum_section = ""
        if kb.get("curriculum"):
            modules_str = "\n".join([f"- {m}" for m in kb["curriculum"]])
            curriculum_section = (
                f"\n\nKURIKULUM & SILABUS MATERI RESMI:\n"
                f"{modules_str}\n"
                f"- Link Akses Materi: {kb.get('delivery_url', '')}\n"
            )

        # Jika tenant memiliki custom system prompt spesifik dari dashboard/Supabase:
        if custom_system_prompt and custom_system_prompt.strip() and not custom_system_prompt.startswith("Kamu adalah asisten resmi untuk toko"):
            prompt = (
                f"{custom_system_prompt.strip()}\n\n"
                f"{strategy_rules}\n\n"
                f"IDENTITAS ASISTEN & TOKO:\n"
                f"- Nama Asisten AI: {assistant_name}\n"
                f"- Nama Toko / Merchant: {store_name} ({vertical})\n"
                f"- Gaya Komunikasi / Tone: {strategy_info['tone']}\n"
                f"- Sapaan Pembuka: {welcome}\n\n"
                f"KATALOG PRODUK RIIL:\n"
                f"{catalog_text}"
                f"{curriculum_section}\n\n"
                f"INSTRUKSI PEMBAYARAN QRIS:\n"
                f"Pembayaran transaksi otomatis didukung via Dynamic QRIS instan (BCA, Mandiri, BRI, BNI, DANA, GoPay, OVO, ShopeePay)."
            )
            return prompt

        prompt = (
            f"Anda adalah {assistant_name}, Konsultan Ahli & Sales Closer profesional untuk '{store_name}' ({vertical}).\n"
            f"Gaya Komunikasi: {strategy_info['tone']} ({tone}), santai, luwes, ramah, dan solutif seperti manusia (anti-robotik).\n\n"
            f"INFORMASI TOKO:\n"
            f"- Nama Toko: {store_name}\n"
            f"- Nama Asisten AI: {assistant_name}\n"
            f"- Kategori Vertikal: {vertical}\n"
            f"- Sapaan Pembuka: {welcome}\n\n"
            f"{strategy_rules}\n\n"
            f"KATALOG PRODUK RIIL YANG TERSEDIA:\n"
            f"{catalog_text}"
            f"{curriculum_section}\n\n"
            f"BATASAN TOPIK & INTEGRITAS TOKO (STRICT NEGATIVE BOUNDARIES):\n"
            f"1. Kamu HANYA melayani seputar produk, pemesanan, dan layanan resmi dari {store_name} ({vertical}).\n"
            f"2. JANGAN PERNAH membahas, memberikan jadwal, atau melayani topik:\n"
            f"   - Fasilitas gym, keanggotaan fitness, atau turnstile gate Atmosfitnes.\n"
            f"   - Layanan publik kelurahan, pengurusan KTP/SKU/bansos, surat pengantar nikah, atau Balé Pananggeuhan.\n"
            f"   - Bimbingan ibadah/riyadhoh Om Budi atau konsultasi karir umum.\n"
            f"3. Jika pelanggan bertanya tentang topik di luar katalog dan layanan {store_name}, tolak dengan sopan dan arahkan kembali ke produk toko:\n"
            f"   Contoh: 'Mohon maaf Kakak, saya {assistant_name}, asisten resmi {store_name}. Saya khusus melayani seputar produk dan pesanan di {store_name}. Ada produk kami yang ingin Kakak tanyakan?'"
        )
        return prompt

    def is_product_info_trigger(self, message: str, button_id: Optional[str] = None) -> bool:
        """Detects whether incoming message or button payload requests product/catalog details."""
        clean_btn = str(button_id or "").strip().upper()
        clean_text = str(message or "").strip().lower()

        btn_triggers = [
            "INFO_PRODUK", "DETAIL_PRODUK", "INFO_PAKET", "ORDER_PRODUK",
            "LIHAT_PRODUK", "INFO_CATALOG", "PRODUK_DETAIL", "INFO_SILABUS",
            "INFO_KURIKULUM", "BUKA_MATERI", "INFO_GYM", "INFO_ZUMBA",
            "BTN_VIEW_SYLLABUS"
        ]
        if clean_btn in btn_triggers or any(clean_btn.startswith(prefix) for prefix in ["INFO_", "DETAIL_"]):
            return True

        text_triggers = [
            "info produk", "detail produk", "info paket", "detail paket",
            "lihat produk", "katalog produk", "informasi produk", "penjelasan produk",
            "produk apa saja", "daftar produk", "silabus", "kurikulum",
            "modul", "materi", "belajar apa", "isi materi", "isi kursus",
            "harga paket", "daftar paket", "paket gym", "kelas zumba"
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
        bot_strategy: Optional[str] = None,
    ) -> str:
        """Generates contextual AI completion using the strategy-oriented system prompt."""
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
        tenant = details.get("tenant", {})
        persona = details.get("persona", {})

        strategy_key = (
            bot_strategy
            or tenant.get("bot_strategy")
            or persona.get("bot_strategy")
            or "trust_builder"
        ).lower().strip()
        if strategy_key not in BOT_STRATEGY_DIRECTIVES:
            strategy_key = "trust_builder"

        system_prompt = self.build_commerce_system_prompt(tenant_slug, bot_strategy=strategy_key)
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
        if is_info_request and details.get("products"):
            query_to_llm = self.build_internal_product_query(details)
            logger.info(
                f"[{tenant_slug}] Routed quick-reply button payload '{button_id or clean_msg}' to internal LLM query: {query_to_llm}"
            )
        else:
            query_to_llm = clean_msg

        try:
            # ADR: Route BUYER_ASSISTANT profile (Store Sales Agent) to FAST Model Profile
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
                return response.strip()
        except Exception as e:
            logger.warning(f"[{tenant_slug}] AI generation error, falling back: {e}")

        # Intelligent Closing Fallback based on bot_strategy:
        clean_lower = clean_msg.lower()

        # 1. Fallback Atmosfitnes
        if tenant_slug == "atmosfitnes":
            if any(w in clean_lower for w in ["zumba", "kelas", "jadwal", "studio", "aerobik"]):
                if strategy_key == "hard_selling":
                    return (
                        "Kelas Zumba & Studio Prima Fit Gym ready Selasa, Kamis (19:00 WIB) & Sabtu (08:30 WIB).\n"
                        "Tarif Rp45.000/sesi. Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
                    )
                elif strategy_key == "balanced":
                    return (
                        "Halo Kakak! Di *Prima Fit Gym (Atmosfitnes)*, kami mengadakan *Kelas Zumba & Studio ber-AC*:\n"
                        "• Jadwal: Selasa & Kamis (19:00 WIB), Sabtu (08:30 WIB)\n"
                        "• Tarif: Rp45.000 / sesi atau Rp200.000 / bulan (Unlimited Studio)\n\n"
                        "Mau saya bantu amankan slot kelasnya sekarang Kak?"
                    )
                else:
                    return (
                        "Halo Kakak! Di *Prima Fit Gym (Atmosfitnes)*, kami mengadakan *Kelas Zumba & Studio ber-AC* yang dipandu instruktur bersertifikat:\n"
                        "• Jadwal: Selasa & Kamis pukul 19:00 WIB, Sabtu pukul 08:30 WIB\n"
                        "• Tarif: Rp45.000 / sesi atau Rp200.000 / bulan (Unlimited Studio)\n\n"
                        "Kami memastikan ruangan ber-AC nyaman dan fasilitas shower air hangat lengkap. Apakah ada pertanyaan lain seputar jadwal atau kelas kami?"
                    )
            if strategy_key == "hard_selling":
                return "Paket Gym Basic Prima Fit Gym ready Rp150.000/bulan! Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
            elif strategy_key == "balanced":
                return (
                    "Halo Kakak! Di *Prima Fit Gym*, pilihan membership:\n"
                    "• Gym Basic: Rp150.000/bulan\n"
                    "• Zumba & Studio: Rp200.000/bulan\n"
                    "• All Access VIP: Rp350.000/bulan\n\n"
                    "Mau saya bantu amankan slot membershipnya sekarang Kak?"
                )
            else:
                return (
                    "Halo Kakak! Selamat datang di *Prima Fit Gym (Atmosfitnes)*.\n"
                    "Kami menyediakan pilihan paket membership mulai dari Gym Basic (Rp150rb/bln) hingga All Access VIP (Rp350rb/bln) dengan fasilitas lengkap dan akses smart turnstile.\n\n"
                    "Apakah ada paket atau fasilitas tertentu yang ingin Kakak tanyakan lebih detail?"
                )

        # 2. Fallback Bale Pananggeuhan
        if tenant_slug in ("bale_pananggeuhan", "bale-pananggeuhan"):
            return (
                "Sampurasun! Di *Balé Pananggeuhan*, kami siap membantu:\n"
                "1. Pelaporan Fasilitas Umum (Jalan rusak, lampu PJU mati, PDAM bocor, sampah)\n"
                "2. Pengurusan Administrasi Kependudukan (Syarat KTP, KK, SKU, Surat Pengantar Nikah)\n"
                "3. Info Bantuan Sosial (DTKS / PKH)\n\n"
                "Silakan sampaikan detail laporan atau layanan yang Kakak butuhkan."
            )

        # 3. Fallback Suhu Ads Masterclass / Commerce
        store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug
        products = details.get("products", [])
        kb = EXPANDED_TENANT_KNOWLEDGE.get(tenant_slug, {})
        asks_curriculum = any(w in clean_lower for w in ["silabus", "kurikulum", "modul", "materi", "belajar apa"]) or is_info_request

        if kb.get("curriculum") and asks_curriculum:
            modules_formatted = "\n".join([f"• *{m}*" for m in kb["curriculum"]])
            p_price = f"Rp{float(products[0].get('price', 149000)):,.0f}" if products else "Rp149,000"

            if strategy_key == "hard_selling":
                return (
                    f"Halo Kak! Materi di *{store_name}* ready seharga {p_price} (Akses Seumur Hidup & Update Materi).\n"
                    f"Stok promo ready, mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
                )
            elif strategy_key == "balanced":
                return (
                    f"Halo Kak! Di *{store_name}*, kurikulum materi mencakup riset winning audience, struktur campaign, hingga scaling seharga {p_price}.\n"
                    f"Materi dirancang to-the-point untuk praktek langsung. Mau saya bantu amankan slot promonya sekarang Kak?"
                )
            else:  # trust_builder
                return (
                    f"Halo Kakak! Di *{store_name}*, berikut kurikulum & silabus materi lengkap yang akan dipelajari:\n\n"
                    f"📚 *SILABUS & KURIKULUM LENGKAP:*\n"
                    f"{modules_formatted}\n\n"
                    f"🔥 *Investasi Pembelajaran:* {p_price} (Akses Seumur Hidup & Update Materi)\n"
                    f"🛡️ *Jaminan Keamanan:* Kami memberikan 100% garansi kepuasan pembelajaran dan link Google Drive resmi langsung dikirimkan ke WhatsApp Anda.\n\n"
                    f"Apakah ada materi atau modul tertentu yang ingin Kakak tanyakan lebih detail?"
                )

        if products:
            p = products[0]
            title = p.get("title", "Produk Unggulan")
            price = f"Rp{float(p.get('price', 0)):,.0f}"
            desc = p.get("description", "Materi dan silabus lengkap siap pakai")
            p_type = p.get("product_type", "Standard Resmi")

            if strategy_key == "hard_selling":
                return (
                    f"*{title}* di *{store_name}* ready seharga {price} ({p_type}).\n"
                    f"Stok ready, mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
                )
            elif strategy_key == "balanced":
                return (
                    f"Halo Kakak! Di *{store_name}*, kami menyediakan *{title}* seharga {price}.\n"
                    f"Keunggulan: {desc}.\n"
                    f"Apakah Kakak ingin saya bantu amankan stok promonya sekarang?"
                )
            else:  # trust_builder
                return (
                    f"Halo Kakak! Senang bisa membantu di *{store_name}*.\n"
                    f"Produk unggulan kami adalah *{title}* ({price}) dengan jaminan mutu resmi toko dan komitmen pengiriman rapi terpercaya.\n\n"
                    f"Detail: {desc}\n\n"
                    f"Apakah ada informasi lain terkait produk yang ingin Kakak tanyakan lebih detail?"
                )

        if strategy_key == "hard_selling":
            return f"Halo Kak! Selamat datang di *{store_name}*. Stok ready, mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
        elif strategy_key == "balanced":
            return f"Halo Kakak! Selamat datang di *{store_name}*. Mau saya bantu amankan stok promonya sekarang Kak?"
        else:
            return (
                f"Halo Kakak! Selamat datang di *{store_name}*. Kami memberikan 100% garansi resmi dan transaksi terpercaya. "
                f"Ada yang bisa kami bantu jelaskan seputar produk dan layanan kami?"
            )

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
