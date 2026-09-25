"""app/services/booking_service.py
---------------------------------
High-Concurrency, Idempotent Booking Engine for Multi-Tenant Stores (e.g. Kelas Bos).

Features:
1. Strict Multi-Tenant Data Isolation (TenantScoped queries via tenant_slug).
2. Anti Double-Booking Concurrency Lock (Atomic UPDATE with status = 'AVAILABLE' guard).
3. Concurrency / Idempotency Check (Repeated booking with same idempotency_key / order_id returns existing record).
4. Full Alignment with CHECKOUT_FLOW.
"""

from __future__ import annotations

import os
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor, Json

logger = logging.getLogger("BOOKING_ENGINE")


class SlotUnavailableError(Exception):
    """Raised when slot is not available or does not exist."""
    pass


class SlotAlreadyBookedError(Exception):
    """Raised when an attempt is made to double-book an already confirmed slot."""
    pass


class InvalidBookingDataError(Exception):
    """Raised when required booking payload fields are missing or invalid."""
    pass


class BookingEngine:
    """
    Core engine managing slot availability, atomic concurrency reservation,
    and release lifecycle.
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")

    def _get_connection(self):
        if not self.db_url:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))
            self.db_url = os.getenv("DATABASE_URL")
        return psycopg2.connect(self.db_url)

    def get_available_slots(
        self,
        tenant_slug: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all currently available slots for a tenant within an optional date range.
        Strictly filters by status = 'AVAILABLE'.
        """
        clean_slug = (tenant_slug or "").strip().lower()
        query = """
            SELECT id, tenant_slug, slot_date, start_time, end_time,
                   duration_minutes, quota, booked_count, status, timezone
            FROM public.booking_slots
            WHERE tenant_slug = %s AND status = 'AVAILABLE'
        """
        params: List[Any] = [clean_slug]

        if date_from:
            query += " AND slot_date >= %s"
            params.append(date_from)
        if date_to:
            query += " AND slot_date <= %s"
            params.append(date_to)

        query += " ORDER BY slot_date ASC, start_time ASC;"

        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def book_slot(
        self,
        tenant_slug: str,
        slot_date: date | str,
        start_time: str,
        customer_name: str,
        customer_phone: str,
        customer_email: Optional[str] = None,
        business_topic: Optional[str] = None,
        service_id: Optional[str] = None,
        service_title: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Atomically locks a slot for a customer.
        Guarantees that no slot can ever be double-booked concurrently.
        Idempotent: Re-calling with the exact same idempotency_key returns the confirmed slot.
        """
        clean_slug = (tenant_slug or "").strip().lower()
        clean_time = start_time.strip().replace(" WIB", "")

        # Validations
        if not customer_name or not customer_phone:
            raise InvalidBookingDataError("customer_name and customer_phone are required to book a consultation slot.")

        conn = self._get_connection()
        conn.autocommit = False
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Idempotency Check: if already booked with this idempotency_key or order_id
                if idempotency_key or order_id:
                    check_idemp_sql = """
                        SELECT * FROM public.booking_slots
                        WHERE tenant_slug = %s AND (
                            (idempotency_key IS NOT NULL AND idempotency_key = %s)
                            OR (order_id IS NOT NULL AND order_id = %s)
                        );
                    """
                    cur.execute(check_idemp_sql, (clean_slug, idempotency_key or "", order_id or ""))
                    existing_idemp = cur.fetchone()
                    if existing_idemp:
                        logger.info(f"[BOOKING_ENGINE] Idempotent hit for key={idempotency_key or order_id}")
                        conn.rollback()
                        return dict(existing_idemp)

                # 2. Atomic Conditional Update (Concurrency Lock)
                # Only transitions if current status is 'AVAILABLE' and booked_count < quota
                atomic_update_sql = """
                    UPDATE public.booking_slots
                    SET status = 'BOOKED',
                        booked_count = booked_count + 1,
                        customer_name = %s,
                        customer_phone = %s,
                        customer_email = %s,
                        business_topic = %s,
                        service_id = %s,
                        service_title = %s,
                        idempotency_key = %s,
                        order_id = %s,
                        updated_at = now()
                    WHERE tenant_slug = %s
                      AND slot_date = %s
                      AND (start_time = %s OR start_time = %s)
                      AND status = 'AVAILABLE'
                      AND booked_count < quota
                    RETURNING *;
                """
                cur.execute(
                    atomic_update_sql,
                    (
                        customer_name.strip(),
                        customer_phone.strip(),
                        (customer_email or "").strip(),
                        (business_topic or "").strip(),
                        service_id,
                        service_title,
                        idempotency_key,
                        order_id,
                        clean_slug,
                        slot_date,
                        clean_time,
                        start_time.strip(),
                    ),
                )
                updated_slot = cur.fetchone()

                if not updated_slot:
                    # Slot was NOT updated -> check why
                    cur.execute(
                        """
                        SELECT status, booked_count, quota, customer_name
                        FROM public.booking_slots
                        WHERE tenant_slug = %s AND slot_date = %s AND (start_time = %s OR start_time = %s);
                        """,
                        (clean_slug, slot_date, clean_time, start_time.strip()),
                    )
                    slot_state = cur.fetchone()
                    conn.rollback()

                    if not slot_state:
                        raise SlotUnavailableError(
                            f"Slot on {slot_date} at {start_time} does not exist for tenant '{clean_slug}'."
                        )
                    else:
                        raise SlotAlreadyBookedError(
                            f"Slot on {slot_date} at {start_time} is already booked (status: {slot_state['status']}). Concurrency lock protected."
                        )

                conn.commit()
                logger.info(f"[BOOKING_ENGINE] Slot booked successfully: {slot_date} {start_time} by {customer_name}")
                return dict(updated_slot)

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release_slot(
        self,
        tenant_slug: str,
        slot_date: date | str,
        start_time: str,
        idempotency_key: Optional[str] = None,
    ) -> bool:
        """
        Releases a booked slot back to 'AVAILABLE' status.
        """
        clean_slug = (tenant_slug or "").strip().lower()
        clean_time = start_time.strip().replace(" WIB", "")

        conn = self._get_connection()
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                sql = """
                    UPDATE public.booking_slots
                    SET status = 'AVAILABLE',
                        booked_count = 0,
                        customer_name = NULL,
                        customer_phone = NULL,
                        customer_email = NULL,
                        business_topic = NULL,
                        service_id = NULL,
                        service_title = NULL,
                        idempotency_key = NULL,
                        order_id = NULL,
                        updated_at = now()
                    WHERE tenant_slug = %s
                      AND slot_date = %s
                      AND (start_time = %s OR start_time = %s);
                """
                cur.execute(sql, (clean_slug, slot_date, clean_time, start_time.strip()))
                return cur.rowcount > 0
        finally:
            conn.close()


booking_engine = BookingEngine()
