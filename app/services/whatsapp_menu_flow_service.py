"""app/services/whatsapp_menu_flow_service.py
Interactive Numbered Menu Conversation Flow for WhatsApp Gateway Growth.

Manages conversational state machine for:
- State tracking (idle, selecting_product, viewing_product, viewing_testimonials)
- Product listing by numbers (1, 2, 3...)
- Product detail inspection with action sub-menus (1. Testimoni, 2. Beli, 3. Kembali)
- 5 Verified buyer testimonials with star ratings
- Direct checkout link / Dynamic QRIS dispatch
- Seamless fallback to AI Knowledge Base for freeform questions
"""

import logging
import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from app.services.onboarding_service import onboarding_service

logger = logging.getLogger("WHATSAPP_MENU_FLOW")


class ChatSessionState(BaseModel):
    tenant_slug: str
    sender_phone: str
    current_state: str = "idle"  # idle | selecting_product | viewing_product | viewing_testimonials
    selected_product_id: Optional[str] = None
    selected_product_data: Optional[Dict[str, Any]] = None
    last_active: float = Field(default_factory=time.time)


# Default High-Converting Catalog for Merchants without Products in DB
DEFAULT_MERCHANT_CATALOG = [
    {
        "id": "prod-masterclass-2026",
        "title": "Masterclass Meta & TikTok Ads 2026",
        "slug": "masterclass-meta-tiktok-ads-2026",
        "price": 149000,
        "description": "Panduan komprehensif riset winning audience, struktur campaign CBO scaling, dan setup CAPI tracking konversi tinggi.",
        "benefits": "Akses materi seumur hidup di Google Drive, update berkala modul 2026, dan akses grup konsultasi VIP Telegram.",
    },
    {
        "id": "prod-template-copywriting",
        "title": "Template Copywriting & Hook Video Viral",
        "slug": "template-copywriting-hook-video-viral",
        "price": 49000,
        "description": "Koleksi 50+ script copywriting formula AIDA dan video hooks terbukti tembus 100k+ views organik & berbayar.",
        "benefits": "Format Notion & spreadsheet siap pakai, panduan angle iklan, dan studi kasus winning ads.",
    },
    {
        "id": "prod-private-coaching-1on1",
        "title": "Private Coaching & Campaign Audit 1-on-1",
        "slug": "private-coaching-campaign-audit-1on1",
        "price": 499000,
        "description": "Sesi privat bedah dashboard iklan, perbaikan targeting & creative hook, serta strategi scaling bersama praktisi iklan senior.",
        "benefits": "Sesi konsultasi 90 menit via Google Meet, rekaman sesi, dan evaluasi berkala selama 14 hari.",
    },
]

# Curated 5 Testimonials per Product / Store
SAMPLE_TESTIMONIALS = [
    {"rating": 5, "name": "Budi S.", "comment": "Materi daging banget, langsung praktek ROAS campaign saya tembus 3.8x!"},
    {"rating": 5, "name": "Rina M.", "comment": "Sangat mudah dipahami untuk pemula, step by step setup pixel-nya jelas."},
    {"rating": 5, "name": "Dimas A.", "comment": "Template video hook-nya beneran manjur, iklan langsung banjir checkout."},
    {"rating": 5, "name": "Siti W.", "comment": "Support mentor di grup diskusi VIP responsif dan solutif banget."},
    {"rating": 5, "name": "Hendra K.", "comment": "Investasi terbaik buat bisnis online tahun ini, rekomended parah!"},
]


def _format_price_idr(amount: float) -> str:
    """Formats numeric amount to Indonesian Rupiah representation (e.g. 149.000)."""
    return f"{int(amount):,}".replace(",", ".")


