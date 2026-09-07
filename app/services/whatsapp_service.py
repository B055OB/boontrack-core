import os
import io
import re
import json
import mimetypes
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union, List, Tuple
import httpx
from supabase import create_client, Client

import uuid
import asyncio

logger = logging.getLogger(__name__)

_supabase_client: Optional[Client] = None

def get_supabase() -> Optional[Client]:
    global _supabase_client
    if _supabase_client is None:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass

        supabase_url = (
            os.getenv("SUPABASE_URL") 
            or os.getenv("NEXT_PUBLIC_SUPABASE_URL") 
            or "https://mpluzajlzpregmjwpjqr.supabase.co"
        )
        supabase_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
            or os.getenv("SUPABASE_KEY") 
            or os.getenv("SUPABASE_ANON_KEY") 
            or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY") 
            or ""
        )
        if supabase_url and supabase_key:
            try:
                _supabase_client = create_client(supabase_url, supabase_key)
            except Exception as e:
                logger.error(f"[Supabase Init Error] {e}")
    return _supabase_client



def normalize_phone_number(raw_phone: Optional[str]) -> str:
    """Menyeragamkan format nomor telepon WhatsApp ke standar internasional E.164 tanpa tanda plus (e.g. 628123456789)."""
    if not raw_phone:
        return ""
    cleaned = "".join(filter(str.isdigit, str(raw_phone)))
    if cleaned.startswith("08"):
        cleaned = "62" + cleaned[1:]
    elif cleaned.startswith("008"):
        cleaned = "62" + cleaned[2:]
    elif cleaned.startswith("8") and len(cleaned) in (9, 10, 11, 12, 13):
        cleaned = "62" + cleaned
    elif cleaned.startswith("6208"):
        cleaned = "62" + cleaned[3:]
    return cleaned


# Session memory map linking sender phone number to dynamic tenant slug
user_tenant_sessions: Dict[str, str] = {}
user_session_states: Dict[str, str] = {}
user_cart_sessions: Dict[str, List[Dict[str, Any]]] = {}
user_phone_number_id_sessions: Dict[str, str] = {}

DEMO_MENU_TEXT = (
    "Halo! Selamat datang di *Portal Pengujian Ekosistem BoonTrack* 🚀\n\n"
    "Silakan pilih demo asisten/merchant yang ingin Anda uji coba:\n"
    "1️⃣ *Om Budi Channel* (slug: ombudi / retail showcase)\n"
    "2️⃣ *Tier Growth+* (slug: growthplus / Unofficial WhatsApp + Ads Tracking Meta CAPI & TikTok)\n"
    "3️⃣ *Tier ProScale* (slug: proscale / Official Meta Cloud WABA + Omnichannel & BoonPilot AI)\n"
    "4️⃣ *OnlineBoost* (slug: onlineboost / Digital Marketing & Course Vault)\n\n"
    "Balas dengan mengetik angka *1*, *2*, *3*, atau *4* (atau ketik *#reset* kapan saja untuk ganti toko)."
)

