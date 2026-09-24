"""app/services/tools/public_read_tools.py
-----------------------------------------
Public READ tools for BoonTrack Platform Assistant.

ADR REV-1 Compliant:
- Classification: READ tools (no side effects, read-only).
- Permission: PUBLIC_ASSISTANT_ALLOWED (ANONYMOUS, TENANT_USER, TENANT_ADMIN, PLATFORM_ADMIN, SUPPORT_AGENT).
- Tenant Scope: requires_tenant_scope=False (public platform tools).
- Enforcement: ALL tools must pass through ToolExecutionGateway.
- Invariant: Zero raw SQL directly to private tenant tables.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from app.schemas.rev1_contracts import (
    RoleEnum,
    ToolExecutionPermission,
    ToolType,
    TrustedSessionContext,
)
from app.core.rev1.gateway import ToolExecutionGateway
from app.core.rev1.exceptions import PermissionDeniedError, AuthorizationError

logger = logging.getLogger("PUBLIC_READ_TOOLS")

# =============================================================================
# 1. Allowed Roles & Permission Definitions
# =============================================================================

PUBLIC_ASSISTANT_ALLOWED: List[RoleEnum] = [
    RoleEnum.ANONYMOUS,
    RoleEnum.TENANT_USER,
    RoleEnum.TENANT_ADMIN,
    RoleEnum.PLATFORM_ADMIN,
    RoleEnum.SUPPORT_AGENT,
]


# =============================================================================
# 2. Tool Implementations (Zero Raw SQL, Pure Read-Only Logic)
# =============================================================================

def get_public_solution_catalog() -> Dict[str, Any]:
    """
    Menjelaskan layanan platform orkestrasi BoonTrack, integrasi WhatsApp Business API,
    POS, IoT Doorlock, dan BoonTrack Shop.
    """
    logger.info("[PUBLIC_TOOL] Executing get_public_solution_catalog")
    return {
        "status": "success",
        "title": "Katalog Solusi Resmi BoonTrack (PT Boontrack Inovasi Digital)",
        "solutions": [
            {
                "id": "platform_orchestration",
                "name": "BoonTrack Platform Orchestration",
                "description": (
                    "Layanan orkestrasi bisnis digital terpadu untuk integrasi multi-channel, "
                    "otomatisasi alur kerja, pengelolaan inventori terpusat, dan kepatuhan audit Meta WABA."
                ),
                "features": [
                    "Isolasi multi-tenant berkategori Enterprise",
                    "Transactional Outbox Dispatcher (anti-duplikasi kirim pesan)",
                    "Audit log & event streaming real-time"
                ],
            },
            {
                "id": "waba_integration",
                "name": "WhatsApp Business API (Official Meta WABA)",
                "description": (
                    "Integrasi resmi WhatsApp Cloud API (v26.0) dengan verifikasi Meta Business Manager, "
                    "centang hijau resmi, pesan interaktif (CTA/Quick Reply), dan SLA pengiriman tinggi."
                ),
                "features": [
                    "Meta Cloud API v26.0 Direct Provider",
                    "Automated 24-hour service window compliance",
                    "Deterministic verification & activation engine"
                ],
            },
            {
                "id": "pos_system",
                "name": "BoonTrack POS (Point of Sale)",
                "description": (
                    "Sistem kasir pintar multi-outlet untuk ritel dan FnB dengan pencatatan transaksi offline/online, "
                    "sinkronisasi katalog terpusat, dan auto-reconciliation pembayaran."
                ),
                "features": [
                    "Multi-outlet & multi-kasir real-time sync",
                    "Manajemen stok bahan baku & produk jadi",
                    "Laporan penjualan & akuntansi otomatis"
                ],
            },
            {
                "id": "iot_doorlock",
                "name": "IoT Doorlock & Smart Access Control",
                "description": (
                    "Solusi kontrol akses pintar IoT berbasis QR Code dinamis dan RFID untuk gym, "
                    "co-working space, dan kantor modern yang terintegrasi otomatis dengan membership."
                ),
                "features": [
                    "Akses masuk instan via scan QR dinamis WhatsApp/App",
                    "Integrasi turnstile barrier & magnetic doorlock",
                    "Sinkronisasi status membership & langganan aktif"
                ],
            },
            {
                "id": "boontrack_shop",
                "name": "BoonTrack Shop (Social Commerce)",
                "description": (
                    "Platform toko online instan untuk merchant UMKM & brand dengan alur checkout WhatsApp terpadu, "
                    "verifikasi pembayaran QRIS otomatis 0% fee platform, dan pelacakan iklan Meta CAPI."
                ),
                "features": [
                    "Checkout instan tanpa registrasi panjang",
                    "Verifikasi QRIS real-time otomatis",
                    "Server-Side Tracking bawaan (Meta CAPI & GTM DataLayer)"
                ],
            },
        ],
        "contact": {
            "website": "https://boontrack.com",
            "shop_portal": "https://shop.boontrack.com",
            "support_email": "support@boontrack.com",
        },
    }


def check_shipping_rates(origin: str, destination: str, weight: int) -> Dict[str, Any]:
    """
    Kalkulasi estimasi tarif ekspedisi publik (JNE, SiCepat, J&T).
    weight dalam gram (minimal 1 gram).
    """
    logger.info(f"[PUBLIC_TOOL] Executing check_shipping_rates: {origin} -> {destination} ({weight}g)")
    origin_clean = str(origin or "Jakarta").strip().title()
    dest_clean = str(destination or "Jakarta").strip().title()
    
    try:
        weight_clean = max(1, int(weight))
    except (ValueError, TypeError):
        weight_clean = 1000

    # Kalkulasi tarif berbasis berat pembulatan kg (tarif acuan Jabodetabek / Antarkota)
    weight_kg = (weight_clean + 999) // 1000  # Ceiling per kg
    is_same_city = (origin_clean.lower() == dest_clean.lower())

    base_jne = 9000 if is_same_city else 14000
    base_sicepat = 8500 if is_same_city else 13500
    base_jnt = 9500 if is_same_city else 15000

    rates = [
        {
            "courier": "SiCepat",
            "service": "SIUNT (Reguler)",
            "etd": "1-2 Hari" if is_same_city else "2-3 Hari",
            "cost": base_sicepat * weight_kg,
            "weight_charged_kg": weight_kg,
        },
        {
            "courier": "JNE",
            "service": "REG (Reguler)",
            "etd": "1-2 Hari" if is_same_city else "2-3 Hari",
            "cost": base_jne * weight_kg,
            "weight_charged_kg": weight_kg,
        },
        {
            "courier": "J&T",
            "service": "EZ (Reguler)",
            "etd": "1-2 Hari" if is_same_city else "2-3 Hari",
            "cost": base_jnt * weight_kg,
            "weight_charged_kg": weight_kg,
        },
    ]

    return {
        "status": "success",
        "origin": origin_clean,
        "destination": dest_clean,
        "weight_grams": weight_clean,
        "weight_kg": weight_kg,
        "rates": rates,
        "notes": "Estimasi tarif publik resmi. Tarif aktual dapat bervariasi bergantung pada dimensi dan asuransi pengiriman.",
    }


def search_public_jobs(keyword: str = "") -> Dict[str, Any]:
    """
    Menampilkan daftar lowongan resmi di ekosistem BoonTrack.
    """
    logger.info(f"[PUBLIC_TOOL] Executing search_public_jobs with keyword: '{keyword}'")
    official_openings = [
        {
            "id": "JOB-ENG-01",
            "title": "Senior Staff Software Architect",
            "department": "Platform Core Engineering",
            "location": "Jakarta / Hybrid",
            "type": "Full-Time",
            "requirements": "Python 3.12+, Distributed Systems, PostgreSQL Multi-Tenant, High-Concurrency Webhooks, Event-Driven Architecture.",
        },
        {
            "id": "JOB-AI-02",
            "title": "AI & Agentic Systems Engineer",
            "department": "AI & Innovation Labs",
            "location": "Jakarta / Remote",
            "type": "Full-Time",
            "requirements": "LLM Orchestration, Prompt Guardrails, Tool Calling Gateway, Meta Cloud API Conversational Concierge.",
        },
        {
            "id": "JOB-OPS-03",
            "title": "Customer Success & Operations Specialist",
            "department": "Client Experience",
            "location": "Jakarta / On-site",
            "type": "Full-Time",
            "requirements": "Pengalaman onboarding merchant UMKM/Enterprise, penanganan tiket eskalasi WABA, pemahaman SLA.",
        },
        {
            "id": "JOB-IOT-04",
            "title": "IoT & Smart Hardware Integration Engineer",
            "department": "IoT Hardware Infrastructure",
            "location": "Bandung / Hybrid",
            "type": "Full-Time",
            "requirements": "Firmware ESP32, MQTT/TCP protocols, integrasi turnstile & magnetic doorlock, edge synchronization.",
        },
    ]

    kw_clean = str(keyword or "").strip().lower()
    if not kw_clean or kw_clean in ("all", "semua", "*"):
        matched = official_openings
    else:
        matched = [
            job for job in official_openings
            if kw_clean in job["title"].lower()
            or kw_clean in job["department"].lower()
            or kw_clean in job["requirements"].lower()
        ]

    return {
        "status": "success",
        "keyword": keyword,
        "total_found": len(matched),
        "jobs": matched,
        "application_portal": "https://careers.boontrack.com",
        "contact_hr": "hr@boontrack.com",
    }


# =============================================================================
# 3. Tool Permissions Registry & Gateway Dispatcher
# =============================================================================

PUBLIC_TOOL_REGISTRY: Dict[str, ToolExecutionPermission] = {
    "get_public_solution_catalog": ToolExecutionPermission(
        tool_name="get_public_solution_catalog",
        tool_type=ToolType.READ,
        allowed_roles=PUBLIC_ASSISTANT_ALLOWED,
        requires_tenant_scope=False,
    ),
    "check_shipping_rates": ToolExecutionPermission(
        tool_name="check_shipping_rates",
        tool_type=ToolType.READ,
        allowed_roles=PUBLIC_ASSISTANT_ALLOWED,
        requires_tenant_scope=False,
    ),
    "search_public_jobs": ToolExecutionPermission(
        tool_name="search_public_jobs",
        tool_type=ToolType.READ,
        allowed_roles=PUBLIC_ASSISTANT_ALLOWED,
        requires_tenant_scope=False,
    ),
}

PUBLIC_TOOL_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "get_public_solution_catalog": get_public_solution_catalog,
    "check_shipping_rates": check_shipping_rates,
    "search_public_jobs": search_public_jobs,
}


def execute_public_tool(
    tool_name: str,
    context: TrustedSessionContext,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Executes a public READ tool strictly through ToolExecutionGateway.
    Enforces RBAC and scope invariant checks.
    """
    if tool_name not in PUBLIC_TOOL_REGISTRY:
        raise ValueError(f"Unknown public tool: '{tool_name}'")

    permission = PUBLIC_TOOL_REGISTRY[tool_name]
    executor_func = PUBLIC_TOOL_FUNCTIONS[tool_name]

    return ToolExecutionGateway.execute_tool(
        context=context,
        permission=permission,
        target_tenant_id=None,
        executor_func=executor_func,
        *args,
        **kwargs,
    )
