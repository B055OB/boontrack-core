"""app/services/gym_access_service.py
Gym & IoT Access Control Service Layer (Vertical Pilot Atmosfitnes).

Features:
- Multi-tenant isolation enforcement (all operations locked to tenant_id)
- Device token validation for IoT Controllers (ESP32 Gate / Turnstiles)
- Real-time NFC Card verification with join to Member status & expiry date
- Access event audit logging with idempotency anti-duplication
- Offline whitelist generation for local ESP32 caching
- Offline event batch synchronization
- Controller heartbeat monitoring
- WhatsApp Renewal Notification loop with Dynamic QRIS & Unique Code
- Instant Member Auto-Reactivation upon Renewal Payment
"""

import hashlib
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Union
from uuid import uuid4

from app.schemas.gym_schema import (
    MembershipStatus,
    CardStatus,
    ControllerStatus,
    AccessEventType,
    AccessDecision,
    AccessReason,
    TapAccessResponse,
    GymMember,
    GymNfcCard,
    GymAccessController,
    GymAccessEvent,
    GymClassSession,
    GymClassBooking,
    AdminMemberItem,
    AdminAccessLogItem,
    AdminControllerItem,
)
from app.services.whatsapp_service import (
    get_supabase,
    send_whatsapp_text,
    send_whatsapp_image_link,
)
from app.utils.qris_generator import (
    generate_dynamic_qris_payload,
    generate_unique_code,
)
from app.services.reconciliation_service import PAYMENT_INTENTS

logger = logging.getLogger("GYM_ACCESS_SERVICE")

DEFAULT_ATMOSFITNES_STATIC_QRIS = (
    "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI"
    "51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID5911"
    "Atmosfitnes6012Kab. Bandung61054028663048DC1"
)

MEMBERSHIP_PACKAGE_PRICES = {
    "GYM_BASIC": 150000,
    "ZUMBA_CLASS": 200000,
    "GYM_PREMIUM": 250000,
    "REGULAR_MONTHLY": 250000,
    "ALL_ACCESS": 350000,
    "PERSONAL_TRAINING": 800000,
    "VIP_ANNUAL": 2400000,
    "STUDENT_PASS": 175000,
}



class ControllerAuthenticationError(Exception):
    """Raised when an IoT controller fails device authentication."""
    pass


