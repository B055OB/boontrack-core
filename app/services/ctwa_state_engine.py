"""app/services/ctwa_state_engine.py
Engine Flow WA Bot Specification v2.0 (Tenant 'onlineboost')
WhatsApp Flows Funnel (Single Offer 249K), Value Stacking Hook & Single-Use Telegram Fulfillment.

1. Aturan Penawaran Tunggal & Copywriting Script (Single Offer 249K):
   - Kunci Penawaran Tunggal: Paket Starter dinonaktifkan/dihapus mutlak.
   - Fokus interaksi bot HANYA pada Paket Lengkap Kelas Inkubasi CTWA Batch 1 (Rp249.000).
   - Script Value Stacking dengan Hook Bot Natural & QRIS 0%.

2. WhatsApp Flows Form (Native Form WABA) + Fallback Teks:
   - Jalur Utama: WhatsApp Flows Form (interactive: flow, flow_message_version: '3').
   - Parser: nfm_reply (Flows response) & FAST_TRACK_PATTERN (CTA landing page).
   - Pre-LLM Gatekeeper:
     * Buat order baru PENDING di Supabase orders (Rp249.000 - 3 digit kode unik downward).
     * Bentuk Dynamic QRIS EMVCo Tag 54 presisi (preservasi Tag 62 acquirer sesuai §14.1).
     * Kirim gambar QRIS via Meta Media Endpoint beserta total tagihan presisi.
     * Dispatch server-side event Meta CAPI InitiateCheckout.

3. Post-Payment Fulfillment:
   - Terbitkan single-use Telegram invite link (member_limit=1, expire_date=now+86400).
   - Simpan link ke orders.metadata['telegram_single_invite_link'] (idempoten).
   - Kirim notifikasi sukses via WhatsApp WABA.
   - Dispatch Meta CAPI Purchase.
"""

import re
import os
import json
import uuid
import random
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List, Union
import urllib.parse

from app.services.whatsapp_service import normalize_phone_number, get_supabase
from app.services.whatsapp import cloud_api
from app.utils.qris_generator import (
    generate_dynamic_qris_payload,
    render_qris_bytes,
    generate_unique_code,
)
from app.services.xendit_service import xendit_service
from app.services.qris_generator import generate_qris_png_bytes
from app.modules.tracking.capi_dispatcher import capi_dispatcher
from app.services.ctwa_fulfillment_service import (
    fulfill_onlineboost_ctwa_order,
    create_telegram_single_use_invite_link,
    format_idr,
)

logger = logging.getLogger("CTWA_STATE_ENGINE")

# ============================================================================
# KONFIGURASI SINGLE OFFER (249K) & ASSETS
# ============================================================================

SINGLE_OFFER_PRICE: int = 249000  # Rp 249.000 (Sekali Bayar)
SINGLE_OFFER_NAME: str = "Paket Lengkap Kelas Inkubasi CTWA Batch 1"
SINGLE_OFFER_SLUG: str = "kelas-inkubasi-ctwa-batch-1-scale"
CANONICAL_BATCH1_SKU: str = "OB-BATCH1-249K"
LEGACY_BATCH1_SKU: str = "SKU-BTA-ALUMNI-249K"
STOREFRONT_URL: str = "https://shop.boontrack.com/onlineboost/p/kelas-inkubasi-ctwa-batch-1-scale"

# Master Static QRIS fallback (Official BoonTrack / OnlineBoost QRIS)
DEFAULT_STATIC_QRIS: str = (
    os.getenv("ONLINEBOOST_STATIC_QRIS")
    or os.getenv("BOONTRACK_STATIC_QRIS")
    or "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI"
       "51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID"
       "5909BoonTrack6012Kab. Bandung61054028663048DC1"
).strip()

