r"""
app/services/waba_sales_service.py

Layanan Context-Aware Customer Sales Conversation untuk WABA Resmi (+6285181830080).
Mengubah generic greeting menjadi percakapan penjualan kontekstual berbasis etalase storefront:
1. Mendeteksi pola regex: r"\(Ref:\s*([^#]+)#([^\)]+)\)" pada pesan masuk customer.
2. Mengambil data riil dari PostgreSQL: Nama Toko, Nama Produk, Harga Resmi, Deskripsi, Link Checkout.
3. Mengirimkan First Response natural dengan Quick Reply buttons [📚 Isi Produk], [💳 Cara Beli], [👨💼 Tanya Admin].
4. Mencatat atribusi percakapan ke waba_conversations (source='STOREFRONT').
5. Menangani percakapan lanjutan (Detail Isi, Harga, Checkout, Handover Admin) berdasarkan data riil DB.
"""

import re
import logging
import asyncio
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor

from app.core.database import get_db_connection
from app.services.whatsapp_service import normalize_phone_number
from app.services.whatsapp.cloud_api import send_whatsapp_buttons, send_whatsapp_text
from app.services.waba_conversation_service import record_waba_conversation

logger = logging.getLogger("WABA_SALES_SERVICE")

# Pola regex resmi untuk tag referensi storefront
STOREFRONT_REF_REGEX = re.compile(r"\(Ref:\s*([^#]+)#([^\)]+)\)", re.IGNORECASE)

# Quick Reply buttons resmi untuk Sales Conversation WABA
WABA_SALES_BUTTONS: List[Dict[str, str]] = [
    {"id": "btn_isi_produk", "title": "📚 Isi Produk"},
    {"id": "btn_cara_beli", "title": "💳 Cara Beli"},
    {"id": "btn_tanya_admin", "title": "👨💼 Tanya Admin"},
]

QUICK_REPLY_TEXT_FOOTER: str = (
    "\n\n━━━━━━━━━━━━━━━━━━━━\n"
    "Pilihan Cepat:\n"
    "[📚 Isi Produk]\n"
    "[💳 Cara Beli]\n"
    "[👨💼 Tanya Admin]"
)


def format_idr(amount: Any) -> str:
    """Format angka ke format Rupiah standar Indonesia (menggunakan pemisah titik)."""
    try:
        val = int(float(amount or 0))
        return f"{val:,}".replace(",", ".")
    except Exception:
        return "0"


def extract_storefront_ref(text: str) -> Optional[Tuple[str, str]]:
    """
    Ekstrak (tenant_slug, product_slug) dari teks pesan customer.
    Contoh masukan: 'Halo saya mau tanya (Ref: onlineboost#ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense)'
    Kembalian: ('onlineboost', 'ecourse-strategi-youtube-ai-metode-praktis-raih-pendapatan-adsense')
    """
    if not text or not isinstance(text, str):
        return None
    match = STOREFRONT_REF_REGEX.search(text)
    if match:
        t_slug = match.group(1).strip()
        p_slug = match.group(2).strip()
        if t_slug and p_slug:
            return t_slug, p_slug
    return None


