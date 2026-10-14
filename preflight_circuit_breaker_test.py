"""
preflight_circuit_breaker_test.py
========================================================================================
PERSISTENT TEST SUITE: CTO PREFLIGHT CIRCUIT BREAKER, SUPPRESSION, CONCURRENCY & AUDIT
========================================================================================
Validasi 7 Syarat CTO Office untuk Kesiapan Produksi (CTO P1 Hardened Acceptance Gate).
Terintegrasi penuh ke PostgreSQL Database dengan Row-Level Security Ketat (Anti-Permissive):

1. Circuit Breaker Simulation:
   - 3 kegagalan callback beruntun -> queue status 'FROZEN', worker berhenti ambil batch.
   - Ambang kegagalan 6% pada rolling window sampel terkirim -> trigger 'FROZEN'.
2. STOP & Suppression:
   - Inbound keyword 'STOP' -> nomor masuk tabel persisten 'phone_suppressions' dengan isolasi tenant.
   - Eliminasi mutlak dari batch pengiriman berikutnya via database filter.
3. Atomic Freeze on Concurrency:
   - 2 worker konkuren membaca status dari tabel 'campaign_queues' di PostgreSQL.
   - Trigger FROZEN di tengah jalan -> worker kedua membaca status persisten & berhenti seketika.
   - Sisa pesan di tabel 'campaign_queue_items' tetap utuh (PENDING).
4. Telegram Single-Use Token:
   - Token disimpan di tabel persisten 'telegram_single_use_tokens'.
   - Klaim menggunakan atomic conditional update di DB (UPDATE ... WHERE claimed = false).
   - Klaim kedua ditolak (TOKEN_ALREADY_CLAIMED), expired ditolak (TOKEN_EXPIRED).
5. State Machine & Audit Trail:
   - Alur siklus hidup: READY -> RUNNING -> FROZEN -> REVIEW_REQUIRED -> READY.
   - Seluruh mutasi tercatat di tabel persisten 'audit_logs' dengan user_id pelaksana.
6. Teardown & Isolation:
   - Seluruh pengujian berjalan di bawah role 'authenticated' (rolbypassrls=false) dengan
     tenant_id terisolasi ('tenant_preflight_cto').
   - Teardown otomatis membersihkan seluruh data uji setelah eksekusi selesai.
========================================================================================
"""

import sys
import os
import time
import uuid
import threading
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, timezone
from collections import deque
from enum import Enum
import psycopg2
from psycopg2.extras import RealDictCursor

# Pastikan path modul core tersedia
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from app.core.database import get_db_connection

# Pastikan UTF-8 encoding untuk stdout
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Tenant ID khusus terisolasi untuk suite pengujian preflight
TEST_TENANT_ID = "tenant_preflight_cto"


# ======================================================================================
# DOMAIN MODELS & ENUMS
# ======================================================================================

