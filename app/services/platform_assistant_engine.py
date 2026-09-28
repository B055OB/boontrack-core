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
ASSISTANT_NAME_EN = "BoonTrack Business Concierge — Enterprise Orchestration & Digital Solutions PT Boontrack Inovasi Digital"

FOOTER_HELP_TEXT = "Ketik 'BANTUAN' untuk berbicara langsung dengan tim representatif kami."
FOOTER_HELP_TEXT_EN = "Type 'HELP' to connect directly with our human representative."

# Rule-based regex patterns for English language detection
ENGLISH_PATTERNS = [
    r"\bhello\b",
    r"\bhi\b",
    r"\bhey\b",
    r"\bhi\s+boontrack\b",
    r"\binterested\b",
    r"\bactivation\b",
    r"\benglish\b",
    r"\benterprise\s+solutions?\b",
    r"\bcustom\s+app\b",
    r"\bpricing\b",
    r"\bfeatures?\b",
    r"\bhow\s+to\b",
    r"\bwhat\s+is\b",
    r"\bhelp\b",
]


def detect_language(text: str) -> str:
    """
    Rule-based language detector for inbound messages.
    Returns 'en' if English greeting, prefilled inquiry, or keywords are matched,
    otherwise defaults to 'id'.
    """
    if not text or not isinstance(text, str):
        return "id"
    lower = text.lower()
    for pattern in ENGLISH_PATTERNS:
        if re.search(pattern, lower):
            return "en"
    return "id"