DEMO_TENANT_GREETINGS: Dict[str, str] = {
    "ombudi": (
        "🛒 *Selamat Datang di Om Budi Channel!*\n\n"
        "Showcase ritel & produk UMKM terpercaya. Layanan pelanggan cepat dan produk berkualitas siap kirim.\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
    "om-budi": (
        "🛒 *Selamat Datang di Om Budi Channel!*\n\n"
        "Showcase ritel & produk UMKM terpercaya. Layanan pelanggan cepat dan produk berkualitas siap kirim.\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
    "growthplus": (
        "⚡ *Selamat Datang di Tier Growth+ BoonTrack!*\n\n"
        "Paket scale-up bisnis via Unofficial WhatsApp Gateway terintegrasi Server-Side Ads Tracking Meta CAPI & TikTok Pixel.\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
    "proscale": (
        "🏢 *Selamat Datang di Tier ProScale Enterprise!*\n\n"
        "Solusi Official Meta Cloud WABA verified, Omnichannel Inbox multi-CS, dan BoonPilot AI Copilot 24/7.\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
    "onlineboost": (
        "🚀 *Selamat datang di OnlineBoost Digital Hub*\n\n"
        "Digital Marketing & Course Vault: Koleksi Ecourse Paid Traffic, Strategi YouTube AI, dan Masterclass scale-up bisnis.\n\n"
        "Ketik *Katalog* untuk memilih paket materi langsung atau ketik *Beli* untuk checkout cepat."
    ),
    "bale_pananggeuhan": (
        "🏛️ *Sampurasun! Selamat Datang di Balé Pananggeuhan*\n\n"
        "Layanan Aspirasi & Pengaduan Online Warga Jawa Barat.\n"
        "Silakan sampaikan laporan fasilitas umum, aduan warga, atau pengurusan administrasi kependudukan Anda.\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
    "atmosfitnes": (
        "🏋️ *Selamat Datang di Prima Fit Gym (Atmosfitnes)!*\n\n"
        "Asisten reservasi dan keanggotaan fitness modern.\n"
        "Ada yang bisa kami bantu seputar paket membership, jadwal kelas, atau akses fasilitas turnstile?\n\n"
        "_Ketik #reset kapan saja untuk kembali ke menu pilihan demo toko._"
    ),
}

def reset_whatsapp_user_session(phone: str) -> None:
    """Clear all session states across all stores and tenant services for a user."""
    clean_phone = normalize_phone_number(phone)
    if not clean_phone:
        return
    user_tenant_sessions.pop(clean_phone, None)
    user_session_states.pop(clean_phone, None)
    user_cart_sessions.pop(clean_phone, None)
    user_phone_number_id_sessions.pop(clean_phone, None)
    raw_phone = str(phone).strip().replace("+", "")
    if raw_phone:
        user_tenant_sessions.pop(raw_phone, None)
        user_session_states.pop(raw_phone, None)
        user_cart_sessions.pop(raw_phone, None)
        user_phone_number_id_sessions.pop(raw_phone, None)

    try:
        from app.services.session_store import clear_user_tenant_session
        clear_user_tenant_session(clean_phone)
        if raw_phone:
            clear_user_tenant_session(raw_phone)
    except Exception:
        pass

    try:
        from app.tenants.om_budi.service import om_budi_service
        om_budi_service.user_sessions.pop(clean_phone, None)
        if raw_phone:
            om_budi_service.user_sessions.pop(raw_phone, None)
    except Exception:
        pass

    try:
        from app.services.cv_state_engine import GLOBAL_USER_STATES
        GLOBAL_USER_STATES.pop(clean_phone, None)
        if raw_phone:
            GLOBAL_USER_STATES.pop(raw_phone, None)
    except Exception:
        pass

    try:
        from app.repositories.session_repository import _SESSION_CACHE
        for k in list(_SESSION_CACHE.keys()):
            if clean_phone in k or (raw_phone and raw_phone in k):
                _SESSION_CACHE.pop(k, None)
    except Exception:
        pass



def sanitize_whatsapp_message_text(text: Any) -> str:
    """Sanitasi respons AI agar tidak pernah membocorkan raw JSON {"reply": ...} ke chat WhatsApp."""
    if not text:
        return ""
    if not isinstance(text, str):
        if isinstance(text, dict):
            val = text.get("reply") or text.get("reply_text") or text.get("message") or text.get("text") or ""
            return str(val).strip()
        return str(text).strip()

    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if len(lines) >= 2 and lines[-1].strip().startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()
        elif raw.startswith("```json"):
            raw = raw[7:].rstrip("`").strip()
        elif raw.startswith("```"):
            raw = raw[3:].rstrip("`").strip()

    if (raw.startswith("{") and raw.endswith("}")) or '"reply"' in raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                val = parsed.get("reply") or parsed.get("reply_text") or parsed.get("message") or parsed.get("text")
                if val is not None:
                    raw = str(val).strip()
        except Exception:
            match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
            if match:
                try:
                    raw = match.group(1).encode().decode("unicode_escape", errors="ignore").strip()
                except Exception:
                    raw = match.group(1).strip()

    try:
        from app.services.ai_gateway.models import clean_ai_response
        return clean_ai_response(raw)
    except Exception:
        return raw


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


async def send_whatsapp_tenant_catalog(phone: str, tenant_slug: str = "onlineboost", tenant_id: Optional[str] = None, phone_number_id: Optional[str] = None, access_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
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

    # Kirim sebagai teks murni agar seluruh produk (lebih dari 3) tampil utuh tanpa error Meta API
    return await send_whatsapp_text(clean_phone, catalog_text, tenant_id=target_tenant, phone_number_id=phone_number_id, access_token=access_token)


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


async def generate_cart_checkout_response(
    tenant_slug: str,
    from_phone: str,
    contact_name: str = "Kakak",
    gateway: str = "xendit",
) -> Tuple[str, Dict[str, Any], bytes]:
    from app.services.xendit_service import xendit_service
    import urllib.parse

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
        invoice = await xendit_service.create_qris_invoice(
            tenant_slug=tenant_slug,
            amount=total_amount,
            product_name=product_summary,
            customer_phone=clean_phone,
        )

    if clean_phone:
        user_session_states[clean_phone] = "AWAITING_PAYMENT"

    qr_string = str(invoice.get("qr_string") or "").strip()
    external_id = invoice.get("external_id", "-")
    invoice_url = invoice.get("invoice_url") or f"https://checkout.xendit.co/web/{external_id}"
    invoice["invoice_url"] = invoice_url
    invoice["web_pay_url"] = invoice_url

    qr_string = str(invoice.get("qr_string") or "").strip()
    qr_data = qr_string or invoice_url
    # Render QR code image natively directly from official Xendit qr_string or invoice_url
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
    from app.services.xendit_service import xendit_service
    import urllib.parse

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

    # Khusus tenant onlineboost / produk CPM: selalu pasang harga resmi Rp1.000
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
        invoice = await xendit_service.create_qris_invoice(
            tenant_slug=clean_slug,
            amount=amount,
            product_name=product_name,
            customer_phone=clean_phone,
        )

    if clean_phone:
        user_session_states[clean_phone] = "AWAITING_PAYMENT"

    external_id = invoice.get("external_id", "-")
    invoice_url = invoice.get("invoice_url") or f"https://checkout.xendit.co/web/{external_id}"
    invoice["invoice_url"] = invoice_url
    invoice["web_pay_url"] = invoice_url

    qr_string = str(invoice.get("qr_string") or "").strip()
    qr_data = qr_string or invoice_url

    # Render QR code image natively directly from official Xendit qr_string or invoice_url
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


def resolve_dynamic_tenant_for_whatsapp(
    phone_id: str,
    from_phone: str,
    message_text: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[str, bool]:
    import re
    clean_phone = normalize_phone_number(from_phone)
    text = (message_text or "").strip()
    text_lower = text.lower()
    clean_phone_id = str(phone_id).strip()
    career_phone_id = os.getenv("CAREER_PHONE_NUMBER_ID", "1340866379104241")
    is_career_phone = (clean_phone_id == "1340866379104241" or clean_phone_id == career_phone_id)

    option_map = {
        "1": "ombudi",
        "ombudi": "ombudi",
        "om budi": "ombudi",
        "om-budi": "ombudi",
        "retail": "ombudi",
        "2": "growthplus",
        "growth": "growthplus",
        "growthplus": "growthplus",
        "growth+": "growthplus",
        "tier growth+": "growthplus",
        "3": "proscale",
        "proscale": "proscale",
        "pro scale": "proscale",
        "tier proscale": "proscale",
        "waba": "proscale",
        "4": "onlineboost",
        "onlineboost": "onlineboost",
        "digital": "onlineboost",
        "course": "onlineboost",
        "suhu-ads-masterclass": "onlineboost",
        "suhu ads": "onlineboost",
        "bale": "bale_pananggeuhan",
        "bale pananggeuhan": "bale_pananggeuhan",
        "gym": "atmosfitnes",
        "prima fit": "atmosfitnes",
        "prima fit gym": "atmosfitnes",
        "atmosfitnes": "atmosfitnes",
    }

    # =========================================================================
    # JALUR KHUSUS NOMOR CAREER ASSISTANT
    # =========================================================================
    from app.services.session_store import (
        get_user_tenant_session,
        set_user_tenant_session,
        detect_demo_intent_keyword
    )

    if is_career_phone:
        # HANYA '#reset' eksplisit yang boleh membuka menu 4 portal pengujian di nomor Career
        if text_lower == "#reset":
            if clean_phone:
                reset_whatsapp_user_session(clean_phone)
                user_session_states[clean_phone] = "AWAITING_PORTAL_CHOICE"
            logger.info(f"[DYNAMIC TENANT WA] Career sender {clean_phone} explicitly triggered #reset -> portal menu")
            return "__MENU__", False

        # Jika user di nomor Career sedang memilih portal setelah #reset
        if user_session_states.get(clean_phone) == "AWAITING_PORTAL_CHOICE" and text_lower in option_map:
            target_slug = option_map[text_lower]
            if clean_phone:
                set_user_tenant_session(clean_phone, target_slug)
            logger.info(f"[DYNAMIC TENANT WA] Career sender {clean_phone} chose portal '{target_slug}'")
            return target_slug, True

        # Jika user di nomor Career sudah mengunci session ke demo tenant (misal OnlineBoost)
        locked_career = get_user_tenant_session(clean_phone, text)
        if locked_career in ("onlineboost", "growthplus", "proscale"):
            return locked_career, False

        # Pesan salam biasa ("halo", "hi", "p", dst) atau pertanyaan karir TIDAK BOLEH di-intercept!
        # Langsung arahkan ke agent konsultasi Career
        return "boontrack-career", False

    # =========================================================================
    # JALUR NOMOR OM BUDI / DEMO NUMBER (SANDBOX)
    # =========================================================================
    if text_lower in ("#reset", "reset", "menu utama", "#menu", "menu", "demo"):
        if clean_phone:
            reset_whatsapp_user_session(clean_phone)
            user_session_states[clean_phone] = "AWAITING_PORTAL_CHOICE"
        logger.info(f"[DYNAMIC TENANT WA] Sender {clean_phone} triggered reset/demo menu")
        return "__MENU__", False

    if text_lower in option_map:
        target_slug = option_map[text_lower]
        if clean_phone:
            set_user_tenant_session(clean_phone, target_slug)
        logger.info(f"[DYNAMIC TENANT WA] Sender {clean_phone} selected option '{text_lower}' -> locked to '{target_slug}'")
        return target_slug, True

    # Cek session lock persisten (In-memory -> Disk -> Supabase DB -> Recent History -> Keyword)
    locked_tenant = get_user_tenant_session(clean_phone, text)
    if locked_tenant and locked_tenant in ("onlineboost", "growthplus", "proscale", "ombudi"):
        return locked_tenant, False

    match = re.search(
        r"saya\s+baru\s+(?:saja\s+)?(?:mendaftar|daftar)\s+toko\s+([a-zA-Z0-9\-_]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"toko\s*:\s*([a-zA-Z0-9\-_]+)", text, re.IGNORECASE)

    if match:
        target_slug = match.group(1).lower().strip()
        if clean_phone:
            set_user_tenant_session(clean_phone, target_slug)
        logger.info(f"[DYNAMIC TENANT WA] Bound sender {clean_phone} to store '{target_slug}' via onboarding message")
        return target_slug, True

    # Salam biasa ("halo", "hi", "test", dll) untuk nomor demo / Om Budi: tampilkan menu 4 portal sebagai default/fallback
    if text_lower in ("halo", "hi", "p", "test", "tes", "hai", "start", "info"):
        return "__MENU__", False

    if clean_phone_id == "1268977686299719":
        return "om_budi", False

    try:
        from app.services.onboarding_service import onboarding_service
        latest_slug = onboarding_service.get_latest_commerce_tenant()
        if latest_slug:
            if clean_phone:
                set_user_tenant_session(clean_phone, latest_slug)
            return latest_slug, False
    except Exception as e:
        logger.warning(f"[DYNAMIC TENANT WA] Failed to query latest commerce tenant: {e}")

    return "onlineboost", False


def get_user_session(phone: str, message_text: str = "") -> Optional[str]:
    """Helper persisten get_user_session(phone) tahan restart container."""
    from app.services.session_store import get_user_tenant_session
    return get_user_tenant_session(phone, message_text)


def set_user_session(phone: str, tenant_slug: str, state: str = "ACTIVE", context: Optional[dict] = None) -> None:
    """Helper persisten set_user_session(phone, tenant) tahan restart container."""
    from app.services.session_store import set_user_tenant_session
    set_user_tenant_session(phone, tenant_slug, state, context)



async def log_to_supabase_messages(
    sender: str, 
    text: Optional[str] = None, 
    tenant_id: str = "boontrack-career",
    channel: str = "whatsapp",
    user_phone: Optional[str] = None,
    user_name: Optional[str] = None,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    message_text: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool:
    try:
        supabase = get_supabase()
        content = text if text is not None else (message_text or "")
        if not supabase or not content:
            return False

        raw_tenant = str(tenant_id or "boontrack-career").strip().lower()
        if raw_tenant in ["om_budi", "om-budi", "1268977686299719"]:
            clean_tenant = "om-budi"
        elif raw_tenant in ["aduan", "aduan-sandbox", "aduan_sandbox", "1306479742542883"]:
            clean_tenant = "aduan-sandbox"
        elif raw_tenant in ["boontrack-career", "boontrack_career", "career", "1340866379104241", "00000000-0000-0000-0000-000000000000"]:
            clean_tenant = "boontrack-career"
        else:
            clean_tenant = tenant_id

        s_lower = str(sender or "user").strip().lower()
        if s_lower in ["user", "customer"] or "customer" in s_lower:
            normalized_sender = "user"
        elif s_lower in ["bot", "ai", "boontrack ai", "system", "assistant"] or "bot" in s_lower or "ai" in s_lower:
            normalized_sender = "bot"
        else:
            normalized_sender = sender

        clean_digits = normalize_phone_number(user_phone or user_id or conversation_id or "")
        resolved_uid = clean_digits or user_id or normalized_sender
        resolved_phone = clean_digits or None

        if conversation_id and "-" in str(conversation_id) and len(str(conversation_id)) == 36:
            conv_uuid = str(conversation_id)
        elif clean_digits:
            conv_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{clean_tenant}:{clean_digits}"))
        else:
            conv_uuid = None

        now_iso = datetime.now(timezone.utc).isoformat()

        if conv_uuid and clean_digits:
            try:
                supabase.table("conversations").upsert({
                    "id": conv_uuid,
                    "tenant_id": clean_tenant,
                    "phone_number": clean_digits,
                    "contact_name": user_name or f"User {clean_digits[-4:]}",
                    "updated_at": now_iso
                }).execute()
            except Exception as conv_err:
                logger.debug(f"[Supabase Conv Upsert Warning] {conv_err}")

        payload = {
            "sender": normalized_sender,
            "text": content,
            "tenant_id": clean_tenant,
            "tenant_slug": clean_tenant,
            "channel": channel,
            "user_id": resolved_uid,
            "user_phone": resolved_phone,
            "user_name": user_name,
            "conversation_id": conv_uuid,
            "created_at": now_iso
        }
        supabase.table("messages").insert(payload).execute()
        return True
    except Exception as e:
        logger.error(f"[Supabase Logging Error] {e}")
        return False


def safe_log_to_supabase_messages(
    sender: str,
    text: Optional[str] = None,
    tenant_id: str = "boontrack-career",
    channel: str = "whatsapp",
    user_phone: Optional[str] = None,
    user_name: Optional[str] = None,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    message_text: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(log_to_supabase_messages(
            sender=sender,
            text=text,
            tenant_id=tenant_id,
            channel=channel,
            user_phone=user_phone,
            user_name=user_name,
            user_id=user_id,
            conversation_id=conversation_id,
            message_text=message_text,
            metadata=metadata
        ))
    except RuntimeError:
        asyncio.create_task(log_to_supabase_messages(
            sender=sender,
            text=text,
            tenant_id=tenant_id,
            channel=channel,
            user_phone=user_phone,
            user_name=user_name,
            user_id=user_id,
            conversation_id=conversation_id,
            message_text=message_text,
            metadata=metadata
        ))
    except Exception as e:
        logger.error(f"[Safe Supabase Log Exception] {e}")


def extract_meta_whatsapp_event(data: dict) -> Dict[str, Any]:
    res = {
        "is_message": False,
        "is_status": False,
        "phone_id": "",
        "from_phone": "",
        "contact_name": "",
        "msg_type": "",
        "text": "",
        "button_id": None,
        "media_id": None,
        "media_mime": None,
        "media_filename": None,
        "media_caption": "",
        "raw_msg": {}
    }
    try:
        if not isinstance(data, dict):
            return res

        entries = data.get("entry", [])
        if not entries or not isinstance(entries, list):
            return res

        entry = entries[0]
        if not isinstance(entry, dict):
            return res

        changes = entry.get("changes", [])
        if not changes or not isinstance(changes, list):
            return res

        value = changes[0].get("value", {})
        if not isinstance(value, dict):
            return res

        if "statuses" in value and value.get("statuses"):
            res["is_status"] = True
            return res

        messages = value.get("messages", [])
        if not messages or not isinstance(messages, list):
            return res

        msg_obj = messages[0]
        if not isinstance(msg_obj, dict):
            return res

        res["is_message"] = True
        res["raw_msg"] = msg_obj
        res["from_phone"] = str(msg_obj.get("from", "")).strip()
        res["msg_type"] = str(msg_obj.get("type", "text")).strip()
        res["timestamp"] = msg_obj.get("timestamp")
        res["message_id"] = msg_obj.get("id")
        res["referral"] = msg_obj.get("referral")

        meta = value.get("metadata", {})
        if isinstance(meta, dict):
            res["phone_id"] = str(meta.get("phone_number_id", "")).strip()

        contacts = value.get("contacts", [])
        if contacts and isinstance(contacts, list) and len(contacts) > 0:
            profile = contacts[0].get("profile", {})
            if isinstance(profile, dict):
                res["contact_name"] = str(profile.get("name", "")).strip()

        msg_type = res["msg_type"]
        if msg_type == "text":
            text_obj = msg_obj.get("text", {})
            if isinstance(text_obj, dict):
                res["text"] = str(text_obj.get("body", "")).strip()

        elif msg_type == "interactive":
            inter = msg_obj.get("interactive", {})
            if isinstance(inter, dict):
                inter_type = inter.get("type")
                if inter_type == "button_reply" or "button_reply" in inter:
                    btn = inter.get("button_reply", {})
                    if isinstance(btn, dict):
                        res["button_id"] = btn.get("id")
                        res["text"] = str(btn.get("title", "") or btn.get("id", "")).strip()
                elif inter_type == "list_reply" or "list_reply" in inter:
                    item = inter.get("list_reply", {})
                    if isinstance(item, dict):
                        res["button_id"] = item.get("id")
                        res["text"] = str(item.get("title", "") or item.get("id", "")).strip()

        elif msg_type == "button":
            btn_obj = msg_obj.get("button", {})
            if isinstance(btn_obj, dict):
                res["button_id"] = btn_obj.get("payload")
                res["text"] = str(btn_obj.get("text", "")).strip()

        elif msg_type == "image":
            img = msg_obj.get("image", {})
            if isinstance(img, dict):
                res["media_id"] = img.get("id")
                res["media_mime"] = img.get("mime_type", "image/jpeg")
                res["media_caption"] = str(img.get("caption", "")).strip()
                res["text"] = res["media_caption"] or "[FOTO_TERLAMPIR]"

        elif msg_type == "document":
            doc = msg_obj.get("document", {})
            if isinstance(doc, dict):
                res["media_id"] = doc.get("id")
                res["media_mime"] = doc.get("mime_type")
                res["media_filename"] = str(doc.get("filename", "document.pdf")).strip()
                res["media_caption"] = str(doc.get("caption", "")).strip()
                res["text"] = f"[DOKUMEN: {res['media_filename']}]"

        return res
    except Exception as err:
        logger.error(f"[Extract Meta WA Event Error] {err}")
        return res

def get_wa_credentials(tenant_id: str = "boontrack-career", phone_number_id: Optional[str] = None, access_token: Optional[str] = None) -> Tuple[str, str, str]:
    default_token = (
        os.getenv("WHATSAPP_TOKEN")
        or os.getenv("META_WA_TOKEN")
        or os.getenv("WA_TOKEN")
        or os.getenv("META_WA_ACCESS_TOKEN")
        or os.getenv("META_ACCESS_TOKEN")
        or "EAANbiVgBfGQBSQkvsZBc8JmqdEZBJWSrZAWR1gnJep0lkyZAv4O02LKEwjoNAc8lNOvaEeKhtb6pcr45S8wtd5CrSKdoMwEq6A1eJV4Yb140DBOMbmj3wLzo0Y7fZBrus25EJ0xeqXlPbDisP6d4DmZAGkvbJ7hnKfFih3G7L7mn6g56OQVU42dZByNSHNEiwZDZD"
    )
    version = os.getenv("META_GRAPH_VERSION", "v20.0")

    clean_tenant = str(tenant_id).lower().strip() if tenant_id else "ombudi"

    # Priority 1: Explicit overrides from webhook payload
    if phone_number_id and str(phone_number_id).strip():
        resolved_phone_id = str(phone_number_id).strip()
        
        # Guard: cegah nomor Career membalas di toko showcase / retail
        if clean_tenant in ["ombudi", "om-budi", "om_budi", "onlineboost", "growthplus", "proscale"] and resolved_phone_id == "1340866379104241":
            resolved_phone_id = os.getenv("OM_BUDI_PHONE_NUMBER_ID") or "1268977686299719"

        resolved_token = str(access_token).strip() if access_token else default_token
        if not access_token:
            if resolved_phone_id == (os.getenv("CAREER_PHONE_NUMBER_ID") or "1340866379104241"):
                resolved_token = (os.getenv("CAREER_ACCESS_TOKEN") or "").strip() or default_token
            elif resolved_phone_id == (os.getenv("OM_BUDI_PHONE_NUMBER_ID") or "1268977686299719"):
                resolved_token = (os.getenv("OM_BUDI_ACCESS_TOKEN") or "").strip() or default_token
            elif resolved_phone_id == (os.getenv("PHONE_NUMBER_ID") or "1306479742542883"):
                resolved_token = (os.getenv("ADUAN_ACCESS_TOKEN") or "").strip() or default_token
        return (resolved_token or default_token).strip(), resolved_phone_id, version

    # Priority 2: Tenant-based resolution
    if clean_tenant in ["ombudi", "om-budi", "om_budi", "onlineboost", "growthplus", "proscale"]:
        phone_id = (os.getenv("OM_BUDI_PHONE_NUMBER_ID") or "").strip() or "1268977686299719"
        token = (os.getenv("OM_BUDI_ACCESS_TOKEN") or "").strip() or default_token
        return token.strip(), str(phone_id).strip(), version

    if clean_tenant in ["boontrack-career", "career"]:
        phone_id = (os.getenv("CAREER_PHONE_NUMBER_ID") or "").strip() or "1340866379104241"
        token = (os.getenv("CAREER_ACCESS_TOKEN") or "").strip() or default_token
        return token.strip(), str(phone_id).strip(), version

    if clean_tenant in ["aduan", "aduan-sandbox", "sandbox"]:
        phone_id = (os.getenv("PHONE_NUMBER_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip() or "1306479742542883"
        token = (os.getenv("ADUAN_ACCESS_TOKEN") or "").strip() or default_token
        return token.strip(), str(phone_id).strip(), version

    phone_id = (os.getenv("OM_BUDI_PHONE_NUMBER_ID") or "").strip() or "1268977686299719"
    return default_token.strip(), str(phone_id).strip(), version

def _get_auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

async def send_whatsapp_text(to_phone: str, text: str, preview_url: bool = False, tenant_id: str = "boontrack-career", phone_number_id: Optional[str] = None, access_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    if not token or not phone_id:
        logger.error(f"[WhatsApp Service] Missing credentials (phone_id={phone_id}, tenant={tenant_id})")
        return None

    clean_phone = normalize_phone_number(to_phone)
    if not clean_phone:
        logger.error(f"[WhatsApp Service] Invalid phone number provided: {to_phone}")
        return None

    sanitized_text = sanitize_whatsapp_message_text(text)
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "text",
        "text": {
            "preview_url": preview_url,
            "body": sanitized_text
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.error(f"[WhatsApp Service] send_text failed: {response.status_code} - {response.text}")
                return None
            
            await log_to_supabase_messages(
                sender="bot",
                text=sanitized_text,
                tenant_id=tenant_id,
                channel="whatsapp",
                user_phone=clean_phone,
                user_id=clean_phone,
                conversation_id=clean_phone,
                metadata={"msg_type": "text", "preview_url": preview_url}
            )
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_text: {e}", exc_info=True)
        return None


async def send_otp_whatsapp(
    to_phone: str,
    otp_code: str,
    tenant_id: str = "boontrack-career",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    clean_phone = normalize_phone_number(to_phone)
    if not clean_phone or len(clean_phone) < 10:
        logger.error(f"[WhatsApp OTP] Invalid phone number: {to_phone}")
        return None

    msg = (
        "🔐 *KODE VERIFIKASI RESMI BOONTRACK*\n\n"
        f"Kode OTP Anda: *{otp_code}*\n\n"
        "• Berlaku selama *5 menit*.\n"
        "• Jangan berikan kode ini kepada siapa pun demi keamanan akun Anda.\n\n"
        "_Pesan otomatis dari Meta Cloud API Gateway BoonTrack Career._"
    )
    return await send_whatsapp_text(clean_phone, msg, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)


async def send_ereceipt_whatsapp(
    to_phone: str,
    order_data: Dict[str, Any],
    tenant_id: str = "boontrack-career",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    clean_phone = normalize_phone_number(to_phone)
    if not clean_phone or len(clean_phone) < 10:
        return None

    order_id = str(
        order_data.get("order_id")
        or order_data.get("id")
        or order_data.get("external_id")
        or "ORD-UNKNOWN"
    )
    raw_amount = (
        order_data.get("amount")
        or order_data.get("total_amount")
        or order_data.get("gross_amount")
        or 0
    )
    try:
        amt_val = int(float(raw_amount))
    except (ValueError, TypeError):
        amt_val = 0
    amt_str = f"Rp{amt_val:,}".replace(",", ".")

    customer_name = str(order_data.get("customer_name") or order_data.get("name") or "Pelanggan Terhormat").strip()
    payment_method = str(order_data.get("payment_method") or order_data.get("method") or "QRIS Dinamis").upper()
    paid_time = str(order_data.get("paid_at") or datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M:%S UTC"))
    product_name = str(order_data.get("product_name") or order_data.get("title") or "Layanan / Produk Digital")

    delivery_url = order_data.get("delivery_url") or order_data.get("download_url") or ""
    delivery_section = f"📦 *AKSES / TAUTAN PENGIRIMAN:*\n👉 {delivery_url}\n\n" if delivery_url else ""

    receipt_msg = (
        "🧾 *BUKTI PEMBAYARAN RESMI (E-RECEIPT)* 🧾\n"
        "*BOONTRACK COMMERCE NETWORK*\n\n"
        f"Halo *{customer_name}*, terima kasih! Pembayaran Anda telah berhasil diverifikasi oleh payment gateway resmi.\n\n"
        "📋 *RINCIAN TRANSAKSI:*\n"
        f"• *Nomor Pesanan*: `{order_id}`\n"
        f"• *Item*: {product_name}\n"
        f"• *Total Nominal*: *{amt_str}*\n"
        f"• *Metode Bayar*: {payment_method}\n"
        f"• *Status*: *LUNAS (PAID / SETTLED)*\n"
        f"• *Waktu Verifikasi*: {paid_time}\n\n"
        f"{delivery_section}"
        "Pesanan Anda otomatis diproses dan tercatat aman di sistem. Terima kasih atas kepercayaan Anda! 🙏"
    )

    return await send_whatsapp_text(clean_phone, receipt_msg, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)


async def send_whatsapp_buttons(to_phone: str, body_text: str, buttons: List[Dict[str, str]], header_text: str = "", footer_text: str = "", tenant_id: str = "boontrack-career", phone_number_id: Optional[str] = None, access_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    if not token or not phone_id:
        return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)

    clean_phone = str(to_phone).replace("+", "").strip()
    sanitized_body = sanitize_whatsapp_message_text(body_text)
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        **_get_auth_headers(token),
        "Content-Type": "application/json"
    }

    button_action_list = []
    for btn in buttons[:3]:
        button_action_list.append({
            "type": "reply",
            "reply": {
                "id": btn.get("id", "btn_id"),
                "title": btn.get("title", "Tombol")[:20]
            }
        })

    interactive_obj: Dict[str, Any] = {
        "type": "button",
        "body": {"text": sanitized_body},
        "action": {"buttons": button_action_list}
    }

    if header_text:
        interactive_obj["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive_obj["footer"] = {"text": footer_text}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "interactive",
        "interactive": interactive_obj
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)
            
            await log_to_supabase_messages(
                sender="bot",
                text=body_text,
                tenant_id=tenant_id,
                channel="whatsapp",
                user_phone=clean_phone,
                user_id=clean_phone,
                conversation_id=clean_phone,
                metadata={"msg_type": "buttons", "buttons": buttons}
            )
            return response.json()
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_buttons: {e}", exc_info=True)
        return await send_whatsapp_text(to_phone, body_text, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)

async def upload_media(bytes_data: bytes, mime_type: str = "image/png", filename: str = "qris.png", tenant_id: str = "boontrack-career", phone_number_id: Optional[str] = None, access_token: Optional[str] = None) -> Optional[str]:
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    if not token or not phone_id:
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        files = {"file": (filename, bytes_data, mime_type)}
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            if response.status_code not in (200, 201):
                logger.warning(f"[WhatsApp Service] upload_media failed: HTTP {response.status_code} - {response.text}")
                return None
            res_json = response.json()
            return str(res_json.get("id"))
    except Exception as e:
        logger.warning(f"[WhatsApp Service] Exception in upload_media: {e}")
        return None

async def upload_whatsapp_media(file_bytes: bytes, filename: str, mime_type: str, tenant_id: str = "boontrack-career", phone_number_id: Optional[str] = None, access_token: Optional[str] = None) -> Optional[str]:
    return await upload_media(bytes_data=file_bytes, mime_type=mime_type, filename=filename, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)

async def send_whatsapp_image_link(
    to: str = "",
    image_url: str = "",
    caption: str = "",
    tenant: str = "boontrack-career",
    to_phone: Optional[str] = None,
    tenant_id: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    target_phone = str(to or to_phone or "").replace("+", "").strip()
    effective_tenant = str(tenant or tenant_id or "boontrack-career").strip()
    token, phone_id, version = get_wa_credentials(effective_tenant, phone_number_id=phone_number_id, access_token=access_token)
    if not token or not phone_id:
        return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    safe_caption = (caption or "")[:1024]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": target_phone,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": safe_caption
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in (200, 201):
                logger.warning(f"[WhatsApp Service] send_whatsapp_image_link failed (HTTP {response.status_code}): {response.text}")
                return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)

            res_data = response.json()
            await log_to_supabase_messages(
                sender="bot",
                text=f"[Kirim Gambar Link] {caption}".strip(),
                tenant_id=effective_tenant,
                channel="whatsapp",
                user_phone=target_phone,
                user_id=target_phone,
                conversation_id=target_phone,
                metadata={"msg_type": "image", "caption": caption, "link": image_url}
            )
            return res_data
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in send_whatsapp_image_link: {e}")
        return await send_whatsapp_text(target_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)

async def send_whatsapp_image(
    to_phone: str = "",
    image_path_or_bytes: Optional[Union[str, bytes, io.BytesIO]] = None,
    caption: str = "",
    tenant_id: str = "boontrack-career",
    to: Optional[str] = None,
    image_bytes: Optional[Union[str, bytes, io.BytesIO]] = None,
    tenant: Optional[str] = None,
    media_id: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    target_phone = str(to or to_phone or "").strip()
    img_data = image_bytes if image_bytes is not None else image_path_or_bytes
    effective_tenant = str(tenant or tenant_id or "boontrack-career").strip()

    token, phone_id, version = get_wa_credentials(effective_tenant, phone_number_id=phone_number_id, access_token=access_token)
    clean_phone = str(target_phone).replace("+", "").strip()

    if isinstance(img_data, str) and img_data.startswith(("http://", "https://")):
        return await send_whatsapp_image_link(
            to=clean_phone,
            image_url=img_data,
            caption=caption,
            tenant=effective_tenant,
            phone_number_id=phone_number_id,
            access_token=access_token,
        )

    resolved_media_id = media_id
    if not resolved_media_id and img_data:
        b_data: Optional[bytes] = None
        if isinstance(img_data, io.BytesIO):
            b_data = img_data.getvalue()
        elif isinstance(img_data, bytes):
            b_data = img_data
        elif isinstance(img_data, str) and os.path.exists(img_data):
            try:
                with open(img_data, "rb") as f:
                    b_data = f.read()
            except Exception:
                pass

        if b_data:
            resolved_media_id = await upload_media(
                bytes_data=b_data, 
                mime_type="image/png", 
                filename="qris_code.png", 
                tenant_id=effective_tenant,
                phone_number_id=phone_number_id,
                access_token=access_token
            )

    if resolved_media_id:
        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        safe_caption = (caption or "")[:1024]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": {
                "id": str(resolved_media_id),
                "caption": safe_caption
            }
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    await log_to_supabase_messages(
                        sender="bot",
                        text=f"[Kirim Gambar] {caption}".strip(),
                        tenant_id=effective_tenant,
                        channel="whatsapp",
                        user_phone=clean_phone,
                        user_id=clean_phone,
                        conversation_id=clean_phone,
                        metadata={"msg_type": "image", "media_id": str(resolved_media_id)}
                    )
                    return resp.json()
                logger.warning(f"[WhatsApp Service] send_whatsapp_image failed (HTTP {resp.status_code}): {resp.text}")
        except Exception as e:
            logger.warning(f"[WhatsApp Service] Exception in send_whatsapp_image: {e}")

    return await send_whatsapp_text(clean_phone, caption, tenant_id=effective_tenant, phone_number_id=phone_number_id, access_token=access_token)

async def send_whatsapp_document(
    to_phone: str,
    file_path_or_bytes: Union[str, bytes],
    filename: str = "CV_Hasil_Polish.docx",
    caption: str = "",
    mime_type: Optional[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    tenant_id: str = "boontrack-career",
    phone_number_id: Optional[str] = None,
    access_token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    token, phone_id, version = get_wa_credentials(tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    clean_phone = str(to_phone).replace("+", "").strip()

    if not token or not phone_id:
        return None

    if not mime_type:
        guessed, _ = mimetypes.guess_type(filename)
        mime_type = guessed or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    if isinstance(file_path_or_bytes, str) and file_path_or_bytes.startswith(("http://", "https://")):
        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers = {**_get_auth_headers(token), "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "document",
            "document": {"link": file_path_or_bytes, "filename": filename, "caption": caption}
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code in (200, 201):
                    await log_to_supabase_messages(
                        sender="bot",
                        text=f"[Kirim Dokumen: {filename}] {caption}".strip(),
                        tenant_id=tenant_id,
                        channel="whatsapp",
                        user_phone=clean_phone,
                        user_id=clean_phone,
                        conversation_id=clean_phone,
                        metadata={"msg_type": "document", "filename": filename, "url": file_path_or_bytes}
                    )
                    return res.json()
        except Exception:
            pass

    file_bytes: Optional[bytes] = None
    if isinstance(file_path_or_bytes, bytes):
        file_bytes = file_path_or_bytes
    elif isinstance(file_path_or_bytes, str):
        candidate_paths = [
            file_path_or_bytes,
            os.path.join(os.getcwd(), file_path_or_bytes),
            os.path.join(os.getcwd(), "output", tenant_id, file_path_or_bytes),
            os.path.join(os.getcwd(), "data", "r2_mock_storage", file_path_or_bytes.lstrip("/"))
        ]
        for p in candidate_paths:
            if os.path.exists(p) and os.path.isfile(p):
                try:
                    with open(p, "rb") as f:
                        file_bytes = f.read()
                    break
                except Exception:
                    pass

    if not file_bytes:
        return None

    media_id = await upload_whatsapp_media(file_bytes, filename, mime_type, tenant_id=tenant_id, phone_number_id=phone_number_id, access_token=access_token)
    if not media_id:
        return None

    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {**_get_auth_headers(token), "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "document",
        "document": {"id": media_id, "filename": filename, "caption": caption}
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code in (200, 201):
                await log_to_supabase_messages(
                    sender="bot",
                    text=f"[Kirim Dokumen: {filename}] {caption}".strip(),
                    tenant_id=tenant_id,
                    channel="whatsapp",
                    user_phone=clean_phone,
                    user_id=clean_phone,
                    conversation_id=clean_phone,
                    metadata={"msg_type": "document", "filename": filename, "media_id": media_id}
                )
                return response.json()
    except Exception:
        pass
    return None

async def download_whatsapp_media_by_id(media_id: str, phone_number_id: Optional[str] = None, access_token: Optional[str] = None) -> Optional[bytes]:
    token, _, version = get_wa_credentials(phone_number_id=phone_number_id, access_token=access_token)
    if not token:
        return None

    headers = _get_auth_headers(token)
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            meta_res = await client.get(f"https://graph.facebook.com/{version}/{media_id}", headers=headers)
            if meta_res.status_code != 200:
                return None

            download_url = meta_res.json().get("url")
            if not download_url:
                return None

            file_res = await client.get(download_url, headers=headers)
            if file_res.status_code == 200:
                return file_res.content
            return None
    except Exception as e:
        logger.error(f"[WhatsApp Service] Exception in download_whatsapp_media_by_id: {e}")
        return None


# =====================================================================
# EVOLUTION API V2 ADAPTER (GROWTH PLAN - QR & PAIRING CODE)
# =====================================================================

EVOLUTION_BASE_URL = os.getenv("WA_GATEWAY_BASE_URL", "https://evolution-api-production-abb7.up.railway.app").rstrip("/")
EVOLUTION_API_KEY = os.getenv("WA_GATEWAY_INTERNAL_API_KEY", "4398809d97f770b1a2b243ed0ee33bf3312d02dec42be8789ea3512f487f4c5e")

def get_evolution_headers() -> Dict[str, str]:
    return {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }

async def get_or_create_evolution_session(tenant_slug: str = "onlineboost") -> Dict[str, Any]:
    instance_name = f"tenant_{tenant_slug.replace('-', '_')}"
    headers = get_evolution_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            status_res = await client.get(
                f"{EVOLUTION_BASE_URL}/instance/connectionState/{instance_name}",
                headers=headers
            )
            
            if status_res.status_code == 200:
                data = status_res.json()
                state = data.get("instance", {}).get("state") or data.get("state")
                
                if state == "open":
                    owner = data.get("instance", {}).get("ownerJid") or ""
                    phone_number = owner.split("@")[0] if "@" in owner else owner
                    return {
                        "success": True,
                        "status": "CONNECTED",
                        "phone_number": phone_number or None,
                        "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
                    }

            if status_res.status_code in (404, 400):
                create_payload = {
                    "instanceName": instance_name,
                    "token": EVOLUTION_API_KEY,
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS",
                    "clientName": "BoonTrack Engine"
                }
                await client.post(
                    f"{EVOLUTION_BASE_URL}/instance/create",
                    headers=headers,
                    json=create_payload
                )

            backend_url = os.getenv("BACKEND_WEBHOOK_URL") or os.getenv("FASTAPI_BASE_URL", "https://boontrack-core-production.up.railway.app").rstrip("/")
            try:
                await client.post(
                    f"{EVOLUTION_BASE_URL}/webhook/set/{instance_name}",
                    headers=headers,
                    json={
                        "webhook": {
                            "enabled": True,
                            "url": f"{backend_url}/api/v1/whatsapp/webhook/evolution/{tenant_slug}",
                            "byEvents": False,
                            "base64": False,
                            "events": ["MESSAGES_UPSERT"]
                        }
                    }
                )
            except Exception as hook_err:
                logger.debug(f"[Evolution Webhook Setup Note] {hook_err}")

            qr_res = await client.get(
                f"{EVOLUTION_BASE_URL}/instance/connect/{instance_name}",
                headers=headers
            )
            
            if qr_res.status_code in (200, 201):
                qr_data = qr_res.json()
                qr_raw = qr_data.get("code") or qr_data.get("pairingCode")
                qr_base64 = qr_data.get("base64")

                return {
                    "success": True,
                    "status": "CONNECTING",
                    "qr_raw": qr_raw,
                    "qr_image": qr_base64 if (qr_base64 and qr_base64.startswith("data:image")) else None,
                    "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
                }

            return {
                "success": False,
                "status": "DEGRADED",
                "disconnect_reason": "GATEWAY_SESSION_PENDING",
                "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
            }

        except Exception as e:
            logger.error(f"[Evolution API Handshake Error] {e}")
            return {
                "success": False,
                "status": "DEGRADED",
                "disconnect_reason": "GATEWAY_UNREACHABLE",
                "capabilities": {"qr_pairing": True, "pairing_code": True, "multi_agent": False}
            }