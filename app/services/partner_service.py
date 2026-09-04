import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

try:
    from jose import jwt
except ImportError:
    try:
        import jwt
    except ImportError:
        jwt = None

from supabase import create_client, Client

logger = logging.getLogger("PARTNER_SERVICE")

# Configuration & Constants
JWT_SECRET = os.getenv("JWT_SECRET", "boontrack-secret-key-production-3000")
JWT_ALGORITHM = "HS256"

RESERVED_SLUGS = {
    "ADMIN", "ROOT", "API", "DASHBOARD", "SHOP", "SUPPORT",
    "HELP", "OFFICIAL", "OWNER", "BILLING", "SYSTEM"
}

ALLOWED_BANKS = {
    "BCA", "MANDIRI", "BRI", "BNI", "BSI", "CIMB", "GOPAY", "DANA", "OVO"
}

MINIMUM_PAYOUT_AMOUNT = 50000

SLUG_REGEX = re.compile(r"^[A-Z0-9]{3,20}$")

# Supabase Initialization
supabase_url = os.getenv("SUPABASE_URL", "https://mpluzajlzpregmjwpjqr.supabase.co")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")
supabase: Client = create_client(supabase_url, supabase_key)


def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode signed JWT token with multi-library and HMAC fallback support."""
    clean_token = token.replace("Bearer ", "").strip()
    if jwt is not None:
        try:
            return jwt.decode(clean_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except Exception as e:
            logger.warning(f"JWT library decode failed: {e}")

    # Manual HMAC-SHA256 decode fallback
    try:
        import base64
        import json
        import hmac
        import hashlib

        parts = clean_token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, sig_b64 = parts

        def b64_decode(data: str) -> bytes:
            padding = 4 - (len(data) % 4)
            if padding and padding != 4:
                data += "=" * padding
            return base64.urlsafe_b64decode(data.encode())

        expected_sig = hmac.new(
            JWT_SECRET.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
        ).digest()
        actual_sig = b64_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload_bytes = b64_decode(body_b64)
        return json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        logger.error(f"Fallback JWT decode error: {e}")
        return None


class PartnerService:
    """
    Service Layer untuk Manajemen Mitra Whitelist (AM & Affiliate),
    Rekening Bank Payout, dan Custom Referral Slug.
    """

    def __init__(self):
        # In-memory storage cache & fallback
        self._memory_partners: Dict[str, Dict[str, Any]] = {}
        self._memory_bank_accounts: Dict[str, Dict[str, Any]] = {}
        self._memory_payouts: Dict[str, Dict[str, Any]] = {}

    # =========================================================================
    # 1. RESERVED SLUGS & VALIDATION
    # =========================================================================

    def validate_referral_slug_detailed(
        self, slug: str, exclude_partner_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Validasi lengkap slug kustom referral:
        1. Format Regex: ^[A-Z0-9]{3,20}$
        2. Blacklist kata sistem: ADMIN, ROOT, API, DASHBOARD, SHOP, SUPPORT, dll.
        3. Keunikan di database secara case-insensitive.
        """
        if not slug or not isinstance(slug, str):
            return False, "Slug referral tidak boleh kosong"

        normalized = slug.strip().upper()

        # 1. Cek Regex: 3-20 karakter alfanumerik kapital
        if not SLUG_REGEX.match(normalized):
            return (
                False,
                "Format slug tidak valid. Wajib 3-20 karakter alfanumerik (huruf kapital dan angka saja, tanpa spasi/simbol).",
            )

        # 2. Cek Blacklist kata reserved sistem
        if normalized in RESERVED_SLUGS:
            return (
                False,
                f"Slug '{normalized}' merupakan reserved keyword sistem dan tidak dapat digunakan.",
            )

        # 3. Cek Keunikan di database (case-insensitive)
        is_taken = self._is_slug_taken(normalized, exclude_partner_id=exclude_partner_id)
        if is_taken:
            return False, f"Slug referral '{normalized}' sudah digunakan oleh mitra lain."

        return True, "Slug referral valid dan tersedia."

    def validate_referral_slug(self, slug: str) -> bool:
        """
        Fungsi validator standar: mengembalikan boolean True jika slug valid dan tersedia.
        """
        is_valid, _ = self.validate_referral_slug_detailed(slug)
        return is_valid

    def _is_slug_taken(self, normalized_slug: str, exclude_partner_id: Optional[str] = None) -> bool:
        """Pengecekan keunikan slug di memory dan Supabase database."""
        # Cek memory store
        for pid, p in self._memory_partners.items():
            if exclude_partner_id and pid == exclude_partner_id:
                continue
            if p.get("ref_code", "").strip().upper() == normalized_slug:
                return True

        # Cek Supabase database (jika tersedia)
        try:
            res = (
                supabase.table("partners")
                .select("id, ref_code")
                .ilike("ref_code", normalized_slug)
                .execute()
            )
            if res.data:
                for row in res.data:
                    if exclude_partner_id and row["id"] == exclude_partner_id:
                        continue
                    return True
        except Exception:
            # Fallback jika tabel partners belum ada di remote, cek affiliates
            try:
                res_aff = (
                    supabase.table("affiliates")
                    .select("id, affiliate_code")
                    .ilike("affiliate_code", normalized_slug)
                    .execute()
                )
                if res_aff.data:
                    for row in res_aff.data:
                        if exclude_partner_id and row["id"] == exclude_partner_id:
                            continue
                        return True
            except Exception:
                pass

        return False

    def check_slug_availability(self, slug: str) -> Dict[str, Any]:
        """Cek ketersediaan slug kustom."""
        normalized = slug.strip().upper() if slug else ""
        is_valid, reason = self.validate_referral_slug_detailed(normalized)
        return {
            "slug": normalized,
            "available": is_valid,
            "reason": None if is_valid else reason,
        }

    # =========================================================================
    # 2. PARTNER / AFFILIATE CLAIM & MANAGEMENT
    # =========================================================================

    def get_partner_by_id(self, partner_id: str) -> Optional[Dict[str, Any]]:
        """Ambil data mitra berdasarkan ID."""
        if partner_id in self._memory_partners:
            return self._memory_partners[partner_id]

        try:
            res = supabase.table("partners").select("*").eq("id", partner_id).execute()
            if res.data:
                partner = res.data[0]
                self._memory_partners[partner_id] = partner
                return partner
        except Exception:
            try:
                res_aff = supabase.table("affiliates").select("*").eq("id", partner_id).execute()
                if res_aff.data:
                    aff = res_aff.data[0]
                    partner = {
                        "id": aff["id"],
                        "name": aff.get("name", "Mitra"),
                        "phone": aff.get("phone", ""),
                        "email": aff.get("email"),
                        "role": aff.get("role", "AFFILIATE"),
                        "ref_code": aff.get("affiliate_code") or aff.get("ref_code", ""),
                        "is_ref_customized": aff.get("is_ref_customized", False),
                        "registered_by_am_id": aff.get("registered_by_am_id"),
                        "status": aff.get("status", "ACTIVE"),
                        "created_at": aff.get("created_at", datetime.now(timezone.utc).isoformat()),
                    }
                    self._memory_partners[partner_id] = partner
                    return partner
            except Exception:
                pass

        return None

    def get_partner_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Ambil data mitra berdasarkan nomor telepon."""
        for p in self._memory_partners.values():
            if p.get("phone") == phone:
                return p

        try:
            res = supabase.table("partners").select("*").eq("phone", phone).execute()
            if res.data:
                partner = res.data[0]
                self._memory_partners[partner["id"]] = partner
                return partner
        except Exception:
            pass

        return None

    def claim_custom_referral_slug(self, partner_id: str, slug: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Klaim dan kunci slug custom untuk user yang sedang login.
        Aturan:
        - Jika is_ref_customized bernilai True: Gagal (Kunci perubahan setelah 1x klaim).
        - Validasi regex, blacklist, dan keunikan case-insensitive.
        - Update ref_code dan set is_ref_customized = True.
        """
        partner = self.get_partner_by_id(partner_id)
        if not partner:
            return False, "Data mitra tidak ditemukan", {}

        # 1. Pengecekan Kunci 1x Klaim
        if partner.get("is_ref_customized", False):
            return (
                False,
                "Kode referral kustom hanya dapat diklaim 1 kali dan sudah dikunci secara permanen.",
                partner,
            )

        normalized = slug.strip().upper() if slug else ""

        # 2. Validasi slug
        is_valid, reason = self.validate_referral_slug_detailed(
            normalized, exclude_partner_id=partner_id
        )
        if not is_valid:
            return False, reason, partner

        # 3. Update data mitra
        now_iso = datetime.now(timezone.utc).isoformat()
        partner["ref_code"] = normalized
        partner["is_ref_customized"] = True
        partner["updated_at"] = now_iso
        self._memory_partners[partner_id] = partner

        # Update di Supabase jika terhubung
        try:
            supabase.table("partners").update({
                "ref_code": normalized,
                "is_ref_customized": True,
                "updated_at": now_iso,
            }).eq("id", partner_id).execute()
        except Exception as e:
            logger.warning(f"Supabase update partner ref_code failed, memory store updated: {e}")

        return True, "Kode referral custom berhasil diklaim dan dikunci.", partner

    # =========================================================================
    # 3. BANK ACCOUNT MANAGEMENT
    # =========================================================================

    def upsert_bank_account(
        self,
        partner_id: str,
        bank_name: str,
        account_number: str,
        account_holder_name: str,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Simpan atau perbarui rekening bank mitra.
        Validasi bank_name terhadap AllowedBank.
        """
        partner = self.get_partner_by_id(partner_id)
        if not partner:
            return False, "Data mitra tidak ditemukan", {}

        norm_bank = bank_name.strip().upper()
        if norm_bank not in ALLOWED_BANKS:
            allowed_str = ", ".join(sorted(ALLOWED_BANKS))
            return (
                False,
                f"Nama bank / e-wallet '{bank_name}' tidak didukung. Bank yang didukung: {allowed_str}",
                {},
            )

        if not account_number or len(account_number.strip()) < 5:
            return False, "Nomor rekening / nomor e-wallet tidak valid.", {}

        if not account_holder_name or len(account_holder_name.strip()) < 2:
            return False, "Nama pemilik rekening wajib diisi.", {}

        # Cari rekening bank yang sudah ada untuk partner ini
        existing_id = None
        for bid, ba in self._memory_bank_accounts.items():
            if ba.get("partner_id") == partner_id:
                existing_id = bid
                break

        now_iso = datetime.now(timezone.utc).isoformat()
        bank_account_id = existing_id or str(uuid.uuid4())

        record = {
            "id": bank_account_id,
            "partner_id": partner_id,
            "bank_name": norm_bank,
            "account_number": account_number.strip(),
            "account_holder_name": account_holder_name.strip(),
            "is_verified": False,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        self._memory_bank_accounts[bank_account_id] = record

        # Simpan ke Supabase jika tersedia
        try:
            supabase.table("partner_bank_accounts").upsert(record).execute()
        except Exception as e:
            logger.warning(f"Supabase upsert bank account fallback to memory: {e}")

        return True, "Data rekening bank mitra berhasil disimpan.", record

    def get_bank_account_by_partner(self, partner_id: str) -> Optional[Dict[str, Any]]:
        """Dapatkan data rekening bank aktif milik mitra."""
        for ba in self._memory_bank_accounts.values():
            if ba.get("partner_id") == partner_id:
                return ba

        try:
            res = (
                supabase.table("partner_bank_accounts")
                .select("*")
                .eq("partner_id", partner_id)
                .order("created_at", desc=True)
                .execute()
            )
            if res.data:
                account = res.data[0]
                self._memory_bank_accounts[account["id"]] = account
                return account
        except Exception:
            pass

        return None

    # =========================================================================
    # 4. PAYOUT REQUEST MANAGEMENT
    # =========================================================================

    def request_payout(
        self,
        partner_id: str,
        amount: float,
        bank_account_id: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Pengajuan penarikan dana / saldo komisi mitra.
        Validasi:
        1. Minimal payout Rp 50.000.
        2. Mitra wajib memiliki rekening bank terdaftar.
        """
        if amount < MINIMUM_PAYOUT_AMOUNT:
            return (
                False,
                f"Minimal penarikan dana adalah Rp {MINIMUM_PAYOUT_AMOUNT:,.0f} (diajukan: Rp {amount:,.0f})",
                {},
            )

        partner = self.get_partner_by_id(partner_id)
        if not partner:
            return False, "Data mitra tidak ditemukan", {}

        # Dapatkan rekening bank
        bank_account = None
        if bank_account_id:
            bank_account = self._memory_bank_accounts.get(bank_account_id)
        if not bank_account:
            bank_account = self.get_bank_account_by_partner(partner_id)

        if not bank_account:
            return (
                False,
                "Mitra belum mendaftarkan rekening bank tujuan pencairan. Silakan daftarkan rekening bank terlebih dahulu.",
                {},
            )

        payout_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        payout_record = {
            "id": payout_id,
            "partner_id": partner_id,
            "bank_account_id": bank_account["id"],
            "bank_name": bank_account["bank_name"],
            "account_number": bank_account["account_number"],
            "account_holder_name": bank_account["account_holder_name"],
            "partner_name": partner["name"],
            "partner_phone": partner["phone"],
            "amount": float(amount),
            "status": "PENDING",
            "proof_attachment_url": None,
            "created_at": now_iso,
            "processed_at": None,
        }
        self._memory_payouts[payout_id] = payout_record

        try:
            supabase.table("payout_requests").insert(payout_record).execute()
        except Exception as e:
            logger.warning(f"Supabase insert payout request fallback to memory: {e}")

        return True, "Pengajuan penarikan saldo komisi berhasil dibuat.", payout_record

    # =========================================================================
    # 5. CONTROL TOWER & MANAGER (AM & ADMIN)
    # =========================================================================

    def whitelist_new_partner(
        self,
        name: str,
        phone: str,
        role: str = "AFFILIATE",
        ref_code: Optional[str] = None,
        registered_by_am_id: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Pendaftaran mitra baru oleh AM / Admin ke dalam Whitelist.
        """
        clean_phone = "".join(filter(str.isdigit, phone))
        if clean_phone.startswith("0"):
            clean_phone = "62" + clean_phone[1:]

        # Cek apakah nomor sudah terdaftar
        existing = self.get_partner_by_phone(clean_phone)
        if existing:
            return False, f"Mitra dengan nomor WhatsApp {clean_phone} sudah terdaftar.", existing

        clean_role = role.strip().upper()
        if clean_role not in ["AM", "AFFILIATE"]:
            clean_role = "AFFILIATE"

        # Validasi atau generate ref_code
        is_customized = False
        if ref_code:
            norm_slug = ref_code.strip().upper()
            is_valid, reason = self.validate_referral_slug_detailed(norm_slug)
            if not is_valid:
                return False, f"Kode referral kustom tidak valid: {reason}", {}
            final_ref_code = norm_slug
            is_customized = True
        else:
            # Generate default code (e.g. AM8899 atau AFF889912)
            prefix = "AM" if clean_role == "AM" else "AFF"
            suffix = clean_phone[-4:] if len(clean_phone) >= 4 else "8888"
            candidate = f"{prefix}{suffix}"
            counter = 1
            while self._is_slug_taken(candidate):
                candidate = f"{prefix}{suffix}{counter}"
                counter += 1
            final_ref_code = candidate

        now_iso = datetime.now(timezone.utc).isoformat()
        partner_id = str(uuid.uuid4())

        new_partner = {
            "id": partner_id,
            "name": name.strip(),
            "phone": clean_phone,
            "email": email.strip() if email else None,
            "role": clean_role,
            "ref_code": final_ref_code,
            "is_ref_customized": is_customized,
            "registered_by_am_id": registered_by_am_id,
            "status": "ACTIVE",
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        self._memory_partners[partner_id] = new_partner

        try:
            supabase.table("partners").insert(new_partner).execute()
        except Exception as e:
            logger.warning(f"Supabase insert partner fallback to memory: {e}")

        return True, f"Mitra {clean_role} '{name}' berhasil didaftarkan ke whitelist.", new_partner

    def list_all_partners(
        self, role: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List semua AM dan Affiliate beserta status & ringkasan performa.
        """
        results = []
        # Gabungkan dari memory
        for p in self._memory_partners.values():
            if role and p.get("role") != role.upper():
                continue
            if status and p.get("status") != status.upper():
                continue

            # Performa dummy / akumulasi
            pid = p["id"]
            bank_acc = self.get_bank_account_by_partner(pid)
            
            # Hitung sub-affiliate jika AM
            registered_affiliates = sum(
                1 for sub in self._memory_partners.values() if sub.get("registered_by_am_id") == pid
            )

            results.append({
                **p,
                "bank_account": bank_acc,
                "registered_affiliates_count": registered_affiliates,
            })

        return results

    def list_payout_requests(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List seluruh antrean permohonan penarikan dana.
        """
        results = []
        for pr in self._memory_payouts.values():
            if status and pr.get("status") != status.upper():
                continue
            results.append(pr)
        # Urutkan berdasarkan created_at descending
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results

    def mark_payout_as_paid(
        self,
        payout_id: str,
        proof_attachment_url: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Konfirmasi pembayaran payout oleh Admin/Manager:
        Update status ke 'PAID', lampirkan bukti transfer, dan catat processed_at.
        """
        payout = self._memory_payouts.get(payout_id)
        if not payout:
            # Coba cari di Supabase
            try:
                res = supabase.table("payout_requests").select("*").eq("id", payout_id).execute()
                if res.data:
                    payout = res.data[0]
                    self._memory_payouts[payout_id] = payout
            except Exception:
                pass

        if not payout:
            return False, f"Pengajuan payout dengan ID '{payout_id}' tidak ditemukan.", {}

        now_iso = datetime.now(timezone.utc).isoformat()
        payout["status"] = "PAID"
        payout["proof_attachment_url"] = proof_attachment_url
        payout["processed_at"] = now_iso
        if notes:
            payout["settlement_notes"] = notes
        self._memory_payouts[payout_id] = payout

        try:
            supabase.table("payout_requests").update({
                "status": "PAID",
                "proof_attachment_url": proof_attachment_url,
                "processed_at": now_iso,
            }).eq("id", payout_id).execute()
        except Exception as e:
            logger.warning(f"Supabase update payout paid status fallback to memory: {e}")

        return True, "Pembayaran payout berhasil dikonfirmasi dan status diperbarui menjadi PAID.", payout


# Global Service Instance
partner_service = PartnerService()

# Standalone validator function as requested in prompt:
# validate_referral_slug(slug: str) -> bool
def validate_referral_slug(slug: str) -> bool:
    """Fungsi validator global untuk slug custom referral."""
    return partner_service.validate_referral_slug(slug)
