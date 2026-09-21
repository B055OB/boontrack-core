import random
"""
app/services/whatsapp/commerce.py
--------------------------------------
Logika commerce: katalog produk, keranjang belanja,
checkout QRIS, dan fungsi generate QR code image.
"""
import io
import logging
import uuid
from typing import Optional, Dict, Any, List, Tuple

from app.services.whatsapp.credentials import (
    normalize_phone_number,
    user_cart_sessions,
    user_session_states,
    get_supabase,
)
from app.services.whatsapp.cloud_api import send_whatsapp_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Buy-intent detection
# ---------------------------------------------------------------------------

BUY_INTENTS = {
    "ya", "mau", "ya mau", "boleh", "ya boleh", "daftar", "beli", "pesan", "bayar", "transfer", "qris", "checkout", "lanjut",
    "mau daftar", "mau beli", "mau pesan", "mau bayar", "buatkan qris", "minta qris", "kirim qris",
    "daftar sekarang", "beli sekarang", "pesan sekarang", "gas", "ok", "oke", "deal", "setuju", "siap", "order", "mau dong", "boleh dong",
    "beli & bayar qris", "bayar qris", "btn_buy_now", "btn_checkout_cart"
}


def is_closing_buy_intent(text: str, button_id: Optional[str] = None) -> bool:
    clean_btn = str(button_id or "").strip().lower()
    if clean_btn in {"btn_buy_now", "buy_now", "order_now", "qris_buy", "beli_qris", "btn_checkout_cart"} or clean_btn.startswith("prod_"):
        return True

    clean = (text or "").strip().lower()
    if clean in BUY_INTENTS:
        return True
    tokens = set(clean.split())
    if any(intent in tokens for intent in {"beli", "pesan", "bayar", "qris", "checkout", "daftar", "order"}):
        return True
    if any(phrase in clean for phrase in ["buatkan qris", "minta qris", "kirim qris", "mau bayar", "mau daftar", "mau beli", "beli & bayar qris", "bayar qris", "ya boleh"]):
        return True
    return False


# ---------------------------------------------------------------------------
# QRIS image
# ---------------------------------------------------------------------------

def generate_qris_image_bytes(qr_string: str) -> bytes:
    """Renders QR code PNG directly from raw QRIS string."""
    if not qr_string or not isinstance(qr_string, str):
        return b""
    try:
        import qrcode
        from PIL import Image
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(qr_string.strip())
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        if hasattr(img, "size") and (img.size[0] < 500 or img.size[1] < 500):
            img = img.resize((540, 540), Image.Resampling.NEAREST)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.error(f"[QR Image Render Error] Failed to generate PNG from qr_string: {e}")
        return b""


# ---------------------------------------------------------------------------
# Product catalogue helpers
# ---------------------------------------------------------------------------

def get_tenant_products_from_db(tenant_slug: str) -> Tuple[str, List[Dict[str, Any]]]:
    from app.services.onboarding_service import onboarding_service

    clean_slug = str(tenant_slug or "").strip().lower()
    if not clean_slug:
        return "Toko Baru", []

    candidate_slugs = [
        clean_slug,
        clean_slug.replace("_", "-"),
        clean_slug.replace("-", "_"),
    ]

    details = onboarding_service.get_tenant_details_by_slug(clean_slug) or {}
    store_name = details.get("tenant", {}).get("name") or clean_slug.replace("-", " ").replace("_", " ").title()
    products = details.get("products", [])

    if not products:
        supabase = get_supabase()
        if supabase:
            try:
                t_id = None
                try:
                    t_res = supabase.table("tenants").select("id, name, slug").in_("slug", candidate_slugs).execute()
                    if t_res.data:
                        t_id = t_res.data[0].get("id")
                        store_name = t_res.data[0].get("name") or store_name
                except Exception as te:
                    logger.debug(f"[TENANT RESOLVE ERROR] {te}")

                if t_id:
                    try:
                        p_res = supabase.table("products").select("*").eq("tenant_id", t_id).execute()
                        if p_res.data:
                            products = [p for p in p_res.data if p.get("is_available") is not False]
                    except Exception as pe:
                        logger.debug(f"[PRODUCTS BY TENANT_ID ERROR] {pe}")

                if not products:
                    try:
                        p_res2 = supabase.table("products").select("*").in_("tenant_slug", candidate_slugs).execute()
                        if p_res2.data:
                            products = [p for p in p_res2.data if p.get("is_available") is not False]
                    except Exception:
                        pass

                if not products:
                    try:
                        cp_res = supabase.table("commerce_products").select("*").in_("tenant_slug", candidate_slugs).execute()
                        if cp_res.data:
                            products = [p for p in cp_res.data if p.get("is_available") is not False]
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[DB PRODUCTS FETCH ERROR] {e}")

    # Mengikuti urutan produk murni dari database Supabase (Zero Hardcoding Policy)

    return store_name, products