def get_storefront_product_context(tenant_slug: str, product_slug: str) -> Optional[Dict[str, Any]]:
    """
    Mengambil data riil toko dan produk dari database PostgreSQL.
    Tabel: tenants & products.
    """
    clean_tenant = str(tenant_slug).strip().lower()
    clean_product = str(product_slug).strip().lower()

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT 
                t.id as tenant_id,
                t.name as tenant_name,
                t.slug as tenant_slug,
                t.metadata as tenant_metadata,
                p.id as product_id,
                p.title as product_title,
                p.slug as product_slug,
                p.price as product_price,
                p.promo_price as product_promo_price,
                p.description as product_description,
                p.category as product_category,
                p.image as product_image
            FROM tenants t
            JOIN products p ON p.tenant_id = t.id
            WHERE (LOWER(t.slug) = %s OR t.id::text = %s)
              AND (LOWER(p.slug) = %s OR p.id::text = %s OR LOWER(p.title) ILIKE %s)
            LIMIT 1;
        """, (clean_tenant, clean_tenant, clean_product, clean_product, f"%{clean_product}%"))
        row = cur.fetchone()
        cur.close()

        if row:
            data = dict(row)
            # Standarisasi storefront checkout url
            data["storefront_url"] = f"https://shop.boontrack.com/{data['tenant_slug']}/p/{data['product_slug']}"
            return data
        return None
    except Exception as exc:
        logger.error(f"[WABA_SALES] Gagal mengambil konteks produk DB ({tenant_slug}#{product_slug}): {exc}", exc_info=True)
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


class WabaSalesSessionManager:
    """
    Manajer sesi konteks percakapan penjualan customer WABA.
    Menyimpan context produk aktif per nomor pengirim agar percakapan lanjutan
    (misal: 'Isinya apa?', 'Harganya berapa?') dapat dijawab secara tepat konteks
    tanpa perlu customer menyertakan ulang tag (Ref: ...).
    """
    _sessions: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def set_context(cls, sender_phone: str, context: Dict[str, Any]) -> None:
        clean = normalize_phone_number(sender_phone) or sender_phone
        context["updated_at"] = datetime.now(timezone.utc)
        cls._sessions[clean] = context
        logger.info(f"[WABA_SALES_SESSION] Context saved for {clean}: product='{context.get('product_title')}'")

    @classmethod
    def get_context(cls, sender_phone: str) -> Optional[Dict[str, Any]]:
        clean = normalize_phone_number(sender_phone) or sender_phone
        ctx = cls._sessions.get(clean)
        if ctx:
            return ctx

        # Fallback database lookup dari waba_conversations jika in-memory kosong
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT wc.tenant_id, wc.product_id, wc.storefront_url,
                       t.name as tenant_name, t.slug as tenant_slug,
                       p.title as product_title, p.slug as product_slug,
                       p.price as product_price, p.promo_price as product_promo_price,
                       p.description as product_description
                FROM waba_conversations wc
                JOIN tenants t ON wc.tenant_id = t.id
                JOIN products p ON wc.product_id = p.id
                WHERE wc.wa_user_id = %s AND wc.source = 'STOREFRONT' AND wc.product_id IS NOT NULL
                ORDER BY wc.created_at DESC
                LIMIT 1;
            """, (clean,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                loaded = dict(row)
                cls._sessions[clean] = loaded
                return loaded
        except Exception as e:
            logger.debug(f"[WABA_SALES_SESSION] DB session lookup note: {e}")

        return None

    @classmethod
    def clear_context(cls, sender_phone: str) -> None:
        clean = normalize_phone_number(sender_phone) or sender_phone
        cls._sessions.pop(clean, None)


def build_context_aware_first_response(ctx: Dict[str, Any]) -> str:
    """
    Membangun first response natural sesuai arahan CTO:
    "Siap Kak! 👍 Saya lihat Kakak tertarik dengan [NAMA PRODUK] di [NAMA TOKO].
    Harga resmi: Rp [Harga Terformat]

    Saya bisa bantu jelaskan detail materi/isi produk, harga, atau cara belinya. Mau yang mana Kak? 😊"
    """
    product_name = ctx.get("product_title") or "Produk Pilihan"
    store_name = ctx.get("tenant_name") or "Toko Resmi"
    
    # Ambil harga resmi dari DB
    price = ctx.get("product_price") or ctx.get("product_promo_price") or 0
    formatted_price = format_idr(price)

    return (
        f"Siap Kak! 👍 Saya lihat Kakak tertarik dengan *{product_name}* di *{store_name}*.\n"
        f"Harga resmi: Rp {formatted_price}\n\n"
        f"Saya bisa bantu jelaskan detail materi/isi produk, harga, atau cara belinya. Mau yang mana Kak? 😊"
        f"{QUICK_REPLY_TEXT_FOOTER}"
    )


def build_product_detail_response(ctx: Dict[str, Any]) -> str:
    """Membangun respons detail isi / materi produk dari database."""
    product_name = ctx.get("product_title") or "Produk Pilihan"
    description = ctx.get("product_description") or "Materi dan panduan eksklusif langsung dari merchant resmi."
    price = ctx.get("product_price") or ctx.get("product_promo_price") or 0
    formatted_price = format_idr(price)
    checkout_url = ctx.get("storefront_url") or f"https://shop.boontrack.com/{ctx.get('tenant_slug')}/p/{ctx.get('product_slug')}"

    return (
        f"📚 *DETAIL & ISI PRODUK*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"*{product_name}*\n\n"
        f"📝 *Ringkasan Materi / Manfaat:*\n"
        f"{description.strip()}\n\n"
        f"💰 *Harga Resmi:* Rp {formatted_price}\n"
        f"🔗 *Tautan Checkout Langsung:*\n"
        f"{checkout_url}\n\n"
        f"Mau langsung beli sekarang atau ada hal lain yang ingin Kakak tanyakan? 😊"
        f"{QUICK_REPLY_TEXT_FOOTER}"
    )


def build_price_and_checkout_response(ctx: Dict[str, Any]) -> str:
    """Membangun respons harga dan tautan checkout resmi dari database."""
    product_name = ctx.get("product_title") or "Produk Pilihan"
    price = ctx.get("product_price") or ctx.get("product_promo_price") or 0
    formatted_price = format_idr(price)
    checkout_url = ctx.get("storefront_url") or f"https://shop.boontrack.com/{ctx.get('tenant_slug')}/p/{ctx.get('product_slug')}"

    return (
        f"💳 *INFORMASI HARGA & CARA PEMBELIAN*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Harga resmi untuk *{product_name}* adalah *Rp {formatted_price}* Kak! 🏷️\n\n"
        f"Untuk melakukan pemesanan dan checkout langsung secara aman, silakan klik tautan resmi berikut:\n"
        f"👉 {checkout_url}\n\n"
        f"Setelah transaksi selesai, pesanan/akses produk Kakak akan langsung diproses dan dikirimkan secara otomatis.\n"
        f"Ada yang ingin dibantu lagi Kak? 😊"
        f"{QUICK_REPLY_TEXT_FOOTER}"
    )


def build_admin_handover_response(ctx: Dict[str, Any]) -> str:
    """Membangun respons pengalihan ke admin / representatif toko."""
    store_name = ctx.get("tenant_name") or "Toko Resmi"
    return (
        f"Siap Kak! Pertanyaan Kakak telah kami teruskan ke representatif resmi *{store_name}*. "
        f"Tim admin kami akan segera membantu Kakak secara langsung di sini. Mohon ditunggu ya Kak! 👨💼"
    )


async def send_waba_sales_reply(
    to_phone: str,
    message_text: str,
    phone_number_id: str = "1365010890024026",
    buttons: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """Mengirim balasan sales WABA menggunakan tombol Quick Reply interaktif atau teks fallback."""
    clean_phone = normalize_phone_number(to_phone) or to_phone
    active_buttons = buttons if buttons is not None else WABA_SALES_BUTTONS

    # 1. Coba kirim via send_whatsapp_buttons
    try:
        res = await send_whatsapp_buttons(
            to_phone=clean_phone,
            body_text=message_text,
            buttons=active_buttons,
            header_text="BoonTrack Storefront Assistant",
            footer_text="BoonTrack Official WABA",
            tenant_id="shop",
            phone_number_id=phone_number_id,
        )
        if res:
            logger.info(f"[WABA_SALES] Quick reply buttons sent to {clean_phone}")
            return True
    except Exception as btn_err:
        logger.debug(f"[WABA_SALES] Button dispatch note: {btn_err}, trying text fallback...")

    # 2. Fallback text
    try:
        res_text = await send_whatsapp_text(
            to_phone=clean_phone,
            text=message_text,
            tenant_id="shop",
            phone_number_id=phone_number_id,
        )
        if res_text:
            logger.info(f"[WABA_SALES] Text fallback sent to {clean_phone}")
            return True
    except Exception as txt_err:
        logger.error(f"[WABA_SALES] Error dispatching reply: {txt_err}", exc_info=True)

    return False


async def handle_waba_storefront_sales_inbound(
    sender_phone: str,
    incoming_text: str,
    phone_number_id: str = "1365010890024026",
    raw_msg: Optional[Dict[str, Any]] = None,
    trace: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Handler utama untuk alur percakapan penjualan kontekstual etalase (Storefront Context Sales).
    
    Mengembalikan dict dengan key 'handled': True jika berhasil ditangani,
    atau None / {'handled': False} jika pesan bukan bagian dari konteks etalase.
    """
    clean_phone = normalize_phone_number(sender_phone) or sender_phone
    raw_text = str(incoming_text or "").strip()
    lower_text = raw_text.lower()

    # Ekstrak button_id jika pesan berasal dari event klik tombol interaktif Meta
    btn_id = ""
    if raw_msg and isinstance(raw_msg, dict):
        if raw_msg.get("type") == "interactive":
            btn_id = str(raw_msg.get("interactive", {}).get("button_reply", {}).get("id") or "").strip().lower()
        elif raw_msg.get("type") == "button":
            btn_id = str(raw_msg.get("button", {}).get("payload") or "").strip().lower()

    def _log(step: str, detail: str):
        if trace and hasattr(trace, "log_step"):
            trace.log_step(step, detail)
        logger.info(f"[WABA_SALES] [{step}] {detail}")

    # =========================================================================
    # KASUS 1: Pesan Masuk Membawa Tag Referensi (Ref: tenant_slug#product_slug)
    # =========================================================================
    ref_match = extract_storefront_ref(raw_text)
    if ref_match:
        tenant_slug, product_slug = ref_match
        _log("RefTagDetected", f"Extracted tenant='{tenant_slug}', product='{product_slug}'")

        ctx = get_storefront_product_context(tenant_slug, product_slug)
        if ctx:
            # Simpan sesi konteks aktif
            WabaSalesSessionManager.set_context(clean_phone, ctx)

            # Susun first response natural
            first_reply = build_context_aware_first_response(ctx)

            # Kirim balasan via WABA resmi (+6285181830080)
            await send_waba_sales_reply(
                to_phone=clean_phone,
                message_text=first_reply,
                phone_number_id=phone_number_id,
                buttons=WABA_SALES_BUTTONS,
            )

            # Catat atribusi percakapan ke waba_conversations
            try:
                await record_waba_conversation(
                    wa_user_id=clean_phone,
                    source="STOREFRONT",
                    tenant_id=str(ctx.get("tenant_id")) if ctx.get("tenant_id") else None,
                    product_id=str(ctx.get("product_id")) if ctx.get("product_id") else None,
                    storefront_url=ctx.get("storefront_url"),
                )
            except Exception as e:
                logger.warning(f"[WABA_SALES] Failed to record conversation attribution: {e}")

            res = {
                "status": "success",
                "handled": True,
                "lane": "STOREFRONT_CONTEXT_SALES",
                "action": "context_aware_first_response",
                "product_slug": ctx.get("product_slug"),
                "tenant_slug": ctx.get("tenant_slug"),
                "reply": first_reply,
            }
            if trace:
                trace.early_return = True
                trace.response_status = 200
                trace.response_payload = res
            return res
        else:
            _log("RefTagNotFoundInDB", f"Product or tenant not found for '{tenant_slug}#{product_slug}'")

    # =========================================================================
    # KASUS 2: Pesan Lanjutan dari Pelanggan yang Memiliki Konteks Produk Aktif
    # =========================================================================
    active_ctx = WabaSalesSessionManager.get_context(clean_phone)
    if active_ctx:
        # A. Tanya Isi / Detail Materi Produk (btn_isi_produk atau keyword isi/materi/detail)
        is_detail_inquiry = (
            btn_id == "btn_isi_produk"
            or "btn_isi_produk" in lower_text
            or any(kw in lower_text for kw in ["isi produk", "isi materi", "isinya apa", "apa isinya", "detail", "materi", "penjelasan", "kurikulum", "manfaat"])
        )
        if is_detail_inquiry:
            _log("FollowUpDetail", f"Customer {clean_phone} asking for product details")
            reply = build_product_detail_response(active_ctx)
            await send_waba_sales_reply(
                to_phone=clean_phone,
                message_text=reply,
                phone_number_id=phone_number_id,
                buttons=[
                    {"id": "btn_cara_beli", "title": "💳 Cara Beli"},
                    {"id": "btn_tanya_admin", "title": "👨💼 Tanya Admin"},
                ],
            )
            return {
                "status": "success",
                "handled": True,
                "lane": "STOREFRONT_CONTEXT_SALES",
                "action": "product_detail_response",
                "reply": reply,
            }

        # B. Tanya Harga / Cara Beli / Checkout (btn_cara_beli atau keyword harga/beli/checkout)
        is_checkout_inquiry = (
            btn_id == "btn_cara_beli"
            or "btn_cara_beli" in lower_text
            or any(kw in lower_text for kw in ["cara beli", "cara pesan", "harganya berapa", "berapa harganya", "harga", "beli", "checkout", "order", "mau bayar", "bayar"])
        )
        if is_checkout_inquiry:
            _log("FollowUpPriceCheckout", f"Customer {clean_phone} asking for price/checkout")
            reply = build_price_and_checkout_response(active_ctx)
            await send_waba_sales_reply(
                to_phone=clean_phone,
                message_text=reply,
                phone_number_id=phone_number_id,
                buttons=[
                    {"id": "btn_isi_produk", "title": "📚 Isi Produk"},
                    {"id": "btn_tanya_admin", "title": "👨💼 Tanya Admin"},
                ],
            )
            return {
                "status": "success",
                "handled": True,
                "lane": "STOREFRONT_CONTEXT_SALES",
                "action": "price_and_checkout_response",
                "reply": reply,
            }

        # C. Tanya Admin (btn_tanya_admin atau keyword admin/cs/operator)
        is_admin_inquiry = (
            btn_id == "btn_tanya_admin"
            or "btn_tanya_admin" in lower_text
            or any(kw in lower_text for kw in ["tanya admin", "hubungi admin", "bicara admin", "cs toko"])
        )
        if is_admin_inquiry:
            _log("FollowUpAdminHandover", f"Customer {clean_phone} requesting admin handover")
            reply = build_admin_handover_response(active_ctx)
            await send_waba_sales_reply(
                to_phone=clean_phone,
                message_text=reply,
                phone_number_id=phone_number_id,
                buttons=[],
            )
            return {
                "status": "success",
                "handled": True,
                "lane": "STOREFRONT_CONTEXT_SALES",
                "action": "admin_handover_response",
                "reply": reply,
            }

    # Bukan pesan storefront context sales -> serahkan ke jalur selanjutnya (fallback protection)
    return None
