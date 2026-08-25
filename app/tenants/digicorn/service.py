import os
import logging
from typing import Dict, Any, Optional, List

from app.tenants.digicorn.config import DIGICORN_CONFIG, DIGICORN_TENANT_ID
from app.modules.commerce.catalog import CommerceCatalogService
from app.modules.commerce.service import CommerceService
from app.services.ai_service import ai_gateway
from app.core.messaging.composer import MessageComposer

logger = logging.getLogger("DIGICORN_SERVICE")


class DigicornService:
    """Service pemrosesan pesan dan pencarian produk digital untuk tenant Digicorn."""

    @classmethod
    async def handle_message(
        cls,
        chat_id: int | str,
        user_text: str,
        callback_data: str = "",
        user_name: str = ""
    ) -> Dict[str, Any]:
        """
        Memproses pesan masuk Telegram/WhatsApp untuk Digicorn:
        1. Routing intent menu / start
        2. Pencarian katalog produk digital
        3. Integrasi AI Gateway -> MessageComposer
        4. Checkout & pemesanan produk
        """
        clean_text = (user_text or "").strip()
        clean_text_lower = clean_text.lower()
        sapaan = f", *{user_name}*" if user_name else ""

        # 1. Handling Callback / Button Click
        if callback_data:
            if callback_data.startswith("buy_"):
                product_code = callback_data.replace("buy_", "").strip()
                try:
                    product = await CommerceCatalogService.get_product_by_code(DIGICORN_TENANT_ID, product_code)
                    if product:
                        reply = (
                            f"📦 *PEMESANAN PRODUK DIGITAL*\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"🏷️ *Produk:* {product['title']}\n"
                            f"📂 *Kategori:* {product['category']}\n"
                            f"💰 *Harga:* Rp{product['price']:,}\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"Silakan lakukan pembayaran sebesar *Rp{product['price']:,}* via QRIS / Bank Transfer.\n"
                            f"_Link akses Google Drive akan langsung dikirimkan seketika setelah pembayaran terverifikasi._"
                        )
                        buttons = [
                            [{"text": "💳 Bayar Sekarang", "callback_data": f"pay_{product_code}"}],
                            [{"text": "🔙 Kembali ke Katalog", "callback_data": "menu_catalog"}]
                        ]
                        return {"text": reply, "buttons": buttons}
                except Exception as e:
                    logger.warning(f"Error fetching product for callback {callback_data}: {e}")

            if callback_data == "menu_catalog":
                clean_text = "/start"

        # 2. Greeting / Start Menu
        if clean_text in ["/start", "menu", "katalog", "halo", "hi", "help", "/help", "/menu"]:
            try:
                top_products = await CommerceCatalogService.search_products(DIGICORN_TENANT_ID, query="", limit=5)
            except Exception:
                top_products = []

            product_lines = []
            buttons = []
            for p in top_products:
                product_lines.append(f"• *[{p['product_code']}]* {p['title']} — _Rp{p['price']:,}_")
                buttons.append([{"text": f"🛒 Beli {p['product_code']}", "callback_data": f"buy_{p['product_code']}"}])

            listing_text = "\n".join(product_lines) if product_lines else "• Template Excel Keuangan\n• 30.000+ Video Reels\n• 10.000+ Template Canva\n• 100+ Template CV ATS"
            
            static_body = (
                f"Halo{sapaan}! Selamat datang di *Digicorn* 🦄📦\n"
                f"_{DIGICORN_CONFIG['tagline']}_\n\n"
                f"🔥 *Koleksi Produk Terpopuler (Semua Serba Rp5.000):*\n"
                f"{listing_text}\n\n"
                f"💡 *Cara Cari Produk:* Ketikkan kata kunci kebutuhan Anda.\n"
                f"_(Contoh: 'template canva', 'excel kas', 'video reels', 'notion bundle', 'undangan nikah')_"
            )

            llm_coro = ai_gateway.generate(
                user_message="Buatkan sapaan pembuka 1 kalimat hangat dan ramah dari maskot Digicorn untuk pembeli produk digital.",
                context={"tenant": "digicorn", "feature": "greeting"}
            )
            
            final_text = await MessageComposer.compose_hybrid(llm_coro, static_body, timeout_sec=1.2)
            return {"text": final_text, "buttons": buttons}

        # 3. Product Search via Catalog & AI Gateway Recommendation
        try:
            matched_products = await CommerceCatalogService.search_products(DIGICORN_TENANT_ID, query=clean_text, limit=6)
        except Exception as e:
            logger.warning(f"Error searching products: {e}")
            matched_products = []

        if matched_products:
            prod_rows = []
            buttons = []
            for p in matched_products:
                prod_rows.append(f"• *[{p['product_code']}]* {p['title']}\n  📂 _{p['category']}_ — *Rp{p['price']:,}*")
                buttons.append([{"text": f"🛒 Beli {p['title'][:25]}", "callback_data": f"buy_{p['product_code']}"}])

            static_data = (
                f"🔎 *HASIL PENCARIAN PRODUK DIGITAL: \"{clean_text}\"*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                + "\n\n".join(prod_rows) +
                "\n\n━━━━━━━━━━━━━━━━━━━━\n"
                "👉 *Ketuk tombol di bawah untuk memesan langsung, atau ketik kata kunci lain.*"
            )

            llm_coro = ai_gateway.generate(
                user_message=f"Berikan 1 kalimat pendek kurasi/rekomendasi cerdas untuk pencarian produk digital '{clean_text}'.",
                context={"tenant": "digicorn", "query": clean_text}
            )

            final_text = await MessageComposer.compose_hybrid(llm_coro, static_data, timeout_sec=1.5)
            return {"text": final_text, "buttons": buttons}

        # 4. Fallback AI Assistant with Product Guidance
        fallback_prompt = (
            f"Anda adalah Asisten Virtual Cerdas Toko Produk Digital 'Digicorn'.\n"
            f"Pengguna menanyakan: '{clean_text}'\n"
            "Jawab ramah dalam 2-3 kalimat Bahasa Indonesia dan sarankan kategori yang tersedia di Digicorn:\n"
            "1. Template Excel Keuangan & Pembukuan\n"
            "2. Bundle 30.000+ Video Reels/Shorts Mentahan\n"
            "3. 10.000+ Template Canva Desain & Sosmed\n"
            "4. Template CV ATS Profesional\n"
            "5. Ultimate Notion Planner Bundle\n"
            "6. Template Presentasi PowerPoint Animatif\n"
            "7. Template Undangan Nikah Digital\n"
            "Semua produk berharga flat Rp5.000 dengan akses Google Drive instan."
        )

        ai_response = await ai_gateway.generate(user_message=fallback_prompt, context={"tenant": "digicorn"})
        if not ai_response:
            ai_response = (
                f"Maaf Kak{sapaan}, produk dengan kata kunci *'{clean_text}'* belum ditemukan di katalog saat ini.\n\n"
                "Coba ketik kata kunci umum seperti:\n"
                "• `excel` untuk template keuangan\n"
                "• `canva` untuk template desain\n"
                "• `video` untuk konten reels\n"
                "• `notion` untuk template produktivitas"
            )

        buttons = [
            [{"text": "📂 Buka Katalog Utama", "callback_data": "menu_catalog"}]
        ]
        return {"text": ai_response, "buttons": buttons}


digicorn_service = DigicornService()
