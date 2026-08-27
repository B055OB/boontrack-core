import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from app.utils.qris_generator import (
    generate_dynamic_qris_payload,
    render_qris_bytes,
    generate_unique_code
)
from app.services.cv_state_engine import GLOBAL_USER_STATES
from app.services.reconciliation_service import PAYMENT_INTENTS

logger = logging.getLogger("PAYMENT_SERVICE")


def get_supabase():
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
    if url and key:
        try:
            from supabase import create_client
            return create_client(url, key)
        except Exception:
            return None
    return None


class PaymentService:
    """Service manajemen pesanan & Dynamic QRIS 3-digit kode unik acak."""

    @classmethod
    def create_qris_order(
        cls,
        user_id: str,
        base_amount: int,
        order_id: Optional[str] = None,
        tenant_id: str = "boontrack-career",
        meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Membuat pesanan baru dan merender Dynamic QRIS dengan 3-digit kode unik acak.
        
        Args:
            user_id: Phone / WA ID / ID pengguna.
            base_amount: Nominal dasar produk (misal Rp25.000 atau Rp10.000).
            order_id: ID invoice opsional. Jika None, digenerate otomatis (BT-...).
            tenant_id: Tenant ID pengelola produk.
            meta: Metadata opsional.
            
        Returns:
            Dict berisi detail order, dynamic_payload, qr_bytes / qr_image_bytes (PNG), dan status 'PENDING'.
        """
        # 1. Ambil master static string resmi dari environment
        master_static = os.getenv("BOONTRACK_STATIC_QRIS", "").strip()
        if not master_static:
            master_static = "00020101021126570011ID.DANA.WWW011893600915303379682702090337968270303UMI51440014ID.CO.QRIS.WWW0215ID10265640751030303UMI5204737253033605802ID5909BoonTrack6012Kab. Bandung61054028663048DC1"

        # 2. Generate 3-digit unik acak (rentang 100 - 999)
        unique_code = generate_unique_code(100, 999)
        total_amount = int(base_amount) + unique_code

        # 3. Bentuk invoice / order_id jika belum ada
        if not order_id:
            ts = int(datetime.now().timestamp())
            order_id = f"BT-{ts}-{unique_code}"

        # 4. Generate dynamic payload QRIS dengan Tag 54 dan Tag 01=010212
        dynamic_payload = generate_dynamic_qris_payload(master_static, total_amount)

        # 5. Render matriks QR murni ke in-memory byte buffer (PNG)
        qr_image_bytes = render_qris_bytes(dynamic_payload)

        # 6. Simpan order ke in-memory PAYMENT_INTENTS
        now_dt = datetime.now()
        PAYMENT_INTENTS[order_id] = {
            "invoice_id": order_id,
            "order_id": order_id,
            "user_id": str(user_id),
            "base_amount": base_amount,
            "unique_code": unique_code,
            "total_amount": total_amount,
            "amount": total_amount,
            "dynamic_payload": dynamic_payload,
            "tenant_id": tenant_id,
            "status": "PENDING",
            "created_at": now_dt,
            "expires_at": now_dt + timedelta(minutes=30),
            "meta": meta or {}
        }

        # 7. Simpan active_payment ke GLOBAL_USER_STATES
        user_str_id = str(user_id)
        user_session = GLOBAL_USER_STATES.setdefault(user_str_id, {"step": 0, "mode": "menu", "data": {}})
        user_session["active_payment"] = {
            "order_id": order_id,
            "invoice_id": order_id,
            "base_amount": base_amount,
            "unique_code": unique_code,
            "total_amount": total_amount,
            "amount": total_amount,
            "status": "PENDING",
            "created_at": now_dt.isoformat()
        }

        # 8. Simpan ke database Supabase: tabel orders (untuk log) & tabel document_jobs (untuk payment matching)
        supabase = get_supabase()
        if supabase:
            # 8a. Upsert ke tabel orders (opsional, bisa tidak ada)
            try:
                supabase.table("orders").upsert({
                    "id": order_id,
                    "user_id": user_str_id,
                    "tenant_id": tenant_id,
                    "base_amount": base_amount,
                    "total_amount": total_amount,
                    "status": "PENDING",
                    "qris_payload": dynamic_payload,
                    "created_at": now_dt.isoformat()
                }).execute()
            except Exception as e:
                logger.debug(f"[PAYMENT SERVICE] Supabase order upsert note: {e}")

            # 8b. INSERT record WAJIB ke tabel document_jobs agar payment matcher bisa menemukan order
            # ini dilakukan TERLEPAS dari apakah file asli dokumen tersedia / valid
            import uuid
            job_uuid = str(uuid.uuid4())
            job_db_record = {
                "id": job_uuid,
                "job_id": job_uuid,
                "tenant_id": tenant_id,
                "user_id": user_str_id,
                "source_channel": "whatsapp",
                "original_filename": (meta or {}).get("filename", "order.docx"),
                "mime_type": "application/pdf",
                "file_size": 0,
                "storage_key": f"inbox/{job_uuid}",
                "task_type": (meta or {}).get("product", "PAYMENT_ORDER"),
                "status": "WAITING_PAYMENT",
                "payment_status": "UNPAID",
                "price_amount": total_amount,      # field utama untuk payment matching
            }
            try:
                supabase.table("document_jobs").insert(job_db_record).execute()
                logger.info(
                    f"[PAYMENT SERVICE] document_jobs record inserted: id={job_uuid} "
                    f"price_amount={total_amount} user={user_str_id} status=UNPAID"
                )
            except Exception as e:
                logger.error(f"[PAYMENT SERVICE] CRITICAL: document_jobs insert failed: {e}")


        logger.info(
            f"[PAYMENT ORDER CREATED] Order {order_id} | User {user_id} | "
            f"Base: Rp{base_amount:,} + Code: {unique_code} -> Total: Rp{total_amount:,}"
        )

        return {
            "order_id": order_id,
            "invoice_id": order_id,
            "user_id": user_str_id,
            "base_amount": base_amount,
            "unique_code": unique_code,
            "total_amount": total_amount,
            "amount": total_amount,
            "dynamic_payload": dynamic_payload,
            "qr_image_bytes": qr_image_bytes,
            "qr_bytes": qr_image_bytes,
            "status": "PENDING"
        }

    @classmethod
    def create_dynamic_order(
        cls,
        user_id: str,
        base_amount: int,
        order_id: Optional[str] = None,
        tenant_id: str = "boontrack-career",
        meta: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Alias untuk create_qris_order."""
        return cls.create_qris_order(
            user_id=user_id,
            base_amount=base_amount,
            order_id=order_id,
            tenant_id=tenant_id,
            meta=meta
        )


payment_service = PaymentService()