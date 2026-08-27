import os

def is_owner(telegram_user_id: int) -> bool:
    """
    Mengecek apakah ID pengirim adalah Owner/Admin resmi.
    """
    owner_id = os.getenv("OWNER_TELEGRAM_ID", "").strip()
    if not owner_id:
        return False
    return str(telegram_user_id) == str(owner_id)
