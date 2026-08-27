"""Tenant Dynamic Loader & Fault Isolation Engine.

Menjamin proses registrasi tenant bersifat modular, dynamic, dan terisolasi.
Jika salah satu tenant mengalami ImportError, syntax error, atau runtime crash saat startup,
tenant lain dan server utama TETAP BOOTSTRAP dan BERJALAN NORMAL (Zero Cascade Crash).
"""

import os
import json
import importlib
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from aiohttp import web

from app.schemas.tenant_config import TenantConfig, TenantStatus
from app.engines.generic_tenant_engine import generic_tenant_engine, GenericTenantEngine
from app.services.whatsapp_service import send_whatsapp_text, send_whatsapp_image_link

logger = logging.getLogger("TENANT_LOADER")

TENANT_CONFIG_DIR = os.getenv(
    "TENANTS_CONFIG_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "tenants")
)

# Registry tenant berbasis konfigurasi (Sprint B)
LOADED_CONFIG_TENANTS: Dict[str, TenantConfig] = {}

TENANT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "gym": {
        "name": "Atmosfitnes Gym Assistant",
        "module": "app.tenants.gym.router",
        "register_func": "register_gym_routes",
        "description": "Smart Gym & IoT Turnstile WhatsApp Assistant",
        "enabled": True,
    },
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


def load_tenant_configs(config_dir: Optional[str] = None) -> Dict[str, TenantConfig]:
    """Memuat seluruh file konfigurasi tenant dari direktori JSON/YAML.
    Jika satu config corrupt / invalid schema, error diisolasi dan dicatat tanpa mematikan server.
    """
    target_dir = config_dir or TENANT_CONFIG_DIR
    configs: Dict[str, TenantConfig] = {}

    if not os.path.exists(target_dir):
        logger.info(f"[TENANT_CONFIG] Folder konfigurasi tidak ditemukan: {target_dir}")
        return configs

    for fname in sorted(os.listdir(target_dir)):
        stem, ext = os.path.splitext(fname)
        ext_lower = ext.lower()
        if ext_lower not in (".json", ".yaml", ".yml"):
            continue

        file_path = os.path.join(target_dir, fname)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if ext_lower == ".json":
                raw_data = json.loads(content)
            else:
                try:
                    import yaml
                    raw_data = yaml.safe_load(content)
                except ImportError:
                    raise RuntimeError("PyYAML tidak terinstal untuk memproses file konfigurasi YAML")

            tenant_cfg = TenantConfig.model_validate(raw_data)
            t_id = tenant_cfg.identity.tenant_id
            configs[t_id] = tenant_cfg
            LOADED_CONFIG_TENANTS[t_id] = tenant_cfg
            logger.info(f"[TENANT_CONFIG_OK] Berhasil memvalidasi config tenant '{t_id}' dari {fname}")

        except Exception as err:
            logger.error(f"[TENANT_CONFIG_ERROR] Gagal memuat file konfigurasi '{fname}': {err}")
            TENANT_STATUS[stem] = {
                "name": stem,
                "status": "degraded",
                "health": "degraded",
                "module": f"config:{fname}",
                "error": str(err),
                "loaded_at": None,
            }

    return configs


