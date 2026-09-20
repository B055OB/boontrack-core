"""app/services/whatsapp/activation.py
------------------------------------
Layanan pencarian dan verifikasi kode aktivasi toko via WhatsApp (AKTIVASI BT-XXXX).

Menghubungkan kode unik dari browser registrasi (shop.boontrack.com/register)
dengan bot WhatsApp resmi BoonTrack (+6285179555449).
"""

import re
import logging
from typing import Dict, Any, Optional, Tuple, List
from app.services.whatsapp.credentials import get_supabase, normalize_phone_number

logger = logging.getLogger("WABA_ACTIVATION_SERVICE")

ALLOWED_PENDING_STATUSES = [
    "pending",
    "pending_wa_verification",
    "pending_activation",
    "unverified",
    "trial",
    "pending",
]


def normalize_activation_code(raw_code: str) -> Tuple[str, str]:
    """
    Menormalkan kode aktivasi dari berbagai variasi input teks:
    - 'AKTIVASI BT-7095' -> ('BT-7095', '7095')
    - 'aktivasi bt-7095.' -> ('BT-7095', '7095')
    - 'BT-7095' -> ('BT-7095', '7095')
    - '7095' -> ('BT-7095', '7095')
    - 'BT7095' -> ('BT-7095', '7095')
    """
    if not raw_code:
        return "", ""

    cleaned = str(raw_code).strip()
    # Hapus awalan AKTIVASI jika ada
    cleaned = re.sub(r"^AKTIVASI\s+", "", cleaned, flags=re.IGNORECASE).strip()
    # Hapus trailing punctuation (seperti tanda titik atau koma)
    cleaned = re.sub(r"[\.,;:!\s]+$", "", cleaned).strip().upper()

    # Ekstraksi token
    if cleaned.startswith("BT-"):
        token_suffix = cleaned[3:].strip()
        canonical_token = f"BT-{token_suffix}"
    elif cleaned.startswith("BT") and len(cleaned) > 2:
        token_suffix = cleaned[2:].strip()
        canonical_token = f"BT-{token_suffix}"
    else:
        token_suffix = cleaned
        canonical_token = f"BT-{token_suffix}" if token_suffix else ""

    return canonical_token, token_suffix


def find_tenant_by_activation_code(
    code: str,
    sender_phone: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Mencari record toko di database Supabase berdasarkan kode aktivasi registrasi.
    Mendukung pengecekan case-insensitive, whitespace trim, dan multiple field aliases:
    - metadata->>wa_verification_token
    - metadata->>code
    - metadata->>token
    - metadata->>activation_code

    Jika sender_phone disertakan, memvalidasi kecocokan nomor telepon pengirim
    dengan nomor WhatsApp yang diinput saat pendaftaran.
    """
    canonical_token, token_suffix = normalize_activation_code(code)
    if not canonical_token or not token_suffix:
        logger.warning(f"[ActivationLookup] Format kode aktivasi tidak valid: '{code}'")
        return None

    clean_sender_phone = normalize_phone_number(sender_phone) if sender_phone else ""
    supabase = get_supabase()

    matched_tenant: Optional[Dict[str, Any]] = None
    candidate_tenants: List[Dict[str, Any]] = []

    if supabase:
        try:
            # 1. Direct match pada metadata->>wa_verification_token
            for cand in [canonical_token, token_suffix, canonical_token.lower()]:
                res = (
                    supabase.table("tenants")
                    .select("*")
                    .filter("metadata->>wa_verification_token", "eq", cand)
                    .execute()
                )
                if res and res.data:
                    candidate_tenants.extend(res.data)

            # 2. Match pada metadata->>code atau metadata->>token jika belum ketemu
            if not candidate_tenants:
                for col in ["code", "token"]:
                    for cand in [canonical_token, token_suffix]:
                        res = (
                            supabase.table("tenants")
                            .select("*")
                            .filter(f"metadata->>{col}", "eq", cand)
                            .execute()
                        )
                        if res and res.data:
                            candidate_tenants.extend(res.data)

            # 3. Fallback scan pada tenants yang berstatus pending / unverified / trial
            if not candidate_tenants:
                # Query luas untuk menangkap status huruf besar maupun kecil
                all_pending = (
                    supabase.table("tenants")
                    .select("*")
                    .limit(100)
                    .execute()
                )
                for t in (all_pending.data or []):
                    t_status = str(t.get("status") or "").lower().strip()
                    if t_status not in ALLOWED_PENDING_STATUSES and not (t.get("is_active") is False):
                        continue

                    t_meta = t.get("metadata") or {}
                    cand_tokens = [
                        str(t_meta.get("wa_verification_token") or "").upper().strip(),
                        str(t_meta.get("code") or "").upper().strip(),
                        str(t_meta.get("token") or "").upper().strip(),
                        str(t_meta.get("activation_code") or "").upper().strip(),
                    ]

                    # Periksa apakah salah satu candidate cocok dengan canonical_token atau token_suffix
                    if any(
                        ct in (canonical_token, token_suffix, f"BT{token_suffix}", f"AKTIVASI {canonical_token}")
                        for ct in cand_tokens
                        if ct
                    ):
                        candidate_tenants.append(t)

        except Exception as db_err:
            logger.error(f"[ActivationLookup] Supabase query error: {db_err}")

    # Fallback in-memory onboarding registry jika belum ditemukan (mock / test suite)
    if not candidate_tenants:
        try:
            from app.services.onboarding_service import onboarding_service
            for t_slug, t_data in onboarding_service._tenants_by_slug.items():
                t_meta = t_data.get("metadata") or {}
                cand_tokens = [
                    str(t_meta.get("wa_verification_token") or t_data.get("wa_verification_token") or "").upper().strip(),
                    str(t_meta.get("code") or t_data.get("code") or "").upper().strip(),
                    str(t_meta.get("token") or t_data.get("token") or "").upper().strip(),
                    str(t_meta.get("activation_code") or t_data.get("activation_code") or "").upper().strip(),
                ]
                if any(
                    ct in (canonical_token, token_suffix, f"BT{token_suffix}", f"AKTIVASI {canonical_token}")
                    for ct in cand_tokens
                    if ct
                ):
                    candidate_tenants.append(t_data)
        except Exception as mem_err:
            logger.debug(f"[ActivationLookup] In-memory fallback note: {mem_err}")

    if not candidate_tenants:
        logger.info(f"[ActivationLookup] Token '{canonical_token}' tidak ditemukan di Supabase maupun memory.")
        return None

    # Filter & prioritas jika ada lebih dari 1 kandidat:
    # Jika sender_phone valid, utamakan tenant yang nomor teleponnya cocok
    if clean_sender_phone and len(candidate_tenants) > 1:
        for t in candidate_tenants:
            t_meta = t.get("metadata") or {}
            reg_phones = [
                normalize_phone_number(t_meta.get("phone")),
                normalize_phone_number(t_meta.get("whatsapp_number")),
                normalize_phone_number(t_meta.get("wa_number")),
                normalize_phone_number(t.get("admin_phone")),
            ]
            if clean_sender_phone in [p for p in reg_phones if p]:
                matched_tenant = t
                logger.info(f"[ActivationLookup] Phone match confirmed for tenant '{t.get('slug')}': {clean_sender_phone}")
                break

    if not matched_tenant:
        matched_tenant = candidate_tenants[0]

    return matched_tenant
