"""app/services/ctwa_state_engine.py
Engine Flow WA Bot Specification v1.2 (Tenant 'onlineboost')
Conversation State Machine:
- STATE 0: Inbound greeting Meta Ads & kualifikasi kebutuhan.
- STATE 1: Penjelasan 6 poin benefit di atas + kunci bonus hari ini.
- STATE 2: Pricing pitch:
  * Paket Starter: Rp99.000
  * Scale Bundle: Rp149.000 (Bonus Tool Ads Rp299k + Reseller)
- STATE 3: Lead capture (Nama & Email aktif).
- STATE 4: Dispatch dynamic QRIS Xendit nominal pas + panduan bayar 1 HP (screenshot & upload galeri di m-banking/e-wallet).
- STATE 5: Auto-fulfillment via Webhook Xendit PAID -> kirim link Telegram Channel & materi otomatis.

Rule Kadaluarsa 24 Jam per Nomor Telepon:
- Menghitung selisih waktu dari 'first_contact_at' nomor tersebut.
- Jika > 24 jam dan belum lunas, otomatis hilangkan penawaran bonus Tool Ads Rp299k dan arahkan ke tarif reguler.
"""

import re
import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List

from app.services.whatsapp_service import normalize_phone_number, get_supabase
from app.services.xendit_service import xendit_service

logger = logging.getLogger("CTWA_STATE_ENGINE")

TELEGRAM_CHANNEL_URL = "https://t.me/+ctwa_batch1_onlineboost"
BONUS_TOOL_ADS_URL = "https://shop.boontrack.com/register"
SCALE_BUNDLE_PRICE = 149000
STARTER_PRICE = 99000
SCALE_BUNDLE_NAME = "Kelas Inkubasi CTWA Batch 1 - Scale Bundle (Recommended)"
STARTER_NAME = "Kelas Inkubasi CTWA Batch 1 - Paket Starter"
SCALE_BUNDLE_ACCESS = "https://onlineboost.id/ctwa-scale-bundle"
STARTER_ACCESS = "https://onlineboost.id/ctwa-starter"