class PlatformAssistantEngine:
    """
    Official Platform Assistant Engine serving inbound conversations on the official WABA number.
    Ensures strict adherence to Meta Cloud API policies and ADR REV-1 security contracts.
    """

    def __init__(self):
        self.name = ASSISTANT_NAME
        self.name_en = ASSISTANT_NAME_EN

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
        lines.append("Untuk pendaftaran, rancang otomatisasi, & simulasi pilot gratis 14 hari, silakan isi formulir resmi kami di:")
        lines.append("👉 https://boontrack.com/onboarding")
        return "\n".join(lines)

    def _format_catalog_reply_en(self, catalog_data: Optional[Dict[str, Any]] = None) -> str:
        lines = [
            f"Hello! I am the *{self.name_en}*.",
            "",
            "Here is the official solutions portfolio of the BoonTrack enterprise platform:",
            "1. *BoonTrack Platform Orchestration*",
            "   Unified enterprise digital orchestration for multi-channel integration, automated workflow state machines, and real-time transaction processing.",
            "2. *WhatsApp Business API (Official Meta WABA)*",
            "   Official high-speed Meta Cloud API integration with verified green badge, interactive messaging (CTA/Quick Reply), and enterprise SLA.",
            "3. *BoonTrack POS (Point of Sale)*",
            "   Smart multi-outlet cloud POS system for retail & FnB with centralized catalog management and automated payment reconciliation.",
            "4. *IoT Doorlock & Smart Access Control*",
            "   Hardware-to-cloud access control with dynamic QR Code and RFID for gyms, co-working spaces, and modern offices.",
            "5. *BoonTrack Shop (Commerce Engine)*",
            "   Sub-second instant e-commerce storefront for physical and digital goods with WhatsApp checkout and automated QRIS payments.",
            "",
            "To register, design custom automations, & access your 14-day free pilot simulation, please complete our official form at:",
            "👉 https://boontrack.com/onboarding?lang=en",
        ]
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
            "Ada yang bisa kami bantu seputar solusi orkestrasi bisnis, aktivasi akun, integrasi WhatsApp Business API, atau layanan BoonTrack Shop hari ini?\n\n"
            "Untuk pendaftaran, rancang otomatisasi, & simulasi pilot gratis 14 hari, silakan isi formulir resmi kami di:\n"
            "👉 https://boontrack.com/onboarding"
        )

    def _format_general_greeting_en(self) -> str:
        return (
            f"Hello! I am the *{self.name_en}*.\n\n"
            "How can we assist you with enterprise business orchestration, account activation, WhatsApp Business API integration, or BoonTrack Shop solutions today?\n\n"
            "To register, design custom automations, & access your 14-day free pilot simulation, please complete our official form at:\n"
            "👉 https://boontrack.com/onboarding?lang=en"
        )

    def _format_kelasbos_consulting_reply(self, data: Dict[str, Any]) -> str:
        """
        Formats response with Fahami Digital Concierge persona:
        - Tone: Profesional, direct, edukatif, orientasi konsultasi bisnis.
        - Strict Guard: Fixed prices (no modification), only AVAILABLE slots.
        """
        services = data.get("services", [])
        slots = data.get("available_slots", [])
        booking_url = data.get("booking_url", "https://shop.boontrack.com/kelasbos")

        lines = [
            "Halo! Saya *Concierge Konsultasi Bisnis Kelas Bos (Fahami Digital)*.",
            "",
            "Kami mendampingi pelaku bisnis, UKM, dan brand untuk scale-up melalui perbaikan funnel konversi, sistem automasi WhatsApp, dan strategi paid traffic berbasis data nyata.",
            "",
            "📋 *Paket Layanan Konsultasi & Mentoring Resmi:*",
        ]

        for idx, s in enumerate(services, 1):
            price_val = int(s.get("price") or s.get("promo_price") or 0)
            cost_str = f"Rp {price_val:,}".replace(",", ".")
            title = s.get("title") or s.get("name")
            desc = s.get("description", "")
            lines.append(f"{idx}. *{title}* — {cost_str}")
            if desc:
                lines.append(f"   _{desc[:95]}..._" if len(desc) > 95 else f"   _{desc}_")

        lines.append("")
        lines.append("🗓️ *Jadwal Sesi Tersedia (Status: AVAILABLE):*")
        
        if slots:
            # Show up to 4 available upcoming slots
            for slot in slots[:4]:
                s_date = str(slot.get("slot_date"))
                s_time = slot.get("start_time")
                lines.append(f"• Tanggal {s_date}, Pukul {s_time} WIB (Tersedia)")
        else:
            lines.append("• Slot konsultasi minggu ini dapat dipilih langsung melalui kalender etalase.")

        lines.append("")
        lines.append("🔒 *Alur Pemesanan & Penguncian Slot:*")
        lines.append("1. Kunjungi etalase resmi:")
        lines.append(f"   👉 {booking_url}")
        lines.append("2. Pilih paket dan tentukan tanggal & jam sesi yang masih AVAILABLE.")
        lines.append("3. Lengkapi formulir & selesaikan pembayaran QRIS untuk mengunci slot (BOOKED).")
        lines.append("")
        lines.append("_Catatan: Seluruh tarif layanan bersifat tetap sesuai katalog resmi dan slot sesi dikunci otomatis setelah verifikasi pembayaran._")

        return "\n".join(lines).strip()

    async def generate_response(
        self,
        user_text: str,
        context: TrustedSessionContext,
        is_first_message: bool = False,
    ) -> str:
        """
        Generates conversational response using intent routing, public read tools via gateway,
        and Meta compliance formatting with dual-language (ID/EN) support.
        """
        clean_text = user_text.strip()
        lower_text = clean_text.lower()
        lang = detect_language(clean_text)
        logger.info(f"[PLATFORM_ASSISTANT] Processing inquiry ({lang}) for context {context.context_id}: '{clean_text[:60]}'")

        reply_body = ""

        # Intent -1: Storefront Context-Aware Sales Tag (Ref: tenant#product)
        from app.services.waba_sales_service import (
            extract_storefront_ref,
            get_storefront_product_context,
            build_context_aware_first_response
        )
        ref_match = extract_storefront_ref(clean_text)
        if ref_match:
            t_slug, p_slug = ref_match
            storefront_ctx = get_storefront_product_context(t_slug, p_slug)
            if storefront_ctx:
                return build_context_aware_first_response(storefront_ctx)

        # Intent 0: Kelas Bos / Business Consulting Inquiry (Tenant Concierge)
        kelasbos_keywords = [
            "kelasbos", "kelas bos", "fahami", "fahami digital", "konsultasi bisnis",
            "audit funnel", "audit bisnis", "mentoring bisnis", "jadwal konsultasi",
            "booking kelas", "booking sesi", "scale up bisnis"
        ]
        is_kelasbos_context = (
            any(kw in lower_text for kw in kelasbos_keywords) or
            context.metadata.get("tenant_slug") == "kelasbos"
        )
        if is_kelasbos_context:
            consulting_data = execute_public_tool(
                "get_tenant_consulting_catalog_and_slots",
                context=context,
                tenant_slug="kelasbos"
            )
            reply_body = self._format_kelasbos_consulting_reply(consulting_data)

        # Intent 1: Catalog & Solutions Inquiry (Bilingual keywords)
        elif (
            any(kw in lower_text for kw in [
                "katalog", "solusi", "layanan", "fitur", "produk", "pos", "iot",
                "doorlock", "shop", "waba", "whatsapp", "paket", "harga", "kelebihan",
                "catalog", "solutions", "solution", "portfolio", "features", "products", "pricing", "services", "interested"
            ])
        ):
            if lang == "en":
                reply_body = self._format_catalog_reply_en()
            else:
                catalog_data = execute_public_tool("get_public_solution_catalog", context=context)
                reply_body = self._format_catalog_reply(catalog_data)

        # Intent 2: Shipping Rate Inquiry
        elif any(kw in lower_text for kw in ["ongkir", "tarif", "pengiriman", "ekspedisi", "ongkos kirim", "shipping"]):
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
            if lang == "en":
                reply_body = self._format_general_greeting_en()
            else:
                reply_body = self._format_general_greeting()

        # Meta Compliance Policy: Append assistance footer on first message
        if is_first_message:
            footer = FOOTER_HELP_TEXT_EN if lang == "en" else FOOTER_HELP_TEXT
            reply_body = f"{reply_body}\n\n{footer}"

        return reply_body.strip()


# Module-level singleton
platform_assistant_engine = PlatformAssistantEngine()
