-- =============================================================================
-- Migration 032: Authoritative Payment HMAC Anti-Replay Store & Audit Log
-- Phase 1 — Stage 1: Security Foundation (Corrective Implementation)
--
-- Enforces:
--   1. Dedicated table owner (`bt_migration_owner`) separate from runtime (`bt_app_runtime`)
--      and cleanup (`bt_replay_cleanup`) roles.
--   2. Runtime least privilege: `bt_app_runtime` has ONLY `SELECT, INSERT` on
--      `public.payment_hmac_replay_nonces` and `USAGE, SELECT` on the BIGSERIAL
--      sequence (`nextval` allowed; `UPDATE`, `DELETE`, `TRUNCATE`, `setval` prohibited).
--   3. Append-only semantics enforced via both PostgreSQL privilege revocation and
--      a BEFORE UPDATE OR DELETE trigger (`trg_payment_hmac_replay_immutability`).
--   4. Retention policy:
--      - Active replay window: `expires_at >= consumed_at + INTERVAL '600 seconds'` (10 min).
--      - Forensic retention window: 90 days after `expires_at` (`INTERVAL '90 days'`).
--   5. Controlled cleanup function (`public.purge_expired_payment_replay_nonces`)
--      restricted exclusively to `bt_replay_cleanup` with an append-only cleanup
--      audit trail (`public.payment_hmac_replay_cleanup_audit_log`).
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_migration_owner') THEN
        CREATE ROLE bt_migration_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_app_runtime') THEN
        CREATE ROLE bt_app_runtime NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bt_replay_cleanup') THEN
        CREATE ROLE bt_replay_cleanup NOLOGIN;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.payment_hmac_replay_nonces (
    id BIGSERIAL PRIMARY KEY,
    key_id VARCHAR(128) NOT NULL,
    nonce VARCHAR(128) NOT NULL,
    actor_principal VARCHAR(255) NOT NULL,
    canonical_tenant_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    http_method VARCHAR(16) NOT NULL,
    canonical_path TEXT NOT NULL,
    request_timestamp BIGINT NOT NULL,
    body_sha256 CHAR(64) NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_payment_hmac_replay_key_nonce UNIQUE (key_id, nonce),
    CONSTRAINT chk_payment_hmac_replay_non_empty CHECK (
        BTRIM(key_id) <> ''
        AND BTRIM(nonce) <> ''
        AND BTRIM(actor_principal) <> ''
        AND BTRIM(canonical_tenant_id) <> ''
        AND BTRIM(order_id) <> ''
        AND BTRIM(http_method) <> ''
        AND BTRIM(canonical_path) <> ''
        AND LENGTH(BTRIM(body_sha256)) = 64
    ),
    CONSTRAINT chk_payment_hmac_replay_active_window CHECK (
        expires_at >= consumed_at + INTERVAL '600 seconds'
    )
);

CREATE TABLE IF NOT EXISTS public.payment_hmac_replay_cleanup_audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    executed_by_role VARCHAR(128) NOT NULL,
    deleted_row_count INTEGER NOT NULL CHECK (deleted_row_count >= 0),
    cutoff_expires_at TIMESTAMPTZ NOT NULL,
    min_deleted_expires_at TIMESTAMPTZ,
    max_deleted_expires_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.payment_hmac_replay_nonces OWNER TO bt_migration_owner;
ALTER SEQUENCE public.payment_hmac_replay_nonces_id_seq OWNER TO bt_migration_owner;

ALTER TABLE public.payment_hmac_replay_cleanup_audit_log OWNER TO bt_migration_owner;
ALTER SEQUENCE public.payment_hmac_replay_cleanup_audit_log_audit_id_seq OWNER TO bt_migration_owner;

CREATE INDEX IF NOT EXISTS idx_payment_hmac_replay_expires_at
    ON public.payment_hmac_replay_nonces (expires_at);

CREATE INDEX IF NOT EXISTS idx_payment_hmac_replay_order_tenant
    ON public.payment_hmac_replay_nonces (canonical_tenant_id, order_id);

-- =============================================================================
-- Append-Only & 90-Day Forensic Retention Guard Trigger
-- =============================================================================

CREATE OR REPLACE FUNCTION public.enforce_payment_replay_nonces_retention_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'NONCE_TABLE_IMMUTABLE: UPDATE on public.payment_hmac_replay_nonces is strictly prohibited.'
            USING ERRCODE = '42501';
    ELSIF TG_OP = 'DELETE' THEN
        IF CURRENT_USER <> 'bt_replay_cleanup' THEN
            RAISE EXCEPTION 'NONCE_DELETE_FORBIDDEN: Role % is not authorized to DELETE from public.payment_hmac_replay_nonces.', CURRENT_USER
                USING ERRCODE = '42501';
        END IF;
        IF OLD.expires_at >= (NOW() - INTERVAL '90 days') THEN
            RAISE EXCEPTION 'FORENSIC_RETENTION_ACTIVE: Cannot delete replay nonce (id=%) before 90-day forensic retention window elapses (expires_at=%).',
                OLD.id, OLD.expires_at
                USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$fn$;

ALTER FUNCTION public.enforce_payment_replay_nonces_retention_guard() OWNER TO bt_migration_owner;

DROP TRIGGER IF EXISTS trg_payment_hmac_replay_immutability ON public.payment_hmac_replay_nonces;
CREATE TRIGGER trg_payment_hmac_replay_immutability
    BEFORE UPDATE OR DELETE ON public.payment_hmac_replay_nonces
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_payment_replay_nonces_retention_guard();

