"""
scripts/sync_evolution_gateway_webhook.py
-----------------------------------------
Script utilitas untuk memastikan Evolution API instance 'boontrack-gateway'
mengarahkan webhook MESSAGES_UPSERT ke URL publik boontrack-core.
"""
import os
import sys
import httpx

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.whatsapp.evolution import EVOLUTION_BASE_URL, get_evolution_headers
from app.services.whatsapp_service import get_supabase

TARGET_INSTANCE = "boontrack-gateway"
DEFAULT_PUBLIC_URL = "https://api.boontrack.com"


def sync_gateway_webhook(public_base_url: str = DEFAULT_PUBLIC_URL):
    backend_url = os.getenv("BACKEND_WEBHOOK_URL") or os.getenv("FASTAPI_BASE_URL") or public_base_url
    webhook_url = f"{backend_url.rstrip('/')}/api/v1/whatsapp/webhook/evolution/{TARGET_INSTANCE}"

    print(f"[*] Syncing webhook for instance '{TARGET_INSTANCE}' -> {webhook_url}...")
    headers = get_evolution_headers()

    payload = {
        "webhook": {
            "enabled": True,
            "url": webhook_url,
            "byEvents": False,
            "base64": True,
            "events": ["MESSAGES_UPSERT"]
        }
    }

    resp = httpx.post(
        f"{EVOLUTION_BASE_URL}/webhook/set/{TARGET_INSTANCE}",
        headers=headers,
        json=payload,
        timeout=15.0
    )

    if resp.status_code in (200, 201):
        print(f"[OK] Webhook for '{TARGET_INSTANCE}' successfully set! Status: {resp.status_code}")
        print("     Detail:", resp.json())
        
        # Update whatsapp_connections in Supabase
        try:
            sb = get_supabase()
            if sb:
                sb.table("whatsapp_connections").upsert({
                    "instance_name": TARGET_INSTANCE,
                    "tenant_id": "boontrack-holding",
                    "tenant_slug": TARGET_INSTANCE,
                    "provider": "EVOLUTION",
                    "channel_type": "BAILEYS",
                    "status": "open",
                    "gateway_node_url": webhook_url,
                    "metadata": {
                        "mode": "SHARED",
                        "purpose": "SHARED_GATEWAY",
                        "webhook_url": webhook_url,
                        "events": ["MESSAGES_UPSERT"]
                    }
                }, on_conflict="instance_name").execute()
                print("[OK] Recorded in whatsapp_connections table.")
        except Exception as db_err:
            print(f"[WARN] Failed to update whatsapp_connections: {db_err}")
    else:
        print(f"[ERROR] Failed to set webhook. Status: {resp.status_code}, Body: {resp.text}")


if __name__ == "__main__":
    url_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PUBLIC_URL
    sync_gateway_webhook(url_arg)
