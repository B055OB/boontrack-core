"""app/services/whatsapp_menu_flow_service.py
Interactive Numbered Menu Conversation Flow for WhatsApp Gateway Growth.

Manages conversational state machine for:
* State tracking (idle, selecting_product, viewing_product, viewing_testimonials)
* Product listing by numbers (1, 2, 3...)
* Product detail inspection with action sub-menus (1. Testimoni, 2. Beli, 3. Kembali)
* Verified buyer testimonials with star ratings from Supabase DB
* Direct checkout link / Dynamic QRIS dispatch
* Seamless fallback to AI Knowledge Base for freeform questions
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
        """Fetches active products for the given merchant from real database / onboarding without mock fallback."""
        from app.services.whatsapp_service import get_tenant_products_from_db
        _, prods = get_tenant_products_from_db(tenant_slug)
        if prods and isinstance(prods, list) and len(prods) > 0:
            formatted = []
            for idx, p in enumerate(prods, 1):
                formatted.append({
                    "id": str(p.get("id") or f"prod-{idx}"),
                    "title": p.get("title") or p.get("name") or f"Produk {idx}",
                    "slug": p.get("slug") or f"produk-{idx}",
                    "price": float(p.get("promo_price") or p.get("price") or 50000),
                    "description": p.get("description") or p.get("short_description") or "Katalog produk resmi berkualitas.",
                    "benefits": p.get("benefits") or "Garansi resmi, materi berkualitas, dan dukungan pelanggan prioritas.",
                    "single_page_config": p.get("single_page_config"),
                    "metadata": p.get("metadata"),
                })
            return formatted
        return []

    def _normalize_testimonials(self, raw_list: List[Any]) -> List[Dict[str, Any]]:
        """Normalizes various testimonial schemas into unified rating, name, comment format."""
        normalized = []
        for item in raw_list:
            if isinstance(item, dict):
                name = item.get("name") or item.get("author") or item.get("user") or item.get("customer_name") or "Pelanggan Terverifikasi"
                comment = item.get("comment") or item.get("review") or item.get("quote") or item.get("text") or item.get("content") or ""
                if not comment or not str(comment).strip():
                    continue
                try:
                    rating = int(item.get("rating") or item.get("stars") or 5)
                except Exception:
                    rating = 5
                normalized.append({
                    "name": str(name).strip(),
                    "comment": str(comment).strip(),
                    "rating": min(max(rating, 1), 5),
                })
        return normalized[:5]

    def get_product_testimonials(
        self,
        tenant_slug: str,
        product_id: str,
        product_title: str,
        product_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Dynamically fetches verified testimonials/reviews from database:
        1. product_data.testimonials / single_page_config.testimonials / metadata.testimonials
        2. Supabase product record (single_page_config.testimonials or metadata.testimonials)
        3. Supabase tenant metadata.testimonials / metadata.reviews
        4. Supabase product_reviews table (if exists)
        Returns [] if no testimonials are configured in DB. Zero hardcoded mock fallback.
        """
        # 1. Cek langsung di product_data
        if product_data and isinstance(product_data, dict):
            spc = product_data.get("single_page_config") or {}
            if isinstance(spc, dict) and spc.get("testimonials"):
                t_list = spc.get("testimonials")
                if isinstance(t_list, list) and len(t_list) > 0:
                    norm = self._normalize_testimonials(t_list)
                    if norm:
                        return norm

            if product_data.get("testimonials") and isinstance(product_data.get("testimonials"), list):
                norm = self._normalize_testimonials(product_data.get("testimonials"))
                if norm:
                    return norm

            meta = product_data.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("testimonials") and isinstance(meta.get("testimonials"), list):
                norm = self._normalize_testimonials(meta.get("testimonials"))
                if norm:
                    return norm

        # 2. Cek di Supabase database (products, tenants, product_reviews)
        try:
            from app.services.whatsapp_service import get_supabase
            sb = get_supabase()
            if sb:
                clean_slug = (tenant_slug or "").strip().lower()
                # A. Cek tabel products jika ada product_id
                if product_id:
                    try:
                        p_res = sb.from_("products").select("single_page_config, metadata").eq("id", product_id).maybe_single().execute()
                        if p_res and p_res.data:
                            spc = p_res.data.get("single_page_config") or {}
                            if isinstance(spc, dict) and spc.get("testimonials"):
                                norm = self._normalize_testimonials(spc.get("testimonials"))
                                if norm:
                                    return norm
                            pmeta = p_res.data.get("metadata") or {}
                            if isinstance(pmeta, dict) and pmeta.get("testimonials"):
                                norm = self._normalize_testimonials(pmeta.get("testimonials"))
                                if norm:
                                    return norm
                    except Exception:
                        pass

                # B. Cek metadata tenant di Supabase
                if clean_slug:
                    try:
                        t_res = sb.from_("tenants").select("metadata").eq("slug", clean_slug).maybe_single().execute()
                        if t_res and t_res.data:
                            t_meta = t_res.data.get("metadata") or {}
                            if isinstance(t_meta, dict):
                                if t_meta.get("testimonials") and isinstance(t_meta.get("testimonials"), list):
                                    norm = self._normalize_testimonials(t_meta.get("testimonials"))
                                    if norm:
                                        return norm
                                if t_meta.get("reviews") and isinstance(t_meta.get("reviews"), list):
                                    norm = self._normalize_testimonials(t_meta.get("reviews"))
                                    if norm:
                                        return norm
                    except Exception:
                        pass

                # C. Cek tabel product_reviews jika ada
                try:
                    r_res = sb.from_("product_reviews").select("*").eq("tenant_slug", clean_slug).limit(5).execute()
                    if r_res and r_res.data and len(r_res.data) > 0:
                        norm = self._normalize_testimonials(r_res.data)
                        if norm:
                            return norm
                except Exception:
                    pass
        except Exception as _err:
            logger.warning(f"[TESTIMONIALS_QUERY_WARN] {_err}")

        return []

    def build_products_menu_message(self, tenant_slug: str) -> str:
        """Constructs numbered list of active products."""
        products = self.get_tenant_products(tenant_slug)
        if not products:
            clean_name = tenant_slug.replace("-", " ").replace("_", " ").title()
            return f"Saat ini katalog produk untuk *{clean_name}* sedang disiapkan oleh admin. Silakan hubungi kami untuk informasi lebih lanjut ya, Kak! 🙏"

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

    def build_testimonials_message(
        self,
        product_title: str,
        testimonials: List[Dict[str, Any]],
        product: Optional[Dict[str, Any]] = None,
        tenant_slug: Optional[str] = None,
    ) -> str:
        """
        Constructs buyer testimonials formatted with star ratings.
        If testimonials exist in DB: displays verified buyer reviews with stars.
        If NO testimonials in DB: constructs an elegant contextual message based on product benefits,
        NEVER showing fake ad course / ROAS claims!
        """
        if testimonials and len(testimonials) > 0:
            lines = [f"⭐ *Testimoni & Ulasan Pembeli untuk {product_title}:*\n"]
            for idx, item in enumerate(testimonials, 1):
                stars = "★" * item.get("rating", 5)
                name = item.get("name", "Pelanggan")
                comment = item.get("comment", "")
                lines.append(f"{idx}. {stars} - *{name}*: \"{comment}\"")

            lines.append("\nMau lanjut ke mana, Kak?")
            lines.append("*1.* Beli Sekarang | *2.* Kembali ke Daftar Produk\n")
            lines.append("Ketik *1* atau *2* untuk memilih.")
            return "\n".join(lines)

        # Fallback elegan jika belum ada ulasan tersimpan di DB
        benefit_text = ""
        if product and isinstance(product, dict):
            spc = product.get("single_page_config") or {}
            if isinstance(spc, dict) and spc.get("subheadline"):
                subh = str(spc.get("subheadline")).strip()
                if len(subh) > 10:
                    benefit_text = subh
            elif product.get("benefits"):
                b = str(product.get("benefits")).strip()
                if len(b) > 10 and "Jaminan garansi resmi toko" not in b:
                    benefit_text = b
            elif product.get("description"):
                d = str(product.get("description")).strip()
                first_line = d.split("\n")[0].strip()
                if len(first_line) > 15:
                    benefit_text = first_line

        if not benefit_text:
            benefit_text = "Produk ini dirancang dengan materi dan panduan terstruktur yang mengutamakan hasil nyata, kemudahan penerapan, dan kepuasan pelanggan."

        return (
            f"⭐ *Ulasan & Bukti Pembeli untuk {product_title}:*\n\n"
            f"Ulasan dan testimoni untuk produk ini sedang dihimpun oleh tim kami.\n\n"
            f"💡 *Keunggulan Utama Produk:*\n"
            f"{benefit_text}\n\n"
            f"Mau lanjut ke mana, Kak?\n"
            f"*1.* Beli Sekarang / Lanjut Pemesanan\n"
            f"*2.* Kembali ke Daftar Produk\n\n"
            f"Ketik *1* atau *2* untuk memilih, atau tanyakan langsung apa pun yang ingin Kakak ketahui tentang produk ini ya! 🙏"
        )

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
            selected_product = session.selected_product_data or (products[0] if products else {})
            if not selected_product:
                self.reset_session(tenant_slug, sender_phone)
                return "Katalog produk sedang disiapkan oleh admin toko kami."
            
            if clean_text == "1":
                # Sub-menu 1: Lihat Testimoni Pembeli
                logger.info(f"[{tenant_slug}:{sender_phone}] Submenu 1: Testimoni for '{selected_product.get('title', 'Produk')}'")
                testimonials = self.get_product_testimonials(
                    tenant_slug,
                    selected_product.get("id", ""),
                    selected_product.get("title", ""),
                    product_data=selected_product,
                )
                self.set_session_state(tenant_slug, sender_phone, state="viewing_testimonials")
                return self.build_testimonials_message(
                    selected_product.get("title", "Produk"),
                    testimonials,
                    product=selected_product,
                    tenant_slug=tenant_slug,
                )

            elif clean_text == "2":
                # Sub-menu 2: Masukkan Keranjang / Beli Sekarang
                logger.info(f"[{tenant_slug}:{sender_phone}] Submenu 2: Checkout for '{selected_product.get('title', 'Produk')}'")
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
            selected_product = session.selected_product_data or (products[0] if products else {})
            if not selected_product:
                self.reset_session(tenant_slug, sender_phone)
                return "Katalog produk sedang disiapkan oleh admin toko kami."

            if clean_text == "1":
                # Beli Sekarang
                logger.info(f"[{tenant_slug}:{sender_phone}] Testimonials option 1: Checkout '{selected_product.get('title', 'Produk')}'")
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