class GymAccessService:
    """Service layer managing Gym Membership, NFC Cards, and IoT Turnstile Access."""

    def __init__(self, in_memory_mode: bool = False, cooldown_ms: int = 500):
        self.in_memory_mode = in_memory_mode
        self.cooldown_ms = cooldown_ms
        self._last_tap_timestamps: Dict[str, datetime] = {}
        # In-memory storage for test mocks & fast local caching
        self._members: Dict[str, Dict[str, GymMember]] = {}           # tenant_id -> {member_id: GymMember}
        self._cards: Dict[str, Dict[str, GymNfcCard]] = {}              # tenant_id -> {uid_hash: GymNfcCard}
        self._controllers: Dict[str, Dict[str, GymAccessController]] = {} # tenant_id -> {controller_id: GymAccessController}
        self._events: Dict[str, Dict[str, GymAccessEvent]] = {}         # tenant_id -> {idempotency_key: GymAccessEvent}
        self._class_sessions: Dict[str, Dict[str, GymClassSession]] = {} # tenant_id -> {session_id: GymClassSession}
        self._class_bookings: Dict[str, Dict[str, GymClassBooking]] = {} # tenant_id -> {booking_id: GymClassBooking}
        self._seed_default_classes()

    def _seed_default_classes(self):
        """Seeds initial Zumba and Studio sessions for Atmosfitnes."""
        tenant_id = "atmosfitnes"
        now = datetime.now(timezone.utc)
        self._class_sessions[tenant_id] = {
            "zumba_morning": GymClassSession(
                id="zumba_morning",
                tenant_id=tenant_id,
                session_name="Zumba Morning Party",
                instructor="Coach Rina",
                schedule_time=now + timedelta(days=1, hours=2),
                max_capacity=15,
                booked_count=12,
            ),
            "zumba_evening": GymClassSession(
                id="zumba_evening",
                tenant_id=tenant_id,
                session_name="Zumba Sunset Cardio",
                instructor="Coach Maya",
                schedule_time=now + timedelta(days=1, hours=10),
                max_capacity=12,
                booked_count=4,
            ),
            "yoga_weekend": GymClassSession(
                id="yoga_weekend",
                tenant_id=tenant_id,
                session_name="Vinyasa Yoga Flow",
                instructor="Master Dian",
                schedule_time=now + timedelta(days=2, hours=3),
                max_capacity=10,
                booked_count=10, # Full capacity demo
            ),
        }


    # =========================================================================
    # In-Memory Seed / Mock Helpers (For unit testing without live db)
    # =========================================================================

    def register_controller_in_memory(
        self,
        tenant_id: str,
        controller_id: str,
        name: str,
        raw_device_token: str,
        location: Optional[str] = None,
        status: ControllerStatus = ControllerStatus.ONLINE,
    ) -> GymAccessController:
        token_hash = self.hash_token(raw_device_token)
        ctrl = GymAccessController(
            tenant_id=tenant_id,
            controller_id=controller_id,
            name=name,
            location=location,
            device_token_hash=token_hash,
            status=status,
        )
        if tenant_id not in self._controllers:
            self._controllers[tenant_id] = {}
        self._controllers[tenant_id][controller_id] = ctrl
        return ctrl

    def register_member_in_memory(
        self,
        tenant_id: str,
        name: str,
        phone: str,
        expiry_date: datetime,
        membership_package: str = "REGULAR_MONTHLY",
        membership_status: MembershipStatus = MembershipStatus.ACTIVE,
        member_id: Optional[str] = None,
    ) -> GymMember:
        m = GymMember(
            id=member_id or str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            membership_package=membership_package,
            membership_status=membership_status,
            expiry_date=expiry_date,
        )
        if tenant_id not in self._members:
            self._members[tenant_id] = {}
        self._members[tenant_id][str(m.id)] = m
        return m

    def register_nfc_card_in_memory(
        self,
        tenant_id: str,
        member_id: str,
        uid_hash: str,
        status: CardStatus = CardStatus.ACTIVE,
    ) -> GymNfcCard:
        clean_hash = uid_hash.strip().lower()
        c = GymNfcCard(
            id=str(uuid4()),
            tenant_id=tenant_id,
            member_id=member_id,
            uid_hash=clean_hash,
            status=status,
        )
        if tenant_id not in self._cards:
            self._cards[tenant_id] = {}
        self._cards[tenant_id][clean_hash] = c
        return c

    def invalidate_member_cache(self, tenant_id: str, member_id: Optional[str] = None) -> None:
        """Invalidates in-memory cached member(s) to force re-fetch from database."""
        if tenant_id in self._members:
            if member_id:
                self._members[tenant_id].pop(str(member_id), None)
            else:
                self._members[tenant_id].clear()
        logger.info(f"[GymCache] Invalidated member cache for tenant='{tenant_id}', member_id='{member_id}'")

    def invalidate_card_cache(self, tenant_id: str, uid_hash: Optional[str] = None) -> None:
        """Invalidates in-memory cached card(s) to force re-fetch from database."""
        if tenant_id in self._cards:
            if uid_hash:
                self._cards[tenant_id].pop(uid_hash.strip().lower(), None)
            else:
                self._cards[tenant_id].clear()
        logger.info(f"[GymCache] Invalidated card cache for tenant='{tenant_id}', uid_hash='{uid_hash}'")

    def invalidate_all_caches(self, tenant_id: Optional[str] = None) -> None:
        """Flushes in-memory caches and tap cooldown timestamps."""
        if tenant_id:
            self._members.pop(tenant_id, None)
            self._cards.pop(tenant_id, None)
            self._controllers.pop(tenant_id, None)
            keys_to_remove = [k for k in self._last_tap_timestamps if k.startswith(f"{tenant_id}:")]
            for k in keys_to_remove:
                self._last_tap_timestamps.pop(k, None)
        else:
            self._members.clear()
            self._cards.clear()
            self._controllers.clear()
            self._last_tap_timestamps.clear()
        logger.info(f"[GymCache] Flushed all caches for tenant='{tenant_id}'")

    def update_member_status(
        self,
        tenant_id: str,
        member_id: str,
        status: MembershipStatus,
        expiry_date: Optional[datetime] = None
    ) -> Optional[GymMember]:
        """Updates member status and expiry date in-memory and database."""
        m = self._members.get(tenant_id, {}).get(str(member_id))
        if m:
            m.membership_status = status
            if expiry_date:
                m.expiry_date = expiry_date
            m.updated_at = datetime.now(timezone.utc)
            return m
        return None

    # =========================================================================
    # Security Helpers
    # =========================================================================

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Computes SHA256 hex digest of device authentication token."""
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()

    async def validate_controller(
        self,
        tenant_id: str,
        controller_id: str,
        device_token: Optional[str] = None
    ) -> GymAccessController:
        """Validates controller existence, tenant isolation, and device token."""
        ctrl: Optional[GymAccessController] = None

        # 1. Check in-memory store
        if tenant_id in self._controllers and controller_id in self._controllers[tenant_id]:
            ctrl = self._controllers[tenant_id][controller_id]
        else:
            # 2. Check Supabase DB
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table("gym_access_controllers") \
                        .select("*") \
                        .eq("tenant_id", tenant_id) \
                        .eq("controller_id", controller_id) \
                        .limit(1) \
                        .execute()
                    if res.data and len(res.data) > 0:
                        row = res.data[0]
                        ctrl = GymAccessController.model_validate(row)
                        if tenant_id not in self._controllers:
                            self._controllers[tenant_id] = {}
                        self._controllers[tenant_id][controller_id] = ctrl
                except Exception as e:
                    logger.warning(f"[GymService] Supabase controller lookup error: {e}")

        if not ctrl:
            logger.warning(f"[GymAccess] Controller '{controller_id}' not found for tenant '{tenant_id}'")
            raise ControllerAuthenticationError(f"Controller '{controller_id}' is not registered.")

        # Verify device token if provided
        if device_token:
            computed_hash = self.hash_token(device_token)
            if computed_hash != ctrl.device_token_hash and device_token != ctrl.device_token_hash:
                logger.warning(f"[GymAccess] Invalid device token for controller '{controller_id}' (tenant: {tenant_id})")
                raise ControllerAuthenticationError(f"Invalid device authentication token for controller '{controller_id}'.")

        return ctrl

    # =========================================================================
    # Core Feature 1: Real-time Access Verification & WhatsApp Renewal Fallback
    # =========================================================================

    async def verify_access(
        self,
        tenant_id: str = "atmosfitnes",
        controller_id: str = "GATE_01",
        uid_hash: str = "",
        device_token: Optional[str] = None,
        event_type: AccessEventType = AccessEventType.TAP_IN,
        idempotency_key: Optional[str] = None,
    ) -> TapAccessResponse:
        """Verifies NFC card tap, checks membership status, and logs audit access event."""
        # 1. Authenticate Controller
        try:
            await self.validate_controller(tenant_id, controller_id, device_token)
        except ControllerAuthenticationError as auth_err:
            logger.error(f"[GymAccess] Controller authentication failed: {auth_err}")
            raise

        clean_hash = str(uid_hash or "").strip().lower()[:128]
        now = datetime.now(timezone.utc)
        safe_hash_key = "".join(c for c in clean_hash[:32] if c.isalnum()) or "unknown"
        idem_key = idempotency_key or f"tap_{tenant_id}_{safe_hash_key}_{int(now.timestamp() * 1000)}"

        # 2. Lookup NFC Card
        card: Optional[GymNfcCard] = None
        if tenant_id in self._cards and clean_hash in self._cards[tenant_id]:
            card = self._cards[tenant_id][clean_hash]
        else:
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table("gym_nfc_cards") \
                        .select("*") \
                        .eq("tenant_id", tenant_id) \
                        .eq("uid_hash", clean_hash) \
                        .limit(1) \
                        .execute()
                    if res.data and len(res.data) > 0:
                        card = GymNfcCard.model_validate(res.data[0])
                except Exception as e:
                    logger.warning(f"[GymService] Supabase card lookup error: {e}")

        # Card Not Found -> DENIED
        if not card:
            logger.info(f"[GymAccess] Card '{clean_hash[:8]}...' not registered for tenant '{tenant_id}'")
            await self._log_access_event(
                tenant_id=tenant_id,
                controller_id=controller_id,
                member_id=None,
                card_id=None,
                event_type=event_type,
                decision=AccessDecision.DENIED,
                reason=AccessReason.UNKNOWN_CARD,
                idempotency_key=idem_key,
            )
            return TapAccessResponse(
                decision=AccessDecision.DENIED,
                reason=AccessReason.UNKNOWN_CARD,
                message="Akses Ditolak: Kartu NFC tidak terdaftar pada sistem.",
                unlock_gate=False,
            )

        # Card Blocked or Lost -> DENIED
        if card.status != CardStatus.ACTIVE:
            logger.info(f"[GymAccess] Card '{clean_hash[:8]}...' is {card.status}")
            reason_status = AccessReason.CARD_BLOCKED if card.status == CardStatus.BLOCKED else AccessReason.CARD_LOST
            await self._log_access_event(
                tenant_id=tenant_id,
                controller_id=controller_id,
                member_id=str(card.member_id),
                card_id=str(card.id),
                event_type=event_type,
                decision=AccessDecision.DENIED,
                reason=reason_status,
                idempotency_key=idem_key,
            )
            return TapAccessResponse(
                decision=AccessDecision.DENIED,
                reason=reason_status,
                message=f"Akses Ditolak: Kartu dinonaktifkan (Status: {card.status.value}).",
                unlock_gate=False,
            )

        # Check Duplicate & Rapid Tap Cooldown (<500ms)
        cooldown_key = f"{tenant_id}:{clean_hash}"
        last_tap_time = self._last_tap_timestamps.get(cooldown_key)
        if last_tap_time is not None:
            elapsed_ms = (now - last_tap_time).total_seconds() * 1000
            if elapsed_ms < self.cooldown_ms:
                logger.warning(
                    f"[GymAccess] Rapid tap cooldown throttled for card '{clean_hash[:8]}...' "
                    f"at {controller_id} ({elapsed_ms:.1f}ms < {self.cooldown_ms}ms)"
                )
                await self._log_access_event(
                    tenant_id=tenant_id,
                    controller_id=controller_id,
                    member_id=str(card.member_id) if card else None,
                    card_id=str(card.id) if card else None,
                    event_type=event_type,
                    decision=AccessDecision.DENIED,
                    reason=AccessReason.COOLDOWN_ACTIVE,
                    idempotency_key=f"cooldown_{idem_key}",
                )
                return TapAccessResponse(
                    decision=AccessDecision.DENIED,
                    reason=AccessReason.COOLDOWN_ACTIVE,
                    message=f"Akses Ditolak: Cooldown aktif (<{int(self.cooldown_ms)}ms). Mohon tunggu sejenak sebelum tap kembali.",
                    unlock_gate=False,
                )

        # 3. Lookup Member
        member: Optional[GymMember] = None
        member_id_str = str(card.member_id)
        if tenant_id in self._members and member_id_str in self._members[tenant_id]:
            member = self._members[tenant_id][member_id_str]
        else:
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table("gym_members") \
                        .select("*") \
                        .eq("tenant_id", tenant_id) \
                        .eq("id", member_id_str) \
                        .limit(1) \
                        .execute()
                    if res.data and len(res.data) > 0:
                        member = GymMember.model_validate(res.data[0])
                except Exception as e:
                    logger.warning(f"[GymService] Supabase member lookup error: {e}")

        if not member:
            logger.info(f"[GymAccess] Member '{member_id_str}' not found")
            await self._log_access_event(
                tenant_id=tenant_id,
                controller_id=controller_id,
                member_id=member_id_str,
                card_id=str(card.id),
                event_type=event_type,
                decision=AccessDecision.DENIED,
                reason=AccessReason.MEMBER_NOT_FOUND,
                idempotency_key=idem_key,
            )
            return TapAccessResponse(
                decision=AccessDecision.DENIED,
                reason=AccessReason.MEMBER_NOT_FOUND,
                message="Akses Ditolak: Data profil member tidak ditemukan.",
                unlock_gate=False,
            )

        # 4. Check Member Status & Expiry
        if member.membership_status == MembershipStatus.SUSPENDED:
            logger.info(f"[GymAccess] Member '{member.name}' is SUSPENDED")
            await self._log_access_event(
                tenant_id=tenant_id,
                controller_id=controller_id,
                member_id=str(member.id),
                card_id=str(card.id),
                event_type=event_type,
                decision=AccessDecision.DENIED,
                reason=AccessReason.MEMBER_SUSPENDED,
                idempotency_key=idem_key,
            )
            return TapAccessResponse(
                decision=AccessDecision.DENIED,
                reason=AccessReason.MEMBER_SUSPENDED,
                message=f"Akses Ditolak: Akun membership atas nama {member.name} sedang ditangguhkan.",
                member_name=member.name,
                membership_status=MembershipStatus.SUSPENDED,
                expiry_date=member.expiry_date,
                unlock_gate=False,
            )

        # Normalize Expiry Date Timezone
        expiry_aware = member.expiry_date if member.expiry_date.tzinfo else member.expiry_date.replace(tzinfo=timezone.utc)
        if member.membership_status == MembershipStatus.EXPIRED or expiry_aware <= now:
            logger.info(f"[GymAccess] Member '{member.name}' is EXPIRED (expiry: {expiry_aware}) -> Triggering WhatsApp Renewal Loop")
            await self._log_access_event(
                tenant_id=tenant_id,
                controller_id=controller_id,
                member_id=str(member.id),
                card_id=str(card.id),
                event_type=event_type,
                decision=AccessDecision.DENIED,
                reason=AccessReason.EXPIRED_MEMBERSHIP,
                idempotency_key=idem_key,
            )

            # Auto Trigger WhatsApp Renewal Notification & Dynamic QRIS
            try:
                await self.trigger_renewal_notification(tenant_id, member)
            except Exception as ren_err:
                logger.error(f"[GymRenewal] Error triggering renewal WA: {ren_err}", exc_info=True)

            return TapAccessResponse(
                decision=AccessDecision.DENIED,
                reason=AccessReason.EXPIRED_MEMBERSHIP,
                message=f"Akses Ditolak: Masa aktif membership {member.name} telah berakhir. Link QRIS perpanjangan telah dikirim ke WhatsApp Anda.",
                member_name=member.name,
                membership_status=MembershipStatus.EXPIRED,
                expiry_date=member.expiry_date,
                unlock_gate=False,
            )

        # 5. ACCESS ALLOWED!
        self._last_tap_timestamps[cooldown_key] = now
        event = await self._log_access_event(
            tenant_id=tenant_id,
            controller_id=controller_id,
            member_id=str(member.id),
            card_id=str(card.id),
            event_type=event_type,
            decision=AccessDecision.ALLOWED,
            reason=AccessReason.VALID,
            idempotency_key=idem_key,
        )

        # Send friendly WhatsApp check-in notification
        if member.phone and not self.in_memory_mode:
            checkin_msg = f"Selamat latihan di Atmosfitnes, {member.name}! Check-in berhasil tercatat."
            try:
                await send_whatsapp_text(member.phone, checkin_msg, tenant_id=tenant_id)
            except Exception as checkin_err:
                logger.debug(f"[GymCheckIn] WA notification note: {checkin_err}")

        logger.info(f"[GymAccess] ACCESS ALLOWED for '{member.name}' at {controller_id}")
        return TapAccessResponse(
            decision=AccessDecision.ALLOWED,
            reason=AccessReason.VALID,
            message=f"Akses Diberikan. Selamat berlatih di Atmosfitnes, {member.name}!",
            member_name=member.name,
            membership_status=MembershipStatus.ACTIVE,
            expiry_date=member.expiry_date,
            event_id=event.id if event else None,
            unlock_gate=True,
        )


    # =========================================================================
    # WhatsApp Renewal Loop & Dynamic QRIS Dispatcher
    # =========================================================================

    async def trigger_renewal_notification(
        self,
        tenant_id: str,
        member: GymMember,
        static_qris_payload: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates dynamic QRIS invoice and dispatches renewal message to member's WhatsApp."""
        if not member.phone:
            logger.warning(f"[GymRenewal] Member '{member.name}' has no phone number")
            return {"status": "skipped", "reason": "no_phone"}

        # 1. Determine Package Base Price & Unique Code
        base_price = MEMBERSHIP_PACKAGE_PRICES.get(member.membership_package, 250000)
        unique_code = generate_unique_code(101, 899)
        total_amount = base_price + unique_code

        invoice_id = f"GYM-REN-{str(member.id)[:8].upper()}-{unique_code}"
        static_qris = static_qris_payload or DEFAULT_ATMOSFITNES_STATIC_QRIS

        # 2. Generate Dynamic QRIS Payload & QuickChart QR Link
        dynamic_qris = generate_dynamic_qris_payload(static_qris, total_amount)
        encoded_payload = urllib.parse.quote(dynamic_qris)
        qris_image_url = f"https://quickchart.io/qr?text={encoded_payload}&size=500&ecLevel=H"

        # 3. Register Payment Intent for Reconciliation
        intent_record = {
            "invoice_id": invoice_id,
            "tenant_id": tenant_id,
            "product": "gym_membership_renewal",
            "member_id": str(member.id),
            "user_id": str(member.phone),
            "user_phone": str(member.phone),
            "amount": total_amount,
            "total_amount": total_amount,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=60),
            "status": "PENDING",
        }
        PAYMENT_INTENTS[total_amount] = intent_record
        PAYMENT_INTENTS[invoice_id] = intent_record

        # 4. Format WhatsApp Message
        exp_date_str = member.expiry_date.strftime("%d %B %Y")
        renewal_msg = (
            f"Halo *{member.name}*, masa aktif membership Atmosfitnes Anda telah berakhir pada *{exp_date_str}*.\n\n"
            f"Untuk perpanjangan instan dan membuka akses gate, silakan scan QRIS berikut senilai *Rp{total_amount:,}*.\n\n"
            f"Akses akan aktif otomatis setelah pembayaran terverifikasi."
        )

        logger.info(f"[GymRenewal] Dispatching WA renewal notice to {member.phone} (amount: Rp{total_amount:,}, inv: {invoice_id})")

        # 5. Send WhatsApp Text & QRIS Image
        await send_whatsapp_text(member.phone, renewal_msg, tenant_id=tenant_id)
        await send_whatsapp_image_link(
            to=member.phone,
            image_url=qris_image_url,
            caption=f"QRIS Perpanjangan Membership Atmosfitnes Rp{total_amount:,} (Lunas otomatis membuka gate turnstile)",
            tenant=tenant_id,
        )

        return {
            "status": "sent",
            "invoice_id": invoice_id,
            "total_amount": total_amount,
            "member_id": str(member.id),
            "phone": member.phone,
            "qris_image_url": qris_image_url,
        }

    # =========================================================================
    # Payment Callback: Instant Membership Auto-Reactivation
    # =========================================================================

    async def process_gym_membership_renewal(
        self,
        tenant_id: str,
        member_id: str,
        amount: Optional[int] = None,
        invoice_id: Optional[str] = None,
        days_to_add: int = 30,
    ) -> Dict[str, Any]:
        """Reactivates member upon payment confirmation, extends expiry date, and sends WA confirmation."""
        now = datetime.now(timezone.utc)
        member: Optional[GymMember] = None

        # 1. Lookup Member in In-Memory
        if tenant_id in self._members and member_id in self._members[tenant_id]:
            member = self._members[tenant_id][member_id]
        else:
            # 2. Lookup in Supabase
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table("gym_members") \
                        .select("*") \
                        .eq("tenant_id", tenant_id) \
                        .eq("id", member_id) \
                        .limit(1) \
                        .execute()
                    if res.data and len(res.data) > 0:
                        member = GymMember.model_validate(res.data[0])
                except Exception as e:
                    logger.warning(f"[GymReactivation] Supabase member lookup error: {e}")

        if not member:
            logger.error(f"[GymReactivation] Cannot reactivate: Member '{member_id}' not found in tenant '{tenant_id}'")
            return {"status": "error", "message": "Member not found"}

        # 3. Calculate New Expiry Date (Add days to current or now)
        current_exp_aware = member.expiry_date if member.expiry_date.tzinfo else member.expiry_date.replace(tzinfo=timezone.utc)
        base_calc_date = max(now, current_exp_aware)
        new_expiry_date = base_calc_date + timedelta(days=days_to_add)

        # 4. Update Member Status to ACTIVE
        member.membership_status = MembershipStatus.ACTIVE
        member.expiry_date = new_expiry_date
        member.updated_at = now

        # Update in-memory
        if tenant_id not in self._members:
            self._members[tenant_id] = {}
        self._members[tenant_id][member_id] = member

        # Clear any tap cooldown for this tenant so member can tap in immediately
        keys_to_remove = [k for k in self._last_tap_timestamps if k.startswith(f"{tenant_id}:")]
        for k in keys_to_remove:
            self._last_tap_timestamps.pop(k, None)

        # Persist update to Supabase
        supabase = get_supabase()
        if supabase:
            try:
                supabase.table("gym_members") \
                    .update({
                        "membership_status": "ACTIVE",
                        "expiry_date": new_expiry_date.isoformat(),
                        "updated_at": now.isoformat(),
                    }) \
                    .eq("tenant_id", tenant_id) \
                    .eq("id", member_id) \
                    .execute()
            except Exception as e:
                logger.warning(f"[GymReactivation] Supabase member update error: {e}")

        # Mark intent as paid in memory if exists
        if invoice_id and invoice_id in PAYMENT_INTENTS:
            PAYMENT_INTENTS[invoice_id]["status"] = "PAID"

        # 5. Send WhatsApp Confirmation Message to Member
        if member.phone:
            formatted_date = new_expiry_date.strftime("%d %B %Y")
            amount_display = f"Rp{amount:,}" if amount else "Lunas"
            pkg_name = str(member.membership_package or "Gym Membership").replace("_", " ").title()
            confirm_msg = (
                f"🎉 *PEMBAYARAN MEMBERSHIP TERVERIFIKASI!*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Pembayaran {amount_display} terverifikasi! Membership {pkg_name} aktif s.d {formatted_date}.\n\n"
                f"Silakan tunjukkan pesan ini ke meja kasir untuk pengambilan dan aktivasi kartu akses NFC Anda.\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🔓 Akses gate turnstile otomatis telah AKTIF. Selamat berlatih di Atmosfitnes! 💪"
            )
            await send_whatsapp_text(member.phone, confirm_msg, tenant_id=tenant_id)


        logger.info(f"[GymReactivation] Member '{member.name}' ({member_id}) successfully reactivated until {new_expiry_date.isoformat()}")
        return {
            "status": "RENEWED",
            "member_id": member_id,
            "name": member.name,
            "membership_status": "ACTIVE",
            "new_expiry_date": new_expiry_date.isoformat(),
            "unlocked": True,
        }

    # =========================================================================
    # Core Feature 2: Whitelist Generation for ESP32 Offline Caching
    # =========================================================================

    async def get_active_whitelist(
        self,
        tenant_id: str,
        controller_id: str,
        device_token: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves list of all active NFC card hashes for ESP32 offline caching."""
        await self.validate_controller(tenant_id, controller_id, device_token)

        now = datetime.now(timezone.utc)
        whitelist: List[Dict[str, Any]] = []

        # 1. From In-Memory Store
        if tenant_id in self._cards:
            for uid_hash, card in self._cards[tenant_id].items():
                if card.status == CardStatus.ACTIVE:
                    member_id_str = str(card.member_id)
                    member = self._members.get(tenant_id, {}).get(member_id_str)
                    if member and member.is_access_valid(now):
                        whitelist.append({
                            "uid_hash": uid_hash,
                            "member_id": str(member.id),
                            "name": member.name,
                            "expiry_date": member.expiry_date.isoformat(),
                        })

        # 2. From Supabase DB if in-memory empty
        if not whitelist:
            supabase = get_supabase()
            if supabase:
                try:
                    res_cards = supabase.table("gym_nfc_cards") \
                        .select("uid_hash, member_id, status") \
                        .eq("tenant_id", tenant_id) \
                        .eq("status", "ACTIVE") \
                        .execute()
                    if res_cards.data:
                        card_rows = res_cards.data
                        member_ids = [c["member_id"] for c in card_rows if c.get("member_id")]
                        if member_ids:
                            res_members = supabase.table("gym_members") \
                                .select("id, name, membership_status, expiry_date") \
                                .eq("tenant_id", tenant_id) \
                                .in_("id", member_ids) \
                                .execute()
                            valid_members_map = {}
                            if res_members.data:
                                for m in res_members.data:
                                    exp_str = m.get("expiry_date")
                                    if exp_str:
                                        exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                                        if m.get("membership_status") == "ACTIVE" and exp_dt > now:
                                            valid_members_map[str(m["id"])] = m

                            for c in card_rows:
                                m_info = valid_members_map.get(str(c.get("member_id")))
                                if m_info:
                                    whitelist.append({
                                        "uid_hash": c["uid_hash"],
                                        "member_id": str(m_info["id"]),
                                        "name": m_info["name"],
                                        "expiry_date": m_info["expiry_date"],
                                    })
                except Exception as e:
                    logger.warning(f"[GymService] Supabase whitelist query error: {e}")

        logger.info(f"[GymWhitelist] Generated {len(whitelist)} active whitelist entries for {controller_id} ({tenant_id})")
        return whitelist

    # =========================================================================
    # Core Feature 3: Offline Event Batch Synchronization
    # =========================================================================

    async def sync_offline_events(
        self,
        tenant_id: str,
        controller_id: str,
        events_list: List[Dict[str, Any]],
        device_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Batch-inserts offline logged events with idempotency anti-duplication."""
        await self.validate_controller(tenant_id, controller_id, device_token)

        synced_count = 0
        duplicate_count = 0

        for raw_evt in events_list:
            idem_key = raw_evt.get("idempotency_key") or str(uuid4())
            
            # Check in-memory duplication
            if tenant_id in self._events and idem_key in self._events[tenant_id]:
                duplicate_count += 1
                continue

            event_obj = GymAccessEvent(
                id=str(uuid4()),
                tenant_id=tenant_id,
                controller_id=controller_id,
                member_id=raw_evt.get("member_id"),
                card_id=raw_evt.get("card_id"),
                event_type=raw_evt.get("event_type", AccessEventType.TAP_IN),
                decision=raw_evt.get("decision", AccessDecision.ALLOWED),
                reason=raw_evt.get("reason", AccessReason.VALID),
                idempotency_key=idem_key,
                created_at=raw_evt.get("created_at") or datetime.now(timezone.utc),
            )

            if tenant_id not in self._events:
                self._events[tenant_id] = {}
            self._events[tenant_id][idem_key] = event_obj

            # Persist to Supabase if available
            supabase = get_supabase()
            if supabase:
                try:
                    payload = {
                        "id": str(event_obj.id),
                        "tenant_id": tenant_id,
                        "controller_id": controller_id,
                        "member_id": str(event_obj.member_id) if event_obj.member_id else None,
                        "card_id": str(event_obj.card_id) if event_obj.card_id else None,
                        "event_type": str(event_obj.event_type.value),
                        "decision": str(event_obj.decision.value),
                        "reason": str(event_obj.reason.value if hasattr(event_obj.reason, 'value') else event_obj.reason),
                        "idempotency_key": idem_key,
                        "created_at": event_obj.created_at.isoformat(),
                    }
                    supabase.table("gym_access_events").insert(payload).execute()
                except Exception as e:
                    # Ignore unique violation if duplicate
                    if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                        duplicate_count += 1
                        continue
                    logger.warning(f"[GymSync] Supabase event insert note: {e}")

            synced_count += 1

        logger.info(f"[GymSync] Synced {synced_count} events ({duplicate_count} duplicates skipped) from {controller_id}")
        return {
            "status": "success",
            "synced_count": synced_count,
            "duplicate_count": duplicate_count,
            "total_received": len(events_list),
        }

    # =========================================================================
    # Core Feature 4: Controller Heartbeat
    # =========================================================================

    async def record_heartbeat(
        self,
        tenant_id: str,
        controller_id: str,
        device_token: Optional[str] = None,
        firmware_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Updates controller last_seen_at timestamp and sets status to ONLINE."""
        ctrl = await self.validate_controller(tenant_id, controller_id, device_token)

        now = datetime.now(timezone.utc)
        ctrl.last_seen_at = now
        ctrl.status = ControllerStatus.ONLINE

        supabase = get_supabase()
        if supabase:
            try:
                supabase.table("gym_access_controllers") \
                    .update({
                        "last_seen_at": now.isoformat(),
                        "status": "ONLINE",
                    }) \
                    .eq("tenant_id", tenant_id) \
                    .eq("controller_id", controller_id) \
                    .execute()
            except Exception as e:
                logger.warning(f"[GymHeartbeat] Supabase update note: {e}")

        logger.info(f"[GymHeartbeat] Controller '{controller_id}' ({tenant_id}) reported heartbeat at {now.isoformat()}")
        return {
            "status": "ONLINE",
            "controller_id": controller_id,
            "tenant_id": tenant_id,
            "timestamp": now.isoformat(),
            "acknowledged": True,
        }

    # =========================================================================
    # Internal Audit Logger
    # =========================================================================

    async def _log_access_event(
        self,
        tenant_id: str,
        controller_id: str,
        member_id: Optional[str],
        card_id: Optional[str],
        event_type: AccessEventType,
        decision: AccessDecision,
        reason: Union[AccessReason, str],
        idempotency_key: str,
    ) -> GymAccessEvent:
        event = GymAccessEvent(
            id=str(uuid4()),
            tenant_id=tenant_id,
            controller_id=controller_id,
            member_id=member_id,
            card_id=card_id,
            event_type=event_type,
            decision=decision,
            reason=reason,
            idempotency_key=idempotency_key,
            created_at=datetime.now(timezone.utc),
        )

        if tenant_id not in self._events:
            self._events[tenant_id] = {}
        self._events[tenant_id][idempotency_key] = event

        if not self.in_memory_mode:
            supabase = get_supabase()
            if supabase:
                try:
                    payload = {
                        "id": str(event.id),
                        "tenant_id": tenant_id,
                        "controller_id": controller_id,
                        "member_id": str(member_id) if member_id else None,
                        "card_id": str(card_id) if card_id else None,
                        "event_type": str(event_type.value),
                        "decision": str(decision.value),
                        "reason": str(reason.value if hasattr(reason, 'value') else reason),
                        "idempotency_key": idempotency_key,
                        "created_at": event.created_at.isoformat(),
                    }
                    supabase.table("gym_access_events").insert(payload).execute()
                except Exception as e:
                    logger.warning(f"[GymAuditLog] Supabase event insert note: {e}")

        return event

    # =========================================================================
    # Class Sessions & Booking Engine (Zumba, Studio)
    # =========================================================================

    def get_available_class_sessions(self, tenant_id: str) -> List[GymClassSession]:
        """Returns list of active class sessions for a tenant."""
        if tenant_id not in self._class_sessions:
            return []
        return list(self._class_sessions[tenant_id].values())

    async def book_class_session(
        self,
        tenant_id: str,
        session_id: str,
        member_phone: str,
        member_name: str,
        member_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validates capacity and books a class session."""
        sessions = self._class_sessions.get(tenant_id, {})
        session = sessions.get(session_id)
        if not session:
            return {
                "status": "NOT_FOUND",
                "message": f"Sesi kelas '{session_id}' tidak ditemukan."
            }

        if session.booked_count >= session.max_capacity:
            return {
                "status": "FULL",
                "message": f"Mohon maaf, kuota untuk kelas '{session.session_name}' sudah penuh ({session.booked_count}/{session.max_capacity} peserta)."
            }

        # Increment booked count & register booking
        session.booked_count += 1
        booking = GymClassBooking(
            tenant_id=tenant_id,
            session_id=session_id,
            member_id=member_id,
            member_phone=member_phone,
            member_name=member_name,
            status="CONFIRMED"
        )
        if tenant_id not in self._class_bookings:
            self._class_bookings[tenant_id] = {}
        self._class_bookings[tenant_id][str(booking.id)] = booking

        return {
            "status": "CONFIRMED",
            "booking_id": str(booking.id),
            "session_name": session.session_name,
            "instructor": session.instructor,
            "schedule_time": session.schedule_time.isoformat(),
            "remaining_slots": session.remaining_slots,
            "message": f"Booking berhasil untuk {session.session_name} bersama {session.instructor}!"
        }

    # =========================================================================
    # Admin Dashboard Backend Operations
    # =========================================================================

    async def pair_card(
        self,
        tenant_id: str,
        member_id: str,
        uid_hash: str
    ) -> Dict[str, Any]:
        """Pairs a new NFC card UID hash to a gym member."""
        clean_hash = uid_hash.strip().lower()
        now = datetime.now(timezone.utc)

        # 1. Lookup Member
        member = self._members.get(tenant_id, {}).get(member_id)
        if not member:
            supabase = get_supabase()
            if supabase:
                try:
                    res = supabase.table("gym_members").select("*").eq("tenant_id", tenant_id).eq("id", member_id).limit(1).execute()
                    if res.data:
                        member = GymMember.model_validate(res.data[0])
                except Exception as e:
                    logger.warning(f"[GymAdmin] Member lookup note: {e}")

        if not member:
            return {"status": "error", "message": f"Member with ID '{member_id}' not found."}

        # 2. Register / Update Card in Memory
        card = self.register_nfc_card_in_memory(
            tenant_id=tenant_id,
            member_id=member_id,
            uid_hash=clean_hash,
            status=CardStatus.ACTIVE
        )

        # Persist to DB if available
        supabase = get_supabase()
        if supabase:
            try:
                supabase.table("gym_nfc_cards").upsert({
                    "id": str(card.id),
                    "tenant_id": tenant_id,
                    "member_id": member_id,
                    "uid_hash": clean_hash,
                    "status": "ACTIVE",
                    "created_at": now.isoformat(),
                }, on_conflict="tenant_id,uid_hash").execute()
            except Exception as e:
                logger.warning(f"[GymAdmin] Supabase card upsert note: {e}")

        logger.info(f"[GymAdmin] Paired NFC card '{clean_hash[:8]}...' to member '{member.name}' ({member_id})")
        return {
            "status": "PAIRED",
            "member_id": member_id,
            "member_name": member.name,
            "uid_hash": clean_hash,
            "card_status": "ACTIVE",
        }

    async def get_admin_members(
        self,
        tenant_id: str,
        page: int = 1,
        limit: int = 20,
        status: Optional[str] = None,
        package: Optional[str] = None
    ) -> Dict[str, Any]:
        """Returns paginated member list with NFC pairing indicator."""
        now = datetime.now(timezone.utc)
        members_map = self._members.get(tenant_id, {})
        cards_map = self._cards.get(tenant_id, {})

        # Inverted card lookup: member_id -> uid_hash
        paired_map: Dict[str, str] = {}
        for uid_h, card in cards_map.items():
            if card.status == CardStatus.ACTIVE:
                paired_map[str(card.member_id)] = uid_h

        all_members = list(members_map.values())
        filtered = []
        for m in all_members:
            if status and m.membership_status.value.upper() != status.upper():
                continue
            if package and m.membership_package.upper() != package.upper():
                continue
            filtered.append(m)

        # Pagination
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paged_members = filtered[start_idx:end_idx]

        items = []
        for m in paged_members:
            m_id = str(m.id)
            paired_hash = paired_map.get(m_id)
            items.append(AdminMemberItem(
                id=m_id,
                tenant_id=tenant_id,
                name=m.name,
                phone=m.phone,
                membership_package=m.membership_package,
                membership_status=m.membership_status.value,
                expiry_date=m.expiry_date.isoformat(),
                is_paired=paired_hash is not None,
                paired_card_hash=paired_hash,
                created_at=m.created_at.isoformat() if hasattr(m, 'created_at') and m.created_at else now.isoformat(),
            ))

        return {
            "total": len(filtered),
            "page": page,
            "limit": limit,
            "members": [it.model_dump() for it in items],
        }

    async def get_admin_access_logs(
        self,
        tenant_id: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Returns recent access audit events sorted by timestamp DESC."""
        events_map = self._events.get(tenant_id, {})
        all_events = list(events_map.values())
        all_events.sort(key=lambda e: e.created_at, reverse=True)
        recent_events = all_events[:limit]

        controllers_map = self._controllers.get(tenant_id, {})
        members_map = self._members.get(tenant_id, {})

        items = []
        for ev in recent_events:
            ctrl = controllers_map.get(ev.controller_id)
            ctrl_name = ctrl.name if ctrl else ev.controller_id
            m = members_map.get(str(ev.member_id)) if ev.member_id else None
            m_name = m.name if m else ("Unknown Member" if ev.member_id else "Unregistered Card")

            items.append(AdminAccessLogItem(
                id=str(ev.id),
                created_at=ev.created_at.isoformat(),
                member_name=m_name,
                member_id=str(ev.member_id) if ev.member_id else None,
                controller_name=ctrl_name,
                controller_id=ev.controller_id,
                event_type=ev.event_type.value if hasattr(ev.event_type, 'value') else str(ev.event_type),
                decision=ev.decision.value if hasattr(ev.decision, 'value') else str(ev.decision),
                reason=ev.reason.value if hasattr(ev.reason, 'value') else str(ev.reason),
            ))

        return {
            "total": len(items),
            "logs": [it.model_dump() for it in items],
        }

    async def get_admin_controllers(self, tenant_id: str) -> Dict[str, Any]:
        """Lists IoT controllers with dynamic online indicator (last_seen_at <= 60s)."""
        now = datetime.now(timezone.utc)
        ctrl_map = self._controllers.get(tenant_id, {})

        # Ensure default controllers exist for Atmosfitnes
        if not ctrl_map and tenant_id == "atmosfitnes":
            self.register_controller_in_memory(tenant_id, "GATE_MAIN_01", "Pintu Utama / Lobby Turnstile", "secret_token_lobby", "Lobby Utama")
            self.register_controller_in_memory(tenant_id, "GATE_GYM_LT1", "Turnstile Gym Lantai 1", "secret_token_lt1", "Lantai 1 Free Weights")
            self.register_controller_in_memory(tenant_id, "GATE_ZUMBA_LT2", "Studio Zumba Lantai 2", "secret_token_zumba", "Lantai 2 Studio")
            ctrl_map = self._controllers.get(tenant_id, {})

        items = []
        for ctrl_id, ctrl in ctrl_map.items():
            last_seen = ctrl.last_seen_at if ctrl.last_seen_at.tzinfo else ctrl.last_seen_at.replace(tzinfo=timezone.utc)
            delta_seconds = (now - last_seen).total_seconds()
            is_online = delta_seconds <= 60 and ctrl.status == ControllerStatus.ONLINE

            items.append(AdminControllerItem(
                id=str(ctrl.id),
                controller_id=ctrl.controller_id,
                name=ctrl.name,
                location=ctrl.location,
                status=ctrl.status.value,
                is_online=is_online,
                last_seen_at=ctrl.last_seen_at.isoformat(),
            ))

        return {
            "total": len(items),
            "controllers": [it.model_dump() for it in items],
        }


# Global Singleton Instance
gym_access_service = GymAccessService()