def register_config_driven_tenant_routes(
    app: web.Application,
    tenant_cfg: TenantConfig,
    engine: Optional[GenericTenantEngine] = None
) -> bool:
    """Mendaftarkan endpoint webhook WhatsApp secara dinamis untuk tenant berbasis konfigurasi."""
    exec_engine = engine or generic_tenant_engine
    tenant_id = tenant_cfg.identity.tenant_id
    verify_token = tenant_cfg.get_verify_token()

    # Periksa route yang sudah terdaftar di aplikasi untuk menghindari duplikasi
    existing_paths = set()
    for r in app.router.routes():
        info = r.get_info()
        path = info.get("path") or info.get("formatter")
        if path:
            existing_paths.add((r.method, path))

    async def dynamic_wa_verify_handler(request: web.Request) -> web.Response:
        mode = request.query.get("hub.mode")
        token = request.query.get("hub.verify_token")
        challenge = request.query.get("hub.challenge")

        if mode == "subscribe" and token == verify_token:
            logger.info(f"[CONFIG_TENANT:{tenant_id}] Webhook verified successfully (challenge: {challenge})")
            return web.Response(text=challenge or "", status=200)

        logger.warning(f"[CONFIG_TENANT:{tenant_id}] Webhook verification failed (expected: {verify_token}, got: {token})")
        return web.Response(text="Verification token mismatch", status=403)

    async def dynamic_wa_event_handler(request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception as e:
            logger.error(f"[CONFIG_TENANT:{tenant_id}] Invalid JSON payload: {e}")
            return web.json_response({"status": "invalid_json"}, status=200)

        # Tangkap dan isolasi error runtime lokal
        try:
            entries = payload.get("entry", [])
            for entry in entries:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    # Status ack update dari Meta
                    if "statuses" in value:
                        continue

                    # Pesan WhatsApp masuk
                    for msg in value.get("messages", []):
                        sender = str(msg.get("from", "")).strip()
                        msg_type = msg.get("type", "text")
                        
                        incoming_text = ""
                        if msg_type == "text":
                            incoming_text = msg.get("text", {}).get("body", "")
                        elif msg_type == "button":
                            incoming_text = msg.get("button", {}).get("payload", "") or msg.get("button", {}).get("text", "")
                        elif msg_type == "interactive":
                            interactive = msg.get("interactive", {})
                            btn_reply = interactive.get("button_reply", {})
                            incoming_text = btn_reply.get("id", "") or btn_reply.get("title", "")

                        # Eksekusi melalui Generic Tenant Engine
                        result = await exec_engine.handle_message(
                            tenant_config=tenant_cfg,
                            incoming_message=incoming_text,
                            user_id=sender
                        )

                        # Kirim respons ke user WhatsApp
                        action = result.get("action")
                        reply_text = result.get("text", "")
                        image_url = result.get("image_url")

                        if action == "SEND_QRIS" and image_url:
                            await send_whatsapp_image_link(
                                to=sender,
                                to_phone=sender,
                                image_url=image_url,
                                caption=reply_text,
                                tenant_id=tenant_id
                            )
                        elif reply_text:
                            await send_whatsapp_text(
                                to_phone=sender,
                                text=reply_text,
                                tenant_id=tenant_id
                            )

            return web.json_response({"status": "processed"}, status=200)

        except Exception as err:
            logger.exception(f"[CONFIG_TENANT:{tenant_id}] Error processing webhook message: {err}")
            # Selalu return 200 OK agar Meta tidak terus menerus retry
            return web.json_response({"status": "error_isolated", "tenant": tenant_id}, status=200)

    # Daftarkan route webhook jika belum pernah didaftarkan
    primary_webhook_path = f"/webhook/{tenant_id}/whatsapp"
    api_webhook_path = f"/api/v1/tenants/{tenant_id}/webhook/whatsapp"

    registered = False
    if ("GET", primary_webhook_path) not in existing_paths:
        app.router.add_get(primary_webhook_path, dynamic_wa_verify_handler)
        app.router.add_post(primary_webhook_path, dynamic_wa_event_handler)
        registered = True

    if ("GET", api_webhook_path) not in existing_paths:
        app.router.add_get(api_webhook_path, dynamic_wa_verify_handler)
        app.router.add_post(api_webhook_path, dynamic_wa_event_handler)
        registered = True

    return registered


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

    # 2. Muat tenant deklaratif tambahan berbasis file konfigurasi JSON/YAML (Sprint B)
    if registry is None:
        try:
            config_tenants = load_tenant_configs()
            for t_id, t_cfg in config_tenants.items():
                if t_cfg.is_active():
                    register_config_driven_tenant_routes(app, t_cfg)
                    if t_id not in TENANT_STATUS:
                        TENANT_STATUS[t_id] = {
                            "name": t_cfg.identity.name,
                            "status": "active",
                            "health": "healthy",
                            "module": f"config:{t_id}",
                            "error": None,
                            "loaded_at": datetime.now(timezone.utc).isoformat(),
                        }
                        statuses[t_id] = "active"
        except Exception as cfg_err:
            logger.error(f"[TENANT_CONFIG_FAILED] Error loading declarative tenant configs: {cfg_err}")

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
