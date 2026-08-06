import os
import requests

ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
KV_NAMESPACE_ID = os.getenv("CLOUDFLARE_KV_NAMESPACE_ID")
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "boontrack.com")

async def deploy_landing_page_kv(subdomain_name: str, html_content: str) -> str:
    key_name = subdomain_name.lower().strip().replace(" ", "-")
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/storage/kv/namespaces/{KV_NAMESPACE_ID}/values/{key_name}"

    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "text/html; charset=utf-8"
    }

    try:
        response = requests.put(url, headers=headers, data=html_content.encode('utf-8'))
        if response.status_code == 200:
            return f"https://{key_name}.{BASE_DOMAIN}"
        else:
            print(f"Error KV Upload: {response.text}")
            return None
    except Exception as e:
        print(f"Exception KV Upload: {e}")
        return None