class CTWAStateEngine:
    """State Machine Engine untuk Tenant onlineboost v1.2."""

    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def get_session(self, phone: str) -> Dict[str, Any]:
        """Ambil atau inisialisasi sesi percakapan untuk nomor telepon."""
        clean_phone = normalize_phone_number(phone)
        if clean_phone in self.sessions:
            return self.sessions[clean_phone]

        # 1. Coba pulihkan dari database Supabase / Postgres
        now_iso = datetime.now(timezone.utc).isoformat()
        db_session = self._load_session_from_db(clean_phone)
        if db_session:
            self.sessions[clean_phone] = db_session
            return db_session

        # 2. Inisialisasi sesi baru (STATE 0)
        new_session = {
            "phone": clean_phone,
            "tenant_slug": "onlineboost",
            "current_state": "STATE_0",
            "first_contact_at": now_iso,
            "lead_name": None,
            "lead_email": None,
            "selected_package": None,
            "invoice_id": None,
            "is_settled": False,
            "updated_at": now_iso,
        }
        self.sessions[clean_phone] = new_session
        self._save_session_to_db(new_session)
        return new_session

    def check_24h_status(self, session: Dict[str, Any]) -> Tuple[bool, float]:
        """Menghitung apakah bonus Tool Ads Rp299k masih aktif (<= 24 jam).
        Returns: (is_bonus_active, hours_elapsed).
        """
        first_contact_str = session.get("first_contact_at")
        if not first_contact_str:
            return True, 0.0

        try:
            fc_dt = datetime.fromisoformat(first_contact_str.replace("Z", "+00:00"))
            if fc_dt.tzinfo is None:
                fc_dt = fc_dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_elapsed = (now - fc_dt).total_seconds() / 3600.0
            is_valid = hours_elapsed <= 24.0
            return is_valid, hours_elapsed
        except Exception as e:
            logger.debug(f"[CTWA 24H Check Error] {e}")
            return True, 0.0

    async def process_turn(
        self,
        phone: str,
        incoming_text: str,
        sender_name: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Proses input pesan dan eksekusi transisi state deterministik."""
        clean_phone = normalize_phone_number(phone)
        session = self.get_session(clean_phone)
        q = incoming_text.strip()
        q_lower = q.lower()

        # Update contact name jika ada
        if sender_name and not session.get("lead_name"):
            session["lead_name"] = sender_name

        # Cek status kadaluarsa 24 jam
        is_bonus_active, hours_elapsed = self.check_24h_status(session)
        current_state = session.get("current_state", "STATE_0")

        # ---------------------------------------------------------------------
        # Ekstraksi Nama & Email di turn mana pun (Eager Lead Capture)
        # ---------------------------------------------------------------------
        email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', q)
        if email_match:
            session["lead_email"] = email_match.group(0).lower().strip()
            name_match = re.search(r'(?:nama|name)\s*[:=]\s*([^\n,]+)', q, re.IGNORECASE)
            if name_match:
                session["lead_name"] = name_match.group(1).strip()
            elif sender_name and not session.get("lead_name"):
                session["lead_name"] = sender_name

            # Simpan data lead ke Supabase
            self._persist_lead(session)

        # ---------------------------------------------------------------------
        # DETEKSI FAST-FORWARD: Jika user langsung minta bayar / QRIS
        # ---------------------------------------------------------------------
        PAY_DIRECT_WORDS = [
            "mau bayar", "bayar sekarang", "minta qris", "kirim qris", "bayar qris",
            "minta barcode", "kirim barcode", "scan qris", "mau tf", "mau transfer",
            "minta rekening", "bayar via wa", "bayar lewat wa"
        ]
        is_direct_pay_intent = any(w in q_lower for w in PAY_DIRECT_WORDS)

        # Deteksi pemilihan paket langsung
        if any(w in q_lower for w in ["starter", "99"]):
            session["selected_package"] = "starter"
        elif any(w in q_lower for w in ["scale", "bundle", "149", "recom", "rekomendasi"]):
            session["selected_package"] = "scale_bundle"

        if is_direct_pay_intent or (session.get("selected_package") and (session.get("lead_name") and session.get("lead_email"))):
            if not session.get("selected_package"):
                session["selected_package"] = "scale_bundle"  # Default recommended

            # Jika data diri belum ada, tanyakan nama & email (STATE 3)
            if not session.get("lead_name") or not session.get("lead_email"):
                return await self._handle_state_3_capture(session, q, is_bonus_active)

            # Jika data diri sudah ada, langsung dispatch QRIS (STATE 4)
            return await self._handle_state_4_dispatch_qris(session, is_bonus_active)

        # ---------------------------------------------------------------------
        # STATE MACHINE TRANSITIONS
        # ---------------------------------------------------------------------

        # KONDISI 1: STATE 0 (Greeting Awal Meta Ads & Kualifikasi Kebutuhan)
        is_greeting = self._is_greeting_message(q_lower, history)
        if current_state == "STATE_0" and is_greeting:
            return self._handle_state_0(session)

        # KONDISI 2: STATE 1 (Penjelasan 6 Benefit + Kunci Bonus)
        # Jika user sedang di STATE 0 dan membalas tentang bisnis/kebutuhan mereka
        if current_state == "STATE_0":
            return self._handle_state_1_benefits(session, is_bonus_active)

        # KONDISI 3: STATE 1 -> STATE 2 (User bertanya harga / paket / biaya)
        PRICING_INQUIRY = [
            "harga", "biaya", "paket", "berapa", "tarif", "opsi", "pilihan", "info paket",
            "mau", "boleh", "jelasin paket", "lanjut", "biayanya", "harganya"
        ]
        if current_state == "STATE_1" and any(w in q_lower for w in PRICING_INQUIRY):
            return self._handle_state_2_pricing(session, is_bonus_active)

        # KONDISI 4: STATE 2 -> STATE 3 (User memilih paket)
        PACKAGE_SELECTION = [
            "scale", "bundle", "149", "starter", "99", "ambil", "pilih", "mau yang", "daftar"
        ]
        if current_state == "STATE_2" and any(w in q_lower for w in PACKAGE_SELECTION):
            if any(w in q_lower for w in ["starter", "99"]):
                session["selected_package"] = "starter"
            else:
                session["selected_package"] = "scale_bundle"

            return await self._handle_state_3_capture(session, q, is_bonus_active)

        # KONDISI 5: STATE 3 (Menangkap data diri Nama & Email)
        if current_state == "STATE_3":
            if session.get("lead_name") and session.get("lead_email"):
                return await self._handle_state_4_dispatch_qris(session, is_bonus_active)
            else:
                return await self._handle_state_3_capture(session, q, is_bonus_active)

        # KONDISI 6: STATE 4 (Menunggu Pembayaran)
        if current_state == "STATE_4":
            if any(w in q_lower for w in ["sudah bayar", "sudah transfer", "bukti", "cek", "lunas"]):
                reply = (
                    "Terima kasih Kak! Sistem Xendit sedang memverifikasi transaksi Kakak secara otomatis ⏳\n\n"
                    "Begitu pembayaran masuk, bot akan langsung mengirimkan link akses Telegram Channel & materi otomatis ke chat ini dalam hitungan detik ya Kak!"
                )
                return {
                    "success": True,
                    "reply": reply,
                    "action": "WAITING_VERIFICATION",
                    "current_state": "STATE_4",
                }
            # Jika user menanyakan panduan lagi
            return await self._handle_state_4_dispatch_qris(session, is_bonus_active)

        # Fallback ramah jika di tengah percakapan
        if current_state == "STATE_1":
            return self._handle_state_2_pricing(session, is_bonus_active)

        return self._handle_state_1_benefits(session, is_bonus_active)

    # -------------------------------------------------------------------------
    # STATE HANDLERS
    # -------------------------------------------------------------------------

    def _handle_state_0(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """STATE 0: Inbound greeting Meta Ads & kualifikasi kebutuhan."""
        session["current_state"] = "STATE_0"
        self._save_session_to_db(session)

        reply = (
            "Halo Kak! 👋 Salam kenal, saya *BoonSales* dari OnlineBoost. "
            "Senang banget bisa terhubung dengan Kakak dari iklan kami!\n\n"
            "Boleh tahu saat ini Kakak sedang jualan produk apa atau bisnis apa nih Kak? "
            "Biar saya bisa bantu sesuaikan solusinya ya Kak 😊"
        )
        return {
            "success": True,
            "reply": reply,
            "action": "GREETING_QUALIFICATION",
            "current_state": "STATE_0",
            "is_bonus_active": True,
        }

    def _handle_state_1_benefits(self, session: Dict[str, Any], is_bonus_active: bool) -> Dict[str, Any]:
        """STATE 1: Penjelasan 6 poin benefit di atas + kunci bonus hari ini."""
        session["current_state"] = "STATE_1"
        self._save_session_to_db(session)

        bonus_point = (
            "6. 🎁 *Bonus Spesial Tool Ads Performance Senilai Rp299.000* (Akses langsung via https://shop.boontrack.com/register - *Terkunci Khusus Hari Ini / Promo 24 Jam!*)"
            if is_bonus_active else
            "6. ℹ️ *Akses Platform & Ekosistem BoonTrack* (Catatan: Bonus Tool Ads Rp299k berlaku khusus pendaftaran 24 jam pertama)."
        )

        reply = (
            "Wah mantap banget Kak! Pas banget, di *Kelas Inkubasi CTWA Batch 1* ini kita bakal bongkar tuntas strategi scale-up omset jualan lewat WhatsApp:\n\n"
            "✨ *6 Benefit Utama yang Kakak Dapatkan:*\n"
            "1. 🚀 *Praktek CTWA dari Nol:* Dipandu step-by-step dari setup iklan klik ke WhatsApp sampai running & hasilkan closing.\n"
            "2. 🤖 *Setup Bot Natural:* Bikin bot CS yang luwes, cerdas, dan interaktif (anti kaku, persis seperti bot live ini!).\n"
            "3. 🎬 *Praktis Bikin Konten Video:* Formula video promosi convert tinggi untuk datangkan traffic calon pembeli terus-menerus.\n"
            "4. 📦 *Produk Siap Jual:* Disediakan produk siap jual dengan *Lisensi Reseller 100% Hak Milik* (profit 100% bersih milik Kakak tanpa bagi hasil).\n"
            "5. 💳 *QRIS Statis Jadi Dinamis Otomatis:* Pembeli bayar nominal pas, pembayaran terverifikasi otomatis seketika tanpa cek mutasi manual.\n"
            f"{bonus_point}\n\n"
            "Gimana Kak, komplit banget kan? Mau saya infokan pilihan paket dan biaya investasinya sekarang?"
        )
        return {
            "success": True,
            "reply": reply,
            "action": "EXPLAIN_BENEFITS",
            "current_state": "STATE_1",
            "is_bonus_active": is_bonus_active,
        }

    def _handle_state_2_pricing(self, session: Dict[str, Any], is_bonus_active: bool) -> Dict[str, Any]:
        """STATE 2: Pricing pitch (Starter Rp99.000 vs Scale Bundle Rp149.000)."""
        session["current_state"] = "STATE_2"
        self._save_session_to_db(session)

        bonus_badge = "🔥 *+ BONUS Tool Ads Performance Rp299k* + Lisensi Reseller 100%" if is_bonus_active else "🔥 *+ Lisensi Reseller 100% Hak Milik*"

        reply = (
            "Siap Kak! Untuk Kelas Inkubasi CTWA Batch 1, ada 2 pilihan paket yang bisa Kakak pilih:\n\n"
            "1️⃣ *Paket Starter — Rp 99.000*\n"
            "• Akses materi dasar CTWA dari nol\n"
            "• Template setup bot WhatsApp dasar\n"
            "• Grup diskusi komunitas Telegram\n\n"
            "2️⃣ *Scale Bundle — Rp 149.000 (Paling Direkomendasikan! 🚀)*\n"
            "• SEMUA materi CTWA lengkap dari nol sampai running\n"
            "• Modul Setup Bot Natural luwes anti kaku\n"
            "• Lisensi Reseller 100% Hak Milik (profit jualan 100% milik Kakak)\n"
            "• Integrasi QRIS Dinamis Otomatis 0% ribet cek mutasi\n"
            f"• {bonus_badge}\n\n"
            "Selisihnya cuma Rp50rb tapi fasilitas Scale Bundle jauh lebih lengkap dan langsung siap menghasilkan Kak!\n\n"
            "Kira-kira Kakak mau amankan slot untuk paket *Scale Bundle (Rp149.000)* atau *Starter (Rp99.000)* nih Kak?"
        )
        return {
            "success": True,
            "reply": reply,
            "action": "PRICING_PITCH",
            "current_state": "STATE_2",
            "is_bonus_active": is_bonus_active,
        }

    async def _handle_state_3_capture(self, session: Dict[str, Any], q: str, is_bonus_active: bool) -> Dict[str, Any]:
        """STATE 3: Lead capture (Nama & Email aktif)."""
        session["current_state"] = "STATE_3"
        pkg_key = session.get("selected_package") or "scale_bundle"
        pkg_name = SCALE_BUNDLE_NAME if pkg_key == "scale_bundle" else STARTER_NAME
        pkg_price = SCALE_BUNDLE_PRICE if pkg_key == "scale_bundle" else STARTER_PRICE

        # Jika nama & email sudah terisi, langsung lompat ke STATE 4
        if session.get("lead_name") and session.get("lead_email"):
            return await self._handle_state_4_dispatch_qris(session, is_bonus_active)

        self._save_session_to_db(session)
        reply = (
            f"Pilihan tepat banget Kak! 👍 Slot untuk *{pkg_name}* (Rp{pkg_price:,.0f}) sudah kami amankan sementara.\n\n"
            "Untuk penyiapan akses portal materi & pengiriman invoice resmi, boleh dibantu kirimkan data dirinya ya Kak:\n"
            "• *Nama Lengkap:*\n"
            "• *Alamat Email Aktif:* (untuk pengiriman akses akun & materi ya Kak 😊)\n\n"
            "_Contoh format: Budi Santoso, budi@gmail.com_"
        )
        return {
            "success": True,
            "reply": reply,
            "action": "LEAD_CAPTURE",
            "current_state": "STATE_3",
            "is_bonus_active": is_bonus_active,
        }

    async def _handle_state_4_dispatch_qris(self, session: Dict[str, Any], is_bonus_active: bool) -> Dict[str, Any]:
        """STATE 4: Dispatch dynamic QRIS Xendit nominal pas + panduan bayar 1 HP."""
        session["current_state"] = "STATE_4"
        pkg_key = session.get("selected_package") or "scale_bundle"
        pkg_name = SCALE_BUNDLE_NAME if pkg_key == "scale_bundle" else STARTER_NAME
        pkg_price = SCALE_BUNDLE_PRICE if pkg_key == "scale_bundle" else STARTER_PRICE
        pkg_slug = "kelas-inkubasi-ctwa-batch-1-scale" if pkg_key == "scale_bundle" else "kelas-inkubasi-ctwa-batch-1-starter"

        clean_phone = session.get("phone", "")
        external_id = session.get("invoice_id")
        if not external_id:
            external_id = f"INV-OB-{uuid.uuid4().hex[:6].upper()}"
            session["invoice_id"] = external_id

        qr_media_url = None
        try:
            xendit_res = await xendit_service.create_dynamic_qris(
                external_id=external_id,
                amount=pkg_price,
                tenant_id="onlineboost",
                customer_phone=clean_phone,
                metadata={"product_name": pkg_name, "product_slug": pkg_slug}
            )
            qr_media_url = xendit_res.get("qr_code_url")
        except Exception as e:
            logger.error(f"[CTWA Xendit QR Error] {e}")

        self._save_session_to_db(session)
        price_fmt = f"Rp {pkg_price:,.0f}".replace(",", ".")

        caption = (
            f"Berikut Barcode QRIS Resmi untuk Pembayaran Kakak ✨\n\n"
            f"📦 *Nama Paket:* {pkg_name}\n"
            f"💰 *Nominal Pas:* *{price_fmt}*\n"
            f"⏱️ *Batas Waktu Pembayaran:* 15 Menit\n"
            f"📄 *No. Invoice:* `{external_id}`\n\n"
            f"💡 *Panduan Pembayaran Cukup dari 1 HP:*\n"
            f"1. *Screenshot* barcode QRIS di atas.\n"
            f"2. Buka aplikasi m-Banking (BCA, Mandiri, BRI, BNI, dll) atau E-Wallet (GoPay, OVO, DANA, ShopeePay).\n"
            f"3. Pilih menu *QRIS / Bayar*, lalu klik tombol *Upload/Pilih Gambar dari Galeri*.\n"
            f"4. Konfirmasi pembayaran tepat senilai *{price_fmt}*.\n\n"
            f"⚡ *Sistem Terverifikasi Otomatis:* Begitu pembayaran sukses, sistem langsung mengirimkan link akses Telegram Channel & materi otomatis ke chat ini!"
        )

        return {
            "success": True,
            "reply": caption,
            "reply_text": caption,
            "media_url": qr_media_url,
            "qr_code_url": qr_media_url,
            "tenant_slug": "onlineboost",
            "action": "DIRECT_PAYMENT_INSTRUCTIONS",
            "type": "MEDIA" if qr_media_url else "TEXT",
            "current_state": "STATE_4",
            "is_bonus_active": is_bonus_active,
        }

    def generate_state_5_fulfillment_message(
        self,
        phone: str,
        external_id: str,
        amount: int,
        customer_name: Optional[str] = None,
    ) -> str:
        """STATE 5: Auto-fulfillment via Webhook Xendit PAID -> link Telegram Channel & materi otomatis."""
        session = self.get_session(phone)
        session["current_state"] = "STATE_5"
        session["is_settled"] = True
        self._save_session_to_db(session)

        c_name = customer_name or session.get("lead_name") or "Kakak"
        amt_str = f"Rp {amount:,.0f}".replace(",", ".")

        if amount == STARTER_PRICE:
            pkg_name = STARTER_NAME
            portal_url = STARTER_ACCESS
            bonus_section = ""
        else:
            pkg_name = SCALE_BUNDLE_NAME
            portal_url = SCALE_BUNDLE_ACCESS
            bonus_section = (
                f"\n3️⃣ *Klaim Bonus Spesial Tool Ads Performance (Senilai Rp299.000):*\n"
                f"👉 {BONUS_TOOL_ADS_URL}\n"
                f"_(Gunakan email yang sama untuk aktivasi otomatis di dashboard)_\n"
            )

        text = (
            f"🎉 *PEMBAYARAN LUNAS TERVERIFIKASI!*\n\n"
            f"Halo Kak {c_name}! Terima kasih banyak atas pembayarannya. Transaksi untuk *{pkg_name}* "
            f"senilai *{amt_str}* (No. Invoice: `{external_id}`) telah *LUNAS & TERVERIFIKASI OTOMATIS* via Xendit QRIS.\n\n"
            f"🚀 *Akses Resmi Kelas Inkubasi CTWA Batch 1 Telah Aktif:*\n\n"
            f"1️⃣ *Gabung Telegram Channel Eksklusif:* \n"
            f"👉 {TELEGRAM_CHANNEL_URL}\n\n"
            f"2️⃣ *Portal Akses Materi & Modul:*\n"
            f"👉 {portal_url}\n"
            f"{bonus_section}\n"
            f"📌 *Langkah Pertama:* Segera klik link Telegram Channel di atas dan bergabung ke grup agar tidak ketinggalan jadwal sesi perdana ya Kak.\n\n"
            f"Jika ada kendala teknis atau pertanyaan, silakan balas chat ini kapan saja. Selamat belajar dan sukses selalu bersama OnlineBoost! 🔥"
        )
        return text

    # -------------------------------------------------------------------------
    # PERSISTENCE HELPERS
    # -------------------------------------------------------------------------

    def _is_greeting_message(self, q_lower: str, history: Optional[List[Any]]) -> bool:
        """Cek apakah pesan merupakan greeting awal."""
        if not history or len(history) == 0:
            return True
        GREETING_WORDS = {
            "halo", "hai", "pagi", "siang", "sore", "malam", "assalamualaikum",
            "assalam", "permisi", "tes", "test", "ping", "p", "start", "menu",
            "info", "selamat pagi", "selamat siang", "selamat sore", "selamat malam"
        }
        return q_lower in GREETING_WORDS or q_lower.startswith("halo") or q_lower.startswith("hai")

    def _persist_lead(self, session: Dict[str, Any]) -> None:
        """Menyimpan data lead ke tabel leads di Supabase."""
        try:
            sb = get_supabase()
            if sb and session.get("lead_email"):
                sb.table("leads").upsert({
                    "tenant_slug": "onlineboost",
                    "customer_name": session.get("lead_name") or "Pelanggan",
                    "customer_phone": session.get("phone"),
                    "customer_email": session.get("lead_email"),
                    "status": "QUALIFIED",
                    "source": "whatsapp_ctwa_flow",
                }, on_conflict="customer_phone,tenant_slug").execute()
        except Exception as e:
            logger.debug(f"[CTWA Lead Persist Error] {e}")

    def _save_session_to_db(self, session: Dict[str, Any]) -> None:
        """Menyimpan session state ke conversation_sessions dan demo_user_sessions."""
        clean_phone = session.get("phone")
        if not clean_phone:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        session["updated_at"] = now_iso

        # 1. Supabase conversation_sessions
        try:
            sb = get_supabase()
            if sb:
                payload = {
                    "tenant_id": "onlineboost",
                    "channel": "whatsapp",
                    "user_identifier": clean_phone,
                    "current_state": session.get("current_state", "STATE_0"),
                    "metadata": {
                        "first_contact_at": session.get("first_contact_at"),
                        "lead_name": session.get("lead_name"),
                        "lead_email": session.get("lead_email"),
                        "selected_package": session.get("selected_package"),
                        "invoice_id": session.get("invoice_id"),
                        "is_settled": session.get("is_settled", False),
                    },
                    "updated_at": now_iso,
                }
                ex = sb.table("conversation_sessions").select("id").eq("tenant_id", "onlineboost").eq("user_identifier", clean_phone).maybe_single().execute()
                if ex and ex.data:
                    sb.table("conversation_sessions").update(payload).eq("id", ex.data["id"]).execute()
                else:
                    sb.table("conversation_sessions").insert(payload).execute()
        except Exception as e:
            logger.debug(f"[CTWA DB Save Error] {e}")

    def _load_session_from_db(self, clean_phone: str) -> Optional[Dict[str, Any]]:
        """Memuat session state dari database."""
        try:
            sb = get_supabase()
            if sb:
                res = sb.table("conversation_sessions").select("*").eq("tenant_id", "onlineboost").eq("user_identifier", clean_phone).maybe_single().execute()
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
                        "selected_package": meta.get("selected_package"),
                        "invoice_id": meta.get("invoice_id"),
                        "is_settled": meta.get("is_settled", False),
                        "updated_at": row.get("updated_at"),
                    }
        except Exception as e:
            logger.debug(f"[CTWA DB Load Error] {e}")
        return None


# Singleton instance
ctwa_state_engine = CTWAStateEngine()
