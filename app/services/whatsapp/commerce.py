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
    """Renders QR code PNG directly from official Xendit qr_string without local DANA Bisnis generator."""
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
    if clean_slug in ("ombudi", "om-budi", "om_budi"):
        candidate_slugs.extend(["om-budi", "ombudi", "om_budi"])

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

    if products:
        def _cpm_priority(x):
            s = str(x.get("slug") or "").lower()
            t = str(x.get("title") or x.get("name") or "").lower()
            if "cpm-24jam" in s or "cpm-24-jam" in s or "modul-praktis-cpm" in s or "cpm 24 jam" in t:
                return 0
            return 1
        products.sort(key=_cpm_priority)

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
    tenant_slug: str = "onlineboost",
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
    gateway: str = "xendit",
) -> Tuple[str, Dict[str, Any], bytes]:
    import urllib.parse
    from app.services.xendit_service import xendit_service

    clean_phone = normalize_phone_number(from_phone)
    cart_items = user_cart_sessions.get(clean_phone, [])
    store_name, products = get_tenant_products_from_db(tenant_slug)

    if not cart_items:
        default_item = products[0] if products else {"title": f"Pesanan {store_name}", "price": 99000}
        cart_items = [default_item]

    total_amount = sum(int(float(item.get("promo_price") or item.get("price") or 0)) for item in cart_items)
    item_titles = ", ".join([str(item.get("title") or item.get("name")) for item in cart_items])
    product_summary = f"Order {len(cart_items)} Items ({item_titles[:35]}...)" if len(item_titles) > 35 else item_titles

    clean_gateway = str(gateway or "xendit").strip().lower()
    if clean_gateway == "dana_bisnis":
        from app.utils.qris_generator import get_dynamic_qris_string, get_qr_code_image_url
        clean_inv_slug = str(tenant_slug).replace("_", "-").lower()[:8]
        external_id = f"INV-{clean_inv_slug.upper()}-{uuid.uuid4().hex[:6].upper()}"
        qr_string = get_dynamic_qris_string(amount=total_amount, invoice_id=external_id)
        invoice = {
            "external_id": external_id,
            "amount": total_amount,
            "qr_string": qr_string,
            "qr_code_url": get_qr_code_image_url(qr_string),
            "status": "ACTIVE",
            "provider": "DANA_BISNIS",
            "tenant_id": tenant_slug,
        }
    else:
        try:
            invoice = await xendit_service.create_qris_invoice(
                tenant_slug=tenant_slug,
                amount=total_amount,
                product_name=product_summary,
                customer_phone=clean_phone,
            )
        except Exception as e:
            import traceback
            logger.error(f"[CHECKOUT_EXCEPTION] {str(e)}\n{traceback.format_exc()}")
            raise e

    if clean_phone:
        user_session_states[clean_phone] = "AWAITING_PAYMENT"

    qr_string = str(invoice.get("qr_string") or "").strip()
    external_id = invoice.get("external_id", "-")
    invoice_url = invoice.get("invoice_url") or f"https://checkout.xendit.co/web/{external_id}"
    invoice["invoice_url"] = invoice_url
    invoice["web_pay_url"] = invoice_url

    qr_string = str(invoice.get("qr_string") or "").strip()
    qr_data = qr_string or invoice_url
    qr_bytes = generate_qris_image_bytes(qr_data) if qr_data else b""
    qr_code_url = invoice.get("qr_code_url") or f"https://api.qrserver.com/v1/create-qr-code/?size=600x600&margin=16&format=png&data={urllib.parse.quote(qr_data)}"
    invoice["qr_code_url"] = qr_code_url

    items_detail = "\n".join([
        f"• *{item.get('title') or item.get('name')}* (Rp {int(float(item.get('promo_price') or item.get('price') or 0)):,})".replace(",", ".")
        for item in cart_items
    ])

    amount_fmt = f"Rp{total_amount:,.0f}".replace(",", ".")

    caption = (
        f"Berikut Rincian Tagihan Pembayaran Pesanan Anda 💳\n\n"
        f"📦 *Rincian Belanja:*\n{items_detail}\n\n"
        f"💰 *Total Tagihan:* {amount_fmt}\n"
        f"📄 *No. Invoice / Kode Bayar:* `{external_id}`\n"
        f"⏱️ *Masa Berlaku:* 15 Menit\n\n"
        f"🔗 *Link Pembayaran Resmi Xendit:*\n"
        f"{invoice_url}\n\n"
        f"📱 *Petunjuk Pembayaran:*\n"
        f"1. Klik link pembayaran resmi Xendit di atas.\n"
        f"2. Pilih metode bayar QRIS atau E-Wallet (GoPay, OVO, DANA, ShopeePay).\n"
        f"3. Selesaikan transaksi langsung di halaman pembayaran resmi Xendit.\n\n"
        f"_Notifikasi dan link akses produk akan otomatis dikirimkan setelah pembayaran berhasil._ 🚀"
    ).replace(",", ".")

    user_cart_sessions.pop(clean_phone, None)
    return caption, invoice, qr_bytes


