"""tests/test_gym_migration.py
Unit tests for Gym & IoT Access Control Migration, Schemas, and Multi-Tenant Isolation (Atmosfitnes Pilot).
"""

import os
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.schemas.gym_schema import (
    MembershipStatus,
    CardStatus,
    ControllerStatus,
    AccessEventType,
    AccessDecision,
    AccessReason,
    GymMember,
    GymMemberCreate,
    GymNfcCard,
    GymNfcCardCreate,
    GymAccessController,
    GymAccessControllerCreate,
    GymAccessEvent,
    GymAccessEventCreate,
    TapAccessRequest,
    TapAccessResponse,
)


class TestGymMigrationSQL(unittest.TestCase):
    """Test SQL Migration file syntax and database operations."""

    MIGRATION_PATH = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "migrations",
        "004_create_gym_iot_tables.sql"
    )

    def test_migration_file_exists_and_contains_expected_ddl(self):
        """Verify the migration script exists and has all 4 tables, unique constraints, and indexes."""
        self.assertTrue(os.path.exists(self.MIGRATION_PATH), "004_create_gym_iot_tables.sql does not exist")
        with open(self.MIGRATION_PATH, "r", encoding="utf-8") as f:
            sql_content = f.read()

        # Check all 4 tables
        self.assertIn("CREATE TABLE IF NOT EXISTS gym_members", sql_content)
        self.assertIn("CREATE TABLE IF NOT EXISTS gym_nfc_cards", sql_content)
        self.assertIn("CREATE TABLE IF NOT EXISTS gym_access_controllers", sql_content)
        self.assertIn("CREATE TABLE IF NOT EXISTS gym_access_events", sql_content)

        # Check multi-tenant constraints
        self.assertIn("uq_gym_card_tenant_uid", sql_content)
        self.assertIn("uq_gym_controller_tenant", sql_content)
        self.assertIn("uq_gym_event_idempotency", sql_content)

        # Check indexes
        self.assertIn("idx_gym_members_lookup", sql_content)
        self.assertIn("idx_gym_cards_lookup", sql_content)
        self.assertIn("idx_gym_events_lookup", sql_content)

    def test_sqlite_ddl_and_tenant_isolation(self):
        """Test schema integrity, foreign keys, cascade delete, and tenant isolation using SQLite in-memory."""
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()

        # DDL adapted for SQLite in-memory testing
        cursor.executescript("""
        CREATE TABLE gym_members (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            membership_package TEXT DEFAULT 'REGULAR_MONTHLY',
            membership_status TEXT DEFAULT 'ACTIVE',
            expiry_date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE gym_nfc_cards (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            member_id TEXT REFERENCES gym_members(id) ON DELETE CASCADE,
            uid_hash TEXT NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            created_at TEXT DEFAULT (datetime('now')),
            CONSTRAINT uq_gym_card_tenant_uid UNIQUE (tenant_id, uid_hash)
        );

        CREATE TABLE gym_access_controllers (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            controller_id TEXT NOT NULL,
            name TEXT NOT NULL,
            location TEXT,
            device_token_hash TEXT NOT NULL,
            status TEXT DEFAULT 'ONLINE',
            last_seen_at TEXT DEFAULT (datetime('now')),
            created_at TEXT DEFAULT (datetime('now')),
            CONSTRAINT uq_gym_controller_tenant UNIQUE (tenant_id, controller_id)
        );

        CREATE TABLE gym_access_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            controller_id TEXT NOT NULL,
            member_id TEXT,
            card_id TEXT,
            event_type TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT,
            idempotency_key TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            CONSTRAINT uq_gym_event_idempotency UNIQUE (tenant_id, idempotency_key)
        );
        """)

        # 1. Insert Members for two distinct tenants
        member_id_1 = str(uuid4())
        member_id_2 = str(uuid4())
        cursor.execute(
            "INSERT INTO gym_members (id, tenant_id, name, phone, expiry_date) VALUES (?, ?, ?, ?, ?)",
            (member_id_1, "atmosfitnes", "Budi Santoso", "62811223344", "2026-12-31T23:59:59Z")
        )
        cursor.execute(
            "INSERT INTO gym_members (id, tenant_id, name, phone, expiry_date) VALUES (?, ?, ?, ?, ?)",
            (member_id_2, "other_gym", "Siti Rahma", "62899887766", "2026-12-31T23:59:59Z")
        )
        conn.commit()

        # Verify tenant segregation
        cursor.execute("SELECT name FROM gym_members WHERE tenant_id = ?", ("atmosfitnes",))
        atmos_members = cursor.fetchall()
        self.assertEqual(len(atmos_members), 1)
        self.assertEqual(atmos_members[0][0], "Budi Santoso")

        # 2. Insert NFC Cards and test unique constraint per tenant
        card_id_1 = str(uuid4())
        card_id_2 = str(uuid4())
        uid_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        # Same uid_hash in different tenants is ALLOWED
        cursor.execute(
            "INSERT INTO gym_nfc_cards (id, tenant_id, member_id, uid_hash, status) VALUES (?, ?, ?, ?, ?)",
            (card_id_1, "atmosfitnes", member_id_1, uid_hash, "ACTIVE")
        )
        cursor.execute(
            "INSERT INTO gym_nfc_cards (id, tenant_id, member_id, uid_hash, status) VALUES (?, ?, ?, ?, ?)",
            (card_id_2, "other_gym", member_id_2, uid_hash, "ACTIVE")
        )
        conn.commit()

        # Same uid_hash in same tenant must FAIL (unique constraint)
        with self.assertRaises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO gym_nfc_cards (id, tenant_id, member_id, uid_hash, status) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), "atmosfitnes", member_id_1, uid_hash, "ACTIVE")
            )

        # 3. Test Foreign Key Cascade Delete
        cursor.execute("DELETE FROM gym_members WHERE id = ?", (member_id_1,))
        conn.commit()

        cursor.execute("SELECT id FROM gym_nfc_cards WHERE member_id = ?", (member_id_1,))
        self.assertIsNone(cursor.fetchone(), "Card was not cascade-deleted with member")

        # 4. Test Controller Uniqueness
        cursor.execute(
            "INSERT INTO gym_access_controllers (id, tenant_id, controller_id, name, device_token_hash) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), "atmosfitnes", "TURNSTILE_01", "Gate Utama", "hash123456")
        )
        conn.commit()

        # Duplicate controller_id in same tenant fails
        with self.assertRaises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO gym_access_controllers (id, tenant_id, controller_id, name, device_token_hash) VALUES (?, ?, ?, ?, ?)",
                (str(uuid4()), "atmosfitnes", "TURNSTILE_01", "Gate Duplikat", "hash999999")
            )

        # 5. Test Event Idempotency Constraint
        cursor.execute(
            "INSERT INTO gym_access_events (id, tenant_id, controller_id, event_type, decision, idempotency_key) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid4()), "atmosfitnes", "TURNSTILE_01", "TAP_IN", "ALLOWED", "idem_key_1001")
        )
        conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            cursor.execute(
                "INSERT INTO gym_access_events (id, tenant_id, controller_id, event_type, decision, idempotency_key) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), "atmosfitnes", "TURNSTILE_01", "TAP_IN", "ALLOWED", "idem_key_1001")
            )

        conn.close()


