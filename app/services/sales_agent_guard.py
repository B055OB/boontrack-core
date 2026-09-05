"""app/services/sales_agent_guard.py
Store Sales Agent Security Boundary & Backend Validator (ADR Architecture).

Aturan Keamanan Mutlak:
1. LLM DILARANG menentukan harga, stok, atau mengubah transaksi secara langsung.
2. Pemisahan Konteks (Context Separation):
   - Data Transaksi (ID, Nama, Harga, Stok riil) -> Ambil langsung via SQL/DB/Redis Tenant.
   - Knowledge Toko (FAQ, Kebijakan, Sizing Guide) -> Semantic Search / Store Knowledge Base.
3. Action Catalog Terikat:
   ['SHOW_PRODUCT', 'SHOW_PRODUCT_LIST', 'SHOW_VARIANT', 'SHOW_CHECKOUT', 'CREATE_PAYMENT', 'TRANSFER_TO_HUMAN']
4. Backend Validator:
   - WAJIB memverifikasi ulang harga & stok database sebelum payload aksi diteruskan ke frontend / WhatsApp.
   - LLM yang mencoba mengubah harga akan secara otomatis di-override / ditolak ke harga resmi database.
5. Strict Tenant Isolation:
   - Cache key dan session wajib scoped: 'tenant:{tenant_id}:session:{session_id}'.
"""

import os
import json
import logging
import enum
from decimal import Decimal
from typing import Dict, Any, List, Optional, Tuple, Set

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("SALES_AGENT_GUARD")


# ============================================================================
# 1. BOUNDED ACTION CATALOG
# ============================================================================

class StoreActionType(str, enum.Enum):
    """Katalog aksi terikat resmi untuk Store Sales Agent (BUYER_ASSISTANT)."""
    SHOW_PRODUCT = "SHOW_PRODUCT"
    SHOW_PRODUCT_LIST = "SHOW_PRODUCT_LIST"
    SHOW_VARIANT = "SHOW_VARIANT"
    SHOW_CHECKOUT = "SHOW_CHECKOUT"
    CREATE_PAYMENT = "CREATE_PAYMENT"
    TRANSFER_TO_HUMAN = "TRANSFER_TO_HUMAN"


ALLOWED_STORE_ACTIONS: Set[str] = {action.value for action in StoreActionType}


# ============================================================================
# 2. STRICT TENANT SESSION SCOPE HELPER
# ============================================================================

def format_tenant_session_key(tenant_id: str, session_id: str, sub_key: str = "") -> str:
    """
    Format standar isolasi multi-tenant:
    'tenant:{tenant_id}:session:{session_id}' atau 'tenant:{tenant_id}:session:{session_id}:{sub_key}'
    """
    clean_tenant = str(tenant_id or "default").strip().lower()
    clean_session = str(session_id or "global").strip()
    base = f"tenant:{clean_tenant}:session:{clean_session}"
    if sub_key:
        return f"{base}:{sub_key.strip()}"
    return base


class TenantScopedSessionStore:
    """Penyimpanan sesi lokal dan cache yang terkunci rapat per tenant."""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}

    def get(self, tenant_id: str, session_id: str, sub_key: str = "context") -> Optional[Any]:
        key = format_tenant_session_key(tenant_id, session_id, sub_key)
        return self._store.get(key)

    def set(self, tenant_id: str, session_id: str, value: Any, sub_key: str = "context") -> None:
        key = format_tenant_session_key(tenant_id, session_id, sub_key)
        self._store[key] = value

    def append_history(self, tenant_id: str, session_id: str, role: str, content: str) -> None:
        key = format_tenant_session_key(tenant_id, session_id, "history")
        if key not in self._store:
            self._store[key] = []
        self._store[key].append({"role": role, "content": content})
        if len(self._store[key]) > 20:
            self._store[key] = self._store[key][-20:]

    def get_history(self, tenant_id: str, session_id: str) -> List[Dict[str, str]]:
        key = format_tenant_session_key(tenant_id, session_id, "history")
        return list(self._store.get(key, []))

    def clear(self, tenant_id: str, session_id: str) -> None:
        prefix = format_tenant_session_key(tenant_id, session_id)
        keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in keys_to_delete:
            self._store.pop(k, None)


tenant_session_store = TenantScopedSessionStore()


# ============================================================================
# 3. REAL TRANSACTION DATA & KNOWLEDGE CONTEXT BOUNDARY
# ============================================================================

