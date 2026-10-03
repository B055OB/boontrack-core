"""app/services/official_support_router.py
Omnichannel VIP Upsell & Setup Toko Routing Engine (Bot 081215567168).

Architectural Authority (§24.3, §27.4):
- Ingress router for official support bot 081215567168 / instance 'boontrack-app-shop' / 'boon'.
- Identifies sender_phone against tenant admins in Supabase database.
- If sender matches tenant admin, activates VIP Mode:
  Greeting: "Halo Kak [owner_name] dari [shop_name]!"
- If message contains "Setup Toko Terima Beres":
  Presents Paket Terima Beres details (Maks 15 SKU / 30 Varian, SLA 1x24 jam, Rp 149.000).
- Offers Dynamic QRIS BCA issuance directly in WhatsApp chat.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

from app.services.whatsapp_service import get_supabase
from app.services.xendit_service import xendit_service

logger = logging.getLogger("OFFICIAL_SUPPORT_ROUTER")

PAKET_TERIMA_BERES_PRICE = 149000
PAKET_TERIMA_BERES_TITLE = "Paket Terima Beres Setup Toko (Maks 15 SKU / 30 Varian)"


def normalize_phone_digits(phone: str) -> str:
    """Normalizes phone string to digits only without leading 0, +, or 62."""
    digits = "".join(c for c in str(phone or "") if c.isdigit())
    if digits.startswith("62"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    return digits


async def find_tenant_by_admin_phone_or_text(
    sender_phone: str,
    incoming_text: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Identifies if sender_phone matches an admin/owner in Supabase tenants table,
    or extracts tenant slug from incoming text query: 'pemilik toko {{slug}}'.
    Optimized with direct indexed Supabase query without linear scan cap.
    """
    supabase = get_supabase()
    if not supabase:
        return None

    # 1. Check if text specifies slug explicitly: 'pemilik toko <slug>'
    if incoming_text:
        slug_match = re.search(r"pemilik\s+toko\s+([a-zA-Z0-9_-]+)", incoming_text, re.IGNORECASE)
        if slug_match:
            target_slug = slug_match.group(1).strip().lower()
            try:
                res = supabase.from_("tenants").select("id, slug, name, tier, metadata").eq("slug", target_slug).maybe_single().execute()
                if res and getattr(res, "data", None):
                    logger.info(f"[VIP_ROUTER] Identified tenant '{target_slug}' from text query payload.")
                    return res.data
            except Exception as e:
                logger.debug(f"[VIP_ROUTER_SLUG_MATCH_WARN] {e}")

    # 2. Check by sender_phone variants (62... and 0...)
    clean_digits = normalize_phone_digits(sender_phone)
    if not clean_digits:
        return None

    p62 = "62" + clean_digits
    p0 = "0" + clean_digits
    or_conds = [
        f"metadata->>phone.eq.{p62}",
        f"metadata->>phone.eq.{p0}",
        f"metadata->>whatsapp_number.eq.{p62}",
        f"metadata->>whatsapp_number.eq.{p0}",
        f"metadata->>wa_verified_phone.eq.{p62}",
        f"metadata->>wa_verified_phone.eq.{p0}",
        f"metadata->>wa_number.eq.{p62}",
        f"metadata->>wa_number.eq.{p0}",
    ]
    or_filter = ",".join(or_conds)

    try:
        res = supabase.from_("tenants").select("id, slug, name, tier, metadata").or_(or_filter).execute()
        if res and getattr(res, "data", None):
            matched = res.data[0]
            logger.info(f"[VIP_ROUTER] Matched sender {sender_phone} to tenant '{matched.get('slug')}' via direct metadata query")
            return matched

        # Fallback via whatsapp_connections lookup
        conn_res = supabase.from_("whatsapp_connections").select("tenant_id, tenant_slug").or_(f"phone_number.eq.{p62},phone_number.eq.{p0}").execute()
        if conn_res and getattr(conn_res, "data", None):
            t_id = conn_res.data[0].get("tenant_id")
            t_slug = conn_res.data[0].get("tenant_slug")
            if t_id and t_id not in ("boon", "52967979-4760-4cea-b686-cdbdb389c0e1"):
                t_res = supabase.from_("tenants").select("id, slug, name, tier, metadata").or_(f"id.eq.{t_id},slug.eq.{t_slug or t_id}").execute()
                if t_res and getattr(t_res, "data", None):
                    matched = t_res.data[0]
                    logger.info(f"[VIP_ROUTER] Matched sender {sender_phone} to tenant '{matched.get('slug')}' via whatsapp_connections")
                    return matched
    except Exception as err:
        logger.error(f"[VIP_ROUTER_DB_ERROR] Failed looking up tenant for {sender_phone}: {err}")

    return None