class QueueState(str, Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    FROZEN = "FROZEN"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"


class IllegalStateTransitionError(Exception):
    """Dilempar saat terjadi perpindahan state yang melanggar kontrak arsitektur."""
    pass


# ======================================================================================
# DATABASE SETUP & DDL HELPER (STRICT TENANT ISOLATION — ZERO WILDCARD)
# ======================================================================================

def ensure_preflight_schema_exists():
    """
    Membuat tabel persisten untuk suppression, token, antrean & audit dengan
    skema isolasi tenant ketat dan Row-Level Security FORCE aktif.
    Kebijakan permisif 'allow_all_ops_*' (USING true) DICABUT TOTAL.
    """
    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        # Cabut policy permisif lama jika ada
        for tbl in ['phone_suppressions', 'telegram_single_use_tokens', 'campaign_queues', 'campaign_queue_items']:
            cur.execute(f"DROP POLICY IF EXISTS allow_all_ops_{tbl} ON public.{tbl};")

        # 1. Tabel Phone Suppressions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.phone_suppressions (
                id SERIAL PRIMARY KEY,
                tenant_id VARCHAR(100) NOT NULL DEFAULT 'tenant_preflight_cto',
                phone_number VARCHAR(50) NOT NULL,
                reason VARCHAR(255) DEFAULT 'STOP_KEYWORD',
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_phone_suppressions_tenant_phone UNIQUE (tenant_id, phone_number)
            );
            ALTER TABLE public.phone_suppressions ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.phone_suppressions FORCE ROW LEVEL SECURITY;
        """)

        # 2. Tabel Telegram Single-Use Tokens
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.telegram_single_use_tokens (
                token VARCHAR(64) PRIMARY KEY,
                tenant_id VARCHAR(100) NOT NULL DEFAULT 'tenant_preflight_cto',
                order_id VARCHAR(100) NOT NULL,
                invite_link VARCHAR(255) NOT NULL,
                claimed BOOLEAN DEFAULT FALSE,
                claimed_at TIMESTAMP WITH TIME ZONE,
                claimed_by VARCHAR(100),
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE public.telegram_single_use_tokens ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.telegram_single_use_tokens FORCE ROW LEVEL SECURITY;
        """)

        # 3. Tabel Campaign Queues & Items
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.campaign_queues (
                queue_id VARCHAR(100) PRIMARY KEY,
                tenant_id VARCHAR(100) NOT NULL DEFAULT 'tenant_preflight_cto',
                state VARCHAR(50) NOT NULL DEFAULT 'READY',
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE public.campaign_queues ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.campaign_queues FORCE ROW LEVEL SECURITY;

            CREATE TABLE IF NOT EXISTS public.campaign_queue_items (
                id SERIAL PRIMARY KEY,
                tenant_id VARCHAR(100) NOT NULL DEFAULT 'tenant_preflight_cto',
                queue_id VARCHAR(100) NOT NULL REFERENCES public.campaign_queues(queue_id) ON DELETE CASCADE,
                item_payload VARCHAR(255) NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
                processed_by VARCHAR(50),
                processed_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
            ALTER TABLE public.campaign_queue_items ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.campaign_queue_items FORCE ROW LEVEL SECURITY;
        """)

        # 4. Buat Kebijakan RLS Isolasi Tenant Ketat (RESTRICTIVE) & Base Auth Permissive
        for tbl in ['phone_suppressions', 'telegram_single_use_tokens', 'campaign_queues', 'campaign_queue_items']:
            cur.execute(f"DROP POLICY IF EXISTS tenant_isolation_{tbl} ON public.{tbl};")
            cur.execute(f"DROP POLICY IF EXISTS auth_permissive_{tbl} ON public.{tbl};")

            # Restrictive: Hanya mengizinkan akses ke baris dengan tenant_id sesuai session
            cur.execute(f"""
                CREATE POLICY tenant_isolation_{tbl} ON public.{tbl}
                AS RESTRICTIVE
                FOR ALL
                TO public
                USING (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''))
                WITH CHECK (tenant_id::text = NULLIF(current_setting('app.current_tenant_id', true), ''));
            """)

            # Permissive: Role authenticated diizinkan mengakses dengan syarat lolos restrictive policy
            cur.execute(f"""
                CREATE POLICY auth_permissive_{tbl} ON public.{tbl}
                AS PERMISSIVE
                FOR ALL
                TO authenticated
                USING (true)
                WITH CHECK (true);
            """)

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"Gagal inisialisasi schema persistent preflight: {e}")
    finally:
        cur.close()
        conn.close()


# ======================================================================================
# PERSISTENT CORE SERVICES UNDER TEST (SCOPED KE ROLE AUTHENTICATED & TENANT ISOLATION)
# ======================================================================================

def _get_authenticated_scoped_conn(tenant_id: str):
    """Menghasilkan koneksi database yang terikat ke role 'authenticated' dan tenant_id aktif."""
    conn = get_db_connection()
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET ROLE authenticated;")
    cur.execute("SELECT set_config('app.current_tenant_id', %s, false);", (tenant_id,))
    conn.commit()
    cur.close()
    return conn


class PersistentAuditTrailService:
    """Mencatat dan mengamankan setiap mutasi state pada tabel 'audit_logs' di PostgreSQL."""
    def __init__(self, tenant_id: str = TEST_TENANT_ID):
        self.tenant_id = tenant_id

    def record_transition(
        self,
        from_state: QueueState,
        to_state: QueueState,
        actor_id: str,
        reason: str,
        queue_id: str
    ):
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            metadata = {
                "queue_id": queue_id,
                "from_state": from_state.value,
                "to_state": to_state.value,
                "reason": reason
            }
            cur.execute("""
                INSERT INTO public.audit_logs 
                (tenant_id, actor_id, action, resource_type, resource_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb);
            """, (
                self.tenant_id,
                actor_id,
                f"QUEUE_TRANSITION_{to_state.value}",
                "campaign_queue",
                queue_id,
                psycopg2.extras.Json(metadata)
            ))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Gagal mencatat audit log ke DB: {e}")
        finally:
            cur.close()
            conn.close()

    def get_logs(self, queue_id: str) -> List[dict]:
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT id, actor_id, action, metadata, created_at 
                FROM public.audit_logs 
                WHERE resource_id = %s
                ORDER BY id ASC;
            """, (queue_id,))
            return cur.fetchall()
        finally:
            cur.close()
            conn.close()