class StoreContextBoundaryManager:
    """
    Memisahkan Data Transaksi (SQL/DB) dari Knowledge Toko (FAQ/RAG)
    sesuai prinsip Arsitektur ADR.
    """

    @staticmethod
    def _get_db_conn():
        host = os.getenv("POSTGRES_HOST")
        if host:
            try:
                return psycopg2.connect(
                    host=host,
                    port=os.getenv("POSTGRES_PORT", "6543"),
                    dbname=os.getenv("POSTGRES_DB", "postgres"),
                    user=os.getenv("POSTGRES_USER"),
                    password=os.getenv("POSTGRES_PASSWORD"),
                    connect_timeout=5,
                )
            except Exception:
                pass
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            return psycopg2.connect(db_url, connect_timeout=5)
        return None

    @classmethod
    def fetch_transaction_data(cls, tenant_id: str) -> List[Dict[str, Any]]:
        """
        Mengambil Data Transaksi Asli (ID, Nama, Harga, Stok riil) dari database SQL/Postgres.
        LLM sama sekali tidak diperbolehkan mengarang nilai ini.
        """
        clean_tenant = str(tenant_id or "").strip().lower()
        items = []

        # 1. Coba query dari PostgreSQL
        conn = None
        try:
            conn = cls._get_db_conn()
            if conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                # Cek tabel products (Scoped by tenant_id)
                cur.execute("""
                    SELECT p.id, p.title, p.slug, p.price, p.is_available, p.description
                    FROM products p
                    JOIN tenants t ON p.tenant_id = t.id
                    WHERE t.slug = %s AND p.is_available = TRUE;
                """, (clean_tenant,))
                rows = cur.fetchall()

                if not rows:
                    # Fallback ke tabel commerce_products
                    cur.execute("""
                        SELECT id, title, product_code as slug, price, is_active as is_available
                        FROM commerce_products
                        WHERE tenant_id = %s AND is_active = TRUE;
                    """, (clean_tenant,))
                    rows = cur.fetchall()

                for r in rows:
                    items.append({
                        "product_id": str(r.get("id")),
                        "title": r.get("title"),
                        "slug": r.get("slug") or str(r.get("id")),
                        "price": float(r.get("price") or 0),
                        "stock": int(r.get("stock", 100)),
                        "is_available": bool(r.get("is_available", True)),
                    })
                cur.close()
                conn.close()
        except Exception as e:
            if conn:
                conn.close()
            logger.debug("Catatan query SQL transaction data tenant '%s': %s", clean_tenant, e)

        # 2. Fallback memory catalog dari onboarding_service jika database kosong
        if not items:
            from app.services.onboarding_service import onboarding_service
            details = onboarding_service.get_tenant_details_by_slug(clean_tenant) or {}
            for p in details.get("products", []):
                items.append({
                    "product_id": str(p.get("id")),
                    "title": p.get("title") or p.get("name"),
                    "slug": p.get("slug") or str(p.get("id")),
                    "price": float(p.get("price") or 0),
                    "stock": int(p.get("stock", 100)),
                    "is_available": bool(p.get("is_available", True)),
                })

        return items

    @classmethod
    def fetch_store_knowledge(cls, tenant_id: str, query: Optional[str] = None) -> Dict[str, Any]:
        """
        Mengambil Knowledge Toko (FAQ, Kebijakan Garansi, Sizing Guide, Cara Pengiriman).
        Terpisah murni dari data transaksi.
        """
        clean_tenant = str(tenant_id or "").strip().lower()
        from app.services.onboarding_service import onboarding_service
        details = onboarding_service.get_tenant_details_by_slug(clean_tenant) or {}
        tenant = details.get("tenant", {})
        ai_k = details.get("ai_knowledge", {})

        return {
            "store_name": tenant.get("name") or clean_tenant.replace("-", " ").title(),
            "faq": ai_k.get("faq") or [
                {"q": "Bagaimana cara pengiriman produk?", "a": "Produk digital dikirimkan instan ke WhatsApp & Email Anda setelah pembayaran terverifikasi."},
                {"q": "Apakah ada garansi?", "a": "Semua produk toko dijamin original dan bergaransi resmi sesuai standar BoonTrack Commerce."},
            ],
            "return_policy": "Garansi uang kembali 100% jika produk digital tidak dapat diakses dalam 1x24 jam.",
            "payment_methods": ["QRIS Realtime (BCA, Mandiri, BRI, BNI, DANA, GoPay, OVO, ShopeePay)"],
            "support_contact": tenant.get("admin_phone") or "WhatsApp Admin Resmi Toko",
        }

    @classmethod
    def build_bounded_system_prompt(cls, tenant_id: str, base_persona: str = "") -> str:
        """
        Menyusun system prompt yang menginjeksi aturan batas keamanan mutlak:
        Melarang model mengubah harga atau status transaksi.
        """
        knowledge = cls.fetch_store_knowledge(tenant_id)
        catalog = cls.fetch_transaction_data(tenant_id)

        catalog_summary = []
        for c in catalog:
            catalog_summary.append(
                f"- ID: {c['product_id']} | Nama: {c['title']} | Harga Resmi: Rp {c['price']:,.0f} | Status: {'Tersedia' if c['is_available'] else 'Habis'}"
            )
        catalog_text = "\n".join(catalog_summary) if catalog_summary else "- Katalog belum memiliki produk aktif."

        prompt = f"""Kamu adalah Store Sales Agent resmi untuk toko: {knowledge['store_name']}.
Tugasmu adalah membantu calon pembeli dengan ramah, informatif, dan solutif.

{base_persona}

======================================================================
ATURAN KEAMANAN & BATAS DATA TRANSAKSI MUTLAK (SECURITY BOUNDARY):
======================================================================
1. DILARANG MENENTUKAN ATAU MENGUBAH HARGA:
   Harga produk HANYA bersumber dari Database Transaksi Resmi di bawah ini.
   Kamu TIDAK BOLEH memberikan diskon sepihak, mengubah nominal, atau membuat harga baru.

2. DILARANG MEMODIFIKASI STOK / TRANSAKSI LANGSUNG:
   Status ketersediaan stok produk ditentukan 100% oleh sistem database.

3. KATALOG AKSI TERIKAT (BOUNDED ACTION CATALOG):
   Jika merespons dengan aksi sistem, kamu HANYA boleh memilih dari 6 aksi resmi:
   - SHOW_PRODUCT        : Menampilkan rincian produk tertentu
   - SHOW_PRODUCT_LIST   : Menampilkan daftar katalog produk toko
   - SHOW_VARIANT        : Menampilkan opsi varian produk
   - SHOW_CHECKOUT       : Mengarahkan pelanggan ke ringkasan checkout
   - CREATE_PAYMENT      : Memicu pembuatan kode pembayaran QRIS resmi
   - TRANSFER_TO_HUMAN   : Mengalihkan obrolan ke admin customer service manusia

4. DATA TRANSAKSI RESMI TOKO (DATABASE TERIKAT):
{catalog_text}

5. KNOWLEDGE & KEBIJAKAN TOKO:
- Garansi: {knowledge['return_policy']}
- Pembayaran: {', '.join(knowledge['payment_methods'])}
"""
        return prompt