def build_tenant_catalog_sections(tenant_slug: str) -> Tuple[str, List[Dict[str, Any]]]:
    store_name, products = get_tenant_products_from_db(tenant_slug)

    if not products:
        body_text = f"Saat ini katalog produk untuk *{store_name}* sedang disiapkan oleh admin. Silakan hubungi customer support kami untuk informasi lebih lanjut ya, Kak! 🙏"
        return body_text, []

    rows = []
    for p in products[:10]:
        p_id = str(p.get("id", "prod_1"))
        if not p_id.startswith("prod_"):
            p_id = f"prod_{p_id}"

        p_title = str(p.get("title") or p.get("name") or "Produk")[:24]
        price_num = int(float(p.get("promo_price") or p.get("price") or 0))
        price_fmt = f"Rp {price_num:,}".replace(",", ".")
        raw_desc = str(p.get("description") or p.get("short_description") or "")
        desc_text = f"{price_fmt} • {raw_desc}" if raw_desc else price_fmt

        rows.append({
            "id": p_id,
            "title": p_title,
            "description": desc_text[:72]
        })

    sections = [{
        "title": f"Katalog {store_name}"[:24],
        "rows": rows
    }]
    body_text = f"Pilih produk dari *{store_name}* di bawah ini untuk melihat rincian atau checkout langsung:"
    return body_text, sections


