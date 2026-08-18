import os
import json
import logging
import httpx

logger = logging.getLogger(__name__)

CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CF_KV_NAMESPACE_ID = (
    os.getenv("CLOUDFLARE_KV_NAMESPACE_ID") 
    or os.getenv("CLOUDFLARE_KV_NAMESPACE") 
    or ""
)

HEADERS = {
    "Authorization": f"Bearer {CF_API_TOKEN}",
    "Content-Type": "application/json"
}

RESERVED_SLUGS = {
    "www", "cv", "boontrack", "boontrack-router", "admin", 
    "api", "app", "dashboard", "auth", "login", "register", "default"
}

async def is_slug_available(slug: str, current_user_id: int = None) -> tuple[bool, str]:
    """
    Cek ketersediaan slug ke Cloudflare KV.
    """
    clean_slug = slug.strip().lower()

    if clean_slug in RESERVED_SLUGS:
        return False, "Nama tersebut merupakan domain sistem bawaan. Coba nama lain ya kak! 😊"

    if not (CF_ACCOUNT_ID and CF_API_TOKEN and CF_KV_NAMESPACE_ID):
        logger.warning("Cloudflare KV credentials not fully set, bypassing availability check.")
        return True, "OK"

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{clean_slug}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=HEADERS)
            if res.status_code == 404:
                return True, "OK"
            
            if res.status_code == 200:
                try:
                    data = res.json()
                except Exception:
                    data = json.loads(res.text)

                if str(data.get("user_id")) == str(current_user_id):
                    return True, "OK"
                    
                return False, "Waduh, nama domain ini sudah dipakai orang lain kak. Coba variasi nama lain ya! 🙏"
            
            return True, "OK"
    except Exception as e:
        logger.exception(f"Error checking slug availability: {e}")
        return True, "OK"

async def sync_profile_to_cloudflare_kv(slug: str, profile_data: dict) -> bool:
    """
    Kirim payload JSON profil ke Cloudflare Workers KV.
    """
    if not (CF_ACCOUNT_ID and CF_API_TOKEN and CF_KV_NAMESPACE_ID):
        logger.error("Cloudflare KV credentials missing in Railway environment variables.")
        return False

    clean_slug = (slug or "default").strip().lower()
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{clean_slug}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.put(
                url, 
                headers=HEADERS, 
                content=json.dumps(profile_data, ensure_ascii=False)
            )
            if res.status_code in [200, 201]:
                logger.info(f"Successfully synced career page KV for slug: {clean_slug}")
                return True
            else:
                logger.error(f"Cloudflare KV Sync Failed. Status: {res.status_code}, Body: {res.text}")
                return False
    except Exception as e:
        logger.exception(f"Exception during Cloudflare KV sync: {e}")
        return False

async def get_profile_from_cloudflare_kv(slug: str) -> dict:
    """
    Ambil data profil dari KV.
    """
    clean_slug = (slug or "").strip().lower()
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{CF_KV_NAMESPACE_ID}/values/{clean_slug}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(url, headers=HEADERS)
            if res.status_code == 200:
                return res.json()
            return {}
    except Exception as e:
        logger.exception(f"Exception fetching profile from KV: {e}")
        return {}