#!/usr/bin/env python3
"""
scripts/test_waha_pairing.py
Diagnostic test script to verify direct pairing-code generation via official WAHA API.
"""

import sys
import os
import json
import asyncio
import httpx
from dotenv import load_dotenv

# Ensure root directory in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

WAHA_URL = (
    os.getenv("WAHA_URL")
    or os.getenv("WAHA_BASE_URL")
    or os.getenv("WHATSAPP_GATEWAY_URL")
    or "http://localhost:3000"
).rstrip("/")

WAHA_API_KEY = (
    os.getenv("WAHA_API_KEY")
    or os.getenv("WHATSAPP_API_KEY")
    or ""
)

SESSION_NAME = sys.argv[1] if len(sys.argv) > 1 else "onlineboost"
PHONE_NUMBER = sys.argv[2] if len(sys.argv) > 2 else "6281237450222"


async def main():
    print("=" * 65)
    print("[DIAGNOSTIC] WAHA PAIRING CODE DIAGNOSTIC RUNNER")
    print(f"  • WAHA Base URL    : {WAHA_URL}")
    print(f"  • Target Session   : {SESSION_NAME}")
    print(f"  • Target Phone     : {PHONE_NUMBER}")
    print(f"  • API Key Set      : {'Yes (Length: ' + str(len(WAHA_API_KEY)) + ')' if WAHA_API_KEY else 'No (Empty)'}")
    print("=" * 65)

    headers = {"Content-Type": "application/json"}
    if WAHA_API_KEY:
        headers["X-Api-Key"] = WAHA_API_KEY

    async with httpx.AsyncClient(timeout=25.0) as client:
        # STEP 1: Check Session Status
        print(f"\n[STEP 1] Checking session status at: {WAHA_URL}/api/sessions/{SESSION_NAME}")
        session_status = None
        try:
            res_sess = await client.get(f"{WAHA_URL}/api/sessions/{SESSION_NAME}", headers=headers)
            print(f"  -> HTTP Status : {res_sess.status_code}")
            print(f"  -> Raw Body    : {res_sess.text}")
            if res_sess.status_code == 200:
                data = res_sess.json()
                session_status = data.get("status")
                engine = data.get("config", {}).get("engine") or "Unknown"
                print(f"  -> Current Status: {session_status} | Engine: {engine}")
                if engine.upper() == "WEBJS":
                    print("  [WARN] WAHA engine is WEBJS! Pairing code via API REQUIRES 'NOWEB' (Baileys) engine.")
        except Exception as e:
            print(f"  [ERROR] Connection Failed: {e}")

        # STEP 2: If stopped/failed or 404, start/create
        if session_status in ("STOPPED", "FAILED", None):
            print(f"\n[STEP 2] Starting session '{SESSION_NAME}'...")
            try:
                start_res = await client.post(f"{WAHA_URL}/api/sessions/{SESSION_NAME}/start", headers=headers)
                print(f"  -> Start Status: {start_res.status_code} | Body: {start_res.text}")
            except Exception as e:
                print(f"  [ERROR] Start Request Failed: {e}")

        # STEP 3: Request Pairing Code
        request_code_url = f"{WAHA_URL}/api/{SESSION_NAME}/auth/request-code"
        print(f"\n[STEP 3] Requesting Pairing Code: POST {request_code_url}")
        print(f"  Payload: {json.dumps({'phoneNumber': PHONE_NUMBER})}")

        try:
            req_res = await client.post(
                request_code_url,
                headers=headers,
                json={"phoneNumber": PHONE_NUMBER}
            )

            print(f"  -> HTTP Status Code : {req_res.status_code}")
            print(f"  -> Response Headers : {dict(req_res.headers)}")
            print(f"  -> Raw Response Body: {req_res.text}")

            if req_res.status_code in (200, 201):
                res_data = req_res.json()
                code = res_data.get("code") or res_data.get("pairingCode")
                if code:
                    print(f"\n[SUCCESS] Official WhatsApp Pairing Code Received: {code}")
                else:
                    print(f"\n[WARN] Status 200 but 'code' field missing in: {res_data}")
            elif req_res.status_code == 404:
                print("\n[404 NOT FOUND]:")
                print("   Endpoint /api/{session}/auth/request-code was not found.")
                print("   Possible causes:")
                print("   1. The WAHA container is running an older version.")
                print("   2. WAHA session engine is set to WEBJS instead of NOWEB.")
                print("   3. Check WAHA documentation for your version: devlikeapro/waha:latest.")
            elif req_res.status_code == 400:
                print("\n[400 BAD REQUEST]:")
                print("   WAHA rejected the request. Possible causes:")
                print("   1. Session is not in 'SCAN_QR_CODE' status.")
                print("   2. Phone number format invalid or already paired.")
                print("   3. Session engine is WEBJS (which does not support pairing-code API).")
            else:
                print(f"\n[HTTP ERROR] Status: {req_res.status_code}")

        except Exception as e:
            print(f"  [ERROR] Request-Code Call Exception: {e}")

    print("\n" + "=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