async def send_whatsapp_tenant_catalog(
    phone: str,
    tenant_slug: str = "",
    tenant_id: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    clean_phone = normalize_phone_number(phone)
    target_tenant = tenant_id or tenant_slug
    store_name, products = get_tenant_products_from_db(tenant_slug)

    if not products:
        empty_msg = f"Saat ini katalog produk untuk *{store_name}* sedang disiapkan. Silakan hubungi admin kami ya, Kak! 🙏"
        return await send_whatsapp_text(clean_phone, empty_msg, tenant_id=target_tenant, phone_number_id=phone_number_id, access_token=access_token)

    product_lines = []
    for idx, p in enumerate(products, 1):
        p_title = str(p.get("title") or p.get("name") or "Produk").strip()
        price_num = int(float(p.get("promo_price") or p.get("price") or 0))
        price_fmt = f"Rp{price_num:,}".replace(",", ".")
        p_desc = str(p.get("description") or p.get("short_description") or "").strip()
        desc_snippet = f"\n   _{p_desc[:90]}..._" if p_desc else ""
        product_lines.append(f"*{idx}. {p_title}* — *{price_fmt}*{desc_snippet}")

    catalog_text = (
        f"🚀 *KATALOG RESMI {store_name.upper()}*\n\n"
        f"Berikut daftar lengkap {len(products)} produk / ecourse pilihan:\n\n"
        + "\n\n".join(product_lines) +
        f"\n\n━━━━━━━━━━━━━━━━━━\n"
        f"💳 Ketik *Beli* atau *Beli 1* (sampai *Beli {len(products)}*) untuk langsung bayar via *Dynamic QRIS* ⚡\n"
        f"_Ketik #reset kapan saja untuk kembali ke menu demo toko._"
    )

    return await send_whatsapp_text(clean_phone, catalog_text, tenant_id=target_tenant, phone_number_id=phone_number_id, access_token=access_token)


# ---------------------------------------------------------------------------
# Cart helpers
# ---------------------------------------------------------------------------

def add_product_to_cart(from_phone: str, tenant_slug: str, product_key: str) -> Tuple[str, List[Dict[str, str]], int]:
    clean_phone = normalize_phone_number(from_phone)
    _, products = get_tenant_products_from_db(tenant_slug)

    clean_key = str(product_key).replace("prod_", "").strip()
    selected_prod = None
    for p in products:
        if str(p.get("id")) == clean_key or str(p.get("id")) == product_key or str(p.get("slug")) == clean_key:
            selected_prod = p
            break

    if not selected_prod and products:
        selected_prod = products[0]

    if clean_phone not in user_cart_sessions:
        user_cart_sessions[clean_phone] = []

    if selected_prod:
        user_cart_sessions[clean_phone].append(selected_prod)

    cart_items = user_cart_sessions[clean_phone]
    total_price = sum(int(float(item.get("promo_price") or item.get("price") or 0)) for item in cart_items)

    items_text = "\n".join([
        f"• *{item.get('title') or item.get('name')}* — Rp {int(float(item.get('promo_price') or item.get('price') or 0)):,}".replace(",", ".")
        for item in cart_items
    ])

    msg_body = (
        f"🛒 *Keranjang Belanja Anda ({len(cart_items)} Item):*\n\n"
        f"{items_text}\n\n"
        f"💰 *Total Tagihan:* Rp {total_price:,}\n\n"
        f"Silakan pilih aksi di bawah untuk melanjutkan:"
    ).replace(",", ".")

    buttons = [
        {"id": "btn_checkout_cart", "title": "💳 Bayar Semua QRIS"},
        {"id": "btn_view_service", "title": "🛍️ Katalog Produk"},
        {"id": "btn_clear_cart", "title": "🗑️ Kosongkan Keranjang"}
    ]

    return msg_body, buttons, total_price


# ---------------------------------------------------------------------------
# Checkout helpers
# ---------------------------------------------------------------------------

async def generate_cart_checkout_response(
    tenant_slug: str,
    from_phone: str,
    contact_name: str = "Kakak",
    gateway: str = "seller_qris",
) -> Tuple[str, Dict[str, Any], bytes]:
    clean_phone = normalize_phone_number(from_phone)
    clean_slug = str(tenant_slug or "").strip().lower()
    cart_items = user_cart_sessions.get(clean_phone, [])
    store_name, products = get_tenant_products_from_db(clean_slug)

    if not cart_items:
        if not products:
            empty_info = f"Saat ini katalog untuk *{store_name}* belum memiliki produk aktif. Silakan hubungi admin kami ya, Kak! 🙏"
            return empty_info, {}, b""
        default_item = products[0]
        cart_items = [default_item]

    base_amount = sum(int(float(item.get("promo_price") or item.get("price") or 0)) for item in cart_items)
    unique_code = random.randint(100, 999)
    total_amount = max(1, base_amount - unique_code)
    item_titles = ", ".join([str(item.get("title") or item.get("name")) for item in cart_items])
    product_summary = f"Order {len(cart_items)} Items ({item_titles[:35]}...)" if len(item_titles) > 35 else item_titles

    # -----------------------------------------------------------------------
    # SELLER NATIVE QRIS CHECKOUT ENGINE (Manual Upload / Acquirer Mandiri)
    # Default standard for all tenants: no third-party payment gateway
    # -----------------------------------------------------------------------
    from app.services.onboarding_service import onboarding_service
    tenant_details = onboarding_service.get_tenant_details_by_slug(clean_slug) or {}
    tenant_obj = tenant_details.get("tenant", {}) if tenant_details else {}
    tenant_meta = tenant_details.get("metadata") or tenant_obj.get("metadata") or {}

    seller_qris_image = (
        tenant_meta.get("qris_image_url")
        or tenant_meta.get("qris_image")
        or tenant_meta.get("qris_url")
        or (tenant_meta.get("payment_settings", {}) or {}).get("qris")
        or (tenant_meta.get("payment_config", {}) or {}).get("qris_image_url")
        or (tenant_meta.get("qris", {}) or {}).get("image_url")
    )
    raw_qris_string = (
        (tenant_meta.get("payment_settings") or {}).get("qris_raw")
        or (tenant_meta.get("payment_settings") or {}).get("raw_qris_string")
        or (tenant_meta.get("payment_config") or {}).get("raw_qris_string")
        or (tenant_meta.get("payment_config") or {}).get("qris_content")
        or (tenant_meta.get("payment_config") or {}).get("qris_payload")
        or tenant_meta.get("raw_qris_string")
        or tenant_meta.get("qris_static_string")
        or tenant_meta.get("static_qris_payload")
        or (tenant_meta.get("qris", {}) or {}).get("static_qr")
    )
    merchant_qris_name = (
        (tenant_meta.get("qris", {}) or {}).get("merchant_name")
        or tenant_meta.get("merchant_name")
        or store_name
    )
    bank_info = tenant_meta.get("bank") or (tenant_meta.get("payment_settings", {}) or {}).get("bank")

    clean_inv_slug = str(clean_slug).replace("_", "-").lower()[:8]
    external_id = f"INV-{clean_inv_slug.upper()}-{uuid.uuid4().hex[:6].upper()}"

    amount_fmt = f"Rp{total_amount:,.0f}".replace(",", ".")
    prod_slug = str(cart_items[0].get("slug") or cart_items[0].get("id") or "").strip() if cart_items else ""
    prod_checkout_url = f"https://shop.boontrack.com/{clean_slug}/p/{prod_slug}" if prod_slug else f"https://shop.boontrack.com/{clean_slug}"

    # Auto-decode gambar QRIS statis jika string mentah belum ada di database
    if not raw_qris_string and seller_qris_image:
        try:
            from app.utils.qris_generator import decode_qris_image
            decoded_qris = decode_qris_image(str(seller_qris_image).strip())
            if decoded_qris and decoded_qris.startswith("000201"):
                raw_qris_string = decoded_qris
                logger.info(f"[AUTO-DECODE QRIS SUCCESS] Decoded raw EMVCo payload from image for tenant '{clean_slug}'")
                try:
                    from app.services.whatsapp_service import get_supabase
                    sb = get_supabase()
                    if sb and clean_slug:
                        ps = tenant_meta.get("payment_settings") or {}
                        ps["qris_raw"] = decoded_qris
                        tenant_meta["payment_settings"] = ps
                        sb.table("tenants").update({"metadata": tenant_meta}).eq("slug", clean_slug).execute()
                except Exception:
                    pass
        except Exception as _dec_err:
            logger.debug(f"[AUTO-DECODE NOTE] {_dec_err}")

    dynamic_qr_payload = ""
    if raw_qris_string:
        try:
            from app.utils.qris_generator import generate_dynamic_qris_payload
            dynamic_qr_payload = generate_dynamic_qris_payload(raw_qris_string, total_amount, external_id)
        except Exception as dyn_err:
            logger.warning(f"[DYNAMIC QRIS WARN] {dyn_err}")
            dynamic_qr_payload = raw_qris_string

    # Dynamic QRIS Generator: Injeksi nominal EMVCo Tag 54 dan hasilkan direct image PNG
    if dynamic_qr_payload and dynamic_qr_payload.startswith("000201"):
        from app.utils.qris_generator import get_quickchart_qr_url
        qr_img_target = get_quickchart_qr_url(dynamic_qr_payload)
    else:
        qr_img_target = str(seller_qris_image or "").strip()
    qr_bytes = generate_qris_image_bytes(dynamic_qr_payload or raw_qris_string or "") if (dynamic_qr_payload or raw_qris_string) else b""

    if clean_phone:
        user_session_states[clean_phone] = "AWAITING_PAYMENT"

    base_fmt = f"Rp{base_amount:,.0f}".replace(",", ".")
    invoice = {
        "external_id": external_id,
        "order_id": external_id,
        "amount": total_amount,
        "base_amount": base_amount,
        "unique_code": unique_code,
        "product_name": product_summary,
        "provider": "SELLER_NATIVE_QRIS",
        "status": "PENDING",
        "is_manual": True,
        "qr_string": dynamic_qr_payload or raw_qris_string or "",
        "qr_code_url": qr_img_target,
        "media_url": qr_img_target,
        "image_url": qr_img_target,
        "web_pay_url": prod_checkout_url,
        "merchant_name": merchant_qris_name,
        "tenant_id": clean_slug,
    }

    bank_str = ""
    if isinstance(bank_info, dict) and bank_info.get("name") and bank_info.get("holder"):
        b_acc = str(bank_info.get("account") or "").strip()
        acc_display = f"• No. Rek: `{b_acc}`\n" if b_acc and b_acc != "-" else ""
        bank_str = f"\n🏦 *Alternatif Transfer Bank:*\n• Bank: {bank_info.get('name')}\n• Penerima: {bank_info.get('holder')}\n{acc_display}"

    caption = (
        f"Berikut Rincian Tagihan & Barcode QRIS Pembayaran 💳\n\n"
        f"📦 *Nama Pesanan:* {product_summary}\n"
        f"💰 *Total Tagihan:* {amount_fmt}\n"
        f"_(Harga: {base_fmt} - Diskon Kode Unik: {unique_code})_\n"
        f"🏪 *Merchant QRIS:* {merchant_qris_name}\n"
        f"🔖 *No. Pesanan:* `{external_id}`\n"
        f"⏱️ *Masa Berlaku:* 24 Jam\n"
        f"{bank_str}\n"
        f"📲 *Petunjuk Pembayaran:*\n"
        f"1. Scan barcode QRIS toko di atas menggunakan aplikasi M-Banking (BCA, Mandiri, BRI, BNI) atau E-Wallet (GoPay, OVO, DANA, ShopeePay).\n"
        f"2. *PENTING:* Pastikan nominal transfer tepat sebesar *{amount_fmt}* (hingga 3 digit kode unik terakhir) agar pembayaran terverifikasi otomatis.\n"
        f"3. Setelah transfer berhasil, *mohon kirimkan screenshot / bukti transfer pembayaran ke chat WhatsApp ini* agar pesanan & akses Kakak langsung kami proses & aktifkan! ✨\n\n"
        f"🛒 *Link Storefront Toko:*\n"
        f"{prod_checkout_url}"
    )
    user_cart_sessions.pop(clean_phone, None)
    return caption, invoice, qr_bytes


async def generate_fast_track_checkout_response(
    tenant_slug: str,
    from_phone: str,
    contact_name: str = "Kakak",
    product_key: Optional[str] = None,
    gateway: str = "seller_qris",
) -> Tuple[str, Dict[str, Any], bytes]:
    clean_phone = normalize_phone_number(from_phone)
    clean_slug = str(tenant_slug or "").strip().lower()
    store_name, products = get_tenant_products_from_db(clean_slug)

    selected_product = None
    if products and product_key:
        clean_key = str(product_key).replace("prod_", "").strip().lower()
        for p in products:
            p_slug = str(p.get("slug") or "").lower()
            p_id = str(p.get("id") or "").lower()
            p_title = str(p.get("title") or p.get("name") or "").lower()
            if clean_key in p_id or clean_key in p_slug or clean_key in p_title:
                selected_product = p
                break

    if not selected_product and products:
        selected_product = products[0]

    if not selected_product:
        empty_msg = f"Saat ini katalog produk untuk *{store_name}* sedang disiapkan oleh admin toko. Silakan hubungi admin kami ya, Kak! 🙏"
        return empty_msg, {}, b""

    product_name = str(selected_product.get("title") or selected_product.get("name") or f"Produk {store_name}")
    base_amount = int(float(selected_product.get("promo_price") or selected_product.get("price") or 0))
    if base_amount <= 0:
        base_amount = 1000  # Minimal nominal transaksi QRIS

    # Injeksi 3-digit kode unik acak untuk rekonsiliasi mutasi otomatis
    unique_code = random.randint(100, 999)
    total_amount = max(1, base_amount - unique_code)
    amount = total_amount

    # -----------------------------------------------------------------------
    # SELLER NATIVE QRIS CHECKOUT ENGINE (Manual Upload / Acquirer Mandiri)
    # Default standard for all tenants: no third-party payment gateway
    # -----------------------------------------------------------------------
    from app.services.onboarding_service import onboarding_service
    tenant_details = onboarding_service.get_tenant_details_by_slug(clean_slug) or {}
    tenant_obj = tenant_details.get("tenant", {}) if tenant_details else {}
    tenant_meta = tenant_details.get("metadata") or tenant_obj.get("metadata") or {}

    seller_qris_image = (
        tenant_meta.get("qris_image_url")
        or tenant_meta.get("qris_image")
        or tenant_meta.get("qris_url")
        or (tenant_meta.get("payment_settings", {}) or {}).get("qris")
        or (tenant_meta.get("payment_config", {}) or {}).get("qris_image_url")
        or (tenant_meta.get("qris", {}) or {}).get("image_url")
    )
    raw_qris_string = (
        (tenant_meta.get("payment_settings") or {}).get("qris_raw")
        or (tenant_meta.get("payment_settings") or {}).get("raw_qris_string")
        or (tenant_meta.get("payment_config") or {}).get("raw_qris_string")
        or (tenant_meta.get("payment_config") or {}).get("qris_content")
        or (tenant_meta.get("payment_config") or {}).get("qris_payload")
        or tenant_meta.get("raw_qris_string")
        or tenant_meta.get("qris_static_string")
        or tenant_meta.get("static_qris_payload")
        or (tenant_meta.get("qris", {}) or {}).get("static_qr")
    )
    merchant_qris_name = (
        (tenant_meta.get("qris", {}) or {}).get("merchant_name")
        or tenant_meta.get("merchant_name")
        or store_name
    )
    bank_info = tenant_meta.get("bank") or (tenant_meta.get("payment_settings", {}) or {}).get("bank")

    clean_inv_slug = str(clean_slug).replace("_", "-").lower()[:8]
    external_id = f"INV-{clean_inv_slug.upper()}-{uuid.uuid4().hex[:6].upper()}"

    amount_fmt = f"Rp{amount:,.0f}".replace(",", ".")
    prod_slug = str((selected_product or {}).get("slug") or (selected_product or {}).get("id") or "").strip()
    prod_checkout_url = f"https://shop.boontrack.com/{clean_slug}/p/{prod_slug}" if prod_slug else f"https://shop.boontrack.com/{clean_slug}"

    # Auto-decode gambar QRIS statis jika string mentah belum ada di database
    if not raw_qris_string and seller_qris_image:
        try:
            from app.utils.qris_generator import decode_qris_image
            decoded_qris = decode_qris_image(str(seller_qris_image).strip())
            if decoded_qris and decoded_qris.startswith("000201"):
                raw_qris_string = decoded_qris
                logger.info(f"[AUTO-DECODE QRIS SUCCESS] Decoded raw EMVCo payload from image for tenant '{clean_slug}'")
                try:
                    from app.services.whatsapp_service import get_supabase
                    sb = get_supabase()
                    if sb and clean_slug:
                        ps = tenant_meta.get("payment_settings") or {}
                        ps["qris_raw"] = decoded_qris
                        tenant_meta["payment_settings"] = ps
                        sb.table("tenants").update({"metadata": tenant_meta}).eq("slug", clean_slug).execute()
                except Exception:
                    pass
        except Exception as _dec_err:
            logger.debug(f"[AUTO-DECODE NOTE] {_dec_err}")

    dynamic_qr_payload = ""
    if raw_qris_string:
        try:
            from app.utils.qris_generator import generate_dynamic_qris_payload
            dynamic_qr_payload = generate_dynamic_qris_payload(raw_qris_string, total_amount, external_id)
        except Exception as dyn_err:
            logger.warning(f"[DYNAMIC QRIS WARN] {dyn_err}")
            dynamic_qr_payload = raw_qris_string

    # Dynamic QRIS Generator: Injeksi nominal EMVCo Tag 54 dan hasilkan direct image PNG
    if dynamic_qr_payload and dynamic_qr_payload.startswith("000201"):
        from app.utils.qris_generator import get_quickchart_qr_url
        qr_img_target = get_quickchart_qr_url(dynamic_qr_payload)
    else:
        qr_img_target = str(seller_qris_image or "").strip()
    qr_bytes = generate_qris_image_bytes(dynamic_qr_payload or raw_qris_string or "") if (dynamic_qr_payload or raw_qris_string) else b""

    if clean_phone:
        user_session_states[clean_phone] = "AWAITING_PAYMENT"

    base_fmt = f"Rp{base_amount:,.0f}".replace(",", ".")
    invoice = {
        "external_id": external_id,
        "order_id": external_id,
        "amount": total_amount,
        "base_amount": base_amount,
        "unique_code": unique_code,
        "product_name": product_name,
        "provider": "SELLER_NATIVE_QRIS",
        "status": "PENDING",
        "is_manual": True,
        "qr_string": dynamic_qr_payload or raw_qris_string or "",
        "qr_code_url": qr_img_target,
        "media_url": qr_img_target,
        "image_url": qr_img_target,
        "web_pay_url": prod_checkout_url,
        "merchant_name": merchant_qris_name,
        "tenant_id": clean_slug,
    }

    bank_str = ""
    if isinstance(bank_info, dict) and bank_info.get("name") and bank_info.get("holder"):
        b_acc = str(bank_info.get("account") or "").strip()
        acc_display = f"• No. Rek: `{b_acc}`\n" if b_acc and b_acc != "-" else ""
        bank_str = f"\n🏦 *Alternatif Transfer Bank:*\n• Bank: {bank_info.get('name')}\n• Penerima: {bank_info.get('holder')}\n{acc_display}"

    caption = (
        f"Berikut Rincian Tagihan & Barcode QRIS Pembayaran 💳\n\n"
        f"📦 *Nama Produk:* {product_name}\n"
        f"💰 *Total Tagihan:* {amount_fmt}\n"
        f"_(Harga: {base_fmt} - Diskon Kode Unik: {unique_code})_\n"
        f"🏪 *Merchant QRIS:* {merchant_qris_name}\n"
        f"🔖 *No. Pesanan:* `{external_id}`\n"
        f"⏱️ *Masa Berlaku:* 24 Jam\n"
        f"{bank_str}\n"
        f"📲 *Petunjuk Pembayaran:*\n"
        f"1. Scan barcode QRIS toko di atas menggunakan aplikasi M-Banking (BCA, Mandiri, BRI, BNI) atau E-Wallet (GoPay, OVO, DANA, ShopeePay).\n"
        f"2. *PENTING:* Pastikan nominal pembayaran tepat sebesar *{amount_fmt}* (hingga 3 digit kode unik terakhir) agar verifikasi otomatis berjalan lancar.\n"
        f"3. Setelah transfer berhasil, *mohon kirimkan bukti transfer / screenshot pembayaran ke chat ini* agar akses materi langsung kami aktifkan. ✨\n\n"
        f"🛒 *Link Storefront / Web Checkout Toko:*\n"
        f"{prod_checkout_url}"
    )
    user_cart_sessions.pop(clean_phone, None)
    return caption, invoice, qr_bytes