# Script Penawaran Bot Resmi (Value Stacking dengan Hook Bot Natural & QRIS 0%)
SINGLE_OFFER_VALUE_STACKING_SCRIPT: str = (
    "Pilihan yang sangat tepat, Kak! Untuk program Kelas Inkubasi CTWA (Click to WhatsApp), kami fokus pada Paket Lengkap (Mesin Kasir WhatsApp Otomatis 24 Jam) seharga Rp249.000 (Sekali Bayar).\n\n"
    "Fasilitas dan senjata bisnis yang langsung Kakak dapatkan bernilai lebih dari Rp1.700.000+:\n"
    "🎓 Bimbingan Intensif 10 Langkah Praktis (Nilai Rp999.000) — Step-by-step dari nol sampai pecah telur, dirancang langsung praktik tanpa teori berbelit.\n"
    "🤖 Setup Engine Bot WhatsApp Natural AI (Nilai Rp299.000/bln) — Persis seperti cara saya ngobrol luwes sama Kakak sekarang! Nggak kaku kayak bot jadul, dan setup bot pintar model begini susah banget dicari di luaran sana.\n"
    "💳 Kasir Otomatis Dynamic QRIS 0% MDR Fee — Invoice verifikasi otomatis 24 jam dan uang hasil penjualan 100% utuh masuk ke rekening Kakak tanpa potongan komisi sepeser pun.\n"
    "🎬 Generator Video Iklan 9-Scene (Nilai Rp199.000/bln) — Bikin video iklan konversi tinggi tanpa perlu sewa editor mahal.\n"
    "📊 Ads Performance Tracker + Akun Whitelist (WL) — Iklan satset tanpa drama banned/checkpoint akun baru.\n"
    "🔐 Lisensi Produk Siap Jual + Akses Supergroup Praktikum Eksklusif.\n\n"
    "Total Nilai Fasilitas: ~Rp1.796.000~ 🔥 Spesial Hari Ini: Hanya Rp249.000\n\n"
    "Cek detailnya di sini: 👉 https://shop.boontrack.com/onlineboost/p/kelas-inkubasi-ctwa-batch-1-scale"
)

# Pola regex resmi untuk redirect landing page (Fallback Teks)
FAST_TRACK_PATTERN = re.compile(
    r"Halo Admin, saya atas nama (.+?) \((.+?)\) sudah daftar kelas",
    re.IGNORECASE,
)

# Pola deteksi email dan nama umum di chat
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


