"""app/services/crm_service.py
SSOT CRM Contact Normalization & Multi-Tenant Isolation Service (Standar CTO).

Guarantees:
1. Single Source of Truth (SSOT): All customers & alumni derive from contacts table.
2. Multi-Tenant Isolation: Unique composite constraint (tenant_id, clean_phone).
3. Idempotent Upsert: Merges interactions, updates last_order_at & total_spent without duplicating contacts.
4. Non-Destructive Linking: Populates orders.contact_id without mutating financial transaction ledgers.
5. Fail-Safe: If contact sync encounters timeout or error, order creation remains valid and intact.
"""

import os
import json
import uuid
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.core.database import get_db_connection
from app.utils.phone_sanitizer import clean_phone_number

logger = logging.getLogger("CRM_SSOT_SERVICE")

# In-memory LRU/cache for tenant_slug -> tenant_uuid
_TENANT_CACHE: Dict[str, str] = {}


def is_valid_uuid(val: Any) -> bool:
    if not val:
        return False
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def resolve_tenant_uuid(tenant_identifier: Optional[str]) -> Optional[str]:
    """Mengonversi tenant_slug atau identifier ke UUID valid dari tabel tenants."""
    if not tenant_identifier:
        return None

    ident_str = str(tenant_identifier).strip()
    if is_valid_uuid(ident_str):
        return ident_str

    if ident_str in _TENANT_CACHE:
        return _TENANT_CACHE[ident_str]

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM tenants WHERE slug = %s LIMIT 1;", (ident_str,))
        row = cur.fetchone()
        if row:
            tid = str(row[0])
            _TENANT_CACHE[ident_str] = tid
            return tid
    except Exception as e:
        logger.warning(f"[CRM_SSOT] Failed to resolve tenant UUID for '{ident_str}': {e}")
    finally:
        if conn:
            conn.close()

    return None


def sync_contact_from_order(order_payload: Dict[str, Any]) -> Optional[str]:
    """Idempotent sync kontak CRM dari transaksi order.
    
    Menjamin:
    - Kontak di-upsert secara atomik ke tabel `contacts` berdasarkan (tenant_id, clean_phone).
    - Jika kontak baru: INSERT profil baru.
    - Jika kontak sudah ada: UPDATE riwayat interaksi (last_order_at, total_spent) tanpa membuat baris baru.
    - Kolom `orders.contact_id` diisi dengan ID kontak hasil upsert.
    - FAIL-SAFE: Jika ada error/timeout, pesanan transaksi TETAP TERCATAT sah (return None tanpa membatalkan order).
    """
    if not order_payload or not isinstance(order_payload, dict):
        return None

    order_id = (
        order_payload.get("order_id")
        or order_payload.get("id")
        or order_payload.get("external_id")
    )
    tenant_raw = (
        order_payload.get("tenant_id")
        or order_payload.get("tenant_slug")
        or "onlineboost"
    )
    raw_phone = (
        order_payload.get("customer_phone")
        or order_payload.get("phone")
        or order_payload.get("sender_phone")
        or order_payload.get("whatsapp_number")
    )

    clean_phone = clean_phone_number(raw_phone)
    if not clean_phone:
        logger.debug(f"[CRM_SSOT] Order {order_id} has no valid phone number. Skipping contact sync.")
        return None

    try:
        tenant_uuid = resolve_tenant_uuid(tenant_raw)
        if not tenant_uuid:
            logger.warning(f"[CRM_SSOT] Cannot resolve valid tenant UUID for order {order_id} (tenant={tenant_raw}). Skipping.")
            return None

        # Data ekstrak
        customer_name = order_payload.get("customer_name") or order_payload.get("name") or f"Customer {clean_phone[-4:]}"
        customer_email = order_payload.get("customer_email") or order_payload.get("email")
        if customer_email and not str(customer_email).strip():
            customer_email = None

        raw_amount = (
            order_payload.get("gross_amount")
            or order_payload.get("amount")
            or order_payload.get("total_amount")
            or 0
        )
        try:
            amount_numeric = float(raw_amount)
        except (ValueError, TypeError):
            amount_numeric = 0.0

        now_utc = datetime.now(timezone.utc)
        order_time = order_payload.get("paid_at") or order_payload.get("created_at") or now_utc

        tenant_slug = str(order_payload.get("tenant_slug") or tenant_raw)

        initial_metadata = {
            "source": "order_transaction",
            "last_order_id": str(order_id) if order_id else None,
            "tags": ["Customer"]
        }

        conn = get_db_connection()
        conn.autocommit = False
        cur = conn.cursor()

        try:
            # Atomic idempotent upsert using ON CONFLICT (tenant_id, clean_phone)
            upsert_query = """
                INSERT INTO contacts (
                    id, tenant_id, tenant_slug, phone_e164, clean_phone, name, email,
                    contact_status, lifecycle_stage, metadata, last_interaction_at,
                    last_order_at, total_spent, created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), %s, %s, %s, %s, %s, %s,
                    'ACTIVE', 'CUSTOMER', %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (tenant_id, clean_phone) DO UPDATE SET
                    name = COALESCE(NULLIF(EXCLUDED.name, ''), contacts.name),
                    email = COALESCE(NULLIF(EXCLUDED.email, ''), contacts.email),
                    last_interaction_at = EXCLUDED.last_interaction_at,
                    last_order_at = COALESCE(EXCLUDED.last_order_at, contacts.last_order_at),
                    total_spent = COALESCE(contacts.total_spent, 0) + COALESCE(EXCLUDED.total_spent, 0),
                    lifecycle_stage = 'CUSTOMER',
                    updated_at = EXCLUDED.updated_at
                RETURNING id;
            """

            cur.execute(
                upsert_query,
                (
                    tenant_uuid,
                    tenant_slug,
                    clean_phone,
                    clean_phone,
                    customer_name,
                    customer_email,
                    json.dumps(initial_metadata),
                    now_utc,
                    order_time,
                    amount_numeric,
                    now_utc,
                    now_utc,
                )
            )

            contact_id_res = cur.fetchone()
            contact_id = str(contact_id_res[0]) if contact_id_res else None

            # Non-destructively bind contact_id to orders table
            if contact_id and order_id:
                cur.execute(
                    """
                    UPDATE orders
                    SET contact_id = %s
                    WHERE id = %s;
                    """,
                    (contact_id, str(order_id))
                )

            conn.commit()
            logger.info(f"[CRM_SSOT] Idempotent sync success for order {order_id} -> contact {contact_id} ({clean_phone})")
            return contact_id

        except Exception as query_err:
            conn.rollback()
            logger.warning(f"[CRM_SSOT] DB transaction rollbacked for order {order_id}: {query_err}")
            return None
        finally:
            conn.close()

    except Exception as exc:
        # Strict fail-safe: order is never aborted if contact sync fails
        logger.warning(f"[CRM_SSOT] Fail-safe caught error during sync_contact_from_order for order {order_id}: {exc}", exc_info=True)
        return None


async def async_sync_contact_from_order(order_payload: Dict[str, Any]) -> Optional[str]:
    """Asynchronous wrapper for non-blocking contact sync."""
    try:
        return await asyncio.to_thread(sync_contact_from_order, order_payload)
    except Exception as exc:
        logger.warning(f"[CRM_SSOT] Async sync fail-safe caught: {exc}")
        return None
