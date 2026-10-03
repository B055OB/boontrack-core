import os
import json
import requests
from dotenv import load_dotenv

def main():
    load_dotenv()

    # Retrieve access token & WABA ID
    token = (
        os.getenv("META_SYSTEM_USER_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
        or os.getenv("WABA_ACCESS_TOKEN")
    )
    waba_id = (
        os.getenv("WHATSAPP_WABA_ID")
        or os.getenv("CAREER_WABA_ID")
        or os.getenv("META_WABA_BUSINESS_ACCOUNT_ID")
    )

    if not token:
        raise ValueError("Missing Meta Access Token in environment variables (.env).")
    if not waba_id:
        raise ValueError("Missing WABA ID in environment variables (.env).")

    print(f"[*] Access Token Prefix : {token[:15]}...")
    print(f"[*] Target WABA ID       : {waba_id}")

    # Official endpoint requiring whatsapp_business_management permission
    url = f"https://graph.facebook.com/v20.0/{waba_id}"
    params = {
        "fields": "id,name,currency,timezone_id"
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"[*] Dispatching GET request to: {url}")
    response = requests.get(url, headers=headers, params=params, timeout=15)

    print(f"[*] HTTP Status Code     : {response.status_code} {response.reason}")
    print("[*] Response Payload     :")
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except Exception:
        print(response.text)

    # Optional secondary test: message_templates
    templates_url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
    print(f"\n[*] Dispatching GET request to: {templates_url}?limit=1")
    t_response = requests.get(templates_url, headers=headers, params={"limit": 1}, timeout=15)
    print(f"[*] HTTP Status Code     : {t_response.status_code} {t_response.reason}")
    print("[*] Template Response    :")
    try:
        t_data = t_response.json()
        print(json.dumps(t_data, indent=2))
    except Exception:
        print(t_response.text)

    if response.status_code == 200:
        print("\n[SUCCESS] Meta Graph API test call for whatsapp_business_management completed successfully (HTTP 200 OK).")
    else:
        print(f"\n[FAILED] Received status code {response.status_code}")
        exit(1)

if __name__ == "__main__":
    main()