class CTWAStateEngine:
    """State Machine Engine & Deterministic Pre-LLM Gatekeeper untuk Tenant onlineboost."""

    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────────

    def get_session(self, phone: str) -> Dict[str, Any]:
        """Ambil atau inisialisasi sesi percakapan untuk nomor telepon."""
        clean_phone = normalize_phone_number(phone) or str(phone).strip()

        if clean_phone in self.sessions:
            return self.sessions[clean_phone]

        # Coba muat dari database
        db_sess = self._load_session_from_db(clean_phone)
        if db_sess:
            self.sessions[clean_phone] = db_sess
            return db_sess

        # Inisialisasi sesi baru
        now_iso = datetime.now(timezone.utc).isoformat()
        session = {
            "phone": clean_phone,
            "tenant_slug": "onlineboost",
            "current_state": "STATE_0",
            "first_contact_at": now_iso,
            "lead_name": None,
            "lead_email": None,
            "selected_package": SINGLE_OFFER_SLUG,
            "order_id": None,
            "invoice_id": None,
            "total_amount": SINGLE_OFFER_PRICE,
            "unique_code": 0,
            "is_settled": False,
        }
        self.sessions[clean_phone] = session
        return session

    def reset_session(self, phone: str) -> None:
        """Reset sesi percakapan untuk nomor telepon menjadi fresh lead."""
        clean_phone = normalize_phone_number(phone) or str(phone).strip()
        self.sessions.pop(clean_phone, None)
        self.sessions.pop(str(phone).strip(), None)
        self._clear_session_from_db(clean_phone)

    def _clear_session_from_db(self, clean_phone: str) -> None:
        """Menghapus session dari database/Supabase conversation_sessions."""
        try:
            sb = get_supabase()
            if sb:
                sb.table("conversation_sessions").delete().eq("tenant_id", "onlineboost").eq("user_identifier", clean_phone).execute()
                sb.table("conversation_sessions").delete().eq("tenant_id", "onlineboost").eq("session_id", f"wa_{clean_phone}").execute()
        except Exception as e:
            logger.debug(f"[CTWA Clear DB Session Note] {e}")
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM conversation_sessions WHERE tenant_id = 'onlineboost' AND (user_identifier = %s OR session_id = %s)",
                    (clean_phone, f"wa_{clean_phone}")
                )
                conn.commit()
            conn.close()
        except Exception as pg_err:
            logger.debug(f"[CTWA Clear PG Session Note] {pg_err}")

    # ─────────────────────────────────────────────────────────────────────────
    # INBOUND PARSER: FLOWS FORM (nfm_reply) & CTA LANDING PAGE (FAST_TRACK)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def parse_inbound_lead(
        cls,
        raw_msg: Optional[Dict[str, Any]] = None,
        incoming_text: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        r"""
        Inbound Webhook Parser:
        1. Parse Flows Response (nfm_reply):
           Jika pesan masuk memiliki interactive.type == 'nfm_reply',
           ekstrak full_name & email dari response_json.
        2. Parse Fallback Teks (Dari CTA Landing Page):
           FAST_TRACK_PATTERN = re.compile(r'Halo Admin, saya atas nama (.+?) \((.+?)\) sudah daftar kelas', re.IGNORECASE)
        """
        # 1. Parse Flows Response (nfm_reply)
        if isinstance(raw_msg, dict):
            interactive = raw_msg.get("interactive")
            if isinstance(interactive, dict) and interactive.get("type") == "nfm_reply":
                nfm = interactive.get("nfm_reply", {})
                resp_raw = nfm.get("response_json", {})
                data = {}
                if isinstance(resp_raw, str):
                    try:
                        data = json.loads(resp_raw)
                    except Exception as e:
                        logger.debug(f"[CTWA_PARSER] Failed parsing response_json: {e}")
                elif isinstance(resp_raw, dict):
                    data = resp_raw

                name = str(data.get("full_name") or data.get("name") or "").strip()
                email = str(data.get("email") or "").strip()
                if name or email:
                    return name or "Kakak", email

        # 2. Parse Fallback Teks
        text_str = str(incoming_text or "")
        if not text_str and isinstance(raw_msg, dict):
            text_str = str(raw_msg.get("text", {}).get("body", "")).strip()

        if text_str:
            match = FAST_TRACK_PATTERN.search(text_str)
            if match:
                name = match.group(1).strip()
                email = match.group(2).strip()
                return name, email

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # PRE-LLM DETERMINISTIC GATEKEEPER (249K DOWNWARD QRIS & CAPI)
    # ─────────────────────────────────────────────────────────────────────────

    async def execute_deterministic_gatekeeper(
        self,
        phone: str,
        name: str,
        email: str,
        phone_number_id: Optional[str] = None,
        ctwa_clid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Eksekusi Deterministik (Pre-LLM Gatekeeper):
        Begitu nama dan email diperoleh:
        1. Buat baris order baru di Supabase pada tabel orders dengan status PENDING
           (nominal Rp249.000 dikurangi kode unik 3 digit downward).
        2. Bentuk Dynamic QRIS EMVCo Tag 54 presisi (preservasi Tag 62 acquirer sesuai §14.1).
        3. Kirim gambar QRIS ke chat WhatsApp via Meta Media Endpoint beserta total tagihan presisi.
        4. Dispatch server-side event Meta CAPI InitiateCheckout.
        """
        clean_phone = normalize_phone_number(phone) or str(phone or "").strip()
        if not clean_phone:
            raise ValueError("customer_phone wajib diisi dan tidak boleh kosong")
        if not name or not str(name).strip():
            raise ValueError("customer_name wajib diisi dan tidak boleh kosong")
        if not email or not str(email).strip() or "@" not in str(email):
            raise ValueError("customer_email wajib diisi dengan format valid dan tidak boleh kosong")

        session = self.get_session(clean_phone)
        session["lead_name"] = name
        session["lead_email"] = email

        # P0 STRICT HOLD GUARD: Reject request BEFORE Xendit invocation and BEFORE database mutations
        from app.services.academy_service import is_onlineboost_payment_held
        if is_onlineboost_payment_held():
            logger.info(f"[GATEKEEPER] Payment STRICT HOLD active for OnlineBoost Batch 1. Request queued without Xendit or order mutation.")
            session["current_state"] = "STATE_LEAD_QUEUED"
            hold_caption = (
                f"Terima kasih Kak {name}! Data pendaftaran Kakak ({email}) sudah kami catat dalam daftar antrean prioritas Batch 1.\n\n"
                f"Saat ini gerbang pembayaran resmi Batch 1 sedang dalam masa persiapan rilis (strict hold). "
                f"Begitu sistem pembayaran resmi dibuka, Kakak akan langsung menerima instruksi pembayaran di nomor WhatsApp ini."
            )
            if phone_number_id and clean_phone:
                try:
                    await cloud_api.send_whatsapp_text(
                        to_phone=clean_phone,
                        text=hold_caption,
                        phone_number_id=phone_number_id,
                        tenant_id="onlineboost",
                    )
                except Exception as _e:
                    logger.debug(f"[GATEKEEPER] WA dispatch note: {_e}")

            return {
                "status": "STRICT_HOLD",
                "strict_hold": True,
                "order_id": None,
                "total_amount": SINGLE_OFFER_PRICE,
                "qris_payload": "",
                "caption": hold_caption,
            }

        session["current_state"] = "STATE_PAYMENT_PENDING"

        # 1. Hitung 3-digit kode unik downward (100 - 999)
        downward_code = generate_unique_code(min_val=100, max_val=999)
        total_amount = SINGLE_OFFER_PRICE - downward_code
        order_id = f"ORD-OB-{uuid.uuid4().hex[:8].upper()}"
        session["order_id"] = order_id
        session["invoice_id"] = order_id
        session["unique_code"] = downward_code
        session["total_amount"] = total_amount

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # 2. Terbitkan Dynamic QRIS resmi via Xendit API akun PT Boontrack
        xendit_qr_res = {}
        try:
            xendit_qr_res = await xendit_service.create_dynamic_qris(
                external_id=order_id,
                amount=total_amount,
                tenant_id="onlineboost",
                customer_phone=clean_phone,
                metadata={
                    "product_name": SINGLE_OFFER_NAME,
                    "product_slug": SINGLE_OFFER_SLUG,
                    "customer_name": name,
                    "ctwa_clid": ctwa_clid,
                }
            )
        except Exception as x_err:
            logger.warning(f"[GATEKEEPER] Xendit create_dynamic_qris note: {x_err}")
            xendit_qr_res = {}

        qris_payload = str(xendit_qr_res.get("qr_string") or "").strip()
        if not qris_payload or not qris_payload.startswith("000201"):
            # P0 FAIL-CLOSED: DILARANG KERAS mengganti QRIS transaksi dinamis yang gagal dengan QRIS statis (DEFAULT_STATIC_QRIS)
            logger.error(
                f"[GATEKEEPER] Xendit dynamic QRIS generation failed or returned invalid EMVCo payload for order {order_id}. "
                f"Refusing static QRIS fallback per P0 fail-closed policy."
            )
            session["current_state"] = "STATE_QRIS_FAILED"
            fail_caption = (
                f"Mohon maaf Kak {name}, sistem gerbang pembayaran resmi sedang mengalami kendala. "
                f"Data pendaftaran Kakak ({email}) sudah tersimpan aman di sistem kami. "
                f"Silakan ketik 'DAFTAR' untuk mencoba kembali dalam beberapa saat."
            )
            return {
                "status": "QRIS_GENERATION_FAILED",
                "error": "Failed to acquire authoritative dynamic QRIS from payment gateway",
                "order_id": None,
                "total_amount": total_amount,
                "qris_payload": "",
                "caption": fail_caption,
            }

        qris_payload = str(qris_payload or "").strip()
        invoice_url = str(xendit_qr_res.get("invoice_url") or "").strip()
        session["invoice_url"] = invoice_url

        qr_png_bytes = generate_qris_png_bytes(qris_payload) if qris_payload else b""

        # 3. Buat baris order baru di Supabase pada tabel orders dengan status PENDING
        from app.services.referral_attribution_service import get_attribution_snapshot_for_order
        attr_snapshot = get_attribution_snapshot_for_order(session)

        order_metadata = {
            "flow_token": "ctwa_flow_token",
            "base_amount": SINGLE_OFFER_PRICE,
            "unique_code": downward_code,
            "unique_code_system": "DOWNWARD",
            "product_slug": SINGLE_OFFER_SLUG,
            "sku_id": CANONICAL_BATCH1_SKU,
            "sku": CANONICAL_BATCH1_SKU,
            "qris_payload": qris_payload,
            "qr_id": xendit_qr_res.get("qr_id"),
            "invoice_url": invoice_url,
            "payment_provider": "XENDIT",
            "ctwa_clid": ctwa_clid,
        }
        if attr_snapshot:
            order_metadata.update(attr_snapshot)

        sb = get_supabase()
        if sb:
            try:
                sb.table("orders").insert({
                    "id": order_id,
                    "tenant_slug": "onlineboost",
                    "product_id": SINGLE_OFFER_SLUG,
                    "product_title": SINGLE_OFFER_NAME,
                    "gross_amount": total_amount,
                    "customer_name": name,
                    "customer_phone": clean_phone,
                    "customer_email": email,
                    "status": "PENDING",
                    "metadata": order_metadata,
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }).execute()
                logger.info(f"[GATEKEEPER] Order {order_id} (PENDING Rp{total_amount:,}) created in Supabase.")
            except Exception as sb_err:
                logger.warning(f"[GATEKEEPER] Supabase order insert error: {sb_err}")

        # Simpan ke Postgres orders jika koneksi database aktif
        try:
            from app.core.database import get_db_connection
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO orders (
                        id, tenant_slug, product_id, product_title, gross_amount,
                        customer_name, customer_phone, customer_email, status, metadata,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        gross_amount = EXCLUDED.gross_amount,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW();
                    """,
                    (
                        order_id,
                        "onlineboost",
                        SINGLE_OFFER_SLUG,
                        SINGLE_OFFER_NAME,
                        total_amount,
                        name,
                        clean_phone,
                        email,
                        json.dumps(order_metadata),
                        now,
                        now,
                    )
                )
                conn.commit()
            conn.close()
            logger.info(f"[GATEKEEPER] Order {order_id} stored into Postgres orders.")
        except Exception as pg_err:
            logger.debug(f"[GATEKEEPER] Postgres order insert note: {pg_err}")

        self._save_session_to_db(session)

        # 4. Kirim gambar QRIS ke chat WhatsApp via Meta Media Endpoint beserta total tagihan presisi
        total_formatted = format_idr(total_amount)
        web_checkout_part = f"\nAtau selesaikan langsung via Web Checkout Resmi:\n👉 {invoice_url}\n" if invoice_url else ""
        qris_caption = (
            f"📋 *TAGIHAN RESMI PENDAFTARAN BATCH 1*\n\n"
            f"Hai Kak *{name}*! Data pendaftaran Kakak telah kami catat dengan sukses.\n\n"
            f"Detail Pembayaran:\n"
            f"• Program: *{SINGLE_OFFER_NAME}*\n"
            f"• No. Order: `{order_id}`\n"
            f"• Diskon Kode Unik: -Rp {downward_code}\n"
            f"• *TOTAL TAGIHAN PRESISI: Rp {total_formatted}*\n\n"
            f"⚠️ *PENTING:* Mohon transfer tepat hingga 3 digit terakhir (*Rp {total_formatted}*) "
            f"agar sistem AI kami dapat memverifikasi pembayaran Kakak secara otomatis dalam hitungan detik.\n\n"
            f"📲 Silakan scan kode QRIS di atas melalui BCA, Mandiri, BRI, BNI, GoPay, OVO, Dana, atau ShopeePay.\n"
            f"{web_checkout_part}\n"
            f"Akses Supergroup Praktikum akan otomatis diterbitkan begitu pembayaran terverifikasi! 🚀"
        )

        send_image_res = None
        try:
            send_image_res = await cloud_api.send_whatsapp_image(
                to_phone=clean_phone,
                image_path_or_bytes=qr_png_bytes,
                caption=qris_caption,
                tenant_id="onlineboost",
                phone_number_id=phone_number_id,
            )
            logger.info(f"[GATEKEEPER] QRIS image dispatched to {clean_phone} via Meta Media endpoint.")
        except Exception as img_err:
            logger.warning(f"[GATEKEEPER] Meta media image send note: {img_err}")
            # Fallback text jika upload image terhambat
            await cloud_api.send_whatsapp_text(
                to_phone=clean_phone,
                text=qris_caption,
                tenant_id="onlineboost",
                phone_number_id=phone_number_id,
            )

        # 5. Dispatch server-side event Meta CAPI InitiateCheckout
        capi_res = None
        try:
            capi_res = await capi_dispatcher.dispatch_initiate_checkout(
                tenant_id="onlineboost",
                phone=clean_phone,
                total_amount=float(total_amount),
                product_ids=[SINGLE_OFFER_SLUG],
                ctwa_clid=ctwa_clid,
            )
            logger.info(f"[GATEKEEPER] Meta CAPI InitiateCheckout dispatched for Order {order_id}")
        except Exception as capi_err:
            logger.warning(f"[GATEKEEPER] Meta CAPI dispatch note: {capi_err}")

        return {
            "status": "GATEKEEPER_EXECUTED",
            "order_id": order_id,
            "total_amount": total_amount,
            "downward_code": downward_code,
            "qris_payload": qris_payload,
            "name": name,
            "email": email,
            "phone": clean_phone,
            "caption": qris_caption,
            "image_dispatch": send_image_res,
            "capi_dispatch": capi_res,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN CONVERSATION TURN HANDLER (SINGLE OFFER ONLY)
    # ─────────────────────────────────────────────────────────────────────────

    async def process_turn(
        self,
        phone: str,
        incoming_text: str,
        sender_name: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        raw_msg: Optional[Dict[str, Any]] = None,
        phone_number_id: Optional[str] = None,
        ctwa_clid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Memproses pesan masuk untuk tenant 'onlineboost':
        - Seluruh alur HANYA fokus pada Single Offer 249K.
        - Memeriksa Flows response (nfm_reply) atau Fast-Track pattern.
        - Jika lead terdeteksi -> Eksekusi Pre-LLM Gatekeeper.
        - Jika bukan lead -> Tampilkan Value Stacking Script & WhatsApp Flows Form.
        """
        clean_phone = normalize_phone_number(phone) or str(phone).strip()
        session = self.get_session(clean_phone)

        # Ekstraksi marker [r=KODE_RESELLER] dan persistensi atribusi (First Valid Referral Wins)
        from app.services.referral_attribution_service import (
            extract_referral_marker,
            apply_referral_attribution_to_session,
        )
        q, raw_ref_code = extract_referral_marker(incoming_text.strip())
        if raw_ref_code:
            apply_referral_attribution_to_session(session, raw_ref_code, tenant_id="onlineboost")
        q_lower = q.lower()

        # Update sapaan nama jika ada
        if sender_name and not session.get("lead_name"):
            session["lead_name"] = sender_name

        # ─── 1. CEK PRE-LLM GATEKEEPER TRIGGER (Flow Form, QRIS Intent, atau CTA Landing Page) ──
        lead_detected = self.parse_inbound_lead(raw_msg=raw_msg, incoming_text=q)

        # Coba juga deteksi nama & email langsung dari teks santai
        if not lead_detected:
            email_match = EMAIL_REGEX.search(q)
            if email_match:
                extracted_email = email_match.group(0).lower().strip()
                name_match = re.search(r'(?:nama|name)\s*[:=]\s*([^\n,]+)', q, re.IGNORECASE)
                extracted_name = (
                    name_match.group(1).strip()
                    if name_match
                    else (sender_name or session.get("lead_name") or "Kakak")
                )
                lead_detected = (extracted_name, extracted_email)

        # Cek kata kunci intensi pembayaran QRIS langsung atau format pendaftaran
        is_qris_intent = any(kw in q_lower for kw in [
            "saya mau bayar via qris",
            "mau bayar via qris",
            "bayar via qris",
            "bayar qris",
            "mau bayar qris",
            "minta qris",
            "kirim qris",
            "transfer qris",
            "qris 249",
            "bayar lewat qris",
            "mau transfer qris",
            "minta qrisnya",
            "kirim qrisnya",
            "minta qris dong",
        ])

        if not lead_detected and is_qris_intent:
            extracted_name = sender_name or session.get("lead_name") or "Kakak"
            extracted_email = session.get("lead_email") or f"{clean_phone}@customer.boontrack.com"
            lead_detected = (extracted_name, extracted_email)

        if lead_detected:
            full_name, email = lead_detected
            logger.info(f"[CTWA_TURN] Lead / QRIS Intent detected: {full_name} ({email}) -> Triggering Pre-LLM Gatekeeper")
            gk_result = await self.execute_deterministic_gatekeeper(
                phone=clean_phone,
                name=full_name,
                email=email,
                phone_number_id=phone_number_id,
                ctwa_clid=ctwa_clid,
            )
            if gk_result.get("strict_hold"):
                caption = gk_result.get("caption") or ""
                return {
                    "success": True,
                    "action": "GATEKEEPER_STRICT_HOLD",
                    "reply": caption,
                    "reply_text": caption,
                    "media_url": "",
                    "qr_code_url": "",
                    "qris_payload": "",
                    "order_id": None,
                    "total_amount": SINGLE_OFFER_PRICE,
                    "downward_code": 0,
                    "current_state": "STATE_LEAD_QUEUED",
                }

            if gk_result.get("status") == "QRIS_GENERATION_FAILED":
                caption = gk_result.get("caption") or (
                    "Mohon maaf Kak, terjadi kendala koneksi ke gerbang pembayaran resmi saat menyiapkan kode QRIS. "
                    "Silakan ketik 'DAFTAR' untuk mencoba kembali."
                )
                return {
                    "success": False,
                    "action": "GATEKEEPER_FAILED",
                    "reply": caption,
                    "reply_text": caption,
                    "media_url": "",
                    "qr_code_url": "",
                    "qris_payload": "",
                    "order_id": None,
                    "total_amount": SINGLE_OFFER_PRICE,
                    "downward_code": 0,
                    "current_state": "STATE_QRIS_FAILED",
                }

            qris_payload = str(gk_result.get("qris_payload") or "").strip()
            qr_img_url = ""
            if qris_payload:
                qr_encoded = urllib.parse.quote(qris_payload)
                qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?data={qr_encoded}&size=400x400"

            caption = gk_result.get("caption") or (
                "Data pendaftaran Kakak telah kami catat dengan aman. "
                "Instruksi pembayaran akan diinformasikan setelah verifikasi batch resmi dibuka."
            )
            is_executed = bool(gk_result.get("status") == "GATEKEEPER_EXECUTED" or qris_payload)
            if gk_result.get("status") == "GATEKEEPER_PENDING" and not qris_payload:
                is_executed = False

            return {
                "success": is_executed,
                "action": "GATEKEEPER_QRIS_ISSUED" if is_executed else "GATEKEEPER_PENDING",
                "reply": caption,
                "reply_text": caption,
                "media_url": qr_img_url,
                "qr_code_url": qr_img_url,
                "qris_payload": qris_payload,
                "order_id": gk_result.get("order_id"),
                "total_amount": gk_result.get("total_amount"),
                "downward_code": gk_result.get("downward_code"),
                "current_state": "STATE_PAYMENT_PENDING",
            }

        # ─── 2. USER SUDAH DALAM STATUS MENUNGGU PEMBAYARAN ────────────────────
        if session.get("current_state") == "STATE_PAYMENT_PENDING":
            if any(w in q_lower for w in ["sudah bayar", "sudah tf", "sudah transfer", "bukti", "cek"]):
                pending_reply = (
                    "Terima kasih banyak, Kak! ⏳ Sistem verifikasi otomatis 24 jam kami "
                    "sedang mengecek mutasi transfer Kakak.\n\n"
                    "Begitu nominal presisi terverifikasi, link akses eksklusif Supergroup Praktikum "
                    "akan langsung dikirimkan ke chat ini secara otomatis ya Kak!"
                )
                return {
                    "success": True,
                    "action": "WAITING_VERIFICATION",
                    "reply": pending_reply,
                    "reply_text": pending_reply,
                    "current_state": "STATE_PAYMENT_PENDING",
                }

        # ─── 3. INBOUND LANDING PAGE CTA: SATU PERTANYAAN KUALIFIKASI (NO LOOP) ─
        if re.search(r"(?i)(saya\s+tertarik\s+ikut\s+kelas\s*nya\s*kang|tertarik\s+ikut\s+kelas|tertarik\s+kelas)", q):
            from app.services.academy_service import QUALIFICATION_PRIMARY_QUESTION
            session["current_state"] = "STATE_QUALIFYING"
            self._save_session_to_db(session)
            return {
                "success": True,
                "action": "QUALIFY_OFFER",
                "reply": QUALIFICATION_PRIMARY_QUESTION,
                "reply_text": QUALIFICATION_PRIMARY_QUESTION,
                "current_state": "STATE_QUALIFYING",
            }

        # ─── 4. DEFAULT RESPONSE: VALUE STACKING HOOK & WHATSAPP FLOWS FORM ────
        # Fokuskan seluruh grounding dan respon bot HANYA pada Paket Lengkap 249K
        reply = SINGLE_OFFER_VALUE_STACKING_SCRIPT

        # Jalur Utama: Kirim WhatsApp Flows Form (interactive: flow)
        try:
            await cloud_api.send_whatsapp_flow(
                to_phone=clean_phone,
                header_text="Pendaftaran Batch 1",
                body_text="Amankan slot promo Rp249.000 dengan melengkapi data singkat di bawah ini. Invoice resmi akan langsung diterbitkan:",
                footer_text="OnlineBoost x BoonTrack",
                flow_cta="📝 Isi Data Pendaftaran",
                tenant_id="onlineboost",
                phone_number_id=phone_number_id,
            )
        except Exception as flow_err:
            logger.debug(f"[CTWA_TURN] WhatsApp flow send note: {flow_err}")

        session["current_state"] = "STATE_OFFER_PITCHED"
        self._save_session_to_db(session)

        return {
            "success": True,
            "action": "SINGLE_OFFER_PITCH",
            "reply": reply,
            "reply_text": reply,
            "current_state": "STATE_OFFER_PITCHED",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # POST-PAYMENT FULFILLMENT: SINGLE-USE TELEGRAM INVITE LINK
    # ─────────────────────────────────────────────────────────────────────────

    def generate_state_5_fulfillment_message(
        self,
        phone: str,
        external_id: str,
        amount: int,
        customer_name: Optional[str] = None,
    ) -> str:
        """
        Sinkron handler untuk menghasilkan teks konfirmasi pembayaran sukses.
        (Menjalankan asynchronous Telegram single-use invite issuance di background).
        """
        clean_phone = normalize_phone_number(phone) or str(phone).strip()
        session = self.get_session(clean_phone)
        resolved_name = customer_name or session.get("lead_name") or "Kakak"
        if resolved_name in ("Customer", "Pelanggan", "null", ""):
            resolved_name = "Kakak"

        # Trigger asynchronous fulfillment task
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                fulfill_onlineboost_ctwa_order(
                    order_id=external_id,
                    buyer_name=resolved_name,
                    buyer_phone=clean_phone,
                    amount=amount,
                    tenant_id="onlineboost",
                )
            )
        except RuntimeError:
            pass

        amt_formatted = format_idr(amount)
        from app.services.ctwa_fulfillment_service import _ISSUED_TELEGRAM_LINKS_CACHE
        single_use_link = _ISSUED_TELEGRAM_LINKS_CACHE.get(external_id)
        if single_use_link:
            return (
                f"Selamat Kak {resolved_name}! Pembayaran sebesar Rp{amt_formatted} untuk Kelas Inkubasi CTWA Batch 1 telah BERHASIL diverifikasi ✅\n\n"
                f"Berikut link akses eksklusif Kakak untuk bergabung ke Supergroup Praktikum: 🔗 {single_use_link}\n\n"
                f"⚠️ Penting: Tautan di atas adalah link khusus 1 kali masuk dan berlaku selama 24 jam. Jangan dibagikan ke orang lain ya Kak!\n\n"
                f"Sampai jumpa di ruang praktikum!"
            )
        return (
            f"Selamat Kak {resolved_name}! Pembayaran sebesar Rp{amt_formatted} untuk Kelas Inkubasi CTWA Batch 1 telah BERHASIL diverifikasi ✅\n\n"
            f"Tautan akses eksklusif Supergroup Praktikum Kakak sedang diterbitkan secara otomatis dan akan langsung dikirimkan ke chat ini.\n\n"
            f"Sampai jumpa di ruang praktikum!"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION PERSISTENCE HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _save_session_to_db(self, session: Dict[str, Any]) -> None:
        """Menyimpan session state ke conversation_sessions di Supabase."""
        clean_phone = session.get("phone")
        if not clean_phone:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        session["updated_at"] = now_iso

        try:
            sb = get_supabase()
            if sb:
                payload = {
                    "tenant_id": "onlineboost",
                    "channel": "WHATSAPP",
                    "session_id": f"wa_{clean_phone}",
                    "user_identifier": clean_phone,
                    "current_state": session.get("current_state", "STATE_0"),
                    "metadata": {
                        "first_contact_at": session.get("first_contact_at"),
                        "lead_name": session.get("lead_name"),
                        "lead_email": session.get("lead_email"),
                        "selected_package": SINGLE_OFFER_SLUG,
                        "order_id": session.get("order_id"),
                        "invoice_id": session.get("invoice_id"),
                        "total_amount": session.get("total_amount"),
                        "unique_code": session.get("unique_code"),
                        "is_settled": session.get("is_settled", False),
                    },
                    "updated_at": now_iso,
                }
                ex = (
                    sb.table("conversation_sessions")
                    .select("id")
                    .eq("tenant_id", "onlineboost")
                    .eq("user_identifier", clean_phone)
                    .maybe_single()
                    .execute()
                )
                if ex and ex.data:
                    sb.table("conversation_sessions").update(payload).eq("id", ex.data["id"]).execute()
                else:
                    sb.table("conversation_sessions").insert(payload).execute()
        except Exception as e:
            logger.debug(f"[CTWA DB Save Note] {e}")

    def _load_session_from_db(self, clean_phone: str) -> Optional[Dict[str, Any]]:
        """Memuat session state dari database."""
        try:
            sb = get_supabase()
            if sb:
                res = (
                    sb.table("conversation_sessions")
                    .select("*")
                    .eq("tenant_id", "onlineboost")
                    .eq("user_identifier", clean_phone)
                    .maybe_single()
                    .execute()
                )
                if res and res.data:
                    row = res.data
                    meta = row.get("metadata") or {}
                    return {
                        "phone": clean_phone,
                        "tenant_slug": "onlineboost",
                        "current_state": row.get("current_state") or "STATE_0",
                        "first_contact_at": meta.get("first_contact_at") or row.get("created_at"),
                        "lead_name": meta.get("lead_name"),
                        "lead_email": meta.get("lead_email"),
                        "selected_package": SINGLE_OFFER_SLUG,
                        "order_id": meta.get("order_id"),
                        "invoice_id": meta.get("invoice_id"),
                        "total_amount": meta.get("total_amount") or SINGLE_OFFER_PRICE,
                        "unique_code": meta.get("unique_code") or 0,
                        "is_settled": meta.get("is_settled", False),
                        "updated_at": row.get("updated_at"),
                    }
        except Exception as e:
            logger.debug(f"[CTWA DB Load Note] {e}")
        return None


# Global singleton instance
ctwa_state_engine = CTWAStateEngine()