-- Append-Only Guard on Cleanup Audit Log
CREATE OR REPLACE FUNCTION public.enforce_payment_replay_cleanup_audit_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $audit_fn$
BEGIN
    RAISE EXCEPTION 'CLEANUP_AUDIT_IMMUTABLE: % on public.payment_hmac_replay_cleanup_audit_log is strictly prohibited.', TG_OP
        USING ERRCODE = '42501';
END;
$audit_fn$;

ALTER FUNCTION public.enforce_payment_replay_cleanup_audit_immutable() OWNER TO bt_migration_owner;

DROP TRIGGER IF EXISTS trg_payment_replay_cleanup_audit_immutable ON public.payment_hmac_replay_cleanup_audit_log;
CREATE TRIGGER trg_payment_replay_cleanup_audit_immutable
    BEFORE UPDATE OR DELETE ON public.payment_hmac_replay_cleanup_audit_log
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_payment_replay_cleanup_audit_immutable();

-- =============================================================================
-- Controlled Retention Purge Function with Audit Trail (SECURITY INVOKER)
-- Runs under the caller's privileges (must be `bt_replay_cleanup`), ensuring
-- `bt_app_runtime` can NEVER escalate privileges via this function.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.purge_expired_payment_replay_nonces(p_batch_limit INTEGER DEFAULT 5000)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY INVOKER
AS $purge$
DECLARE
    v_cutoff TIMESTAMPTZ := NOW() - INTERVAL '90 days';
    v_deleted_count INTEGER := 0;
    v_min_exp TIMESTAMPTZ;
    v_max_exp TIMESTAMPTZ;
BEGIN
    IF CURRENT_USER <> 'bt_replay_cleanup' THEN
        RAISE EXCEPTION 'PURGE_ROLE_UNAUTHORIZED: Only bt_replay_cleanup may execute purge_expired_payment_replay_nonces (current_user=%).', CURRENT_USER
            USING ERRCODE = '42501';
    END IF;

    WITH candidate_rows AS (
        SELECT id
        FROM public.payment_hmac_replay_nonces
        WHERE expires_at < v_cutoff
        ORDER BY expires_at ASC
        LIMIT GREATEST(1, LEAST(COALESCE(p_batch_limit, 5000), 50000))
    ),
    deleted_rows AS (
        DELETE FROM public.payment_hmac_replay_nonces t
        USING candidate_rows c
        WHERE t.id = c.id
        RETURNING t.expires_at
    )
    SELECT COUNT(*)::INTEGER, MIN(expires_at), MAX(expires_at)
    INTO v_deleted_count, v_min_exp, v_max_exp
    FROM deleted_rows;

    INSERT INTO public.payment_hmac_replay_cleanup_audit_log (
        executed_by_role,
        deleted_row_count,
        cutoff_expires_at,
        min_deleted_expires_at,
        max_deleted_expires_at,
        executed_at
    )
    VALUES (
        CURRENT_USER,
        COALESCE(v_deleted_count, 0),
        v_cutoff,
        v_min_exp,
        v_max_exp,
        NOW()
    );

    RETURN COALESCE(v_deleted_count, 0);
END;
$purge$;

ALTER FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) OWNER TO bt_migration_owner;

-- =============================================================================
-- Least-Privilege Table, Sequence & Function Grants
-- =============================================================================

REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_nonces FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_nonces FROM bt_app_runtime;
REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_nonces FROM bt_replay_cleanup;

GRANT SELECT, INSERT ON TABLE public.payment_hmac_replay_nonces TO bt_app_runtime;
GRANT SELECT, DELETE ON TABLE public.payment_hmac_replay_nonces TO bt_replay_cleanup;

REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_nonces_id_seq FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_nonces_id_seq FROM bt_app_runtime;
REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_nonces_id_seq FROM bt_replay_cleanup;

GRANT USAGE, SELECT ON SEQUENCE public.payment_hmac_replay_nonces_id_seq TO bt_app_runtime;

REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_cleanup_audit_log FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_cleanup_audit_log FROM bt_app_runtime;
REVOKE ALL PRIVILEGES ON TABLE public.payment_hmac_replay_cleanup_audit_log FROM bt_replay_cleanup;

GRANT SELECT ON TABLE public.payment_hmac_replay_cleanup_audit_log TO bt_app_runtime;
GRANT SELECT, INSERT ON TABLE public.payment_hmac_replay_cleanup_audit_log TO bt_replay_cleanup;

REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_cleanup_audit_log_audit_id_seq FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_cleanup_audit_log_audit_id_seq FROM bt_app_runtime;
REVOKE ALL PRIVILEGES ON SEQUENCE public.payment_hmac_replay_cleanup_audit_log_audit_id_seq FROM bt_replay_cleanup;

GRANT USAGE, SELECT ON SEQUENCE public.payment_hmac_replay_cleanup_audit_log_audit_id_seq TO bt_replay_cleanup;

REVOKE ALL ON FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) FROM bt_app_runtime;
GRANT EXECUTE ON FUNCTION public.purge_expired_payment_replay_nonces(INTEGER) TO bt_replay_cleanup;

COMMENT ON TABLE public.payment_hmac_replay_nonces IS
    'Authoritative cross-worker anti-replay nonce store (Stage 1 Security Foundation). Owned by bt_migration_owner; runtime has SELECT/INSERT only; 10m active window + 90d forensic retention.';
COMMENT ON TABLE public.payment_hmac_replay_cleanup_audit_log IS
    'Append-only audit trail of replay nonce retention purges executed by bt_replay_cleanup.';
