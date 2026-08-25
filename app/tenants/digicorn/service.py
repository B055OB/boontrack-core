import os
import logging
from typing import Dict, Any, Optional, List

from app.tenants.digicorn.config import DIGICORN_CONFIG, DIGICORN_TENANT_ID
from app.modules.commerce.catalog import CommerceCatalogService
from app.modules.commerce.service import CommerceService
from app.modules.commerce.delivery import DigitalDeliveryService
from app.services.ai_service import ai_gateway
from app.services.reconciliation_service import generate_unique_payment_intent, PAYMENT_INTENTS
from app.core.messaging.composer import MessageComposer
from app.core.tenants.registry import tenant_registry
from app.core.channels.telegram import send_telegram_message

logger = logging.getLogger("DIGICORN_SERVICE")

QRIS_ASSET_PATH = "assets/qris.jpg"


class DigicornService:
    """Service pemrosesan pesan, katalog, dan pembayaran QRIS otomatis untuk tenant Digicorn."""

    @classmethod
    async def deliver_paid_order(cls, intent: Dict[str, Any]) -> bool:
        """
        Mengirimkan link akses Google Drive ke chat Telegram pembeli secara instan
        saat mutasi pembayaran berhasil dicocokkan oleh BoonTrack Reader.
        """
        chat_id = intent.get("user_id")
        product_code = intent.get("product_id")
        invoice_id = intent.get("invoice_id")
        total_amount = intent.get("total_amount", 5000)

        if not chat_id or not product_code:
            logger.error(f"[DIGICORN AUTO-DELIVERY] Invalid intent data for delivery: {intent}")
            return False

        try:
            product = await CommerceCatalogService.get_product_by_code(DIGICORN_TENANT_ID, product_code)
            delivery_payload = product.get("delivery_payload") if product else "https://drive.google.com"
            title = product.get("title") if product else "Produk Digital"

            delivery_msg = (
                f"🎉 *PEMBAYARAN DIVERIFIKASI! (Rp{total_amount:,})* 🚀\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🧾 *Invoice:* `{invoice_id}`\n"
                f"🏷️ *Produk:* {title}\n"
                f"📊 *Status:* LUNAS (Verified by BoonTrack Reader)\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📥 *LINK AKSES GOOGLE DRIVE RESMI ANDA:*\n"
                f"👉 {delivery_payload}\n\n"
                f"💡 *Petunjuk Penggunaan:*\n"
                f"1. Buka tautan Google Drive di atas.\n"
                f"2. Klik tombol *Download* atau *Make a Copy*.\n"
                f"3. Simpan di perangkat atau Google Drive pribadi Anda.\n\n"
                f"_Terima kasih telah berbelanja di Digicorn! Sukses terus untuk bisnis & karir Anda!_ 🦄✨"
            )

            bot_token = tenant_registry.get_telegram_token(DIGICORN_TENANT_ID)
            if bot_token:
                await send_telegram_message(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    text=delivery_msg
                )
                logger.info(f"[DIGICORN AUTO-DELIVERY] Successfully delivered {product_code} to Telegram chat {chat_id}")
                return True
            else:
                logger.error(f"[DIGICORN AUTO-DELIVERY] Bot token not found for {DIGICORN_TENANT_ID}")
                return False

        except Exception as e:
            logger.error(f"[DIGICORN AUTO-DELIVERY] Delivery failed for {invoice_id}: {e}", exc_info=True)
            return False

    @classmethod
    async def handle_message(
        cls,
        chat_id: int | str,
        user_text: str,
        callback_data: str = "",
        user_name: str = ""
    ) -> Dict[str, Any]:
        """
        Memproses pesan masuk Telegram untuk Digicorn:
        1. Routing intent menu / start
        2. Pencarian katalog produk digital
        3. Pembuatan Invoice QRIS Otomatis dengan 3 Digit Unik
        4. Cek status pembayaran & auto-delivery Google Drive
        """
        clean_text = (user_text or "").strip()
        sapaan = f", *{user_name}*" if user_name else ""

        # 1. Handling Callback / Button Click
        if callback_data:
            # 1.1. Pemesanan Produk -> Terbitkan QRIS + 3 Digit Unik
            if callback_data.startswith("buy_") or callback_data.startswith("pay_"):
                product_code = callback_data.replace("buy_", "").replace("pay_", "").strip()
                try:
                    product = await CommerceCatalogService.get_product_by_code(DIGICORN_TENANT_ID, product_code)
                    if product:
                        # Buat Payment Intent dengan 3 Digit Unik
                        base_price = int(product.get("price", 5000))
                        intent = generate_unique_payment_intent(
                            tenant_id=DIGICORN_TENANT_ID,
                            base_amount=base_price,
                            product_id=product_code,
                            user_id=str(chat_id)
                        )

                        invoice_caption = (
                            f"🦄 *INVOICE PEMBAYARAN QRIS DIGICORN* 📦\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"🏷️ *Produk:* {product['title']}\n"
                            f"📂 *Kategori:* {product['category']}\n"
                            f"🧾 *Invoice ID:* `{intent['invoice_id']}`\n\n"
                            f"💰 *TOTAL TRANSFER:* `Rp{intent['total_amount']:,}`\n"
                            f"*(Harga: Rp{base_price:,} + 3 Digit Unik: Rp{intent['unique_code']})*\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"⚠️ *PENTING: Mohon transfer TEPAT Rp{intent['total_amount']:,} agar sistem BoonTrack Reader otomatis memverifikasi pembayaran Anda.*\n\n"
                            f"📸 *Cara Bayar:*\n"
                            f"1. Scan gambar QRIS di atas via GoPay, OVO, Dana, ShopeePay, BCA, Mandiri, atau Mobile Banking lainnya.\n"
                            f"2. Masukkan nominal persis *Rp{intent['total_amount']:,}*.\n\n"
                            f"🚀 *Setelah transfer, sistem BoonTrack Reader akan mendeteksi mutasi dan langsung mengirimkan link Google Drive secara otomatis!*"
                        )

                        buttons = [
                            [{"text": "🔄 Cek Status Pembayaran", "callback_data": f"check_pay_{intent['invoice_id']}"}],
                            [{"text": "🔙 Batal / Menu Utama", "callback_data": "menu_catalog"}]
                        ]

                        return {
                            "photo": QRIS_ASSET_PATH,
                            "text": invoice_caption,
                            "buttons": buttons
                        }
                except Exception as e:
                    logger.warning(f"Error creating QRIS invoice for callback {callback_data}: {e}")

            # 1.2. Cek Status Pembayaran
            if callback_data.startswith("check_pay_"):
                inv_id = callback_data.replace("check_pay_", "").strip()
                intent = PAYMENT_INTENTS.get(inv_id)

                if intent and intent.get("status") == "PAID":
                    product = await CommerceCatalogService.get_product_by_code(DIGICORN_TENANT_ID, intent.get("product_id"))
                    delivery_payload = product.get("delivery_payload") if product else "https://drive.google.com"
                    title = product.get("title") if product else "Produk Digital"

                    delivery_msg = (
                        f"🎉 *PEMBAYARAN DIVERIFIKASI! TERIMA KASIH* 🚀\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 *Invoice:* `{inv_id}`\n"
                        f"🏷️ *Produk:* {title}\n"
                        f"💰 *Nominal:* Rp{intent.get('total_amount', 5000):,}\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📥 *LINK AKSES GOOGLE DRIVE PRODUK ANDA:*\n"
                        f"👉 {delivery_payload}\n\n"
                        f"💡 *Petunjuk:* Buka tautan di atas dan klik _Download_ atau _Make a Copy_ untuk menyimpan file Anda.\n\n"
                        f"_Sukses selalu untuk Anda bersama Digicorn!_ 🦄✨"
                    )
                    buttons = [
                        [{"text": "📂 Belanja Produk Lain", "callback_data": "menu_catalog"}]
                    ]
                    return {"text": delivery_msg, "buttons": buttons}

                else:
                    exp_amount = intent.get("total_amount", 5000) if intent else 5000
                    pending_msg = (
                        f"⏳ *PEMBAYARAN BELUM TERDETEKSI*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🧾 *Invoice ID:* `{inv_id}`\n"
                        f"💰 *Nominal Transfer:* `Rp{exp_amount:,}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"Sistem BoonTrack Reader belum menemukan mutasi masuk sebesar *Rp{exp_amount:,}*.\n\n"
                        f"⚠️ Pastikan transfer TEPAT sesuai nominal dengan 3 digit uniknya.\n"
                        f"Jika Anda baru saja transfer, mohon tunggu 10-30 detik lalu tekan tombol di bawah ini."
                    )
                    buttons = [
                        [{"text": "🔄 Cek Status Lagi", "callback_data": f"check_pay_{inv_id}"}],
                        [{"text": "🔙 Batal / Menu Utama", "callback_data": "menu_catalog"}]
                    ]
                    return {"text": pending_msg, "buttons": buttons}

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
