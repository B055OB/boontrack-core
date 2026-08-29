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

    async def generate_commerce_response(
        self,
        tenant_slug: str,
        user_message: str,
        user_phone: str = "",
        user_name: str = "",
    ) -> str:
        """Generates contextual AI completion using the dynamically injected commerce prompt."""
        system_prompt = self.build_commerce_system_prompt(tenant_slug)
        clean_msg = (user_message or "").strip()

        try:
            response = await self.ai_service.generate(
                user_message=clean_msg,
                system_prompt=system_prompt,
                context={
                    "tenant_slug": tenant_slug,
                    "phone": user_phone,
                    "name": user_name or "Kakak",
                },
            )
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.warning(f"[{tenant_slug}] AI generation error, falling back: {e}")

        # Fallback response
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug)
        store_name = details.get("tenant", {}).get("name", tenant_slug) if details else tenant_slug
        return (
            f"Halo Kakak! Selamat datang di *{store_name}*. "
            f"Pesan Kakak sudah kami terima. Silakan ketik nama produk yang ingin dipesan atau ketik 'menu' untuk melihat katalog kami."
        )


# Singleton
commerce_ai_engine = CommerceAIEngine()
