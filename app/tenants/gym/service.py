"""app/tenants/gym/service.py
Conversational AI, Package Purchasing, and Zumba Class Booking Service for Atmosfitnes Gym.

Integrates with:
- app.services.gym_access_service (IoT gate verification, class bookings, member lookup)
- app.services.whatsapp_service (WhatsApp messaging & Supabase audit logging)
- app.utils.qris_generator (Dynamic QRIS generation)
"""

import logging
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.tenants.gym.config import (
    TENANT_ID,
    TENANT_NAME,
    GYM_OPERATIONAL_HOURS,
    GYM_LOCATION,
    MEMBERSHIP_PACKAGES,
)
from app.services.gym_access_service import (
    gym_access_service,
    DEFAULT_ATMOSFITNES_STATIC_QRIS,
)
from app.services.whatsapp_service import (
    send_whatsapp_text,
    send_whatsapp_image_link,
    log_to_supabase_messages,
    get_supabase,
)
from app.utils.qris_generator import (
    generate_dynamic_qris_payload,
    generate_unique_code,
)
from app.services.reconciliation_service import PAYMENT_INTENTS
from app.services.ai_service import ai_gateway

logger = logging.getLogger("GYM_TENANT_SERVICE")


class GymTenantService:
    """Conversational Assistant & Interaction Handler for Gym Members."""

    def __init__(self):
        self.tenant_id = TENANT_ID
        self.tenant_name = TENANT_NAME

    async def handle_user_message(
        self,
        user_phone: str,
        incoming_text: str,
        user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Main dispatcher for incoming WhatsApp messages from gym members or prospects."""
        clean_phone = str(user_phone).replace("+", "").strip()
        text = str(incoming_text or "").strip()
        clean_name = user_name or f"Member {clean_phone[-4:]}"

        # 1. Log incoming user message to Supabase
        await log_to_supabase_messages(
            sender=f"User / {clean_name}",
            text=text,
            tenant_id=self.tenant_id,
            channel="whatsapp",
            user_phone=clean_phone,
            user_name=clean_name,
            user_id=clean_phone,
        )

        lower_text = text.lower().strip()

        # 2. Navigation Keywords (Menu, Reset, Start, Help)
        if lower_text in ("menu", "start", "help", "batal", "reset", "ulang", "halo", "hi", "p"):
            return await self.send_main_menu(clean_phone, clean_name)

        # 3. Intent: Daftar Member / Beli Paket
        if lower_text in ("daftar member", "daftar", "beli paket", "paket", "membership", "beli membership"):
            return await self.send_packages_menu(clean_phone, clean_name)

        # 4. Numeric Package Selection (1 to 5)
        if lower_text in MEMBERSHIP_PACKAGES:
            pkg = MEMBERSHIP_PACKAGES[lower_text]
            return await self.create_membership_invoice(clean_phone, clean_name, pkg)

        # 5. Intent: Booking Kelas Zumba / Jadwal Kelas
        if lower_text in ("booking zumba", "jadwal kelas", "jadwal", "booking", "kelas", "zumba", "6"):
            return await self.send_class_schedule(clean_phone, clean_name)

        # 6. Intent: Specific Booking Command (e.g. "book 1", "book 2", "book zumba_morning")
        booking_match = re.search(r"(?:book|booking)\s+([a-zA-Z0-9_-]+)", lower_text)
        if booking_match:
            session_key = booking_match.group(1).strip()
            return await self.handle_class_booking(clean_phone, clean_name, session_key)

        # 7. Intent: Cek Status Membership & Kartu NFC
        if lower_text in ("7", "cek status", "status", "cek kartu", "cek membership", "kartu"):
            return await self.check_member_status_and_reply(clean_phone, clean_name)

        # 8. Intent: Info Fasilitas & Lokasi
        if lower_text in ("8", "fasilitas", "jam", "lokasi", "jam operasional", "alamat"):
            return await self.send_facility_info(clean_phone)

        # 9. Intent: Escalation / CS
        if lower_text in ("9", "admin", "cs", "resepsionis", "bantuan", "staff", "trainer", "komplain"):
            return await self.send_escalation_message(clean_phone)

        # 10. Fallback: AI Conversational Assistance with Gym Persona
        return await self.handle_ai_conversation(clean_phone, text, clean_name)

    async def send_main_menu(self, user_phone: str, user_name: str) -> Dict[str, Any]:
        """Sends the structured Atmosfitnes interactive main menu."""
        menu_text = (
            f"🏋️ *PUSAT LAYANAN & AKSES ATMOSFITNES GYM*\n\n"
            f"Halo *{user_name}*, selamat datang di asisten resmi Atmosfitnes! 💪\n\n"
            f"Pilih opsi menu di bawah ini:\n\n"
            f"📦 *PILIHAN PAKET MEMBERSHIP:*\n"
            f"1️⃣ *Gym Basic* — Rp150.000 / 30 Hari\n"
            f"2️⃣ *Zumba Class* — Rp200.000 / 8x Sesi\n"
            f"3️⃣ *Gym Premium* — Rp250.000 / 30 Hari + Sauna\n"
            f"4️⃣ *All Access* — Rp350.000 / 30 Hari Unlimited\n"
            f"5️⃣ *Personal Training* — Rp800.000 / 12x Sesi PT\n\n"
            f"🎯 *LAYANAN & STUDIO:*\n"
            f"6️⃣ *Jadwal & Booking Kelas Zumba*\n"
            f"7️⃣ *Cek Status Membership & Kartu NFC*\n"
            f"8️⃣ *Info Fasilitas & Jam Operasional*\n"
            f"9️⃣ *Bantuan Staf Resepsionis / CS*\n\n"
            f"_Ketik angka 1-9 atau tanyakan langsung apa yang ingin Anda ketahui._"
        )
        await send_whatsapp_text(user_phone, menu_text, tenant_id=self.tenant_id)
        return {"action": "MAIN_MENU", "status": "sent"}

    async def send_packages_menu(self, user_phone: str, user_name: str) -> Dict[str, Any]:
        """Sends the dedicated packages catalog with pricing & benefits."""
        catalog_text = (
            f"📋 *KATALOG PAKET MEMBERSHIP ATMOSFITNES*\n\n"
            f"1️⃣ *Gym Basic* (Rp150.000)\n"
            f"• Akses area gym & loker reguler selama 30 hari.\n\n"
            f"2️⃣ *Zumba Class* (Rp200.000)\n"
            f"• Kuota 8x sesi kelas Zumba studio bersama instruktur pro.\n\n"
            f"3️⃣ *Gym Premium* (Rp250.000)\n"
            f"• Akses unlimited gym + sauna + loker digital 30 hari.\n\n"
            f"4️⃣ *All Access* (Rp350.000)\n"
            f"• Akses tanpa batas ke semua gym, kelas studio, dan fasilitas VIP.\n\n"
            f"5️⃣ *Personal Training* (Rp800.000)\n"
            f"• 12 sesi pendampingan 1-on-1 dengan Certified Trainer + meal plan.\n\n"
            f"_Ketik angka *1*, *2*, *3*, *4*, atau *5* untuk langsung mendapatkan invoice QRIS pembayaran._"
        )
        await send_whatsapp_text(user_phone, catalog_text, tenant_id=self.tenant_id)
        return {"action": "PACKAGES_CATALOG", "status": "sent"}

    async def create_membership_invoice(
        self,
        user_phone: str,
        user_name: str,
        package_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generates dynamic QRIS invoice for new or renewal membership."""
        base_price = package_info["price"]
        unique_code = generate_unique_code(101, 899)
        total_amount = base_price + unique_code

        invoice_id = f"GYM-ORD-{user_phone[-4:]}-{unique_code}"
        dynamic_qris = generate_dynamic_qris_payload(DEFAULT_ATMOSFITNES_STATIC_QRIS, total_amount)
        encoded_payload = urllib.parse.quote(dynamic_qris)
        qris_image_url = f"https://quickchart.io/qr?text={encoded_payload}&size=500&ecLevel=H"

        # Register or update member record in memory
        now = datetime.now(timezone.utc)
        member = None
        for m in gym_access_service._members.get(self.tenant_id, {}).values():
            if str(m.phone).replace("+", "").strip() == user_phone:
                member = m
                break
        if not member:
            member = gym_access_service.register_member_in_memory(
                tenant_id=self.tenant_id,
                name=user_name,
                phone=user_phone,
                expiry_date=now + timedelta(days=package_info.get("days", 30)),
                membership_package=package_info["code"],
                membership_status="PENDING",
            )

        # Register Payment Intent
        PAYMENT_INTENTS[total_amount] = {
            "invoice_id": invoice_id,
            "tenant_id": self.tenant_id,
            "product": "gym_membership_renewal",
            "member_id": str(member.id),
            "user_id": user_phone,
            "user_phone": user_phone,
            "amount": total_amount,
            "package_code": package_info["code"],
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=60),
            "status": "PENDING",
        }
        PAYMENT_INTENTS[invoice_id] = PAYMENT_INTENTS[total_amount]

        msg = (
            f"💳 *INVOICE PEMBAYARAN MEMBERSHIP*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *Paket:* {package_info['name']}\n"
            f"🆔 *Invoice:* `{invoice_id}`\n"
            f"💰 *Total Pembayaran:* *Rp{total_amount:,}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Silakan scan QRIS dinamis di bawah ini melalui DANA, BCA Mobile, GoPay, OVO, atau m-Banking.\n\n"
            f"⚙️ _Akses turnstile gate IoT Anda akan otomatis aktif setelah pembayaran terverifikasi sistem._"
        )
        await send_whatsapp_text(user_phone, msg, tenant_id=self.tenant_id)
        await send_whatsapp_image_link(
            to=user_phone,
            image_url=qris_image_url,
            caption=f"QRIS {package_info['name']} Rp{total_amount:,}",
            tenant=self.tenant_id,
        )
        return {"action": "INVOICE_CREATED", "invoice_id": invoice_id, "amount": total_amount}

    async def send_class_schedule(self, user_phone: str, user_name: str) -> Dict[str, Any]:
        """Displays available Zumba and Studio class sessions with capacity."""
        sessions = gym_access_service.get_available_class_sessions(self.tenant_id)
        if not sessions:
            reply = "ℹ️ Belum ada jadwal kelas studio aktif saat ini. Silakan hubungi admin resepsionis."
            await send_whatsapp_text(user_phone, reply, tenant_id=self.tenant_id)
            return {"action": "CLASS_SCHEDULE", "sessions_count": 0}

        lines = [
            f"💃 *JADWAL KELAS STUDIO & ZUMBA ATMOSFITNES*\n",
            f"Halo *{user_name}*, berikut jadwal kelas yang tersedia:\n"
        ]

        idx_map = {}
        for i, s in enumerate(sessions, start=1):
            idx_map[str(i)] = s.id
            sched_str = s.schedule_time.strftime("%A, %d %B - %H:%M WIB")
            status_icon = "🟢" if s.is_available else "🔴"
            slot_info = f"Sisa {s.remaining_slots} slot" if s.is_available else "*PENUH*"

            lines.append(
                f"{i}️⃣ *{s.session_name}*\n"
                f"   👤 Instruktur: {s.instructor}\n"
                f"   ⏰ Waktu: {sched_str}\n"
                f"   {status_icon} Kapasitas: {s.booked_count}/{s.max_capacity} ({slot_info})\n"
                f"   👉 _Ketik: *book {i}*_\n"
            )

        lines.append("\n_Ketik *book 1* atau *book 2* untuk memesan slot kelas pilihan Anda._")
        full_text = "\n".join(lines)
        await send_whatsapp_text(user_phone, full_text, tenant_id=self.tenant_id)
        return {"action": "CLASS_SCHEDULE", "sessions_count": len(sessions)}

    async def handle_class_booking(
        self,
        user_phone: str,
        user_name: str,
        session_key: str
    ) -> Dict[str, Any]:
        """Processes booking request and validates capacity."""
        sessions = gym_access_service.get_available_class_sessions(self.tenant_id)

        target_session_id = None
        # Handle numeric choice (e.g. "1" -> first session)
        if session_key.isdigit():
            idx = int(session_key) - 1
            if 0 <= idx < len(sessions):
                target_session_id = str(sessions[idx].id)
        else:
            # Match by session ID
            for s in sessions:
                if str(s.id).lower() == session_key.lower():
                    target_session_id = str(s.id)
                    break

        if not target_session_id:
            reply = f"⚠️ Sesi kelas dengan kode *{session_key}* tidak ditemukan. Ketik *6* untuk melihat daftar jadwal kelas."
            await send_whatsapp_text(user_phone, reply, tenant_id=self.tenant_id)
            return {"action": "BOOKING_FAILED", "reason": "SESSION_NOT_FOUND"}

        # Attempt booking via service layer
        result = await gym_access_service.book_class_session(
            tenant_id=self.tenant_id,
            session_id=target_session_id,
            member_phone=user_phone,
            member_name=user_name,
        )

        if result.get("status") == "FULL":
            reply = (
                f"❌ *BOOKING GAGAL: KUOTA PENUH*\n\n"
                f"{result.get('message')}\n\n"
                f"Silakan pilih jadwal sesi lainnya dengan mengetik *6*."
            )
            await send_whatsapp_text(user_phone, reply, tenant_id=self.tenant_id)
            return {"action": "BOOKING_FULL", "result": result}

        # Booking confirmed!
        reply = (
            f"🎉 *BOOKING KELAS BERHASIL!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💃 *Kelas:* {result.get('session_name')}\n"
            f"👤 *Instruktur:* {result.get('instructor')}\n"
            f"🆔 *Kode Booking:* `{result.get('booking_id')[:8].upper()}`\n"
            f"🎟️ *Sisa Slot Kelas:* {result.get('remaining_slots')} kursi\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Silakan datang 10 menit sebelum kelas dimulai di Lantai 2 Studio Atmosfitnes. Selamat bersenang-senang! 🔥"
        )
        await send_whatsapp_text(user_phone, reply, tenant_id=self.tenant_id)
        return {"action": "BOOKING_SUCCESS", "result": result}

    async def check_member_status_and_reply(self, user_phone: str, user_name: str) -> Dict[str, Any]:
        """Checks membership and NFC card status for the user phone."""
        # 1. Lookup in in-memory
        member = None
        for m in gym_access_service._members.get(self.tenant_id, {}).values():
            if str(m.phone).replace("+", "").strip() == user_phone:
                member = m
                break

        # 2. Lookup in Supabase DB if not in memory
        if not member:
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table("gym_members") \
                        .select("*") \
                        .eq("tenant_id", self.tenant_id) \
                        .eq("phone", user_phone) \
                        .limit(1) \
                        .execute()
                    if res.data and len(res.data) > 0:
                        from app.schemas.gym_schema import GymMember
                        member = GymMember.model_validate(res.data[0])
                except Exception as e:
                    logger.warning(f"[GymTenant] Supabase member lookup error: {e}")

        if not member:
            reply = (
                f"ℹ️ *Status Membership Belum Ditemukan*\n\n"
                f"Nomor WhatsApp Anda (*{user_phone}*) belum terdaftar sebagai member aktif di Atmosfitnes.\n\n"
                f"Ketik *daftar member* atau *1-5* untuk memilih paket membership dan mendapatkan akses turnstile otomatis."
            )
            await send_whatsapp_text(user_phone, reply, tenant_id=self.tenant_id)
            return {"action": "STATUS_CHECK", "found": False}

        now = datetime.now(timezone.utc)
        is_valid = member.is_access_valid(now)
        exp_date_str = member.expiry_date.strftime("%d %B %Y")
        status_icon = "🟢" if is_valid else "🔴"
        status_text = "AKTIF" if is_valid else "KEDALUWARSA / SUSPEND"

        reply = (
            f"📋 *STATUS MEMBERSHIP ATMOSFITNES*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *Nama:* {member.name}\n"
            f"📦 *Paket:* {member.membership_package}\n"
            f"🏷️ *Status:* {status_icon} *{status_text}*\n"
            f"📅 *Masa Berlaku:* s.d. *{exp_date_str}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        if is_valid:
            reply += "🔓 Akses gate turnstile Anda dalam keadaan *AKTIF*. Selamat berlatih!"
        else:
            reply += "⚠️ Masa aktif Anda telah habis. Ketik *1* untuk memperpanjang membership instan."

        await send_whatsapp_text(user_phone, reply, tenant_id=self.tenant_id)
        return {"action": "STATUS_CHECK", "found": True, "is_valid": is_valid}

    async def send_facility_info(self, user_phone: str) -> Dict[str, Any]:
        """Sends gym facility and operational information."""
        info_text = (
            f"🏢 *INFORMASI FASILITAS & OPERASIONAL ATMOSFITNES*\n\n"
            f"📍 *Lokasi:* {GYM_LOCATION}\n"
            f"⏰ *Jam Operasional:* {GYM_OPERATIONAL_HOURS}\n\n"
            f"🌟 *Fasilitas Unggulan:*\n"
            f"• Free Weights & Dumbbells up to 50kg\n"
            f"• Modern Cardio Area (Treadmills, Ellipticals, Rowers)\n"
            f"• Resistance & Pin-Loaded Machines\n"
            f"• Smart IoT NFC Turnstile Access Gate\n"
            f"• Shower Panas/Dingin & Loker Digital\n"
            f"• Area Parkir Luas & Free WiFi High-Speed\n\n"
            f"_Ketik *menu* untuk kembali ke menu utama._"
        )
        await send_whatsapp_text(user_phone, info_text, tenant_id=self.tenant_id)
        return {"action": "FACILITY_INFO", "status": "sent"}

    async def send_escalation_message(self, user_phone: str) -> Dict[str, Any]:
        """Handles escalation to human gym admin / receptionist."""
        esc_text = (
            f"👨‍💼 *BANTUAN STAF RESEPSIONIS ATMOSFITNES*\n\n"
            f"Pesan Anda telah diteruskan ke tim Customer Service & Staf Resepsionis kami.\n\n"
            f"Staf kami akan segera menghubungi Anda melalui nomor WhatsApp ini pada jam operasional."
        )
        await send_whatsapp_text(user_phone, esc_text, tenant_id=self.tenant_id)
        return {"action": "ESCALATED", "status": "sent"}

    async def handle_ai_conversation(self, user_phone: str, user_text: str, user_name: str) -> Dict[str, Any]:
        """Fallback conversational AI using gym receptionist system prompt."""
        system_prompt = (
            "Kamu adalah resepsionis dan asisten AI resmi Atmosfitnes Gym yang ramah, energik, dan solutif.\n\n"
            f"Info Gym: Lokasi di {GYM_LOCATION}, Jam Operasional: {GYM_OPERATIONAL_HOURS}.\n"
            "Harga: Gym Basic Rp150.000, Zumba Class Rp200.000, Gym Premium Rp250.000, All Access Rp350.000, Personal Training Rp800.000.\n"
            "Akses masuk menggunakan kartu NFC otomatis di gate turnstile.\n\n"
            "Jawab secara singkat (maksimal 3 paragraf), ramah, dan tawarkan panduan menu jika diperlukan."
        )
        try:
            ai_reply = await ai_gateway.generate(
                user_message=user_text,
                context={"tenant_id": self.tenant_id, "user_phone": user_phone},
                system_prompt=system_prompt,
            )
            if not ai_reply:
                ai_reply = f"Halo {user_name}! Ada yang bisa kami bantu seputar membership atau akses gym Atmosfitnes? Ketik *menu* untuk melihat opsi layanan."
        except Exception as e:
            logger.warning(f"[GymAI] Completion fallback note: {e}")
            ai_reply = f"Halo {user_name}! Ada yang bisa kami bantu seputar membership atau akses gym Atmosfitnes? Ketik *menu* untuk opsi layanan."

        await send_whatsapp_text(user_phone, ai_reply, tenant_id=self.tenant_id)
        return {"action": "AI_REPLY", "status": "sent"}


# Global Singleton Instance
gym_service = GymTenantService()
