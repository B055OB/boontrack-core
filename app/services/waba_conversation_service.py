"""
app/services/waba_conversation_service.py

Layanan atribusi percakapan WhatsApp Business API (WABA) untuk tabel waba_conversations.
Mencatat dan melacak atribusi percakapan customer melalui berbagai touchpoint:
- STOREFRONT: Klik chat dari halaman storefront/katalog toko
- ORDER_NOTIFICATION: Notifikasi pesanan baru (ORDER_CREATED)
- PAYMENT_NOTIFICATION: Konfirmasi pembayaran sah (PAYMENT_CONFIRMED)
- SHIPPING_NOTIFICATION: Notifikasi pengiriman & nomor resi (SHIPMENT_CREATED)
- DIRECT: Chat langsung masuk ke nomor WABA
- ADS_CTWA: Klik iklan Click-to-WhatsApp (Meta Ads CTWA)
"""

import logging
import re
from typing import Optional, Dict, Any, List
from psycopg2.extras import RealDictCursor
from app.core.database import get_db_connection
from app.services.whatsapp_service import normalize_phone_number, get_supabase

logger = logging.getLogger("WABA_CONVERSATION_SERVICE")

VALID_SOURCES = frozenset([
    "STOREFRONT",
    "ORDER_NOTIFICATION",
    "PAYMENT_NOTIFICATION",
    "SHIPPING_NOTIFICATION",
    "DIRECT",
    "ADS_CTWA",
])


def _is_valid_uuid(val: Optional[str]) -> bool:
    if not val:
        return False
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", str(val).strip(), re.I))


async def record_waba_conversation(
    wa_user_id: str,
    source: str,
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    order_id: Optional[str] = None,
    product_id: Optional[str] = None,
    storefront_url: Optional[str] = None,
    campaign_id: Optional[str] = None,
    status: str = "active",
) -> Optional[Dict[str, Any]]:
    """
    Mencatat atribusi percakapan baru atau memperbarui aktivitas WABA pada waba_conversations.
    
    Guarantees:
    - Normalisasi wa_user_id ke format E.164 numerik (62xxx).
    - Validasi source ke enum standar.
    - Resolusi foreign key yang aman (tenant_id UUID, product_id UUID, order_id TEXT).
    - Fault-tolerant: Kegagalan pencatatan tidak menggagalkan alur transaksi utama.
    """
    clean_phone = normalize_phone_number(wa_user_id) or "".join(filter(str.isdigit, str(wa_user_id or "")))
    if not clean_phone:
        logger.warning(f"[WABA_CONV] Gagal merekam percakapan: wa_user_id kosong '{wa_user_id}'")
        return None

    norm_source = str(source or "DIRECT").upper().strip()
    if norm_source not in VALID_SOURCES:
        logger.warning(f"[WABA_CONV] Source '{norm_source}' tidak dikenal, fallback ke 'DIRECT'")
        norm_source = "DIRECT"

    resolved_tenant_uuid: Optional[str] = None
    resolved_order_id: Optional[str] = None
    resolved_product_uuid: Optional[str] = None

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Resolusi Tenant UUID
        target_tenant = tenant_id or tenant_slug
        if target_tenant:
            target_str = str(target_tenant).strip()
            if _is_valid_uuid(target_str):
                cur.execute("SELECT id FROM tenants WHERE id = %s LIMIT 1;", (target_str,))
            else:
                cur.execute("SELECT id FROM tenants WHERE slug = %s OR id::text = %s LIMIT 1;", (target_str, target_str))
            t_row = cur.fetchone()
            if t_row:
                resolved_tenant_uuid = str(t_row["id"])

        # 2. Resolusi Product UUID (jika ada)
        if product_id and _is_valid_uuid(str(product_id).strip()):
            cur.execute("SELECT id FROM products WHERE id = %s LIMIT 1;", (str(product_id).strip(),))
            p_row = cur.fetchone()
            if p_row:
                resolved_product_uuid = str(p_row["id"])

        # 3. Resolusi Order ID (Foreign Key ke orders.id)
        if order_id:
            ord_str = str(order_id).strip()
            cur.execute("SELECT id FROM orders WHERE id = %s LIMIT 1;", (ord_str,))
            o_row = cur.fetchone()
            if o_row:
                resolved_order_id = str(o_row["id"])
            else:
                # Jika order belum ada di tabel orders, cek apakah ada di product_orders
                cur.execute("SELECT order_id FROM product_orders WHERE order_id = %s LIMIT 1;", (ord_str,))
                po_row = cur.fetchone()
                if po_row:
                    # Buat placeholder entry di orders agar foreign key integritas terpenuhi
                    try:
                        cur.execute("""
                            INSERT INTO orders (id, tenant_id, status, created_at, updated_at)
                            VALUES (%s, %s, 'PENDING', NOW(), NOW())
                            ON CONFLICT (id) DO NOTHING;
                        """, (ord_str, resolved_tenant_uuid))
                        conn.commit()
                        resolved_order_id = ord_str
                    except Exception as ins_err:
                        logger.debug(f"[WABA_CONV] Placeholder order insert skipped: {ins_err}")

        # 4. Insert record ke waba_conversations
        cur.execute("""
            INSERT INTO waba_conversations (
                tenant_id,
                wa_user_id,
                source,
                storefront_url,
                product_id,
                order_id,
                campaign_id,
                status,
                first_message_at,
                last_message_at,
                created_at,
                updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                NOW(), NOW(), NOW(), NOW()
            ) RETURNING id, tenant_id, wa_user_id, source, storefront_url, product_id, order_id, campaign_id, status, created_at;
        """, (
            resolved_tenant_uuid,
            clean_phone,
            norm_source,
            storefront_url,
            resolved_product_uuid,
            resolved_order_id,
            campaign_id,
            status or "active",
        ))

        inserted = cur.fetchone()
        conn.commit()
        cur.close()

        logger.info(
            f"[WABA_CONV ✓] Recorded: user={clean_phone} source={norm_source} "
            f"tenant={resolved_tenant_uuid} order={resolved_order_id}"
        )
        return dict(inserted) if inserted else None

    except Exception as exc:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning(f"[WABA_CONV WARN] Gagal menyimpan waba_conversation: {exc}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


async def get_waba_conversation_by_user(
    wa_user_id: str,
    tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Mengambil riwayat percakapan WABA untuk pengguna tertentu."""
    clean_phone = normalize_phone_number(wa_user_id) or wa_user_id
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if tenant_id:
            cur.execute("""
                SELECT * FROM waba_conversations 
                WHERE wa_user_id = %s AND (tenant_id = %s OR tenant_id::text = %s)
                ORDER BY created_at DESC;
            """, (clean_phone, tenant_id, str(tenant_id)))
        else:
            cur.execute("""
                SELECT * FROM waba_conversations 
                WHERE wa_user_id = %s
                ORDER BY created_at DESC;
            """, (clean_phone,))
        rows = cur.fetchall()
        cur.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error(f"[WABA_CONV] Gagal mengambil percakapan user {clean_phone}: {exc}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
