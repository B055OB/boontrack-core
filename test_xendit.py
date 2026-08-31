# test_xendit.py
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from app.services.xendit_service import xendit_service

async def main():
    print("--- TESTING XENDIT QRIS ---")
    res = await xendit_service.create_dynamic_qris(
        external_id="TEST-ONLINEBOOST-01",
        amount=99000,
        tenant_id="onlineboost"
    )
    print("\n[RESULT]")
    print(f"Status      : {res.get('status')}")
    print(f"External ID : {res.get('external_id')}")
    print(f"QR URL      : {res.get('qr_code_url')}")
    print(f"QR String   : {res.get('qr_string')[:50]}...")

if __name__ == "__main__":
    asyncio.run(main())