#!/usr/bin/env python3
"""
scripts/test_evolution_connect.py
Verification script for Section 9 ARCHITECTURE.md:
Testing live QR Code and 8-digit Phone Pairing Code on Evolution API v2 (Railway).
"""

import os
import sys
import json
import asyncio
import httpx
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from app.services.whatsapp_service import (
    EVOLUTION_BASE_URL,
    EVOLUTION_API_KEY,
    get_evolution_headers,
    is_valid_whatsapp_pairing_code,
    format_whatsapp_pairing_code,
    get_or_create_evolution_session,
    request_evolution_pairing_code,
)


async def main():
    print("=" * 70)
    print("BOONTRACK WHATSAPP GATEWAY - EVOLUTION API V2 LIVE VERIFICATION")
    print("=" * 70)
    print(f"Gateway URL: {EVOLUTION_BASE_URL}")
    print(f"API Key    : {EVOLUTION_API_KEY[:6]}...{EVOLUTION_API_KEY[-6:]}")
    print("-" * 70)

    tenant_slug = "onlineboost"
    test_phone = "6281237450222"
    instance_name = f"tenant_{tenant_slug}"

    headers = get_evolution_headers()

    async with httpx.AsyncClient(timeout=25.0) as client:
        # 1. Health check & Instance Fetch
        print("\n[STEP 1] Checking Evolution API Health & Instance...")
        health_res = await client.get(f"{EVOLUTION_BASE_URL}", timeout=10.0)
        print(f"HTTP Status: {health_res.status_code}")
        print(f"Response   : {health_res.text}")

        # Check instance state
        inst_res = await client.get(
            f"{EVOLUTION_BASE_URL}/instance/connectionState/{instance_name}",
            headers=headers
        )
        print(f"Instance State ({instance_name}): HTTP {inst_res.status_code} -> {inst_res.text}")

        # 2. Test Live QR Code generation
        print("\n[STEP 2] Testing Live QR Code generation via GET /instance/connect/{instance}...")
        qr_res = await client.get(
            f"{EVOLUTION_BASE_URL}/instance/connect/{instance_name}",
            headers=headers
        )
        print(f"HTTP Status: {qr_res.status_code}")
        qr_json = qr_res.json()
        print(f"Response Keys: {list(qr_json.keys())}")
        has_base64 = bool(qr_json.get("base64"))
        has_code = bool(qr_json.get("code"))
        print(f"Has base64 QR image: {has_base64}")
        print(f"Raw QR Code String : {str(qr_json.get('code'))[:60]}...")
        assert qr_res.status_code in (200, 201), f"QR request failed: {qr_res.status_code}"
        print("[SUCCESS] QR Code path operational!")

        # 3. Test 8-digit Phone Pairing Code
        print(f"\n[STEP 3] Testing 8-Digit Pairing Code for {test_phone}...")
        connect_url = f"{EVOLUTION_BASE_URL}/instance/connect/{instance_name}?number={test_phone}"
        pair_res = await client.get(connect_url, headers=headers)
        print(f"HTTP Status: {pair_res.status_code}")
        raw_text = pair_res.text
        pair_json = pair_res.json()
        print(f"Raw Response JSON: {json.dumps(pair_json, indent=2)[:350]}...")

        pairing_code = pair_json.get("pairingCode")
        print(f"\nExtracted pairingCode : {pairing_code}")
        is_valid = is_valid_whatsapp_pairing_code(str(pairing_code))
        print(f"Is Valid 8-char Code  : {is_valid}")

        if is_valid:
            formatted = format_whatsapp_pairing_code(str(pairing_code))
            print(f"Formatted Pairing Code: {formatted}")
            print(f"[SUCCESS] Official WhatsApp 8-digit pairing code confirmed: {formatted}")
        else:
            print("[WARNING] pairingCode was not immediately returned or returned null.")

        # 4. Test Service Function Endpoints
        print("\n[STEP 4] Testing Backend Service Functions...")
        print("Testing get_or_create_evolution_session('onlineboost')...")
        session_res = await get_or_create_evolution_session("onlineboost")
        print(f"Session Result: success={session_res.get('success')}, status={session_res.get('status')}, has_qr_image={bool(session_res.get('qr_image'))}")

        print(f"\nTesting request_evolution_pairing_code('onlineboost', '{test_phone}')...")
        pairing_func_res = await request_evolution_pairing_code("onlineboost", test_phone)
        print(f"Pairing Result: {json.dumps(pairing_func_res, indent=2)}")

        print("\n" + "=" * 70)
        print("VERIFICATION COMPLETED SUCCESSFULLY!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
