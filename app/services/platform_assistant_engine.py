"""app/services/platform_assistant_engine.py
-----------------------------------------
Platform Assistant Engine (BoonTrack Business Concierge).

ADR REV-1 Compliant:
- Persona: BoonTrack Business Concierge — Layanan Orkestrasi & Solusi Digital PT Boontrack Inovasi Digital.
- Context: Enforces TrustedSessionContext (role=ANONYMOUS, ownership_domain="PLATFORM").
- Tool Calling: All read queries route through ToolExecutionGateway via public_read_tools.
- Meta Compliance: Polite, concise, professional Indonesian, with assistance footer on first message.
"""

from __future__ import annotations

import os
import re
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from app.schemas.rev1_contracts import (
    RoleEnum,
    TrustedSessionContext,
)
from app.services.tools.public_read_tools import execute_public_tool
from app.core.rev1.exceptions import PermissionDeniedError, AuthorizationError

logger = logging.getLogger("PLATFORM_ASSISTANT_ENGINE")

# Well-known Platform Tenant UUID (constant invariant)
PLATFORM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")

ASSISTANT_NAME = "BoonTrack Business Concierge — Layanan Orkestrasi & Solusi Digital PT Boontrack Inovasi Digital"
FOOTER_HELP_TEXT = "Ketik 'BANTUAN' untuk berbicara langsung dengan tim representatif kami."


class PlatformAssistantEngine:
    """
    Official Platform Assistant Engine serving inbound conversations on the official WABA number.
    Ensures strict adherence to Meta Cloud API policies and ADR REV-1 security contracts.
    """

    def __init__(self):
        self.name = ASSISTANT_NAME

    def _format_catalog_reply(self, catalog_data: Dict[str, Any]) -> str:
        solutions = catalog_data.get("solutions", [])
        lines = [
            f"Halo! Saya *{self.name}*.",
            "",
            "Berikut adalah portofolio solusi resmi platform BoonTrack:",
        ]
        for idx, s in enumerate(solutions, 1):
            lines.append(f"{idx}. *{s['name']}*")
            lines.append(f"   {s['description']}")
        lines.append("")
        lines.append("Untuk pendaftaran & info kemitraan lengkap, kunjungi: https://boontrack.com atau https://shop.boontrack.com")
        return "\n".join(lines)

    def _format_shipping_reply(self, rates_data: Dict[str, Any]) -> str:
        origin = rates_data.get("origin")
        destination = rates_data.get("destination")
        weight_kg = rates_data.get("weight_kg", 1)
        rates = rates_data.get("rates", [])

        lines = [
            f"📦 *Estimasi Tarif Pengiriman Publik ({origin} ➔ {destination})*",
            f"Berat hitung: {weight_kg} kg",
            "",
        ]
        for r in rates:
            cost_str = f"Rp {r['cost']:,}".replace(",", ".")
            lines.append(f"• *{r['courier']}* ({r['service']}): {cost_str} (Estimasi: {r['etd']})")
        lines.append("")
        lines.append(rates_data.get("notes", "Tarif resmi acuan publik BoonTrack."))
        return "\n".join(lines)

    def _format_jobs_reply(self, jobs_data: Dict[str, Any]) -> str:
        jobs = jobs_data.get("jobs", [])
        lines = [
            "💼 *Peluang Karir Resmi Ekosistem BoonTrack*",
            f"Ditemukan {len(jobs)} posisi terbuka:",
            "",
        ]
        for j in jobs:
            lines.append(f"• *{j['title']}* ({j['type']})")
            lines.append(f"  Divisi: {j['department']} | Lokasi: {j['location']}")
            lines.append(f"  Kualifikasi: {j['requirements']}")
            lines.append("")
        lines.append(f"Kirim CV dan portofolio Anda ke: {jobs_data.get('contact_hr', 'hr@boontrack.com')}")
        lines.append(f"Portal resmi: {jobs_data.get('application_portal', 'https://careers.boontrack.com')}")
        return "\n".join(lines).strip()

    def _format_general_greeting(self) -> str:
        return (
            f"Halo! Saya *{self.name}*.\n\n"
            "Ada yang bisa kami bantu seputar solusi orkestrasi bisnis, aktivasi akun, integrasi WhatsApp Business API, atau layanan BoonTrack Shop hari ini?"
        )

    async def generate_response(
        self,
        user_text: str,
        context: TrustedSessionContext,
        is_first_message: bool = False,
    ) -> str:
        """
        Generates conversational response using intent routing, public read tools via gateway,
        and Meta compliance formatting.
        """
        clean_text = user_text.strip()
        lower_text = clean_text.lower()
        logger.info(f"[PLATFORM_ASSISTANT] Processing inquiry for context {context.context_id}: '{clean_text[:60]}'")

        reply_body = ""

        # Intent 1: Catalog & Solutions Inquiry
        catalog_keywords = [
            "katalog", "solusi", "layanan", "fitur", "produk", "pos", "iot",
            "doorlock", "shop", "waba", "whatsapp", "paket", "harga", "kelebihan"
        ]
        if any(kw in lower_text for kw in catalog_keywords):
            catalog_data = execute_public_tool("get_public_solution_catalog", context=context)
            reply_body = self._format_catalog_reply(catalog_data)

        # Intent 2: Shipping Rate Inquiry
        elif any(kw in lower_text for kw in ["ongkir", "tarif", "pengiriman", "ekspedisi", "ongkos kirim"]):
            # Heuristic extraction of cities
            origin = "Jakarta"
            destination = "Bandung" if "bandung" in lower_text else ("Surabaya" if "surabaya" in lower_text else "Jakarta")
            weight = 1000
            
            weight_match = re.search(r"(\d+)\s*(?:kg|kilo|gram|g)", lower_text)
            if weight_match:
                val = int(weight_match.group(1))
                weight = val * 1000 if "kg" in weight_match.group(0) or "kilo" in weight_match.group(0) else val

            rates_data = execute_public_tool(
                "check_shipping_rates",
                context=context,
                origin=origin,
                destination=destination,
                weight=weight,
            )
            reply_body = self._format_shipping_reply(rates_data)

        # Intent 3: Job & Career Inquiry
        elif any(kw in lower_text for kw in ["loker", "karir", "career", "lowongan", "kerja", "rekrutmen"]):
            keyword = ""
            if "engineer" in lower_text or "tech" in lower_text or "developer" in lower_text:
                keyword = "Engineer"
            elif "cs" in lower_text or "support" in lower_text or "operasi" in lower_text:
                keyword = "Operations"
            
            jobs_data = execute_public_tool("search_public_jobs", context=context, keyword=keyword)
            reply_body = self._format_jobs_reply(jobs_data)

        # Intent 4: General Greeting or Inquiry
        else:
            reply_body = self._format_general_greeting()

        # Meta Compliance Policy: Append assistance footer on first message
        if is_first_message:
            reply_body = f"{reply_body}\n\n{FOOTER_HELP_TEXT}"

        return reply_body.strip()


# Module-level singleton
platform_assistant_engine = PlatformAssistantEngine()
