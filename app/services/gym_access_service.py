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
"""

import hashlib
import logging
from datetime import datetime, timezone
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
)
from app.services.whatsapp_service import get_supabase

logger = logging.getLogger("GYM_ACCESS_SERVICE")


class ControllerAuthenticationError(Exception):
    """Raised when an IoT controller fails device authentication."""
    pass


class GymAccessService:
    """Service layer managing Gym Membership, NFC Cards, and IoT Turnstile Access."""

    def __init__(self, in_memory_mode: bool = False):
        self.in_memory_mode = in_memory_mode
        # In-memory storage for test mocks & fast local caching
        self._members: Dict[str, Dict[str, GymMember]] = {}           # tenant_id -> {member_id: GymMember}
        self._cards: Dict[str, Dict[str, GymNfcCard]] = {}              # tenant_id -> {uid_hash: GymNfcCard}
        self._controllers: Dict[str, Dict[str, GymAccessController]] = {} # tenant_id -> {controller_id: GymAccessController}
        self._events: Dict[str, Dict[str, GymAccessEvent]] = {}         # tenant_id -> {idempotency_key: GymAccessEvent}

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
    # Core Feature 1: Real-time Access Verification
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

        clean_hash = uid_hash.strip().lower()
        now = datetime.now(timezone.utc)
        idem_key = idempotency_key or f"tap_{tenant_id}_{clean_hash}_{int(now.timestamp() * 1000)}"

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
            logger.info(f"[GymAccess] Member '{member.name}' is EXPIRED (expiry: {expiry_aware})")
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
            return TapAccessResponse(
                decision=AccessDecision.DENIED,
                reason=AccessReason.EXPIRED_MEMBERSHIP,
                message=f"Akses Ditolak: Masa aktif membership {member.name} telah berakhir.",
                member_name=member.name,
                membership_status=MembershipStatus.EXPIRED,
                expiry_date=member.expiry_date,
                unlock_gate=False,
            )

        # 5. ACCESS ALLOWED!
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


# Global Singleton Instance
gym_access_service = GymAccessService()
