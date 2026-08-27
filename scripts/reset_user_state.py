#!/usr/bin/env python3
"""Script Utility: Reset User State & Cancel UNPAID Jobs.

Mereset state session percakapan WhatsApp dan membatalkan record job / invoice
berstatus UNPAID / WAITING_PAYMENT agar bot tidak terkunci (unfreeze).

Usage:
    python scripts/reset_user_state.py <nomor_wa_atau_user_id>
    python scripts/reset_user_state.py 6281237450222
"""

import sys
import os
import argparse
import asyncio
from datetime import datetime, timezone

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.services.whatsapp_service import get_supabase
from app.services.cv_state_engine import GLOBAL_USER_STATES
from app.services.reconciliation_service import PAYMENT_INTENTS
from app.tenants.career.service import cancel_user_unpaid_invoices


async def run_reset(target_phone: str) -> dict:
    """Mereset state session dan membatalkan order UNPAID untuk user tertentu."""
    phone_clean = str(target_phone).strip().replace("+", "").replace("-", "").replace(" ", "")
    if not phone_clean:
        print("[ERROR] Nomor WhatsApp / User ID tidak boleh kosong.")
        return {"status": "ERROR", "message": "Nomor kosong"}

    print("\n========================================================")
    print("[RESET] MEMULAI RESET STATE & PEMBATALAN ORDER UNPAID")
    print(f"Target User / Phone : {phone_clean}")
    print(f"Timestamp           : {datetime.now().isoformat()}")
    print("========================================================")

    # 1. Batalkan invoice di Supabase & PAYMENT_INTENTS via service function
    res = await cancel_user_unpaid_invoices(phone_clean)

    # 2. Pastikan session di memori bersih
    user_session = GLOBAL_USER_STATES.setdefault(phone_clean, {"step": 0, "mode": "menu", "data": {}})
    user_session["mode"] = "menu"
    user_session["step"] = 0
    user_session["active_invoice"] = None
    user_session["active_payment"] = None
    user_session["awaiting_payment_at"] = None

    print("\n[OK] HASIL RESET:")
    print(f"  * Status             : SUKSES")
    print(f"  * User ID Terproses  : {res.get('user_id', phone_clean)}")
    print(f"  * Intent Dibatalkan  : {len(res.get('cancelled_intents', []))} ({res.get('cancelled_intents', [])})")
    print(f"  * DB Jobs Dibatalkan : {res.get('cancelled_jobs', 0)}")
    print(f"  * Orders Dibatalkan  : {res.get('cancelled_orders', 0)}")
    print(f"  * Session State Baru : mode='{user_session.get('mode')}', step={user_session.get('step')}")
    print("========================================================\n")

    return res


def main():
    parser = argparse.ArgumentParser(
        description="Reset user session state and cancel UNPAID/WAITING_PAYMENT jobs."
    )
    parser.add_argument(
        "phone",
        nargs="?",
        default=None,
        help="User ID / Nomor WhatsApp (contoh: 6281237450222)"
    )
    args = parser.parse_args()

    target_phone = args.phone
    if not target_phone:
        if sys.stdin.isatty():
            try:
                target_phone = input("Masukkan Nomor WhatsApp / User ID: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nOperasi dibatalkan.")
                sys.exit(0)
        else:
            print("Usage: python scripts/reset_user_state.py <nomor_wa_atau_user_id>")
            sys.exit(1)

    result = asyncio.run(run_reset(target_phone))
    if result.get("status") == "ERROR":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
