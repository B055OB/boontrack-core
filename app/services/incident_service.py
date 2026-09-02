import os
import psycopg2
from psycopg2.extras import Json
from typing import Dict, Any, Optional

def log_tenant_incident(
    tenant_id: str,
    service: str,
    severity: str,
    error_message: str,
    error_code: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Mencatat log insiden kesehatan sistem per tenant ke tabel tenant_incidents.
    Severity: 'LOW', 'MEDIUM', 'CRITICAL'
    Service: 'WhatsApp', 'Payment', 'Webhook', 'AI', 'Shipping'
    """
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    conn = None
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO tenant_incidents (
                tenant_id, service, severity, status, 
                error_code, error_message, metadata, first_seen_at, last_seen_at
            ) VALUES (
                %s, %s, %s, 'OPEN', 
                %s, %s, %s, NOW(), NOW()
            );
        """, (
            tenant_id,
            service,
            severity,
            error_code,
            error_message,
            Json(metadata or {})
        ))
        conn.commit()
        cur.close()
    except Exception as err:
        print(f"[INCIDENT LOGGER ERROR] Gagal mencatat insiden: {err}", flush=True)
    finally:
        if conn:
            conn.close()