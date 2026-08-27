"""Tenant Dynamic Loader & Fault Isolation Engine.

Menjamin proses registrasi tenant bersifat modular, dynamic, dan terisolasi.
Jika salah satu tenant mengalami ImportError, syntax error, atau runtime crash saat startup,
tenant lain dan server utama TETAP BOOTSTRAP dan BERJALAN NORMAL (Zero Cascade Crash).
"""

import importlib
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from aiohttp import web

logger = logging.getLogger("TENANT_LOADER")

TENANT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "career": {
        "name": "Career Assistant",
        "module": "app.tenants.career.router",
        "register_func": "register_career_routes",
        "description": "WhatsApp Career & CV Review Assistant",
        "enabled": True,
    },
    "om_budi": {
        "name": "Om Budi Bot",
        "module": "app.tenants.om_budi.router",
        "register_func": "register_om_budi_routes",
        "description": "Interactive Om Budi WhatsApp Assistant",
        "enabled": True,
    },
    "reader": {
        "name": "Android Reader",
        "module": "app.modules.reader.router",
        "fallback_module": "app.reader.router",
        "register_func": "register_reader_routes",
        "pass_session": True,
        "description": "Android Reader Device Pairing & Token Management",
        "enabled": True,
    },
    "whatsapp_central": {
        "name": "Central WhatsApp Dispatcher",
        "module": "app.routes.whatsapp_central",
        "register_func": "register_central_whatsapp_routes",
        "description": "Centralized Multi-Tenant WhatsApp Webhook Routing",
        "enabled": True,
    },
    "telegram_central": {
        "name": "Central Telegram Channel",
        "module": "app.core.channels.telegram",
        "register_func": "register_central_telegram_routes",
        "description": "Central Multi-Tenant Telegram Broadcast & Notification",
        "enabled": True,
    },
    "public_services": {
        "name": "Public Services Unified Router",
        "module": "app.modules.public_services.router",
        "register_func": "register_public_service_routes",
        "description": "Public B2B/B2C Services",
        "enabled": True,
    },
    "commerce": {
        "name": "Commerce Multi-Tenant",
        "module": "app.modules.commerce.router",
        "routes_attr": "commerce_routes",
        "description": "Digital Products Commerce & Catalog",
        "enabled": True,
    },
    "payment": {
        "name": "Payment Hub",
        "module": "app.routes.payment",
        "register_func": "register_payment_routes",
        "description": "Payment Invoicing & Verification",
        "enabled": True,
    },
    "payment_webhook": {
        "name": "Payment & Reader Webhooks",
        "module": "app.routes.payment_webhook",
        "register_func": "register_payment_webhook_routes",
        "description": "DANA Mutation & Android Reader Webhook Processing",
        "enabled": True,
    },
    "telegram_gateway": {
        "name": "Telegram Gateway Webhook",
        "module": "app.telegram.router",
        "register_func": "register_telegram_routes",
        "pass_session": True,
        "description": "Direct Telegram Gateway Dispatcher",
        "enabled": True,
    },
    "whatsapp_gateway": {
        "name": "WhatsApp Gateway Webhook",
        "module": "app.whatsapp.router",
        "register_func": "register_whatsapp_routes",
        "pass_session": True,
        "description": "Legacy WhatsApp Gateway Dispatcher",
        "enabled": True,
    },
}

# Runtime status storage
TENANT_STATUS: Dict[str, Dict[str, Any]] = {}


