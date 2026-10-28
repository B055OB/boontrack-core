"""app/services/referral_attribution_service.py
Core & Inbox Referral Contract ([r=CODE]) & Authoritative Attribution Service.

Responsibilities:
1. Parse and isolate the referral marker `[r=KODE_RESELLER]` before intent classification.
2. Safe syntax validation (/^[a-zA-Z0-9_-]{3,64}$/).
3. Authoritative verification against Core reseller/affiliate records (reject invalid/inactive safely).
4. Persist validated attribution into session/lead context strictly bound to tenant (First Valid Referral Wins).
5. Forward attribution context snapshot to the order creation boundary (orders.metadata).
"""

import re
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("REFERRAL_ATTRIBUTION_SERVICE")

# Safe regex pattern for [r=CODE] marker extraction
REFERRAL_MARKER_REGEX = re.compile(r"\[r=([a-zA-Z0-9_-]+)\]", re.IGNORECASE)
MALFORMED_MARKER_REGEX = re.compile(r"\[r=[^\]]*\]", re.IGNORECASE)

# Syntax constraint: 3-64 alphanumeric characters, underscores, or hyphens
CODE_SYNTAX_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")

# In-memory authoritative registry for fast lookup & offline/test isolation
# Format: {tenant_id: {code_upper: {data}}}
_DEFAULT_AUTHORITATIVE_REGISTRY: Dict[str, Dict[str, Dict[str, Any]]] = {
    "onlineboost": {
        "RESELLER_ALDI": {
            "id": "aff_aldi_001",
            "code": "RESELLER_ALDI",
            "name": "Aldi Reseller",
            "status": "ACTIVE",
            "tenant_id": "onlineboost",
            "commission_rate": 0.20,
        },
        "KODE_RESELLER": {
            "id": "aff_reseller_002",
            "code": "KODE_RESELLER",
            "name": "Mitra Reseller 02",
            "status": "ACTIVE",
            "tenant_id": "onlineboost",
            "commission_rate": 0.20,
        },
        "CREATOR_SCALE": {
            "id": "aff_creator_003",
            "code": "CREATOR_SCALE",
            "name": "Creator Scale",
            "status": "ACTIVE",
            "tenant_id": "onlineboost",
            "commission_rate": 0.25,
        },
        "INACTIVE_RESELLER": {
            "id": "aff_inactive_004",
            "code": "INACTIVE_RESELLER",
            "name": "Inactive Reseller",
            "status": "SUSPENDED",
            "tenant_id": "onlineboost",
            "commission_rate": 0.20,
        },
    }
}

_AUTHORITATIVE_REFERRAL_REGISTRY: Dict[str, Dict[str, Dict[str, Any]]] = {
    tenant: dict(codes) for tenant, codes in _DEFAULT_AUTHORITATIVE_REGISTRY.items()
}


def is_valid_referral_syntax(code: Optional[str]) -> bool:
    """Validates referral code syntax: 3-64 alphanumeric characters, hyphens, underscores."""
    if not code or not isinstance(code, str):
        return False
    return bool(CODE_SYNTAX_REGEX.match(code.strip()))


def extract_referral_marker(text: str) -> Tuple[str, Optional[str]]:
    """
    Ekstrak marker [r=KODE_RESELLER] dari teks sebelum intent classification.
    Mengembalikan: (clean_text, referral_code)

    Aturan:
    - Jika syntax code valid (/^[a-zA-Z0-9_-]{3,64}$/), code dikembalikan apa adanya (stripped).
    - Jika marker malformed (karakter terlarang, spasi, terlalu pendek/panjang), code = None.
    - Marker [r=...] selalu dibersihkan dari teks pesan sehingga tidak merusak klasifikasi regex.
    """
    if not text or not isinstance(text, str):
        return "", None

    raw = text.strip()
    match = REFERRAL_MARKER_REGEX.search(raw)
    extracted_code = None

    if match:
        candidate = match.group(1).strip()
        if is_valid_referral_syntax(candidate):
            extracted_code = candidate
        clean_text = REFERRAL_MARKER_REGEX.sub("", raw)
    elif MALFORMED_MARKER_REGEX.search(raw):
        clean_text = MALFORMED_MARKER_REGEX.sub("", raw)
    else:
        clean_text = raw

    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text, extracted_code