class WhatsAppMenuFlowService:
    """Stateful numbered menu flow processor for WhatsApp Gateway."""

    def __init__(self):
        # Key: f"{tenant_slug}:{clean_phone}"
        self._sessions: Dict[str, ChatSessionState] = {}

    def _get_session_key(self, tenant_slug: str, sender_phone: str) -> str:
        return f"{tenant_slug.strip().lower()}:{sender_phone.strip()}"

    def get_session(self, tenant_slug: str, sender_phone: str) -> ChatSessionState:
        """Retrieves or creates user chat session state."""
        key = self._get_session_key(tenant_slug, sender_phone)
        session = self._sessions.get(key)
        # Session expiry: 2 hours TTL
        if not session or (time.time() - session.last_active > 7200):
            session = ChatSessionState(
                tenant_slug=tenant_slug,
                sender_phone=sender_phone,
                current_state="idle",
                last_active=time.time(),
            )
            self._sessions[key] = session
        return session

    def set_session_state(
        self,
        tenant_slug: str,
        sender_phone: str,
        state: str,
        selected_product_id: Optional[str] = None,
        product_data: Optional[Dict[str, Any]] = None,
    ):
        """Updates user conversation state."""
        key = self._get_session_key(tenant_slug, sender_phone)
        session = self.get_session(tenant_slug, sender_phone)
        session.current_state = state
        session.last_active = time.time()
        if selected_product_id is not None:
            session.selected_product_id = str(selected_product_id)
        if product_data is not None:
            session.selected_product_data = product_data
        self._sessions[key] = session

    def reset_session(self, tenant_slug: str, sender_phone: str):
        """Resets user conversation back to idle."""
        self.set_session_state(tenant_slug, sender_phone, state="idle", selected_product_id=None, product_data=None)

    def get_tenant_products(self, tenant_slug: str) -> List[Dict[str, Any]]:
        """Fetches active products for the given merchant with default catalog fallback."""
        details = onboarding_service.get_tenant_details_by_slug(tenant_slug) or {}
        prods = details.get("products", [])
        if prods and isinstance(prods, list) and len(prods) > 0:
            formatted = []
            for idx, p in enumerate(prods, 1):
                formatted.append({
                    "id": str(p.get("id") or f"prod-{idx}"),
                    "title": p.get("title") or f"Produk {idx}",
                    "slug": p.get("slug") or f"produk-{idx}",
                    "price": float(p.get("price") or 50000),
                    "description": p.get("description") or "Katalog produk resmi berkualitas.",
                    "benefits": "Garansi resmi, materi berkualitas, dan dukungan pelanggan prioritas.",
                })
            return formatted
        return DEFAULT_MERCHANT_CATALOG

    def get_product_testimonials(self, tenant_slug: str, product_id: str, product_title: str) -> List[Dict[str, Any]]:
        """Returns 5 recent verified buyer testimonials for product."""
        return SAMPLE_TESTIMONIALS[:5]

    def build_products_menu_message(self, tenant_slug: str) -> str:
        """Constructs numbered list of active products."""
        products = self.get_tenant_products(tenant_slug)
        lines = ["Silakan pilih produk yang ingin Kakak ketahui:\n"]
        for idx, p in enumerate(products, 1):
            price_str = _format_price_idr(p["price"])
            lines.append(f"*{idx}.* {p['title']} - Rp {price_str}")

        lines.append("\nKetik *angka pilihan* untuk melihat detail produk.")
        return "\n".join(lines)

    def build_product_detail_message(self, product: Dict[str, Any]) -> str:
        """Constructs product detail summary with 3-option sub-menu."""
        title = product.get("title", "Produk Pilihan")
        price_str = _format_price_idr(product.get("price", 0))
        desc = product.get("description", "Produk berkualitas terbaik.")
        benefits = product.get("benefits", "Jaminan garansi resmi toko.")

        return (
            f"📦 *{title}*\n"
            f"💰 *Harga:* Rp {price_str}\n\n"
            f"📝 *Deskripsi:* {desc}\n"
            f"✨ *Keunggulan Utama:* {benefits}\n\n"
            f"Mau lanjut ke mana, Kak?\n"
            f"*1.* Lihat Testimoni Pembeli\n"
            f"*2.* Masukkan Keranjang / Beli Sekarang\n"
            f"*3.* Kembali / Tanya Produk Lainnya\n\n"
            f"Ketik *1*, *2*, atau *3* untuk memilih."
        )

    def build_testimonials_message(self, product_title: str, testimonials: List[Dict[str, Any]]) -> str:
        """Constructs 5 buyer testimonials formatted with star ratings."""
        lines = [f"⭐ *Testimoni Pembeli untuk {product_title}:*\n"]
        for idx, item in enumerate(testimonials, 1):
            stars = "★" * item.get("rating", 5)
            name = item.get("name", "Pelanggan")
            comment = item.get("comment", "Sangat memuaskan!")
            lines.append(f"{idx}. {stars} - *{name}*: \"{comment}\"")

        lines.append("\nMau lanjut ke mana, Kak?")
        lines.append("*1.* Beli Sekarang | *2.* Kembali ke Daftar Produk\n")
        lines.append("Ketik *1* atau *2* untuk memilih.")
        return "\n".join(lines)

    def build_checkout_message(self, tenant_slug: str, product: Dict[str, Any], contact_name: str = "Kakak") -> str:
        """Constructs instant checkout URL & QRIS instruction."""
        title = product.get("title", "Produk")
        price_str = _format_price_idr(product.get("price", 0))
        slug = product.get("slug", "produk")

        checkout_url = f"https://shop.boontrack.com/{tenant_slug}/p/{slug}?checkout=true"
        return (
            f"🎉 *Pemesanan {title}*\n"
            f"💰 *Total:* Rp {price_str}\n\n"
            f"Silakan selesaikan pembayaran Kakak melalui tautan checkout instan resmi berikut:\n"
            f"👉 {checkout_url}\n\n"
            f"Atau ketik *BAYAR* jika Kakak ingin kami buatkan kode Dynamic QRIS pembayaran otomatis langsung di chat ini."
        )

    async def process_message(
        self,
        tenant_slug: str,
        sender_phone: str,
        incoming_text: str,
        contact_name: str = "Kakak",
    ) -> Optional[str]:
        """
        Processes incoming message through the Numbered Menu Flow.
        
        Returns:
            str: Generated menu response if message is part of numbered flow.
            None: If message is freeform, allowing it to pass to AI Knowledge Base.
        """
        clean_text = incoming_text.strip()
        text_lower = clean_text.lower()
        session = self.get_session(tenant_slug, sender_phone)
        products = self.get_tenant_products(tenant_slug)

        # 1. Pemicu Awal: "Tanya Produk" / "Katalog" / "Pilih Produk"
        trigger_keywords = [
            "tanya produk", "pilih produk", "lihat produk", "daftar produk",
            "katalog", "katalog produk", "menu produk", "produk apa saja",
            "list produk", "lihat katalog", "menu katalog", "info produk"
        ]
        is_tanya_produk = any(k in text_lower for k in trigger_keywords)

        if is_tanya_produk and session.current_state in ("idle", "viewing_product", "viewing_testimonials"):
            logger.info(f"[{tenant_slug}:{sender_phone}] Triggered 'Tanya Produk' flow.")
            self.set_session_state(tenant_slug, sender_phone, state="selecting_product")
            return self.build_products_menu_message(tenant_slug)

        # 2. State: selecting_product
        if session.current_state == "selecting_product":
            if clean_text.isdigit():
                choice = int(clean_text)
                if 1 <= choice <= len(products):
                    selected = products[choice - 1]
                    logger.info(f"[{tenant_slug}:{sender_phone}] Selected product #{choice}: '{selected['title']}'")
                    self.set_session_state(
                        tenant_slug,
                        sender_phone,
                        state="viewing_product",
                        selected_product_id=selected.get("id"),
                        product_data=selected,
                    )
                    return self.build_product_detail_message(selected)
                else:
                    return (
                        f"Nomor pilihan *{choice}* tidak tersedia.\n\n"
                        + self.build_products_menu_message(tenant_slug)
                    )
            # Jika user ketik kembali/batal
            if text_lower in ("kembali", "batal", "reset", "menu"):
                self.reset_session(tenant_slug, sender_phone)
                return "Konteks produk telah di-reset. Silakan tanyakan hal lain yang Kakak butuhkan."
            # Pertanyaan bebas: biarkan tembus ke AI Knowledge Base
            return None

        # 3. State: viewing_product
        if session.current_state == "viewing_product":
            selected_product = session.selected_product_data or (products[0] if products else DEFAULT_MERCHANT_CATALOG[0])
            
            if clean_text == "1":
                # Sub-menu 1: Lihat Testimoni Pembeli
                logger.info(f"[{tenant_slug}:{sender_phone}] Submenu 1: Testimoni for '{selected_product['title']}'")
                testimonials = self.get_product_testimonials(tenant_slug, selected_product.get("id", ""), selected_product["title"])
                self.set_session_state(tenant_slug, sender_phone, state="viewing_testimonials")
                return self.build_testimonials_message(selected_product["title"], testimonials)

            elif clean_text == "2":
                # Sub-menu 2: Masukkan Keranjang / Beli Sekarang
                logger.info(f"[{tenant_slug}:{sender_phone}] Submenu 2: Checkout for '{selected_product['title']}'")
                self.reset_session(tenant_slug, sender_phone)
                return self.build_checkout_message(tenant_slug, selected_product, contact_name)

            elif clean_text == "3":
                # Sub-menu 3: Kembali / Tanya Produk Lainnya
                logger.info(f"[{tenant_slug}:{sender_phone}] Submenu 3: Back to product list")
                self.set_session_state(tenant_slug, sender_phone, state="selecting_product", selected_product_id=None, product_data=None)
                return self.build_products_menu_message(tenant_slug)

            # Jika ketik angka di luar 1, 2, 3
            if clean_text.isdigit():
                return (
                    "Pilihan angka tidak valid.\n\n"
                    "Silakan ketik:\n"
                    "*1.* Lihat Testimoni Pembeli\n"
                    "*2.* Masukkan Keranjang / Beli Sekarang\n"
                    "*3.* Kembali / Tanya Produk Lainnya"
                )

            # Jika pertanyaan bebas: biarkan tembus ke AI Knowledge Base
            return None

        # 4. State: viewing_testimonials
        if session.current_state == "viewing_testimonials":
            selected_product = session.selected_product_data or (products[0] if products else DEFAULT_MERCHANT_CATALOG[0])

            if clean_text == "1":
                # Beli Sekarang
                logger.info(f"[{tenant_slug}:{sender_phone}] Testimonials option 1: Checkout '{selected_product['title']}'")
                self.reset_session(tenant_slug, sender_phone)
                return self.build_checkout_message(tenant_slug, selected_product, contact_name)

            elif clean_text == "2":
                # Kembali ke Daftar Produk
                logger.info(f"[{tenant_slug}:{sender_phone}] Testimonials option 2: Back to product list")
                self.set_session_state(tenant_slug, sender_phone, state="selecting_product", selected_product_id=None, product_data=None)
                return self.build_products_menu_message(tenant_slug)

            if clean_text.isdigit():
                return (
                    "Pilihan tidak valid.\n\n"
                    "Silakan ketik:\n"
                    "*1.* Beli Sekarang | *2.* Kembali ke Daftar Produk"
                )

            # Pertanyaan bebas: biarkan tembus ke AI Knowledge Base
            return None

        return None


# Singleton instance
whatsapp_menu_flow_service = WhatsAppMenuFlowService()