async def generate_fast_track_checkout_response(
    tenant_slug: str,
    from_phone: str,
    contact_name: str = "Kakak",
    product_key: Optional[str] = None,
    gateway: str = "xendit",
) -> Tuple[str, Dict[str, Any], bytes]:
    import urllib.parse
    from app.services.xendit_service import xendit_service

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
            if clean_key in p_id or clean_key in p_slug or clean_key in p_title or ("cpm" in clean_key and ("cpm" in p_slug or "cpm" in p_title)):
                selected_product = p
                break

    if not selected_product and products:
        selected_product = products[0]

    if selected_product:
        product_name = str(selected_product.get("title") or selected_product.get("name") or f"Produk {store_name}")
        amount = int(float(selected_product.get("promo_price") or selected_product.get("price") or 1000))
    else:
        product_name = "Modul Praktis CPM 24 Jam"
        amount = 1000

    if "cpm" in product_name.lower() or (product_key and "cpm" in str(product_key).lower()) or (clean_slug == "onlineboost" and not product_key):
        product_name = "Modul Praktis CPM 24 Jam"
        amount = 1000

    clean_gateway = str(gateway or "xendit").strip().lower()
    if clean_gateway == "dana_bisnis":
        from app.utils.qris_generator import get_dynamic_qris_string, get_qr_code_image_url
        clean_inv_slug = str(clean_slug).replace("_", "-").lower()[:8]
        external_id = f"INV-{clean_inv_slug.upper()}-{uuid.uuid4().hex[:6].upper()}"
        qr_string = get_dynamic_qris_string(amount=amount, invoice_id=external_id)
        invoice = {
            "external_id": external_id,
            "amount": amount,
            "qr_string": qr_string,
            "qr_code_url": get_qr_code_image_url(qr_string),
            "status": "ACTIVE",
            "provider": "DANA_BISNIS",
            "tenant_id": clean_slug,
        }
    else:
        try:
            invoice = await xendit_service.create_qris_invoice(
                tenant_slug=clean_slug,
                amount=amount,
                product_name=product_name,
                customer_phone=clean_phone,
            )
        except Exception as e:
            import traceback
            logger.error(f"[CHECKOUT_EXCEPTION] {str(e)}\n{traceback.format_exc()}")
            raise e

    if clean_phone:
        user_session_states[clean_phone] = "AWAITING_PAYMENT"

    external_id = invoice.get("external_id", "-")
    invoice_url = invoice.get("invoice_url") or f"https://checkout.xendit.co/web/{external_id}"
    invoice["invoice_url"] = invoice_url
    invoice["web_pay_url"] = invoice_url

    qr_string = str(invoice.get("qr_string") or "").strip()
    qr_data = qr_string or invoice_url

    qr_bytes = generate_qris_image_bytes(qr_data) if qr_data else b""
    qr_code_url = invoice.get("qr_code_url") or f"https://api.qrserver.com/v1/create-qr-code/?size=600x600&margin=16&format=png&data={urllib.parse.quote(qr_data)}"
    invoice["qr_code_url"] = qr_code_url

    amount_fmt = f"Rp{amount:,.0f}".replace(",", ".")

    caption = (
        f"Berikut Rincian Tagihan Pembayaran Anda 💳\n\n"
        f"📌 *Nama Produk:* {product_name}\n"
        f"💰 *Total Tagihan:* {amount_fmt}\n"
        f"📄 *No. Invoice / Kode Bayar:* `{external_id}`\n"
        f"⏱️ *Masa Berlaku:* 15 Menit\n\n"
        f"🔗 *Link Pembayaran Resmi Xendit:*\n"
        f"{invoice_url}\n\n"
        f"📱 *Petunjuk Pembayaran:*\n"
        f"1. Klik link pembayaran resmi Xendit di atas.\n"
        f"2. Pilih metode bayar QRIS atau E-Wallet (GoPay, OVO, DANA, ShopeePay).\n"
        f"3. Selesaikan transaksi langsung di halaman pembayaran resmi Xendit.\n\n"
        f"_Akses materi & layanan akan otomatis aktif setelah pembayaran berhasil terverifikasi._ 🚀"
    )
    return caption, invoice, qr_bytes