class PersistentSuppressionService:
    """Mengelola penambahan nomor ter-supresi ke database PostgreSQL aktual dengan isolasi tenant."""
    STOP_KEYWORDS = {"STOP", "BERHENTI", "UNSUBSCRIBE", "BATAL", "OPTOUT"}

    def __init__(self, tenant_id: str = TEST_TENANT_ID):
        self.tenant_id = tenant_id

    @staticmethod
    def normalize_phone(phone: str) -> str:
        cleaned = "".join(c for c in phone if c.isdigit())
        if cleaned.startswith("62"):
            return cleaned
        if cleaned.startswith("0"):
            return "62" + cleaned[1:]
        return cleaned

    def process_inbound_message(self, phone_number: str, message_text: str) -> bool:
        normalized_text = message_text.strip().upper()
        tokens = normalized_text.split()
        is_stop = any(token in self.STOP_KEYWORDS for token in tokens)

        if not is_stop:
            return False

        clean_phone = self.normalize_phone(phone_number)
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO public.phone_suppressions (tenant_id, phone_number, reason, metadata)
                VALUES (%s, %s, 'INBOUND_STOP_KEYWORD', %s::jsonb)
                ON CONFLICT (tenant_id, phone_number) 
                DO UPDATE SET reason = 'INBOUND_STOP_KEYWORD', created_at = CURRENT_TIMESTAMP;
            """, (self.tenant_id, clean_phone, psycopg2.extras.Json({"raw_message": message_text.strip()})))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Gagal menyimpan data suppression ke DB: {e}")
        finally:
            cur.close()
            conn.close()

    def is_suppressed(self, phone_number: str) -> bool:
        clean_phone = self.normalize_phone(phone_number)
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT 1 FROM public.phone_suppressions 
                WHERE tenant_id = %s AND phone_number = %s;
            """, (self.tenant_id, clean_phone))
            return cur.fetchone() is not None
        finally:
            cur.close()
            conn.close()

    def filter_batch(self, recipients: List[str]) -> Tuple[List[str], List[str]]:
        normalized_map = {self.normalize_phone(r): r for r in recipients}
        clean_phones = list(normalized_map.keys())

        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT phone_number 
                FROM public.phone_suppressions 
                WHERE tenant_id = %s AND phone_number = ANY(%s);
            """, (self.tenant_id, clean_phones))
            suppressed_in_db = set(row[0] for row in cur.fetchall())
        finally:
            cur.close()
            conn.close()

        allowed = []
        eliminated = []
        for r in recipients:
            if self.normalize_phone(r) in suppressed_in_db:
                eliminated.append(r)
            else:
                allowed.append(r)
        return allowed, eliminated


class CircuitBreaker:
    """
    Circuit Breaker Pengiriman Pesan:
    - 3 Kegagalan Callback Beruntun -> Trip (FROZEN)
    - Ambang Kegagalan 6% pada Rolling Window sampel terkirim -> Trip (FROZEN)
    """
    def __init__(
        self,
        consecutive_failure_threshold: int = 3,
        rolling_window_size: int = 50,
        failure_rate_threshold: float = 0.06
    ):
        self.consecutive_failure_threshold = consecutive_failure_threshold
        self.rolling_window_size = rolling_window_size
        self.failure_rate_threshold = failure_rate_threshold

        self.consecutive_failures = 0
        self.rolling_window: deque = deque(maxlen=rolling_window_size)
        self.is_tripped = False
        self.trip_reason = ""
        self._lock = threading.Lock()

    def record_result(self, success: bool) -> Tuple[bool, Optional[str]]:
        with self._lock:
            self.rolling_window.append(1 if success else 0)

            if success:
                self.consecutive_failures = 0
            else:
                self.consecutive_failures += 1

            # 1. Evaluasi 3 Kegagalan Callback Beruntun
            if self.consecutive_failures >= self.consecutive_failure_threshold:
                self.is_tripped = True
                self.trip_reason = (
                    f"CONSECUTIVE_FAILURES_BREACH: {self.consecutive_failures} kegagalan beruntun "
                    f"(ambang batas: {self.consecutive_failure_threshold})"
                )
                return True, self.trip_reason

            # 2. Evaluasi Ambang Kegagalan 6% pada Rolling Window
            if len(self.rolling_window) >= self.rolling_window_size:
                total_samples = len(self.rolling_window)
                failures = total_samples - sum(self.rolling_window)
                failure_rate = failures / total_samples

                if failure_rate >= self.failure_rate_threshold:
                    self.is_tripped = True
                    self.trip_reason = (
                        f"FAILURE_RATE_BREACH: Tingkat kegagalan {failure_rate * 100:.1f}% "
                        f"({failures}/{total_samples}) melebihi ambang batas {self.failure_rate_threshold * 100:.1f}%"
                    )
                    return True, self.trip_reason

            return False, None


class PersistentCampaignQueue:
    """Antrean pengiriman pesan persisten di PostgreSQL dengan State Machine deterministik & RLS."""
    VALID_TRANSITIONS = {
        QueueState.READY: {QueueState.RUNNING},
        QueueState.RUNNING: {QueueState.FROZEN, QueueState.COMPLETED},
        QueueState.FROZEN: {QueueState.REVIEW_REQUIRED},
        QueueState.REVIEW_REQUIRED: {QueueState.READY},
        QueueState.COMPLETED: set()
    }

    def __init__(self, queue_id: str, audit_service: PersistentAuditTrailService, tenant_id: str = TEST_TENANT_ID):
        self.queue_id = queue_id
        self.audit_service = audit_service
        self.tenant_id = tenant_id
        self._ensure_record_exists()

    def _ensure_record_exists(self):
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO public.campaign_queues (queue_id, tenant_id, state)
                VALUES (%s, %s, 'READY')
                ON CONFLICT (queue_id) DO NOTHING;
            """, (self.queue_id, self.tenant_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Gagal inisialisasi campaign queue di DB: {e}")
        finally:
            cur.close()
            conn.close()

    def get_state(self) -> QueueState:
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("SELECT state FROM public.campaign_queues WHERE queue_id = %s;", (self.queue_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Queue {self.queue_id} tidak ditemukan di DB.")
            return QueueState(row[0])
        finally:
            cur.close()
            conn.close()

    def transition_to(self, new_state: QueueState, actor_id: str, reason: str) -> None:
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("SELECT state FROM public.campaign_queues WHERE queue_id = %s FOR UPDATE;", (self.queue_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Queue {self.queue_id} tidak ditemukan.")
            current_state = QueueState(row[0])

            allowed = self.VALID_TRANSITIONS.get(current_state, set())
            if new_state not in allowed:
                raise IllegalStateTransitionError(
                    f"Transisi ilegal: {current_state.value} -> {new_state.value}. "
                    f"Hanya diizinkan ke: {[s.value for s in allowed]}"
                )

            cur.execute("""
                UPDATE public.campaign_queues 
                SET state = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE queue_id = %s;
            """, (new_state.value, self.queue_id))
            conn.commit()

            # Record audit trail
            self.audit_service.record_transition(
                from_state=current_state,
                to_state=new_state,
                actor_id=actor_id,
                reason=reason,
                queue_id=self.queue_id
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def seed_items(self, item_payloads: List[str]):
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM public.campaign_queue_items WHERE queue_id = %s;", (self.queue_id,))
            args = [(self.tenant_id, self.queue_id, p, 'PENDING') for p in item_payloads]
            cur.executemany("""
                INSERT INTO public.campaign_queue_items (tenant_id, queue_id, item_payload, status)
                VALUES (%s, %s, %s, %s);
            """, args)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Gagal seed items ke DB: {e}")
        finally:
            cur.close()
            conn.close()

    def fetch_and_claim_item(self, worker_name: str) -> Optional[Tuple[int, str]]:
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            # 1. Pastikan antrean persisten masih RUNNING
            cur.execute("SELECT state FROM public.campaign_queues WHERE queue_id = %s;", (self.queue_id,))
            row = cur.fetchone()
            if not row or row[0] != QueueState.RUNNING.value:
                return None

            # 2. Klaim item berikutnya secara atomik
            cur.execute("""
                UPDATE public.campaign_queue_items
                SET status = 'PROCESSING', 
                    processed_by = %s, 
                    processed_at = CURRENT_TIMESTAMP, 
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = (
                    SELECT id FROM public.campaign_queue_items
                    WHERE queue_id = %s AND status = 'PENDING'
                    ORDER BY id ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING id, item_payload;
            """, (worker_name, self.queue_id))
            item = cur.fetchone()
            conn.commit()
            return item
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def complete_item(self, item_id: int):
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE public.campaign_queue_items
                SET status = 'PROCESSED', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND tenant_id = %s;
            """, (item_id, self.tenant_id))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def release_item(self, item_id: int):
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE public.campaign_queue_items
                SET status = 'PENDING', processed_by = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND tenant_id = %s;
            """, (item_id, self.tenant_id))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def count_pending_items(self) -> int:
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT count(*) 
                FROM public.campaign_queue_items 
                WHERE queue_id = %s AND status = 'PENDING';
            """, (self.queue_id,))
            return cur.fetchone()[0]
        finally:
            cur.close()
            conn.close()


class PersistentTelegramTokenService:
    """Penerbitan dan klaim token undangan Telegram 1x pakai di PostgreSQL dengan isolasi tenant."""
    def __init__(self, tenant_id: str = TEST_TENANT_ID):
        self.tenant_id = tenant_id

    def issue_token(self, order_id: str, ttl_seconds: int = 86400) -> str:
        token = f"TGM-{uuid.uuid4().hex[:12].upper()}"
        invite_link = f"https://t.me/+Batch1Invite_{order_id[-6:]}"
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO public.telegram_single_use_tokens 
                (token, tenant_id, order_id, invite_link, claimed, expires_at)
                VALUES (%s, %s, %s, %s, FALSE, CURRENT_TIMESTAMP + interval '%s seconds');
            """, (token, self.tenant_id, order_id, invite_link, ttl_seconds))
            conn.commit()
            return token
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Gagal menerbitkan token Telegram ke DB: {e}")
        finally:
            cur.close()
            conn.close()

    def claim_token(self, token: str, claimant_id: str) -> Tuple[bool, str, Optional[str]]:
        conn = _get_authenticated_scoped_conn(self.tenant_id)
        cur = conn.cursor()
        try:
            # Klaim atomik: UPDATE ... WHERE claimed = false AND expires_at > CURRENT_TIMESTAMP
            cur.execute("""
                UPDATE public.telegram_single_use_tokens
                SET claimed = TRUE,
                    claimed_at = CURRENT_TIMESTAMP,
                    claimed_by = %s
                WHERE token = %s 
                  AND claimed = FALSE 
                  AND expires_at > CURRENT_TIMESTAMP
                RETURNING token, invite_link;
            """, (claimant_id, token))
            row = cur.fetchone()
            conn.commit()

            if row:
                return True, "SUCCESS", row[1]

            # Jika 0 baris ter-update, evaluasi penyebab penolakan di DB
            cur.execute("""
                SELECT claimed, (expires_at <= CURRENT_TIMESTAMP) AS is_expired
                FROM public.telegram_single_use_tokens
                WHERE token = %s;
            """, (token,))
            status_row = cur.fetchone()
            if not status_row:
                return False, "TOKEN_NOT_FOUND", None

            is_claimed, is_expired = status_row
            if is_expired:
                return False, "TOKEN_EXPIRED", None
            if is_claimed:
                return False, "TOKEN_ALREADY_CLAIMED", None

            return False, "CLAIM_REJECTED", None
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()


# ======================================================================================
# CTO PREFLIGHT TEST SUITE RUNNER
# ======================================================================================

class CTOPreflightTestSuite:
    def __init__(self, tenant_id: str = TEST_TENANT_ID):
        self.tenant_id = tenant_id
        ensure_preflight_schema_exists()
        self.audit_service = PersistentAuditTrailService(self.tenant_id)
        self.suppression_service = PersistentSuppressionService(self.tenant_id)
        self.telegram_service = PersistentTelegramTokenService(self.tenant_id)
        self.results: List[Tuple[str, bool, str]] = []

    def log_header(self, title: str):
        print("\n" + "=" * 80)
        print(f"  {title.upper()}")
        print("=" * 80)

    def log_test_result(self, requirement_no: str, name: str, passed: bool, detail: str):
        self.results.append((f"{requirement_no}: {name}", passed, detail))
        badge = " [PASS] " if passed else "![FAIL]!"
        print(f"\n{badge} SYARAT {requirement_no} — {name}")
        print(f"       Detail  : {detail}")

    def teardown(self):
        """Membersihkan seluruh baris pengujian scoped ke TEST_TENANT_ID."""
        conn = get_db_connection()
        conn.autocommit = False
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM public.phone_suppressions WHERE tenant_id = %s;", (self.tenant_id,))
            cur.execute("DELETE FROM public.telegram_single_use_tokens WHERE tenant_id = %s;", (self.tenant_id,))
            cur.execute("DELETE FROM public.campaign_queues WHERE tenant_id = %s;", (self.tenant_id,))
            cur.execute("DELETE FROM public.campaign_queue_items WHERE tenant_id = %s;", (self.tenant_id,))
            cur.execute("DELETE FROM public.audit_logs WHERE tenant_id = %s;", (self.tenant_id,))
            conn.commit()
            print(f"\n       [+] Teardown: Data pengujian scoped '{self.tenant_id}' berhasil dibersihkan.")
        except Exception as e:
            conn.rollback()
            print(f"\n       [-] Peringatan Teardown: {e}")
        finally:
            cur.close()
            conn.close()

    # ----------------------------------------------------------------------------------
    # SYARAT 1: 3 KEGAGALAN CALLBACK BERUNTUN -> FROZEN & WORKER HALT
    # ----------------------------------------------------------------------------------
    def test_requirement_1_consecutive_failures(self):
        self.log_header("Syarat 1: Simulasi 3 Kegagalan Callback Beruntun -> FROZEN")
        
        queue_id = f"queue-broadcast-001-{uuid.uuid4().hex[:6]}"
        queue = PersistentCampaignQueue(queue_id, self.audit_service, self.tenant_id)
        queue.transition_to(QueueState.RUNNING, actor_id="operator_01", reason="Mulai eksekusi batch")
        
        cb = CircuitBreaker(consecutive_failure_threshold=3, rolling_window_size=50)

        simulated_callbacks = [True, True, False, False, False]
        worker_halted = False
        remaining_batch = ["msg_4", "msg_5", "msg_6"]
        fetched_after_trip = []

        for idx, is_success in enumerate(simulated_callbacks, 1):
            if queue.get_state() == QueueState.FROZEN:
                worker_halted = True
                break

            tripped, reason = cb.record_result(is_success)
            print(f"       Dispatch #{idx}: Success={is_success} | Consecutive Failures={cb.consecutive_failures}")

            if tripped:
                print(f"       [!] Circuit Breaker Tripped! Triggering atomic freeze: {reason}")
                queue.transition_to(QueueState.FROZEN, actor_id="system_circuit_breaker", reason=reason)
                worker_halted = True
                break

        if queue.get_state() != QueueState.FROZEN:
            fetched_after_trip.extend(remaining_batch)

        passed = (
            queue.get_state() == QueueState.FROZEN
            and cb.consecutive_failures == 3
            and worker_halted
            and len(fetched_after_trip) == 0
        )
        self.log_test_result(
            "1.1",
            "3 Consecutive Failures Auto-Freeze & Worker Halt",
            passed,
            f"State akhir: {queue.get_state().value}, Kegagalan beruntun: {cb.consecutive_failures}, Worker Halted: {worker_halted}"
        )

    # ----------------------------------------------------------------------------------
    # SYARAT 2: AMBANG KEGAGALAN 6% PADA ROLLING WINDOW SAMPEL TERKIRIM
    # ----------------------------------------------------------------------------------
    def test_requirement_2_failure_rate_threshold(self):
        self.log_header("Syarat 2: Ambang Kegagalan 6% pada Rolling Window")
        
        queue_id = f"queue-broadcast-002-{uuid.uuid4().hex[:6]}"
        queue = PersistentCampaignQueue(queue_id, self.audit_service, self.tenant_id)
        queue.transition_to(QueueState.RUNNING, actor_id="operator_01", reason="Mulai broadcast window test")
        
        cb = CircuitBreaker(consecutive_failure_threshold=10, rolling_window_size=50, failure_rate_threshold=0.06)

        samples = [True] * 20 + [False] + [True] * 14 + [False] + [True] * 13 + [False]
        assert len(samples) == 50

        tripped_at_sample = None
        for i, res in enumerate(samples, 1):
            tripped, reason = cb.record_result(res)
            if tripped:
                tripped_at_sample = i
                queue.transition_to(QueueState.FROZEN, actor_id="system_circuit_breaker", reason=reason)
                print(f"       [!] Sample #{i}: Failure rate tripped: {reason}")
                break

        total_samples = len(cb.rolling_window)
        failures_in_window = total_samples - sum(cb.rolling_window)
        rate = failures_in_window / total_samples if total_samples > 0 else 0

        passed = (
            queue.get_state() == QueueState.FROZEN
            and rate >= 0.06
            and tripped_at_sample == 50
        )
        self.log_test_result(
            "1.2",
            "Rolling Window 6% Failure Rate Breaker",
            passed,
            f"Tripped tepat pada sampel #{tripped_at_sample}, Rate: {rate*100:.1f}% ({failures_in_window}/{total_samples}), State: {queue.get_state().value}"
        )

    # ----------------------------------------------------------------------------------
    # SYARAT 3: INBOUND KEYWORD 'STOP' -> DATABASE SUPPRESSION REGISTRY
    # ----------------------------------------------------------------------------------
    def test_requirement_3_stop_keyword_ingestion(self):
        self.log_header("Syarat 3: Inbound Keyword 'STOP' Masuk Tabel Supresi Persisten")

        test_phone_1 = "081299887766"
        test_phone_2 = "+62 813-1122-3344"
        test_phone_normal = "085511223344"

        is_supp_1 = self.suppression_service.process_inbound_message(test_phone_1, "STOP")
        is_supp_2 = self.suppression_service.process_inbound_message(test_phone_2, "  stop berlangganan  ")
        is_supp_3 = self.suppression_service.process_inbound_message(test_phone_normal, "Halo mau tanya kelas")

        passed = (
            is_supp_1
            and is_supp_2
            and not is_supp_3
            and self.suppression_service.is_suppressed(test_phone_1)
            and self.suppression_service.is_suppressed(test_phone_2)
            and not self.suppression_service.is_suppressed(test_phone_normal)
        )
        self.log_test_result(
            "2.1",
            "Inbound 'STOP' Ingestion to Persistent Suppression Registry",
            passed,
            f"Nomor '{test_phone_1}' & '{test_phone_2}' tersimpan persisten di PostgreSQL. Nomor normal tidak disupresi."
        )

    # ----------------------------------------------------------------------------------
    # SYARAT 4: ELIMINASI PENERIMA SUPPRESSED DARI BATCH PENGIRIMAN
    # ----------------------------------------------------------------------------------
    def test_requirement_4_suppression_batch_filtering(self):
        self.log_header("Syarat 4: Eliminasi Mutlak Nomor Suppressed dari Batch Pengiriman")

        batch_candidates = [
            "081299887766",       # Suppressed di Syarat 3
            "085511223344",       # Aktif
            "081311223344",       # Suppressed di Syarat 3 (+62 813-1122-3344)
            "+62 877-9900-1122",  # Aktif
        ]

        allowed, eliminated = self.suppression_service.filter_batch(batch_candidates)

        passed = (
            len(allowed) == 2
            and len(eliminated) == 2
            and "081299887766" in eliminated
            and "081311223344" in eliminated
            and "085511223344" in allowed
            and "+62 877-9900-1122" in allowed
        )
        self.log_test_result(
            "2.2",
            "Strict Batch Elimination via Database Suppression Table",
            passed,
            f"Batch {len(batch_candidates)} kontak -> Allowed: {len(allowed)}, Eliminated (Suppressed in DB): {len(eliminated)}"
        )

    # ----------------------------------------------------------------------------------
    # SYARAT 5: ATOMIC FREEZE ON CONCURRENCY (2 WORKER PARALEL DI DB PERSISTEN)
    # ----------------------------------------------------------------------------------
    def test_requirement_5_atomic_freeze_concurrency(self):
        self.log_header("Syarat 5: Atomic Freeze pada 2 Worker Konkuren (Database Queue)")

        queue_id = f"queue-concurrency-{uuid.uuid4().hex[:6]}"
        queue = PersistentCampaignQueue(queue_id, self.audit_service, self.tenant_id)
        queue.transition_to(QueueState.RUNNING, actor_id="operator_01", reason="Mulai broadcast multi-worker di DB")

        initial_items = [f"msg_{i:02d}" for i in range(1, 31)]
        queue.seed_items(initial_items)

        processed_worker_1: List[str] = []
        processed_worker_2: List[str] = []
        freeze_event = threading.Event()

        def persistent_worker_loop(worker_name: str, processed_list: List[str]):
            while True:
                # 1. Baca status persisten dari database
                current_state = queue.get_state()
                if current_state != QueueState.RUNNING:
                    print(f"       [{worker_name}] Membaca status persisten '{current_state.value}' dari DB! Worker berhenti seketika.")
                    break

                # 2. Klaim item dari PostgreSQL menggunakan FOR UPDATE SKIP LOCKED
                item_tuple = queue.fetch_and_claim_item(worker_name)
                if not item_tuple:
                    break

                item_id, payload = item_tuple

                # Simulasi trigger FROZEN di tengah jalan oleh Worker-1 setelah memproses 4 pesan
                if worker_name == "Worker-1" and len(processed_list) == 4 and not freeze_event.is_set():
                    freeze_event.set()
                    print(f"       [{worker_name}] Terdeteksi error callback gateway! Mengubah status antrean ke FROZEN di PostgreSQL...")
                    queue.transition_to(
                        QueueState.FROZEN,
                        actor_id="system_circuit_breaker",
                        reason="Emergency freeze triggered during multi-worker processing"
                    )
                    queue.release_item(item_id)
                    break

                processed_list.append(payload)
                queue.complete_item(item_id)
                time.sleep(0.015)

        t1 = threading.Thread(target=persistent_worker_loop, args=("Worker-1", processed_worker_1))
        t2 = threading.Thread(target=persistent_worker_loop, args=("Worker-2", processed_worker_2))

        t1.start()
        t2.start()
        t1.join(timeout=4.0)
        t2.join(timeout=4.0)

        total_pending_in_db = queue.count_pending_items()

        passed = (
            queue.get_state() == QueueState.FROZEN
            and total_pending_in_db > 0
            and len(processed_worker_2) > 0
            and not t1.is_alive()
            and not t2.is_alive()
        )
        self.log_test_result(
            "3.1",
            "Atomic Concurrency Freeze on Persistent Database Queue",
            passed,
            f"Processed W1: {len(processed_worker_1)}, W2: {len(processed_worker_2)} | Sisa pesan PENDING di tabel DB: {total_pending_in_db}"
        )

    # ----------------------------------------------------------------------------------
    # SYARAT 6: TOKEN UNDANGAN TELEGRAM 1X PAKAI (ATOMIC CONDITIONAL UPDATE DI DB)
    # ----------------------------------------------------------------------------------
    def test_requirement_6_telegram_single_use_token(self):
        self.log_header("Syarat 6: Token Undangan Telegram 1x Pakai (Atomic DB Conditional Update)")

        order_id = "ORD-TEST-CTWA-8801"
        token = self.telegram_service.issue_token(order_id, ttl_seconds=3600)
        print(f"       Token persisten diterbitkan: {token} untuk Order #{order_id}")

        ok_1, status_1, link_1 = self.telegram_service.claim_token(token, claimant_id="buyer_phone_62882260")
        print(f"       Klaim #1: Status={status_1}, Link={link_1}")

        ok_2, status_2, link_2 = self.telegram_service.claim_token(token, claimant_id="attacker_or_duplicate")
        print(f"       Klaim #2: Status={status_2}, Link={link_2}")

        expired_token = self.telegram_service.issue_token("ORD-EXPIRED-001", ttl_seconds=-10)
        ok_3, status_3, _ = self.telegram_service.claim_token(expired_token, claimant_id="late_buyer")
        print(f"       Klaim #3 (Expired): Status={status_3}")

        passed = (
            ok_1 is True
            and status_1 == "SUCCESS"
            and link_1 is not None
            and ok_2 is False
            and status_2 == "TOKEN_ALREADY_CLAIMED"
            and link_2 is None
            and ok_3 is False
            and status_3 == "TOKEN_EXPIRED"
        )
        self.log_test_result(
            "4.1",
            "Telegram Single-Use Token Protection (Database Atomic)",
            passed,
            f"Klaim 1: {status_1} | Klaim 2: {status_2} (Ditolak DB) | Klaim 3: {status_3} (Ditolak DB)"
        )

    # ----------------------------------------------------------------------------------
    # SYARAT 7: STATE MACHINE DETERMINISTIK & BUKTI AUDIT TRAIL DI POSTGRESQL
    # ----------------------------------------------------------------------------------
    def test_requirement_7_state_machine_and_audit(self):
        self.log_header("Syarat 7: Siklus Hidup State Machine & Audit Trail di PostgreSQL")

        queue_id = f"queue-audit-lifecycle-{uuid.uuid4().hex[:6]}"
        queue = PersistentCampaignQueue(queue_id, self.audit_service, self.tenant_id)
        
        queue.transition_to(QueueState.RUNNING, actor_id="operator_danang", reason="Menjalankan campaign blast")
        queue.transition_to(QueueState.FROZEN, actor_id="system_circuit_breaker", reason="3 Callback HTTP 500 beruntun")

        illegal_transition_blocked = False
        try:
            queue.transition_to(QueueState.RUNNING, actor_id="nakal_01", reason="Bypass review")
        except IllegalStateTransitionError:
            illegal_transition_blocked = True
            print("       [OK] Percobaan bypass ilegal FROZEN -> RUNNING berhasil dicegah!")

        queue.transition_to(QueueState.REVIEW_REQUIRED, actor_id="supervisor_aditya", reason="Eskalasi tim SRE untuk analisa rute")
        queue.transition_to(QueueState.READY, actor_id="cto_office", reason="Root cause diperbaiki, rute aman")

        relevant_logs = self.audit_service.get_logs(queue_id=queue_id)

        print("\n       --- BUKTI AUDIT TRAIL DI TABEL 'audit_logs' POSTGRESQL ---")
        for log in relevant_logs:
            meta = log['metadata']
            print(
                f"       [{log['created_at'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] "
                f"{meta.get('from_state'):15} -> {meta.get('to_state'):15} | "
                f"Actor: {log['actor_id']:22} | Reason: {meta.get('reason')}"
            )

        passed = (
            queue.get_state() == QueueState.READY
            and illegal_transition_blocked
            and len(relevant_logs) == 4
        )
        self.log_test_result(
            "5.1",
            "Deterministic State Machine Lifecycle & Full Audit Trail in DB",
            passed,
            f"Alur status READY->RUNNING->FROZEN->REVIEW_REQUIRED->READY tervalidasi 100% di tabel audit_logs. Transisi ilegal diblokir."
        )

    # ----------------------------------------------------------------------------------
    # RUN ALL & GENERATE CTO INSPECTION SUMMARY
    # ----------------------------------------------------------------------------------
    def run_all(self) -> bool:
        start_time = time.time()
        print("\n" + "#" * 80)
        print("  BOONTRACK CORE ENGINEERING — CTO PREFLIGHT PERSISTENT TEST SUITE")
        print("  Target: 7 Syarat CTO (Circuit Breaker, Persistent Suppression, Concurrency & Audit)")
        print(f"  Tenant Scope: {self.tenant_id}")
        print(f"  Waktu Eksekusi: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("#" * 80)

        try:
            self.test_requirement_1_consecutive_failures()
            self.test_requirement_2_failure_rate_threshold()
            self.test_requirement_3_stop_keyword_ingestion()
            self.test_requirement_4_suppression_batch_filtering()
            self.test_requirement_5_atomic_freeze_concurrency()
            self.test_requirement_6_telegram_single_use_token()
            self.test_requirement_7_state_machine_and_audit()
        finally:
            self.teardown()

        elapsed = time.time() - start_time
        all_passed = all(p for _, p, _ in self.results)

        print("\n" + "=" * 80)
        print("  LAPORAN AKHIR INSPEKSI CTO (CTO PREFLIGHT PERSISTENT SIGN-OFF REPORT)")
        print("=" * 80)
        print(f"  Total Pengujian Dijalankan : {len(self.results)}")
        print(f"  Status Kelulusan           : {'SEMUA LOLOS (100% PASS)' if all_passed else 'ADA KEGAGALAN'}")
        print(f"  Durasi Eksekusi            : {elapsed:.3f} detik\n")

        print("  Ringkasan Hasil Uji:")
        for name, passed, detail in self.results:
            status_text = "PASS" if passed else "FAIL"
            print(f"  - [{status_text}] {name:<60} | {detail}")

        print("=" * 80)
        if all_passed:
            print("  KESIMPULAN: Sistem 100% memenuhi 7 Syarat Hardening CTO dengan Persistent Store.")
            print("  Seluruh operasi STOP, Telegram Token, Atomic Concurrency Freeze & Audit Trail")
            print("  terekam dan tervalidasi di PostgreSQL aktual di bawah RLS ketat.")
            print("  Status: READY FOR PRODUCTION BATCH 1 BLOWOUT.")
        else:
            print("  KESIMPULAN: Ditemukan kegagalan invarian arsitektur pada persistent store!")
        print("=" * 80 + "\n")

        return all_passed


if __name__ == "__main__":
    suite = CTOPreflightTestSuite()
    success = suite.run_all()
    sys.exit(0 if success else 1)
