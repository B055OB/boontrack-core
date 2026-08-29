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
from app.services.ai_gateway import ai_gateway

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


class CommerceAIEngine:
    """Universal AI Engine for Multi-Tenant Commerce & Ecosystem with Dynamic Prompt Injection."""

    def __init__(self, ai_service=None):
        self.ai_service = ai_service or ai_gateway

    def build_commerce_system_prompt(self, tenant_slug: str) -> str:
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
        if not details:
            return (
                f"Anda adalah Sales Closer dan konsultan produk profesional untuk '{tenant_slug}'.\n"
                "Jawab dengan ramah, luwes, dan solutif seperti manusia (maksimal 3 kalimat), lalu akhiri dengan: 'Mau saya buatkan kode QRIS pembayarannya sekarang Kak?'"
            )

        tenant = details.get("tenant", {})
        persona = details.get("persona", {})
        products = details.get("products", [])

        store_name = tenant.get("name", tenant_slug)
        vertical = tenant.get("vertical", "COMMERCE")
        tone = persona.get("tone", "Edukatif & Expert, ramah, to-the-point, high conversion closer")
        welcome = persona.get("welcome_message", f"Selamat datang di {store_name}!")

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

        prompt = (
            f"Anda adalah Konsultan Ahli & Sales Closer profesional untuk '{store_name}' ({vertical}).\n"
            f"Gaya Komunikasi: {tone}, santai, luwes, ramah, dan solutif seperti manusia (anti-robotik).\n\n"
            f"INFORMASI TOKO:\n"
            f"- Nama Toko: {store_name}\n"
            f"- Kategori Vertikal: {vertical}\n"
            f"- Sapaan Pembuka: {welcome}\n\n"
            f"KATALOG PRODUK RIIL YANG TERSEDIA:\n"
            f"{catalog_text}"
            f"{curriculum_section}\n\n"
            f"STRATEGI CLOSING & HIGH-CONVERSION SALES CLOSER DIRECTIVE:\n"
            f"1. Jawab pertanyaan, kekhawatiran, atau obrolan calon pembeli secara luwes, meyakinkan, dan padat (maksimal 3 kalimat).\n"
            f"2. SELALU akhiri respons dengan pertanyaan pemicu closing cepat:\n"
            f"   'Mau saya buatkan kode QRIS pembayarannya sekarang Kak?'\n"
            f"3. Pembayaran didukung via Dynamic QRIS otomatis (BCA, Mandiri, BRI, BNI, DANA, GoPay, OVO, ShopeePay) dengan konfirmasi instan.\n\n"
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
    ) -> str:
        """Generates contextual AI completion using the closing-oriented system prompt.
        
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
        if is_info_request and details.get("products"):
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

        # Intelligent Closing Fallback (Non-static & High Conversion):
        clean_lower = clean_msg.lower()

        # 1. Fallback Atmosfitnes
        if tenant_slug == "atmosfitnes":
            if any(w in clean_lower for w in ["zumba", "kelas", "jadwal", "studio", "aerobik"]):
                return (
                    "Halo Kakak! Di *Prima Fit Gym (Atmosfitnes)*, kami mengadakan *Kelas Zumba & Studio ber-AC*:\n"
                    "• *Jadwal*: Selasa & Kamis pukul 19:00 WIB, Sabtu pukul 08:30 WIB\n"
                    "• *Tarif*: Rp45.000 / sesi atau Rp200.000 / bulan (Unlimited Studio)\n\n"
                    "Pembayaran didukung via Dynamic QRIS otomatis. Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
                )
            return (
                "Halo Kakak! Di *Prima Fit Gym (Atmosfitnes)*, pilihan paket membership kami:\n"
                "• *Gym Basic*: Rp150.000/bulan (Alat beban & cardio)\n"
                "• *Zumba & Studio*: Rp200.000/bulan (Kelas zumba & aerobik)\n"
                "• *Gym Premium*: Rp250.000/bulan (Gym + Studio + Locker)\n"
                "• *All Access VIP*: Rp350.000/bulan (Gym + Studio + Sauna + Smart Gate NFC)\n"
                "• *Personal Training*: Rp800.000 (10 sesi 1-on-1)\n\n"
                "Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
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
            return (
                f"Halo Kakak! Di *{store_name}*, berikut kurikulum & silabus materi lengkap yang akan dipelajari:\n\n"
                f"📚 *SILABUS & KURIKULUM LENGKAP:*\n"
                f"{modules_formatted}\n\n"
                f"🔥 *Promo Hari Ini:* {p_price} (Diskon 50% dari ~Rp299.000~ - Akses Seumur Hidup & Update Materi)\n"
                f"📂 *Akses Pembelajaran:* Link Google Drive resmi otomatis dikirimkan ke WhatsApp setelah pembayaran diverifikasi.\n\n"
                f"Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
            )

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
                f"Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
            )

        return (
            f"Halo Kakak! Selamat datang di *{store_name}*. "
            f"Mau saya buatkan kode QRIS pembayarannya sekarang Kak?"
        )


# Singleton
commerce_ai_engine = CommerceAIEngine()
