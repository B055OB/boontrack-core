import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger("TENANT_REGISTRY")

REGISTRY_FILE = Path(__file__).parent / "registry.json"


class TenantRegistry:
    """Config & DB-Driven Multi-Tenant Registry Manager."""

    _cached_data: Optional[Dict[str, Any]] = None

    @classmethod
    def load_registry(cls, force_reload: bool = False) -> Dict[str, Any]:
        """Memuat data registri tenant dari registry.json."""
        if cls._cached_data is not None and not force_reload:
            return cls._cached_data

        if not REGISTRY_FILE.exists():
            logger.warning(f"[TENANT REGISTRY] Registry file not found at {REGISTRY_FILE}, using empty fallback")
            cls._cached_data = {"tenants": {}}
            return cls._cached_data

        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cls._cached_data = data
                return data
        except Exception as e:
            logger.error(f"[TENANT REGISTRY] Failed to read {REGISTRY_FILE}: {e}")
            if cls._cached_data is not None:
                return cls._cached_data
            return {"tenants": {}}

    @classmethod
    def get_all_tenants(cls) -> Dict[str, Any]:
        """Mengembalikan seluruh konfigurasi tenant."""
        data = cls.load_registry()
        return data.get("tenants", {})

    @classmethod
    def get_tenant(cls, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Mendapatkan data konfigurasi tenant berdasarkan tenant_id."""
        clean_id = str(tenant_id or "").strip().lower().replace("_", "-")
        tenants = cls.get_all_tenants()
        return tenants.get(clean_id)

    @classmethod
    def get_telegram_token(cls, tenant_id: str) -> Optional[str]:
        """
        Mendapatkan bot token Telegram untuk tenant tertentu.
        Memprioritaskan Environment Variable (jika ada), lalu fallback ke registry.json.
        """
        clean_id = str(tenant_id or "").strip().lower().replace("_", "-")

        # 1. Cek Environment Variable (opsional override)
        env_key = f"{clean_id.upper().replace('-', '_')}_TELEGRAM_TOKEN"
        token_env = os.getenv(env_key)
        if token_env and token_env.strip():
            return token_env.strip()

        # 2. Cek Config Registry JSON
        tenant = cls.get_tenant(clean_id)
        if tenant:
            tg_channel = tenant.get("channels", {}).get("telegram", {})
            token_cfg = tg_channel.get("bot_token", "").strip()
            if token_cfg:
                return token_cfg

        # 3. Fallback umum
        return os.getenv("TELEGRAM_BOT_TOKEN")

    @classmethod
    def resolve_tenant_from_telegram(
        cls,
        token_or_id: str = "",
        secret_token: str = "",
        path_param: str = ""
    ) -> Optional[str]:
        """
        Secara dinamis mengenali tenant_id dari:
        1. path_param (/webhook/telegram/{path_param})
        2. Token / Bot ID prefix (misal: 8902407474:...)
        3. Header X-Telegram-Bot-Api-Secret-Token
        """
        tenants = cls.get_all_tenants()

        # 1. Cek dari path param (bisa tenant_id langsung atau bot_id)
        if path_param:
            clean_param = path_param.strip().lower().replace("_", "-")
            if clean_param in tenants:
                return clean_param

            # Cek jika path_param adalah bot_id (e.g. 8902407474)
            for tid, tdata in tenants.items():
                tg = tdata.get("channels", {}).get("telegram", {})
                if str(tg.get("bot_id", "")).strip() == clean_param:
                    return tid
                token = tg.get("bot_token", "")
                if token and token.startswith(clean_param):
                    return tid

        # 2. Cek dari Secret Token header
        if secret_token:
            for tid, tdata in tenants.items():
                tg = tdata.get("channels", {}).get("telegram", {})
                if tg.get("secret_token") and tg.get("secret_token") == secret_token.strip():
                    return tid

        # 3. Cek dari full token atau prefix bot ID
        if token_or_id:
            clean_token = token_or_id.strip()
            token_prefix = clean_token.split(":")[0] if ":" in clean_token else clean_token

            for tid, tdata in tenants.items():
                tg = tdata.get("channels", {}).get("telegram", {})
                bot_token = tg.get("bot_token", "").strip()
                bot_id = str(tg.get("bot_id", "")).strip()

                if bot_token and (bot_token == clean_token or bot_token.startswith(token_prefix)):
                    return tid
                if bot_id and bot_id == token_prefix:
                    return tid

        # 4. Default fallback jika hanya ada 1 bot atau digicorn
        return "digicorn" if "digicorn" in tenants else None

    @classmethod
    def register_tenant(
        cls,
        tenant_id: str,
        name: str,
        telegram_token: str = "",
        telegram_bot_id: str = "",
        save_to_disk: bool = False
    ) -> Dict[str, Any]:
        """Mendaftarkan tenant baru secara dinamis."""
        clean_id = str(tenant_id or "").strip().lower().replace("_", "-")
        data = cls.load_registry()
        tenants = data.setdefault("tenants", {})

        if not telegram_bot_id and ":" in telegram_token:
            telegram_bot_id = telegram_token.split(":")[0]

        tenants[clean_id] = {
            "tenant_id": clean_id,
            "name": name,
            "is_active": True,
            "channels": {
                "telegram": {
                    "bot_token": telegram_token,
                    "bot_id": telegram_bot_id
                }
            }
        }

        if save_to_disk:
            try:
                with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                logger.error(f"[TENANT REGISTRY] Failed to save {REGISTRY_FILE}: {e}")

        cls._cached_data = data
        return tenants[clean_id]


tenant_registry = TenantRegistry()