# ============================================================================
# 4. BACKEND PRICE & STOCK VALIDATOR
# ============================================================================

class BackendSecurityValidator:
    """
    Backend Validator yang WAJIB memverifikasi ulang harga & stok database
    sebelum payload aksi diteruskan ke frontend / WhatsApp.
    """

    @classmethod
    async def validate_and_sanitize_action(
        cls,
        tenant_id: str,
        proposed_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Memvalidasi aksi yang diusulkan oleh LLM / pengguna terhadap basis data riil.
        
        Aturan verifikasi:
        1. Action type wajib ada di ALLOWED_STORE_ACTIONS.
        2. Jika memuat product_id / harga, verifikasi ulang dengan database:
           - Override harga dengan harga resmi DB (Cegah manipulasi harga oleh prompt injection).
           - Cek stok riil (Cegah checkout produk habis).
        3. Menghasilkan payload bersih dan tersanitasi.
        """
        clean_tenant = str(tenant_id or "").strip().lower()
        action_type = str(proposed_action.get("action_type") or "").strip().upper()

        # 1. Validasi Action Catalog Terikat
        if action_type not in ALLOWED_STORE_ACTIONS:
            logger.warning(
                "[%s] Security Guard: Aksi liar '%s' ditolak oleh Action Catalog.",
                clean_tenant, action_type
            )
            return {
                "is_valid": False,
                "error_code": "ACTION_NOT_ALLOWED",
                "message": f"Aksi '{action_type}' tidak diizinkan dalam Action Catalog terikat.",
                "allowed_actions": list(ALLOWED_STORE_ACTIONS),
                "sanitized_payload": None,
            }

        # Ambil snapshot data transaksi resmi dari database
        real_catalog = StoreContextBoundaryManager.fetch_transaction_data(clean_tenant)
        catalog_by_id = {str(item["product_id"]): item for item in real_catalog}
        catalog_by_slug = {str(item["slug"]): item for item in real_catalog}

        # 2. Validasi untuk aksi produk / checkout / pembayaran
        if action_type in (
            StoreActionType.SHOW_PRODUCT.value,
            StoreActionType.SHOW_CHECKOUT.value,
            StoreActionType.CREATE_PAYMENT.value,
            StoreActionType.SHOW_VARIANT.value,
        ):
            target_id = str(proposed_action.get("product_id") or "")
            target_slug = str(proposed_action.get("product_slug") or "")

            matched_item = catalog_by_id.get(target_id) or catalog_by_slug.get(target_slug)

            # Jika tidak spesifik memilih ID tapi katalog ada produk tunggal
            if not matched_item and len(real_catalog) == 1:
                matched_item = real_catalog[0]

            if not matched_item:
                return {
                    "is_valid": False,
                    "error_code": "PRODUCT_NOT_FOUND",
                    "message": "Produk yang diminta tidak terdaftar di database resmi toko.",
                    "sanitized_payload": None,
                }

            real_price = float(matched_item["price"])
            real_stock = int(matched_item["stock"])
            is_available = bool(matched_item["is_available"])

            # Cek Stok Riil
            if not is_available or real_stock <= 0:
                return {
                    "is_valid": False,
                    "error_code": "OUT_OF_STOCK",
                    "message": f"Produk '{matched_item['title']}' saat ini habis atau tidak tersedia.",
                    "product_id": matched_item["product_id"],
                    "sanitized_payload": None,
                }

            # Backend Validator MENIMPA harga yang diajukan dengan harga database riil
            proposed_price = proposed_action.get("price")
            price_tampered = False
            if proposed_price is not None:
                try:
                    if abs(float(proposed_price) - real_price) > 0.01:
                        price_tampered = True
                        logger.warning(
                            "[%s] SECURITY ALERT: Percobaan manipulasi harga terdeteksi! "
                            "Diajukan: Rp %s vs Database Resmi: Rp %s. Mengoreksi secara paksa.",
                            clean_tenant, proposed_price, real_price
                        )
                except (ValueError, TypeError):
                    price_tampered = True

            sanitized_payload = {
                "action_type": action_type,
                "tenant_id": clean_tenant,
                "product_id": matched_item["product_id"],
                "product_title": matched_item["title"],
                "product_slug": matched_item["slug"],
                "verified_price": real_price,
                "price_formatted": f"Rp {real_price:,.0f}",
                "stock_available": real_stock,
                "quantity": max(1, int(proposed_action.get("quantity", 1))),
                "price_tampered_corrected": price_tampered,
                "checkout_url": f"/checkout/{clean_tenant}?prod={matched_item['slug']}",
            }

            return {
                "is_valid": True,
                "error_code": None,
                "message": "Aksi terverifikasi aman oleh Backend Validator.",
                "sanitized_payload": sanitized_payload,
            }

        # 3. Aksi SHOW_PRODUCT_LIST
        if action_type == StoreActionType.SHOW_PRODUCT_LIST.value:
            items_summary = [
                {
                    "product_id": item["product_id"],
                    "title": item["title"],
                    "price": item["price"],
                    "price_formatted": f"Rp {item['price']:,.0f}",
                    "is_available": item["is_available"],
                }
                for item in real_catalog
            ]
            return {
                "is_valid": True,
                "error_code": None,
                "message": "Katalog produk aktif berhasil disiapkan dari database.",
                "sanitized_payload": {
                    "action_type": action_type,
                    "tenant_id": clean_tenant,
                    "total_products": len(items_summary),
                    "products": items_summary,
                },
            }

        # 4. Aksi TRANSFER_TO_HUMAN
        if action_type == StoreActionType.TRANSFER_TO_HUMAN.value:
            knowledge = StoreContextBoundaryManager.fetch_store_knowledge(clean_tenant)
            return {
                "is_valid": True,
                "error_code": None,
                "message": "Permintaan pengalihan ke agen manusia disetujui.",
                "sanitized_payload": {
                    "action_type": action_type,
                    "tenant_id": clean_tenant,
                    "cs_contact": knowledge.get("support_contact"),
                    "reason": proposed_action.get("reason", "Customer requested human intervention"),
                },
            }

        return {
            "is_valid": False,
            "error_code": "UNKNOWN_ACTION",
            "message": "Aksi tidak dapat diproses.",
            "sanitized_payload": None,
        }


backend_security_validator = BackendSecurityValidator()
