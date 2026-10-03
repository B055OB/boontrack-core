import os
import sys
import json
import requests
from dotenv import load_dotenv

TARGET_APP_ID = "1398832609107871"
TARGET_BUSINESS_ID = "4490762684368555"
TARGET_WABA_ID = "2039138053385393"

def test_meta_call(token: str):
    token = token.strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"\n=======================================================")
    print(f"[*] Testing Token for Meta App ID: {TARGET_APP_ID}")
    print(f"[*] Token Prefix: {token[:15]}...")
    print(f"=======================================================\n")

    # Step 1: Verify token metadata via debug_token
    print("[1] Verifying Token via /debug_token ...")
    try:
        r_debug = requests.get(
            "https://graph.facebook.com/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=10
        )
        if r_debug.status_code == 200:
            debug_info = r_debug.json().get("data", {})
            app_id = debug_info.get("app_id")
            app_name = debug_info.get("application")
            scopes = debug_info.get("scopes", [])
            print(f"    -> Token App ID     : {app_id}")
            print(f"    -> Application Name : {app_name}")
            print(f"    -> Scopes           : {scopes}")
            if str(app_id) == TARGET_APP_ID:
                print(f"    [MATCH] Token correctly matches App ID {TARGET_APP_ID}!")
            else:
                print(f"    [WARNING] Token app_id ({app_id}) does not match target ({TARGET_APP_ID})")
        else:
            print(f"    -> Debug token status {r_debug.status_code}: {r_debug.text}")
    except Exception as e:
        print(f"    -> Failed debug token check: {e}")

    # Step 2: GET App node
    print(f"\n[2] Dispatching GET to App Node: https://graph.facebook.com/v20.0/{TARGET_APP_ID}?fields=id,name ...")
    r_app = requests.get(
        f"https://graph.facebook.com/v20.0/{TARGET_APP_ID}",
        headers=headers,
        params={"fields": "id,name"},
        timeout=10
    )
    print(f"    -> Status: {r_app.status_code} {r_app.reason}")
    print(f"    -> Response: {r_app.text}")

    # Step 3: GET WABA node (BoonTrack WABA: 2039138053385393)
    print(f"\n[3] Dispatching GET to WABA Node: https://graph.facebook.com/v20.0/{TARGET_WABA_ID}?fields=id,name,currency,timezone_id ...")
    r_waba = requests.get(
        f"https://graph.facebook.com/v20.0/{TARGET_WABA_ID}",
        headers=headers,
        params={"fields": "id,name,currency,timezone_id"},
        timeout=10
    )
    print(f"    -> Status: {r_waba.status_code} {r_waba.reason}")
    print(f"    -> Response: {r_waba.text}")

    # Step 4: GET WABA Message Templates (directly satisfies whatsapp_business_management)
    print(f"\n[4] Dispatching GET to Message Templates: https://graph.facebook.com/v20.0/{TARGET_WABA_ID}/message_templates?limit=1 ...")
    r_tmpl = requests.get(
        f"https://graph.facebook.com/v20.0/{TARGET_WABA_ID}/message_templates",
        headers=headers,
        params={"limit": 1},
        timeout=10
    )
    print(f"    -> Status: {r_tmpl.status_code} {r_tmpl.reason}")
    print(f"    -> Response: {r_tmpl.text}")

    # Summary
    success = (r_app.status_code == 200 or r_waba.status_code == 200 or r_tmpl.status_code == 200)
    if success:
        print("\n=======================================================")
        print(f"[SUCCESS] Meta API call executed with HTTP 200 OK under App ID {TARGET_APP_ID}!")
        print("Refresh your Meta App Review dashboard to confirm the green checkmark.")
        print("=======================================================\n")
    else:
        print("\n[ERROR] None of the endpoints returned 200 OK.")

def main():
    load_dotenv()
    token = None
    if len(sys.argv) > 1:
        token = sys.argv[1]
    else:
        token = os.getenv("META_APP_REVIEW_TOKEN") or os.getenv("META_ACCESS_TOKEN_1398832609107871")

    if not token:
        print("Usage: python scripts/test_meta_app_review_call.py <ACCESS_TOKEN>")
        print("   or set META_APP_REVIEW_TOKEN in .env")
        sys.exit(1)

    test_meta_call(token)

if __name__ == "__main__":
    main()
