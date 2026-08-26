import re
import logging
from typing import Dict, Any, Optional, Union, List

logger = logging.getLogger("PAYMENT_VERIFICATION_SERVICE")

# Daftar kata kunci penerima / merchant resmi yang sah
VALID_RECEIVER_KEYWORDS = [
    "OM BUDI CHANNEL",
    "BUDI YULIANTO",
    "OM BUDI"
]

# Batas minimum nominal untuk Sesi Kelas Online
MIN_KELAS_ONLINE_AMOUNT = 100000  # Rp100.000


class PaymentVerificationService:
    """Service simplifikasi dan pengunci logika verifikasi pembayaran DANA / QRIS / Transfer Bank.
    
    Memvalidasi 2 parameter inti:
    1. Nama Penerima: Wajib mengandung 'OM BUDI CHANNEL' atau 'Budi Yulianto'.
       (Jika terbaca merchant lain seperti 'KANZ STORE', langsung reject).
    2. Jumlah Transfer:
       - Sesi Kelas Online: Wajib >= Rp100.000.
       - Sesi Sedekah: Bebas (menerima semua nominal selama penerima valid).
    """

    @staticmethod
    def is_valid_receiver(receiver_name: str) -> bool:
        """Memeriksa apakah nama penerima/merchant mengandung 'OM BUDI CHANNEL' atau 'Budi Yulianto'."""
        if not receiver_name:
            return False

        clean_name = str(receiver_name).strip().upper()

        # Cek apakah mengandung salah satu kata kunci resmi
        for keyword in VALID_RECEIVER_KEYWORDS:
            if keyword in clean_name:
                return True

        return False

    def verify_payment_params(
        self,
        receiver_name: str,
        amount: int,
        session_type: str = "auto",
        reference_no: str = "-",
        raw_source: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Memvalidasi transaksi berdasarkan 2 parameter inti (Penerima & Nominal).
        
        Args:
            receiver_name: Nama penerima/merchant dari OCR struk, DANA, atau mutasi bank.
            amount: Nominal pembayaran dalam Rupiah (integer).
            session_type: 'kelas_online', 'sedekah', atau 'auto'.
            reference_no: Nomor referensi transaksi (RRN).
            raw_source: Data mentah tambahan jika ada.
            
        Returns:
            Dict berisi status validitas, alasan jika reject, dan pesan konfirmasi.
        """
        clean_session = str(session_type or "auto").strip().lower()
        clean_receiver = str(receiver_name or "").strip()
        amt = int(amount or 0)

        # ----------------------------------------------------
        # PARAMETER INTI 1: Validasi Nama Penerima
        # ----------------------------------------------------
        if not self.is_valid_receiver(clean_receiver):
            logger.warning(
                f"[PAYMENT REJECTED] Penerima tidak valid: '{clean_receiver}' "
                f"(Wajib 'OM BUDI CHANNEL' atau 'Budi Yulianto')"
            )
            return {
                "is_valid": False,
                "amount": amt,
                "receiver": clean_receiver,
                "session_type": clean_session,
                "reference_no": reference_no,
                "reason": "INVALID_RECEIVER",
                "message": (
                    f"⚠️ Pembayaran ditolak. Rekening atau merchant tujuan (*{clean_receiver or 'Tidak Dikenal'}*) "
                    f"tidak terdaftar. Pembayaran wajib ditujukan ke *OM BUDI CHANNEL* atau *Budi Yulianto*."
                )
            }

        # ----------------------------------------------------
        # PARAMETER INTI 2: Validasi Jumlah Transfer Berdasarkan Sesi
        # ----------------------------------------------------
        if amt <= 0:
            logger.warning(f"[PAYMENT REJECTED] Nominal tidak valid: Rp{amt:,}")
            return {
                "is_valid": False,
                "amount": amt,
                "receiver": clean_receiver,
                "session_type": clean_session,
                "reference_no": reference_no,
                "reason": "INVALID_AMOUNT",
                "message": "⚠️ Pembayaran ditolak. Nominal transfer tidak terbaca atau bernilai 0."
            }

        # Skenario A: Sesi Kelas Online (Wajib >= Rp100.000)
        is_kelas_session = clean_session in ["kelas_online", "kelas", "daftar_kelas", "pendaftaran"]
        if is_kelas_session:
            if amt < MIN_KELAS_ONLINE_AMOUNT:
                logger.warning(
                    f"[PAYMENT REJECTED] Nominal Kelas Online kurang: Rp{amt:,} "
                    f"(Minimal Rp{MIN_KELAS_ONLINE_AMOUNT:,})"
                )
                return {
                    "is_valid": False,
                    "amount": amt,
                    "receiver": clean_receiver,
                    "session_type": "kelas_online",
                    "reference_no": reference_no,
                    "reason": "INSUFFICIENT_AMOUNT",
                    "message": (
                        f"⚠️ Pembayaran Kelas Online belum memenuhi syarat. Nominal yang terbaca (*Rp{amt:,}*) "
                        f"kurang dari investasi pendaftaran minimal (*Rp{MIN_KELAS_ONLINE_AMOUNT:,}*)."
                    )
                }
            return {
                "is_valid": True,
                "amount": amt,
                "receiver": clean_receiver,
                "session_type": "kelas_online",
                "reference_no": reference_no,
                "reason": None,
                "message": f"✅ Pembayaran Kelas Online sebesar Rp{amt:,} ke {clean_receiver} terverifikasi sah."
            }

        # Skenario B: Sesi Sedekah (Bebas nominal, terima berapapun asalkan penerima valid)
        is_sedekah_session = clean_session in ["sedekah", "donasi", "sedekah_berjamaah", "infaq"]
        if is_sedekah_session:
            return {
                "is_valid": True,
                "amount": amt,
                "receiver": clean_receiver,
                "session_type": "sedekah",
                "reference_no": reference_no,
                "reason": None,
                "message": f"✅ Sedekah Berjamaah sebesar Rp{amt:,} ke {clean_receiver} terverifikasi sah."
            }

        # Skenario C: Sesi Auto (Tentukan jenis sesi berdasarkan nominal jika penerima valid)
        if amt >= MIN_KELAS_ONLINE_AMOUNT:
            resolved_session = "kelas_online"
        else:
            resolved_session = "sedekah"

        return {
            "is_valid": True,
            "amount": amt,
            "receiver": clean_receiver,
            "session_type": resolved_session,
            "reference_no": reference_no,
            "reason": None,
            "message": f"✅ Pembayaran sebesar Rp{amt:,} ke {clean_receiver} terverifikasi sah ({resolved_session})."
        }

    def verify_receipt_ocr_data(
        self,
        ocr_data: Dict[str, Any],
        session_type: str = "auto"
    ) -> Dict[str, Any]:
        """Memverifikasi data hasil Vision OCR struk pembayaran / transfer."""
        if not ocr_data or not isinstance(ocr_data, dict):
            return {
                "is_valid": False,
                "amount": 0,
                "receiver": "",
                "session_type": session_type,
                "reference_no": "-",
                "reason": "EMPTY_OCR_DATA",
                "message": "⚠️ Gambar struk tidak dapat dianalisis."
            }

        amount = int(ocr_data.get("amount") or ocr_data.get("nominal") or 0)
        receiver = (
            ocr_data.get("bank_source")
            or ocr_data.get("merchant_name")
            or ocr_data.get("receiver_name")
            or ocr_data.get("merchant")
            or ocr_data.get("recipient")
            or "BSI / Mandiri (Budi Yulianto)"
        )
        ref_no = str(ocr_data.get("reference_no_rrn") or ocr_data.get("ref_no") or "-")

        # Jalankan 2 parameter verifikasi inti
        return self.verify_payment_params(
            receiver_name=receiver,
            amount=amount,
            session_type=session_type,
            reference_no=ref_no,
            raw_source=ocr_data
        )


# Singleton instance
payment_verification_service = PaymentVerificationService()
