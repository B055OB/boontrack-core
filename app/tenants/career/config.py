import os

TENANT_ID = "boontrack-career"
CAREER_PHONE_NUMBER_ID = os.getenv("CAREER_PHONE_NUMBER_ID", "1340866379104241")

VERIFY_TOKEN = (
    os.getenv("CAREER_VERIFY_TOKEN")
    or os.getenv("WHATSAPP_VERIFY_TOKEN")
    or os.getenv("META_WA_VERIFY_TOKEN")
    or "boontrack_career_token"
)

CAREER_ACCESS_TOKEN = (
    os.getenv("CAREER_ACCESS_TOKEN")
    or os.getenv("WHATSAPP_TOKEN")
    or ""
).strip()

# Developer & Admin Whitelist Bypass (Auto-Unlock Career Pro & Decision Engine)
CAREER_VIP_WHITELIST = {
    "081237450222",
    "6281237450222",
    "+6281237450222",
    "6281237450222@c.us"
}

env_whitelist = os.getenv("CAREER_VIP_WHITELIST", "")
if env_whitelist:
    for num in env_whitelist.split(","):
        clean_num = num.strip()
        if clean_num:
            CAREER_VIP_WHITELIST.add(clean_num)