class TestGymPydanticSchemas(unittest.TestCase):
    """Test Pydantic schema validation, status enums, and access validity logic."""

    def test_gym_member_schema_and_access_validity(self):
        """Test GymMember model and is_access_valid helper logic."""
        now = datetime.now(timezone.utc)
        future_date = now + timedelta(days=30)
        past_date = now - timedelta(days=1)

        # 1. Active member with future expiry -> Valid access
        active_member = GymMember(
            tenant_id="atmosfitnes",
            name="John Doe",
            phone="+62812-3456-7890",
            membership_package="VIP_ANNUAL",
            membership_status=MembershipStatus.ACTIVE,
            expiry_date=future_date
        )
        self.assertEqual(active_member.phone, "+6281234567890")
        self.assertTrue(active_member.is_access_valid(now))

        # 2. Active member with past expiry -> Invalid access
        expired_member = GymMember(
            tenant_id="atmosfitnes",
            name="Jane Doe",
            phone="08199988877",
            membership_status=MembershipStatus.ACTIVE,
            expiry_date=past_date
        )
        self.assertFalse(expired_member.is_access_valid(now))

        # 3. Suspended member with future expiry -> Invalid access
        suspended_member = GymMember(
            tenant_id="atmosfitnes",
            name="Bob Smith",
            phone="0812345678",
            membership_status=MembershipStatus.SUSPENDED,
            expiry_date=future_date
        )
        self.assertFalse(suspended_member.is_access_valid(now))

    def test_gym_nfc_card_schema(self):
        """Test GymNfcCard validation and status."""
        member_id = uuid4()
        card = GymNfcCard(
            tenant_id="atmosfitnes",
            member_id=member_id,
            uid_hash="a1b2c3d4e5f6g7h8",
            status=CardStatus.ACTIVE
        )
        self.assertEqual(card.tenant_id, "atmosfitnes")
        self.assertEqual(card.status, CardStatus.ACTIVE)

        # Blocked card
        blocked_card = GymNfcCard(
            tenant_id="atmosfitnes",
            member_id=member_id,
            uid_hash="a1b2c3d4e5f6g7h8",
            status=CardStatus.BLOCKED
        )
        self.assertEqual(blocked_card.status, CardStatus.BLOCKED)

    def test_gym_controller_schema(self):
        """Test GymAccessController validation."""
        controller = GymAccessController(
            tenant_id="atmosfitnes",
            controller_id="GATE-EAST-01",
            name="East Turnstile Gate",
            location="Lantai 1 Masuk",
            device_token_hash="secret_hash_value",
            status=ControllerStatus.ONLINE
        )
        self.assertEqual(controller.controller_id, "GATE-EAST-01")
        self.assertEqual(controller.status, ControllerStatus.ONLINE)

    def test_gym_access_event_schema(self):
        """Test GymAccessEvent validation."""
        event = GymAccessEvent(
            tenant_id="atmosfitnes",
            controller_id="GATE-EAST-01",
            member_id=str(uuid4()),
            card_id=str(uuid4()),
            event_type=AccessEventType.TAP_IN,
            decision=AccessDecision.ALLOWED,
            reason=AccessReason.VALID,
            idempotency_key="tap_event_uuid_12345"
        )
        self.assertEqual(event.decision, AccessDecision.ALLOWED)
        self.assertEqual(event.event_type, AccessEventType.TAP_IN)

    def test_tap_access_request_and_response(self):
        """Test IoT Tap In/Out request and response schemas."""
        req = TapAccessRequest(
            tenant_id="atmosfitnes",
            controller_id="GATE-01",
            uid_hash="5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
            event_type=AccessEventType.TAP_IN
        )
        self.assertEqual(req.tenant_id, "atmosfitnes")

        res_allowed = TapAccessResponse(
            decision=AccessDecision.ALLOWED,
            reason=AccessReason.VALID,
            message="Akses Diberikan. Selamat datang di Atmosfitnes!",
            member_name="Budi Santoso",
            membership_status=MembershipStatus.ACTIVE,
            unlock_gate=True
        )
        self.assertTrue(res_allowed.unlock_gate)
        self.assertEqual(res_allowed.decision, AccessDecision.ALLOWED)

        res_denied = TapAccessResponse(
            decision=AccessDecision.DENIED,
            reason=AccessReason.EXPIRED_MEMBERSHIP,
            message="Akses Ditolak: Masa aktif membership Anda telah berakhir.",
            member_name="Jane Doe",
            membership_status=MembershipStatus.EXPIRED,
            unlock_gate=False
        )
        self.assertFalse(res_denied.unlock_gate)
        self.assertEqual(res_denied.decision, AccessDecision.DENIED)


if __name__ == "__main__":
    unittest.main()