async def handle_official_support_vip_upsell(
    incoming_text: str,
    sender_phone: str,
    contact_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Evaluates incoming WhatsApp message to 081215567168:
    1. Checks if keyword 'Setup Toko Terima Beres' or payment confirmation 'YA BAYAR QRIS' is present.
    2. Identifies tenant admin for Mode VIP personalization.
    3. Returns response payload with VIP greeting, package details, or Dynamic QRIS BCA.
    """
    if not incoming_text:
        return None

    text_lower = incoming_text.lower().strip()

    is_upsell_intent = any(kw in text_lower for kw in [
        "setup toko terima beres",
        "terima beres",
        "setup terima beres",
        "jasa setup toko",
        "dibantu setup toko",
        "bantu setup toko",
    ])

    is_qris_confirmation = any(kw in text_lower for kw in [
        "ya bayar qris",
        "bayar qris",
        "proses qris",
        "terbitkan qris",
        "mau bayar qris",
        "minta qris",
        "kirim qris terima beres",
    ])

    if not is_upsell_intent and not is_qris_confirmation:
        return None

    # Lookup tenant in database to activate VIP Mode
    tenant = await find_tenant_by_admin_phone_or_text(sender_phone, incoming_text)

    is_vip = tenant is not None
    if is_vip:
        meta = tenant.get("metadata") or {}
        owner_name = meta.get("merchant_name") or meta.get("owner_name") or contact_name or "Owner"
        shop_name = tenant.get("name") or meta.get("shop_name") or meta.get("store_name") or tenant.get("slug")
        greeting = f"Halo Kak *{owner_name}* dari *{shop_name}*! 👑"
        tenant_slug = tenant.get("slug")
    else:
        target_name = contact_name if contact_name and contact_name != "Kakak" else "Kak"
        greeting = f"Halo {target_name}! 👋"
        tenant_slug = "merchant"

    # Branch A: Konfirmasi Bayar & Penerbitan Dynamic QRIS BCA Langsung di Chat
    if is_qris_confirmation:
        external_id = f"SETUP-{tenant_slug}-{int(datetime.now(timezone.utc).timestamp())}"
        qris_data: Dict[str, Any] = {}
        try:
            qris_data = await xendit_service.create_qr_code(
                external_id=external_id,
                amount=PAKET_TERIMA_BERES_PRICE,
                tenant_id=tenant_slug,
                customer_phone=sender_phone,
                metadata={
                    "product_name": PAKET_TERIMA_BERES_TITLE,
                    "type": "terima_beres_setup",
                    "tenant_slug": tenant_slug,
                },
            )
        except Exception as q_err:
            logger.warning(f"[VIP_QRIS_GEN_WARN] {q_err}")

        invoice_url = qris_data.get("invoice_url") or qris_data.get("web_pay_url") or f"https://shop.boontrack.com/checkout/{external_id}"
        qr_image_url = qris_data.get("qr_code_url") or qris_data.get("qr_image_url")

        reply_lines = [
            f"{greeting}",
            "",
            "Berikut adalah tagihan *Dynamic QRIS BCA* resmi untuk pesanan *Paket Setup Toko Terima Beres* Kakak:",
            "",
            "📋 *Rincian Pesanan:*",
            f"• *Paket:* {PAKET_TERIMA_BERES_TITLE}",
            f"• *Total Tagihan:* Rp 149.000",
            f"• *ID Transaksi:* `{external_id}`",
            "• *SLA Pengerjaan:* 1x24 Jam Kerja setelah pembayaran lunas",
            "",
            f"👉 *Tautan Pembayaran QRIS & Virtual Account:*\n{invoice_url}",
            "",
            "💡 *Panduan Pembayaran:*",
            "1. Buka aplikasi BCA Mobile, myBCA, GoPay, OVO, ShopeePay, atau m-Banking pilihan Kakak.",
            f"2. Scan kode QR atau buka link tagihan di atas dan bayar nominal persis *Rp 149.000*.",
            "3. Sistem kami akan memverifikasi pembayaran secara otomatis (0% biaya MDR).",
            "",
            "Setelah pembayaran selesai, tim teknis kami akan langsung menghubungi Kakak untuk meminta brief foto produk & mulai pengerjaan toko Kakak sampai tuntas! ✨"
        ]
        reply_text = "\n".join(reply_lines)

        return {
            "status": "success",
            "is_vip": is_vip,
            "tenant_slug": tenant_slug,
            "reply_text": reply_text,
            "media_url": qr_image_url,
            "action": "DYNAMIC_QRIS_ISSUED",
        }

    # Branch B: Penjelasan Rinci Paket Terima Beres & Penawaran Dynamic QRIS BCA
    reply_lines = [
        f"{greeting} Terima kasih telah menghubungi Tim IT Resmi BoonTrack 🛍️✨",
        "",
        "Senang sekali Kakak berminat dengan layanan *Paket Setup Toko Terima Beres*! Kami siap membantu toko Kakak live jualan tanpa pusing teknis.",
        "",
        "📦 *Rincian Paket Setup Toko Terima Beres:*",
        "• *Kapasitas Katalog:* Maksimal 15 SKU / 30 Varian Produk (Warna, Ukuran, dsb)",
        "• *SLA Pengerjaan:* 1x24 Jam Kerja (Langsung Siap Pakai & Tayang)",
        f"• *Investasi Layanan:* Rp 149.000 (Sekali Bayar / No Hidden Fee)",
        "",
        "🛠️ *Apa Saja yang Dikerjakan Tim IT Kami?*",
        "1. *Input Katalog Lengkap*: Kami rapikan foto produk, buat varian rapi, dan tulis deskripsi copywriting yang memikat pembeli.",
        "2. *Setup AI CS WhatsApp*: Kami tuning bot WhatsApp toko Kakak agar menjawab ramah, natural, dan pintar mengarahkan pembeli ke checkout.",
        "3. *Integrasi Dynamic QRIS BCA*: Setting barcode pembayaran otomatis real-time (0% fee MDR) langsung masuk ke rekening Kakak.",
        "4. *Quality Control & Simulasi*: Kami uji coba langsung seluruh alur transaksi dari chat sampai konfirmasi lunas.",
        "",
        f"Apakah Kakak ingin kami langsung terbitkan tagihan *Dynamic QRIS BCA* (Rp 149.000) di sini agar tim teknis kami bisa langsung mulai proses pengerjaan toko Kakak?",
        "",
        "👉 Balas *YA BAYAR QRIS* untuk menerbitkan kode QRIS resmi langsung di chat ini! 🚀"
    ]
    reply_text = "\n".join(reply_lines)

    return {
        "status": "success",
        "is_vip": is_vip,
        "tenant_slug": tenant_slug,
        "reply_text": reply_text,
        "media_url": None,
        "action": "UPSELL_PRESENTED",
    }



async def resolve_official_bot_dual_role(
    incoming_text: str,
    sender_phone: str,
    contact_name: Optional[str] = None,
    conversation_scope: str = "DIRECT",
    group_jid: Optional[str] = None,
    image_base64: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Dual-Role Resolver & Message Dispatcher for Official WhatsApp Bot (081215567168 / boontrack-app-shop).
    
    Roles:
    1. GROUP / Non-Tenant DM: Sales Representative & Onboarding Concierge
       (Edukasi fitur platform, 2 CTA resmi: demo URL & register link dengan atribusi granular dari channel_bindings).
    2. REGISTERED MERCHANT DM: Personal AI Assistant (BoonPilot Toko)
       (Analisa dashboard, konsultasi angle iklan, copywriting, operasional katalog & pesanan).
       STRICT GUARD: Dilarang keras menawarkan pendaftaran toko baru (/register) kepada merchant terdaftar.
    """
    import urllib.parse
    from app.whatsapp.traffic_splitter import generate_group_boonpilot_reply

    supabase = get_supabase()
    clean_text = re.sub(r"@[\w.]+", "", incoming_text).strip() if incoming_text else ""

    # =========================================================================
    # ROLE 1: GROUP CONVERSATION SCOPE
    # =========================================================================
    if conversation_scope == "GROUP":
        lookup_jid = group_jid or sender_phone

        # ---------------------------------------------------------------------
        # FITUR CEK ID INSTAN (@boon id / /id / !id)
        # ---------------------------------------------------------------------
        raw_text_lower = (incoming_text or "").lower().strip()
        clean_lower = clean_text.lower().strip()
        is_id_command = (
            clean_lower in ("id", "/id", "!id", "cek id", "group id", "jid", "get id")
            or raw_text_lower in ("@boon id", "/id", "!id", "id", "@boontrack id")
            or raw_text_lower.startswith("@boon id")
            or raw_text_lower.startswith("/id")
            or raw_text_lower.startswith("!id")
        )
        if is_id_command:
            reply_text = f"🆔 *ID Grup WhatsApp Ini:*\n`{lookup_jid}`\n\nSalin ID di atas untuk dimasukkan ke dashboard affiliate."
            return {
                "status": "success",
                "role": "GROUP_ID_COMMAND",
                "tenant_slug": "boon",
                "reply_text": reply_text,
                "media_url": None,
                "demo_url": None,
                "register_url": None,
            }
        wa_binding = None
        if supabase and lookup_jid:
            try:
                res_cb = supabase.table("channel_bindings").select("*").eq("community_source_id", lookup_jid).eq("is_active", True).execute()
                if res_cb and getattr(res_cb, "data", None):
                    wa_binding = res_cb.data[0]
            except Exception as _cb_err:
                logger.warning(f"[WA_GROUP_CHANNEL_BINDING_ERR] {_cb_err}")

        if wa_binding:
            aff_id = wa_binding.get("affiliate_id") or "ob"
            demo_url = wa_binding.get("demo_url") or "https://shop.boontrack.com/boon"
            register_url = f"https://shop.boontrack.com/register?ref={urllib.parse.quote(aff_id)}&src={urllib.parse.quote(lookup_jid)}"
        else:
            demo_url = "https://shop.boontrack.com/boon"
            register_url = "https://shop.boontrack.com/register"

        # Check if message is a simple greeting or general mention
        text_lower = clean_text.lower().strip()
        is_simple_prompt = (
            not clean_text
            or len(clean_text) <= 12
            or text_lower in ("halo", "hai", "info", "demo", "daftar", "tes", "test", "p", "halo boon", "siang", "malam", "pagi")
        )

        if is_simple_prompt:
            reply_text = (
                "👋 *Halo dari BoonTrack!*\n"
                "Platform otomatisasi checkout & katalog digital 24 jam untuk pebisnis online & UKM.\n\n"
                f"🛍️ *Cek Contoh Demo:*\n{demo_url}\n\n"
                f"🚀 *Buka Toko Online / Coba Gratis:*\n{register_url}"
            )
            return {
                "status": "success",
                "role": "SALES_REP_GROUP",
                "tenant_slug": "boon",
                "reply_text": reply_text,
                "media_url": None,
                "demo_url": demo_url,
                "register_url": register_url,
            }

        # Specific inquiry in group: answer with Sales Rep AI and append dynamic CTAs
        group_sales_prompt = f"""\
Anda adalah "BoonPilot", Sales Representative & Konsultan Resmi BoonTrack (https://boontrack.com) di grup komunitas WhatsApp.
Gaya Komunikasi: Hangat, santai, solutif, dan profesional dalam Bahasa Indonesia.
Tugas Anda: Menjawab pertanyaan seputar platform BoonTrack (checkout instan, auto-verifikasi QRIS 0% MDR, kurir agregator, notifikasi WhatsApp).
Tautan Demo Resmi: {demo_url}
Tautan Daftar Uji Coba: {register_url}

ATURAN:
- Jawab pertanyaan secara ringkas dan bersahabat (1-2 paragraf).
- Di akhir jawaban, sertakan tautan demo ({demo_url}) dan daftar uji coba ({register_url}).
"""
        ai_reply = await generate_group_boonpilot_reply(
            clean_text,
            image_base64=image_base64,
            mime_type=mime_type,
            custom_system_prompt=group_sales_prompt,
        )

        # Ensure demo & register URLs are appended if AI omitted them
        if demo_url not in ai_reply and register_url not in ai_reply:
            ai_reply = f"{ai_reply}\n\n🛍️ *Cek Contoh Demo:*\n{demo_url}\n\n🚀 *Buka Toko Online / Coba Gratis:*\n{register_url}"

        return {
            "status": "success",
            "role": "SALES_REP_GROUP",
            "tenant_slug": "boon",
            "reply_text": ai_reply,
            "media_url": None,
            "demo_url": demo_url,
            "register_url": register_url,
        }

    # =========================================================================
    # ROLE 2: DIRECT / PERSONAL DM CONVERSATION SCOPE
    # =========================================================================

    # 1. Check Omnichannel VIP Upsell Router ("Setup Toko Terima Beres" / QRIS BCA)
    vip_res = await handle_official_support_vip_upsell(
        incoming_text=incoming_text,
        sender_phone=sender_phone,
        contact_name=contact_name,
    )
    if vip_res and vip_res.get("reply_text"):
        return vip_res

    # 2. Query sender against registered merchant/tenants
    merchant_tenant = await find_tenant_by_admin_phone_or_text(sender_phone, incoming_text)

    # -------------------------------------------------------------------------
    # SUB-ROLE A: REGISTERED MERCHANT -> BoonPilot Toko (Business Co-Pilot)
    # -------------------------------------------------------------------------
    if merchant_tenant:
        m_meta = merchant_tenant.get("metadata") or {}
        store_name = merchant_tenant.get("name") or merchant_tenant.get("slug")
        store_slug = merchant_tenant.get("slug")
        tier = merchant_tenant.get("tier") or "SOLO"
        owner_name = m_meta.get("owner_name") or m_meta.get("merchant_name") or m_meta.get("pic_name") or contact_name or "Owner"

        merchant_prompt = f"""\
Anda adalah "BoonPilot", Asisten Pribadi Toko & Business Co-Pilot resmi untuk toko "{store_name}" (Tier: {tier}, Pemilik: Kak {owner_name}) di platform BoonTrack.
Gaya Komunikasi: Rekan bisnis yang cerdas, suportif, santun, solutif, dan profesional dalam Bahasa Indonesia.

PERAN & TUGAS UTAMA (MERCHANT TOKO "{store_name}"):
1. Bantuan operasional toko, cek status order, dan panduan fitur 8 tab dashboard BoonTrack (Overview, Katalog Produk, Pesanan, WhatsApp Gateway, Pengiriman, Pembayaran/QRIS, Tim CS, Pengaturan Toko).
2. Membantu analisis performa toko, screenshot analitik iklan / metrik dashboard (ROAS, CTR, CPA, margin), konsultasi angle iklan, dan copywriting promosi.
3. Membantu pemecahan masalah operasional toko (checkout, ongkir, QRIS, notifikasi WhatsApp).

PANDUAN KHUSUS:
- Jika merchant bertanya tentang order / resi: Ingatkan bahwa ringkasan pesanan real-time dapat diakses di tab Pesanan (Orders) pada dashboard.boontrack.com/{store_slug}.
- Jika merchant mengirimkan gambar / screenshot analitik: Berikan analisa visual objektif metrik dan saran angle iklan.

ATURAN MUTLAK (STRICT RULES):
- DILARANG KERAS menawarkan pendaftaran akun baru atau memberikan link registrasi akun (seperti /register) karena merchant ini SUDAH terdaftar dan aktif memiliki toko "{store_name}".
- Sapa merchant secara ramah dengan menyebut Kak {owner_name} dan nama tokonya "{store_name}".
- ISOLASI DATA (ZERO LEAKAGE): Anda hanya berwenang mendiskusikan toko "{store_name}". Dilarang membocorkan data toko privat tenant lain.
"""
        reply_text = await generate_group_boonpilot_reply(
            clean_text or incoming_text,
            image_base64=image_base64,
            mime_type=mime_type,
            custom_system_prompt=merchant_prompt,
        )

        return {
            "status": "success",
            "role": "BOONPILOT_MERCHANT_ASSISTANT",
            "tenant_slug": store_slug,
            "store_name": store_name,
            "owner_name": owner_name,
            "tier": tier,
            "reply_text": reply_text,
            "media_url": None,
        }

    # -------------------------------------------------------------------------
    # SUB-ROLE B: UNREGISTERED GUEST / LEAD -> Sales Representative & Onboarding
    # -------------------------------------------------------------------------
    default_demo_url = "https://shop.boontrack.com/boon"
    default_register_url = "https://shop.boontrack.com/register"

    sales_rep_prompt = f"""\
Anda adalah "BoonPilot", Sales Representative & Onboarding Concierge resmi platform BoonTrack (https://boontrack.com).
Gaya Komunikasi: Ramah, antusias, solutif, edukatif, dan profesional dalam Bahasa Indonesia.

PERAN & TUGAS UTAMA (CALON MERCHANT / GUEST):
1. Mengedukasi calon pengguna tentang keunggulan dan otomasi platform BoonTrack:
   - Otomasi order & notifikasi WhatsApp (pesanan, invoice, konfirmasi, resi otomatis).
   - Verifikasi pembayaran otomatis real-time (QRIS dinamis 0% fee MDR platform & transfer bank).
   - Single-Page Checkout instan tanpa formulir rumit atau registrasi akun.
   - Agregator Kurir multi-ekspedisi BYOK (Lincah, Biteship, JNE, SiCepat, J&T).
   - Bot AI CS & Admin Penjualan WhatsApp 24 jam.
2. Memandu calon pengguna untuk melihat contoh toko demo resmi: {default_demo_url}
3. Memandu pendaftaran akun baru / uji coba gratis di {default_register_url}
4. Menjelaskan paket harga (Solo, Pro Scale, Team Scale) secara transparan dan menarik.

ATURAN MUTLAK:
- DILARANG menggunakan domain internal developer atau link kadaluarsa (seperti buzzerukm).
- Berikan link demo toko resmi: {default_demo_url}
- Berikan link registrasi resmi: {default_register_url}
"""
    reply_text = await generate_group_boonpilot_reply(
        clean_text or incoming_text,
        image_base64=image_base64,
        mime_type=mime_type,
        custom_system_prompt=sales_rep_prompt,
    )

    return {
        "status": "success",
        "role": "SALES_REP_GUEST",
        "tenant_slug": "boon",
        "reply_text": reply_text,
        "media_url": None,
        "demo_url": default_demo_url,
        "register_url": default_register_url,
    }
