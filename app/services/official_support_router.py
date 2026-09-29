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
    """
    supabase = get_supabase()
    if not supabase:
        return None

    # 1. Check if text specifies slug explicitly: 'pemilik toko <slug>'
    slug_match = re.search(r"pemilik\s+toko\s+([a-zA-Z0-9_-]+)", incoming_text, re.IGNORECASE)
    if slug_match:
        target_slug = slug_match.group(1).strip().lower()
        try:
            res = supabase.from_("tenants").select("id, slug, name, tier, metadata").eq("slug", target_slug).maybe_single().execute()
            if res and res.data:
                logger.info(f"[VIP_ROUTER] Identified tenant '{target_slug}' from text query payload.")
                return res.data
        except Exception as e:
            logger.debug(f"[VIP_ROUTER_SLUG_MATCH_WARN] {e}")

    # 2. Check by sender_phone
    clean_digits = normalize_phone_digits(sender_phone)
    if not clean_digits:
        return None

    try:
        # Search tenants in Supabase
        res = supabase.from_("tenants").select("id, slug, name, tier, metadata").limit(100).execute()
        if res and res.data:
            for row in res.data:
                meta = row.get("metadata") or {}
                candidate_phones = [
                    str(meta.get("phone") or ""),
                    str(meta.get("whatsapp_number") or ""),
                    str(meta.get("wa_verified_phone") or ""),
                    str((meta.get("sales_policy") or {}).get("handover_phone") or ""),
                    str(row.get("access_username") or ""),
                ]
                for cp in candidate_phones:
                    cp_clean = normalize_phone_digits(cp)
                    if cp_clean and (cp_clean == clean_digits or clean_digits.endswith(cp_clean) or cp_clean.endswith(clean_digits)):
                        logger.info(f"[VIP_ROUTER] Matched sender {sender_phone} to tenant '{row.get("slug")}' (admin phone {cp})")
                        return row
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

