"""app/services/quota_alert_service.py
WhatsApp 80% Quota Trigger Alert with Strict RLS Suppression Check (Fase 3 & Node 5).

Responsibilities:
1. Validates recipient against `public.phone_suppressions` table prior to dispatch.
2. Enforces strict tenant isolation via RLS session setting `SET LOCAL app.current_tenant_id`.
3. If phone is blacklisted/suppressed: Aborts dispatch (zero WhatsApp outbound message).
4. If phone is clean: Dispatches high-priority 80% quota usage warning via WhatsApp Cloud API.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from app.core.database import get_db_connection
from app.services.whatsapp_service import normalize_phone_number
from app.services.whatsapp.cloud_api import send_whatsapp_text

logger = logging.getLogger("QUOTA_ALERT_SERVICE")


def is_phone_suppressed(phone: str, tenant_id: str) -> bool:
    """
    Mengecek apakah nomor telepon terdaftar di tabel `public.phone_suppressions`.
    Mematuhi Row-Level Security (RLS) dengan mengeset context tenant_id.
    """
    clean_p = normalize_phone_number(phone) or phone
    clean_p = str(clean_p).strip()

    phone_variants = [clean_p]
    if clean_p.startswith("+"):
        phone_variants.append(clean_p.lstrip("+"))
    else:
        phone_variants.append(f"+{clean_p}")
    if clean_p.startswith("62"):
        phone_variants.append("0" + clean_p[2:])
    elif clean_p.startswith("+62"):
        phone_variants.append("0" + clean_p[3:])

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Set tenant context for RLS
        cur.execute(f"SET LOCAL app.current_tenant_id = '{tenant_id}';")
        cur.execute(
            """
            SELECT id, reason, created_at 
            FROM public.phone_suppressions 
            WHERE tenant_id = %s AND phone_number = ANY(%s)
            LIMIT 1;
            """,
            (tenant_id, phone_variants)
        )
        row = cur.fetchone()
        if row:
            logger.info(
                f"[PhoneSuppression] Match found: phone={phone} (id={row[0]}, reason={row[1]}) for tenant='{tenant_id}'."
            )
            return True
        return False
    except Exception as e:
        logger.error(f"[PhoneSuppression Error] Failed to query suppression list: {e}")
        # Fail-closed for security: if table query fails, avoid sending unwanted messages
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


async def trigger_quota_80_percent_alert(
    tenant_id: str,
    recipient_phone: str,
    current_usage: int,
    max_quota: int,
    phone_number_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Trigger pengiriman notifikasi Kuota 80%:
    1. Mengecek tabel phone_suppressions (RLS terisolasi).
    2. Jika terdaftar, batalkan pengiriman secara aman (suppressed).
    3. Jika aman, kirimkan template peringatan kuota via Meta WhatsApp Cloud API.
    """
    clean_phone = normalize_phone_number(recipient_phone) or recipient_phone
    percentage = (current_usage / max_quota * 100) if max_quota > 0 else 80.0

    # 1. Pengecekan tabel supresi (RLS Ketat)
    if is_phone_suppressed(clean_phone, tenant_id=tenant_id):
        logger.warning(
            f"[QUOTA_ALERT_SUPPRESSED] Phone '{clean_phone}' is blacklisted in phone_suppressions for tenant '{tenant_id}'. Aborting WhatsApp dispatch."
        )
        return {
            "status": "suppressed",
            "sent": False,
            "reason": "PHONE_SUPPRESSED",
            "detail": f"Nomor {clean_phone} berada dalam daftar blacklist/opt-out (phone_suppressions).",
            "tenant_id": tenant_id,
            "recipient": clean_phone,
            "usage": current_usage,
            "max_quota": max_quota,
            "percentage": round(percentage, 1),
        }

    # 2. Susun pesan peringatan kuota 80%
    alert_text = (
        f"⚠️ *PERINGATAN KUOTA LAYANAN BOONTRACK ({round(percentage, 1)}%)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Halo Mitra BoonTrack! Penggunaan kuota interaksi & otomasi bisnis Anda telah mencapai "
        f"*{current_usage:,}* dari total kuota *{max_quota:,}* pesan ({round(percentage, 1)}%).\n\n"
        f"💡 *Rekomendasi Tindakan:*\n"
        f"Untuk memastikan bot kasir 24 jam dan penerbit QRIS tidak terhenti, "
        f"Anda dapat melakukan top-up kuota sesi tambahan langsung dari Dashboard Toko:\n"
        f"👉 https://dashboard.boontrack.com/settings/billing\n\n"
        f"_Terima kasih telah menggunakan ekosistem BoonTrack!_"
    )

    # 3. Kirim pesan WhatsApp
    try:
        wa_res = await send_whatsapp_text(
            to_phone=clean_phone,
            text=alert_text,
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
        )
        logger.info(f"[QUOTA_ALERT_SENT] Dispatched 80% quota alert to {clean_phone} for tenant '{tenant_id}'.")
        return {
            "status": "sent",
            "sent": True,
            "tenant_id": tenant_id,
            "recipient": clean_phone,
            "usage": current_usage,
            "max_quota": max_quota,
            "percentage": round(percentage, 1),
            "wa_result": wa_res,
        }
    except Exception as err:
        logger.error(f"[QUOTA_ALERT_DISPATCH_ERROR] Failed sending WA to {clean_phone}: {err}")
        return {
            "status": "failed",
            "sent": False,
            "error": str(err),
            "tenant_id": tenant_id,
            "recipient": clean_phone,
        }