def load_dynamic_tenants(
    app: web.Application,
    session_factory=None,
    registry: Optional[Dict[str, Dict[str, Any]]] = None,
    reset_status: bool = False
) -> Dict[str, str]:
    """Memuat seluruh modul tenant secara dinamis menggunakan importlib dengan proteksi isolasi kesalahan.
    Jika suatu modul tenant gagal dimuat (ImportError, syntax, dsb.), exception ditangkap,
    dicatat di log, ditandai sebagai DEGRADED, dan proses booting berlanjut tanpa mematikan server.
    """
    if registry is not None or reset_status:
        TENANT_STATUS.clear()

    active_registry = registry if registry is not None else TENANT_REGISTRY
    statuses: Dict[str, str] = {}

    for tenant_id, cfg in active_registry.items():
        if not cfg.get("enabled", True):
            TENANT_STATUS[tenant_id] = {
                "name": cfg.get("name", tenant_id),
                "status": "disabled",
                "module": cfg.get("module", ""),
                "error": None,
                "loaded_at": None,
            }
            statuses[tenant_id] = "disabled"
            continue

        mod_name = cfg.get("module", "")
        fallback_mod = cfg.get("fallback_module")
        register_func_name = cfg.get("register_func")
        routes_attr = cfg.get("routes_attr")
        pass_session = cfg.get("pass_session", False)

        loaded_mod = None
        load_error = None

        # 1. Coba import modul utama
        try:
            loaded_mod = importlib.import_module(mod_name)
        except Exception as e1:
            load_error = e1
            # Coba fallback module jika ada
            if fallback_mod:
                try:
                    loaded_mod = importlib.import_module(fallback_mod)
                    load_error = None
                    mod_name = fallback_mod
                except Exception as e2:
                    load_error = e2

        if loaded_mod is None:
            logger.exception(
                f"[TENANT_FAILED] Gagal memuat modul tenant '{tenant_id}' ({cfg.get('name')}): {load_error}"
            )
            TENANT_STATUS[tenant_id] = {
                "name": cfg.get("name", tenant_id),
                "status": "degraded",
                "module": mod_name,
                "error": str(load_error),
                "loaded_at": None,
            }
            statuses[tenant_id] = "degraded"
            continue

        # 2. Daftarkan router tenant ke aplikasi
        try:
            if register_func_name:
                reg_func = getattr(loaded_mod, register_func_name, None)
                if not callable(reg_func):
                    raise AttributeError(f"Registration function '{register_func_name}' tidak ditemukan di {mod_name}")
                
                if pass_session and session_factory is not None:
                    reg_func(app, session_factory)
                else:
                    reg_func(app)

            elif routes_attr:
                routes = getattr(loaded_mod, routes_attr, None)
                if routes is None:
                    raise AttributeError(f"Routes attribute '{routes_attr}' tidak ditemukan di {mod_name}")
                app.add_routes(routes)

            else:
                raise ValueError(f"Konfigurasi tenant '{tenant_id}' tidak memiliki register_func atau routes_attr")

            TENANT_STATUS[tenant_id] = {
                "name": cfg.get("name", tenant_id),
                "status": "active",
                "module": mod_name,
                "error": None,
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }
            statuses[tenant_id] = "active"
            logger.info(f"[TENANT_OK] Berhasil mendaftarkan tenant: {tenant_id} ({cfg.get('name')})")

        except Exception as reg_err:
            logger.exception(
                f"[TENANT_FAILED] Gagal mendaftarkan route tenant '{tenant_id}' ({cfg.get('name')}): {reg_err}"
            )
            TENANT_STATUS[tenant_id] = {
                "name": cfg.get("name", tenant_id),
                "status": "degraded",
                "module": mod_name,
                "error": str(reg_err),
                "loaded_at": None,
            }
            statuses[tenant_id] = "degraded"

    return statuses


def sanitize_error_summary(err_str: Optional[str]) -> Optional[str]:
    """Sanitasi error string agar tidak membocorkan full stack trace, path lokal, atau token/secrets ke publik."""
    if not err_str:
        return None
    
    # Ambil baris pertama atau nama exception jika ada multiline stack trace
    lines = [line.strip() for line in str(err_str).strip().splitlines() if line.strip()]
    if not lines:
        return None
    
    # Cari baris yang menunjukkan nama error utama (misal: 'ModuleNotFoundError:', dsb.)
    summary = lines[0]
    for line in reversed(lines):
        if any(line.startswith(prefix) for prefix in ("ModuleNotFoundError:", "ImportError:", "AttributeError:", "ValueError:", "TypeError:", "RuntimeError:", "Exception:")):
            summary = line
            break
    
    # Bersihkan path lokal OS
    import re
    cleaned = re.sub(r"[A-Za-z]:\\[^ :'\"]+", "<internal_path>", summary)
    cleaned = re.sub(r"/[a-zA-Z0-9_\-\.\/]+", "<internal_path>", cleaned)
    
    return cleaned[:200]


def get_tenant_statuses() -> Dict[str, str]:
    """Mengembalikan ringkasan status per-tenant (misal: {'career': 'active', 'om_budi': 'active'})."""
    if not TENANT_STATUS:
        return {k: "pending" for k in TENANT_REGISTRY}
    return {k: v.get("status", "unknown") for k, v in TENANT_STATUS.items()}


def get_tenant_details(public_safe: bool = True) -> Dict[str, Any]:
    """Mengembalikan rincian lengkap seluruh tenant dan status runtime-nya.
    Jika public_safe=True, stack trace dan path internal disanitasi agar tidak bocor ke publik.
    """
    raw_status = TENANT_STATUS or {
        k: {
            "name": v.get("name", k),
            "status": "pending",
            "module": v.get("module", ""),
            "error": None,
            "loaded_at": None,
        }
        for k, v in TENANT_REGISTRY.items()
    }
    
    details: Dict[str, Any] = {}
    for k, v in raw_status.items():
        st = v.get("status", "unknown")
        # Standardized health indicator: healthy, degraded, or down
        health = "healthy" if st == "active" else ("down" if st == "disabled" else "degraded")
        err = sanitize_error_summary(v.get("error")) if public_safe else v.get("error")
        
        details[k] = {
            "name": v.get("name", k),
            "status": st,
            "health": health,
            "module": v.get("module", ""),
            "error": err,
            "loaded_at": v.get("loaded_at"),
        }
    return details