def register_authoritative_referral(
    code: str,
    tenant_id: str = "onlineboost",
    name: str = "Reseller",
    status: str = "ACTIVE",
    affiliate_id: Optional[str] = None,
    commission_rate: float = 0.20,
) -> None:
    """Helper untuk registrasi kode reseller ke in-memory registry (berguna untuk testing)."""
    clean_code = code.strip().upper()
    t_dict = _AUTHORITATIVE_REFERRAL_REGISTRY.setdefault(tenant_id, {})
    t_dict[clean_code] = {
        "id": affiliate_id or f"aff_{clean_code.lower()}",
        "code": clean_code,
        "name": name,
        "status": status.upper(),
        "tenant_id": tenant_id,
        "commission_rate": commission_rate,
    }


def reset_referral_registry() -> None:
    """Reset in-memory authoritative registry to default seed."""
    global _AUTHORITATIVE_REFERRAL_REGISTRY
    _AUTHORITATIVE_REFERRAL_REGISTRY = {
        tenant: dict(codes) for tenant, codes in _DEFAULT_AUTHORITATIVE_REGISTRY.items()
    }


def validate_referral_code(
    code: Optional[str],
    tenant_id: str = "onlineboost",
) -> Optional[Dict[str, Any]]:
    """
    Validasi otoritatif referral code terhadap database/registry Core.
    1. Reject syntax invalid.
    2. Isolasi tenant: hanya cocok untuk tenant_id yang sesuai.
    3. Cek in-memory registry (authoritative cache).
    4. Cek PostgreSQL (tabel affiliates & partners).
    5. Cek Supabase (jika terpasang).
    6. Reject jika status != 'ACTIVE'.
    Mengembalikan None secara aman tanpa exception jika kode ditolak.
    """
    if not code or not is_valid_referral_syntax(code):
        return None

    clean_code = code.strip()
    code_upper = clean_code.upper()

    # 1. Cek in-memory authoritative registry
    t_registry = _AUTHORITATIVE_REFERRAL_REGISTRY.get(tenant_id, {})
    if code_upper in t_registry:
        item = t_registry[code_upper]
        if item.get("status") == "ACTIVE":
            return {
                "code": item["code"],
                "affiliate_id": str(item["id"]),
                "name": item.get("name"),
                "tenant_id": tenant_id,
                "commission_rate": item.get("commission_rate", 0.20),
                "validated_at": datetime.now(timezone.utc).isoformat(),
                "source": "memory_registry",
            }
        else:
            logger.info(
                f"[Attribution] Referral '{clean_code}' is {item.get('status')} for tenant '{tenant_id}'. Rejected."
            )
            return None

    # 2. Cek database PostgreSQL (jika koneksi tersedia)
    try:
        from app.core.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, referral_code, status, tenant_id, commission_rate
                FROM affiliates
                WHERE (tenant_id = %s OR tenant_id = 'onlineboost')
                  AND (referral_code ILIKE %s OR id::text = %s)
                  AND status = 'ACTIVE'
                LIMIT 1;
                """,
                (tenant_id, clean_code, clean_code)
            )
            row = cur.fetchone()
            if row:
                conn.close()
                return {
                    "code": row[2] or clean_code,
                    "affiliate_id": str(row[0]),
                    "name": row[1],
                    "tenant_id": tenant_id,
                    "commission_rate": float(row[5]) if row[5] is not None else 0.20,
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                    "source": "postgres_affiliates",
                }

            # Cek tabel partners
            cur.execute(
                """
                SELECT id, name, ref_code, status
                FROM partners
                WHERE ref_code ILIKE %s AND status = 'ACTIVE'
                LIMIT 1;
                """,
                (clean_code,)
            )
            p_row = cur.fetchone()
            if p_row:
                conn.close()
                return {
                    "code": p_row[2] or clean_code,
                    "affiliate_id": str(p_row[0]),
                    "name": p_row[1],
                    "tenant_id": tenant_id,
                    "commission_rate": 0.20,
                    "validated_at": datetime.now(timezone.utc).isoformat(),
                    "source": "postgres_partners",
                }
        conn.close()
    except Exception as db_err:
        logger.debug(f"[Attribution] Database lookup note: {db_err}")

    # 3. Cek Supabase (jika terpasang)
    try:
        from app.services.whatsapp_service import get_supabase
        sb = get_supabase()
        if sb:
            res = (
                sb.table("affiliates")
                .select("id, name, referral_code, status, tenant_id")
                .ilike("referral_code", clean_code)
                .eq("status", "ACTIVE")
                .execute()
            )
            if res.data:
                row = res.data[0]
                row_tenant = row.get("tenant_id") or "onlineboost"
                if row_tenant == tenant_id or row_tenant == "onlineboost":
                    return {
                        "code": row.get("referral_code") or clean_code,
                        "affiliate_id": str(row.get("id")),
                        "name": row.get("name"),
                        "tenant_id": tenant_id,
                        "commission_rate": 0.20,
                        "validated_at": datetime.now(timezone.utc).isoformat(),
                        "source": "supabase_affiliates",
                    }
    except Exception as sb_err:
        logger.debug(f"[Attribution] Supabase lookup note: {sb_err}")

    logger.info(
        f"[Attribution] Referral '{clean_code}' unknown or inactive for tenant '{tenant_id}'. Rejected safely."
    )
    return None


def apply_referral_attribution_to_session(
    session: Dict[str, Any],
    raw_code: Optional[str],
    tenant_id: str = "onlineboost",
) -> Tuple[bool, Optional[str]]:
    """
    Terapkan atribusi referral ke sesi percakapan dengan prinsip:
    - First Valid Referral Wins: Jika sesi sudah memiliki referral code valid yang terkunci,
      kode baru TIDAK menimpa kode lama.
    - Safe rejection: Kode tidak valid/tidak aktif/malformed ditolak tanpa mengganggu alur percakapan.
    - Tenant Isolation: Terikat pada tenant yang ditentukan.

    Returns:
    (is_applied, active_code)
    """
    if not isinstance(session, dict):
        return False, None

    # Cek apakah sesi sudah punya referral valid yang terkunci
    existing_code = session.get("referral_code")
    existing_attr = session.get("attribution")

    if existing_code and existing_attr and existing_attr.get("validated"):
        # First Valid Referral Wins!
        if raw_code and raw_code.strip().upper() != str(existing_code).strip().upper():
            logger.info(
                f"[Attribution] First Valid Referral Wins: Existing valid referral '{existing_code}' "
                f"preserved. Incoming code '{raw_code}' ignored."
            )
        return False, existing_code

    if not raw_code:
        return False, existing_code

    # Validasi kode baru terhadap Core authoritative records
    validated = validate_referral_code(raw_code, tenant_id=tenant_id)
    if validated:
        clean_code = validated["code"]
        session["referral_code"] = clean_code
        session["attribution"] = {
            "code": clean_code,
            "affiliate_id": validated.get("affiliate_id"),
            "name": validated.get("name"),
            "tenant_id": tenant_id,
            "source": "waba_inbound_cta",
            "validated": True,
            "locked_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            f"[Attribution] Valid referral '{clean_code}' locked into session for tenant '{tenant_id}'."
        )
        return True, clean_code

    # Kode ditolak secara aman
    return False, None


def get_attribution_snapshot_for_order(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ambil snapshot atribusi untuk diteruskan ke boundary pembuatan order.
    """
    if not session or not isinstance(session, dict):
        return {}
    code = session.get("referral_code")
    attr = session.get("attribution")
    if code and attr and attr.get("validated"):
        return {
            "referral_code": code,
            "attribution": dict(attr),
        }
    return {}
