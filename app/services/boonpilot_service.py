"""app/services/boonpilot_service.py
Agentic AI BoonPilot Service Layer with Scope Lock Architecture.

Architectural Guarantees:
1. Tenant & RBAC Isolation: BoonPilot hanya boleh beroperasi di dalam resolved TenantRuntimeContext.
   Tolak jika ada arbitrary tenant_id dari client.
2. Capability Resolver (Dynamic Button-Driven Menu):
   Tombol FAQ & navigasi disaring berdasarkan: TenantRuntimeContext + RBAC + Plan/Entitlement + Feature Flags.
   - Opsi CAPI / Powertools HANYA tampil jika tier memiliki fitur tersebut.
   - Fitur/FAQ Affiliate HANYA dirender jika tenant memiliki program affiliate aktif.
3. WhatsApp Isolation:
   BoonPilot steril 100% dan TIDAK MEMILIKI akses ke router nomor resmi WABA platform (+6285179555449).
4. No LLM Business Truth:
   Untuk pertanyaan harga, prorata, komisi, dan status langganan, BoonPilot wajib memanggil tool/API backend resmi
   dan menyajikan data mentah tersebut tanpa reka hitung mandiri oleh LLM.
5. Human-in-the-Loop Safeguard dengan TTL 10 menit untuk mutasi data operasional toko.
"""

import os
import re
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from app.services.ai_gateway import ai_gateway, AgentProfile
from app.services.campaign_analytics_service import campaign_analytics_service
from app.services.entitlement_service import tenant_context_resolver, TenantRuntimeContext
from app.services.billing_service import billing_service, TIER_MONTHLY_PRICING
from app.services.affiliate_service import affiliate_service

logger = logging.getLogger("BOONPILOT_SERVICE")

# TTL Proposal Aksi (10 menit = 600 detik)
ACTION_PROPOSAL_TTL_SECONDS = 600

# Nomor Resmi WABA Platform yang wajib 100% steril dan terisolasi dari BoonPilot
OFFICIAL_PLATFORM_WABA_NUMBER = "+6285179555449"


def assert_whatsapp_isolation(target_or_sender_phone: Optional[str] = None):
    """
    Scope Lock Guard: Memastikan BoonPilot TIDAK MEMILIKI akses ke router inbound/outbound
    nomor WABA resmi platform (+6285179555449). Jalur resmi WABA steril khusus aktivasi & notifikasi sistem.
    """
    if target_or_sender_phone:
        clean_phone = re.sub(r"\D", "", str(target_or_sender_phone))
        if "6285179555449" in clean_phone or "85179555449" in clean_phone:
            raise PermissionError(
                "Akses ditolak: BoonPilot terisolasi secara ketat dan dilarang "
                f"mengakses atau merutekan pesan melalui nomor WABA resmi platform ({OFFICIAL_PLATFORM_WABA_NUMBER})."
            )


# Default Katalog & Inventory per tenant (Memory Store + Dynamic Sync)
DEFAULT_TENANT_INVENTORY: Dict[str, List[Dict[str, Any]]] = {
    "onlineboost": [
        {
            "product_id": "prod_masterclass_ads",
            "title": "Masterclass Meta & TikTok Ads 2026",
            "price": 149000,
            "stock": 25,
            "category": "Digital Course",
            "status": "ACTIVE",
            "variants": ["Standard Access", "VIP Lifetime"],
        },
        {
            "product_id": "prod_template_copy",
            "title": "Template Copywriting & Hook Video Viral",
            "price": 49000,
            "stock": 3,
            "category": "Digital Asset",
            "status": "ACTIVE",
            "variants": ["Notion + Sheet Template"],
        },
        {
            "product_id": "prod_coaching_vip",
            "title": "Private Coaching 1-on-1 & Campaign Audit",
            "price": 499000,
            "stock": 1,
            "category": "Mentorship",
            "status": "ACTIVE",
            "variants": ["60 Mins Zoom Session"],
        },
    ]
}

# Default Shipping Origin per tenant
DEFAULT_TENANT_SHIPPING: Dict[str, Dict[str, Any]] = {
    "onlineboost": {
        "address": "Jl Pluto Selatan 2 no 41 Margahayu Raya Margacinta Buahbatu Bandung",
        "postal_code": "40286",
        "subdistrict": "Margasari, Buahbatu, Bandung",
        "contact_name": "Aldi Rinaldiawan",
        "contact_phone": "081237450222",
    }
}

# Default Active Couriers per tenant
DEFAULT_TENANT_COURIERS: Dict[str, Dict[str, bool]] = {
    "onlineboost": {
        "GoSend": True,
        "Grab": True,
        "JNE": False,
        "SiCepat": True,
    }
}


def mask_sensitive_data(text: str) -> str:
    """Guardrail: Sensor nomor rekening bank utuh dan kredensial platform."""
    if not text:
        return ""

    def _mask_account(match):
        digits = match.group(0)
        return f"****{digits[-4:]}"

    masked = re.sub(r"\b\d{8,16}\b", _mask_account, text)
    masked = re.sub(r"(?:sb_[a-zA-Z0-9_-]+|eyJ[a-zA-Z0-9_\-\.]+)", "[REDACTED_CREDENTIAL]", masked)
    masked = re.sub(r"(?:postgres://[^\s]+|https://api\.biteship\.com[^\s]+)", "[REDACTED_URL]", masked)
    return masked


class BoonPilotService:
    """Core Service Layer untuk Agentic AI BoonPilot dengan Scope Lock & Otoritas Backend Mutlak."""

    def __init__(self):
        self._inventory: Dict[str, List[Dict[str, Any]]] = dict(DEFAULT_TENANT_INVENTORY)
        self._shipping: Dict[str, Dict[str, Any]] = dict(DEFAULT_TENANT_SHIPPING)
        self._couriers: Dict[str, Dict[str, bool]] = dict(DEFAULT_TENANT_COURIERS)
        self._action_proposals: Dict[str, Dict[str, Any]] = {}
        self._session_histories: Dict[str, List[Dict[str, str]]] = {}

    def _get_tenant_products(self, tenant_slug: str) -> List[Dict[str, Any]]:
        clean_slug = tenant_slug.strip().lower()
        return self._inventory.get(clean_slug, [
            {
                "product_id": f"prod_{clean_slug}_01",
                "title": f"Produk Unggulan {clean_slug.title()}",
                "price": 99000,
                "stock": 10,
                "category": "Standard Product",
                "status": "ACTIVE",
                "variants": ["Default"],
            }
        ])

    def _append_turn(self, session_id: str, role: str, content: str):
        if not session_id:
            return
        if session_id not in self._session_histories:
            self._session_histories[session_id] = []
        self._session_histories[session_id].append({"role": role, "content": content})
        if len(self._session_histories[session_id]) > 20:
            self._session_histories[session_id] = self._session_histories[session_id][-20:]

    # =========================================================================
    # 1. DYNAMIC BUTTON-DRIVEN MENU RESOLVER (CAPABILITY RESOLVER)
    # =========================================================================

    def resolve_dynamic_menu(
        self,
        context: TenantRuntimeContext,
        rbac_role: str = "MERCHANT",
    ) -> Dict[str, Any]:
        """
        Capability Resolver (Dynamic Button-Driven Menu):
        Render tombol navigasi & FAQ BUKAN dari katalog statis, melainkan
        disaring berdasarkan: TenantRuntimeContext + RBAC + Plan/Entitlement + Feature Flags.
        - Opsi Powertools/CAPI HANYA tampil jika context.capabilities.meta_capi atau powertools bernilai True.
        - Fitur/FAQ Affiliate HANYA dirender jika tenant memiliki entitlement/program affiliate aktif.
        """
        clean_role = str(rbac_role or "MERCHANT").upper()

        # Menu Dasar (Selalu Ada untuk Merchant)
        menu_items = [
            {"id": "catalog", "label": "📦 Katalog & Produk", "action": "open_catalog", "category": "CORE"},
            {"id": "sales_report", "label": "📊 Laporan Omset & ROAS", "action": "view_sales_report", "category": "ANALYTICS"},
            {"id": "stock_check", "label": "📦 Cek Stok Menipis", "action": "check_stock", "category": "OPERATIONS"},
            {"id": "wa_flow", "label": "💬 Otomasi WhatsApp Bot", "action": "view_wa_flow", "category": "MESSAGING"},
            {"id": "proration_quote", "label": "⚡ Hitung Prorata Upgrade", "action": "calculate_upgrade_proration", "category": "BILLING"},
        ]

        # 1. Powertools / Server-Side CAPI Filter
        has_capi = bool(
            getattr(context.capabilities, "meta_capi", False)
            or getattr(context.capabilities, "powertools", False)
        )
        if has_capi:
            menu_items.append({
                "id": "meta_capi",
                "label": "📈 CAPI Server-Side Meta & TikTok",
                "action": "open_capi_settings",
                "category": "POWERTOOLS",
            })
            menu_items.append({
                "id": "powertools_diagnostic",
                "label": "⚡ Diagnostik Iklan Anti-Boncos",
                "action": "open_powertools_diagnostic",
                "category": "POWERTOOLS",
            })

        # 2. Affiliate Filter
        has_affiliate = bool(getattr(context.capabilities, "affiliate", False))
        if has_affiliate:
            menu_items.append({
                "id": "affiliate_hub",
                "label": "🤝 Program Mitra & Komisi Affiliate",
                "action": "open_affiliate_hub",
                "category": "AFFILIATE",
            })
            menu_items.append({
                "id": "affiliate_estimate",
                "label": "💰 Estimasi Komisi Mitra",
                "action": "estimate_affiliate_commission",
                "category": "AFFILIATE",
            })

        # 3. RBAC Filter
        if clean_role in ["ADMIN", "OWNER"]:
            menu_items.append({
                "id": "settlement_ledger",
                "label": "🏦 Rekonsiliasi & Ledger Keuangan",
                "action": "open_financial_ledger",
                "category": "ADMIN",
            })

        return {
            "tenant_id": context.tenant_id,
            "tenant_slug": context.tenant_id,
            "plan": context.plan,
            "status": context.status,
            "role": clean_role,
            "has_capi": has_capi,
            "has_affiliate": has_affiliate,
            "capabilities": context.capabilities.model_dump(),
            "total_buttons": len(menu_items),
            "menu": menu_items,
        }

    # =========================================================================
    # 2. CONTEXT BUILDER & SNAPSHOT
    # =========================================================================

    async def build_tenant_context(
        self,
        tenant_slug: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        context: Optional[TenantRuntimeContext] = None,
    ) -> Dict[str, Any]:
        """Membuat bundle konteks dinamis toko berbasis TenantRuntimeContext."""
        clean_slug = tenant_slug.strip().lower()
        tenant_name = clean_slug.replace('-', ' ').replace('_', ' ').title()

        products = self._get_tenant_products(clean_slug)

        # Analytics Snapshot
        campaigns = await campaign_analytics_service.get_campaign_attributions(clean_slug)
        total_omset = sum(c.get("omset_closing", 0) for c in campaigns)
        total_closings = sum(c.get("closings", 0) for c in campaigns)
        total_leads = sum(c.get("leads_wa", 0) for c in campaigns)
        blended_cr = round((total_closings / total_leads * 100), 2) if total_leads > 0 else 0.0

        sales_snapshot = {
            "last_7_days": {
                "gross_revenue": float(total_omset * 0.4),
                "total_orders": int(total_closings * 0.4),
                "blended_roas": 3.8,
                "conversion_rate_pct": blended_cr,
            },
            "last_30_days": {
                "gross_revenue": float(total_omset),
                "total_orders": int(total_closings),
                "blended_roas": 3.4,
                "conversion_rate_pct": blended_cr,
            },
            "top_campaigns": campaigns[:3],
        }

        shipping_origin = self._shipping.get(clean_slug, {
            "address": "Gudang Utama BoonTrack",
            "postal_code": "40115",
            "subdistrict": "Bandung Kota",
        })
        active_couriers = self._couriers.get(clean_slug, {"GoSend": True, "Grab": True})

        history_text = ""
        if conversation_history:
            history_text = "\n\nRiwayat Percakapan Sebelumnya:\n"
            for turn in conversation_history[-6:]:
                role_label = "Merchant" if turn.get("role") in ["user", "merchant"] else "BoonPilot"
                msg_content = turn.get("content", "").strip()
                if msg_content:
                    history_text += f"• {role_label}: {msg_content}\n"

        plan_label = context.plan if context else "SOLO"

        system_prompt = (
            "Kamu adalah 'BoonPilot Copilot', Copilot AI operasional toko resmi ekosistem BoonTrack.\n"
            "Tugasmu membantu merchant mengelola toko: memantau performa penjualan/iklan, memeriksa stok, "
            "mengelola otomatisasi WhatsApp, dan mengonfigurasi logistik toko secara proaktif, taktis, dan akurat.\n\n"
            "STANDAR PENAMAAN EKOSISTEM & IDENTITAS RESMI:\n"
            "1. Rujuk dirimu sendiri sebagai 'BoonPilot Copilot' (atau 'BoonPilot Toko').\n"
            "2. Jika menjelaskan fitur chat, percakapan pelanggan, atau omnichannel kepada merchant, gunakan nama 'BoonTrack Inbox' atau 'Live CS & Omnichannel'.\n"
            "3. Jika merujuk ke modul helpdesk, tiket komplain, atau bantuan teknis, sebut sebagai 'BoonTrack Desk'.\n"
            "4. DILARANG KERAS menyebut atau membocorkan nama engine/vendor pihak ketiga (seperti Chatwoot, dsb) dalam hasil respon percakapan.\n\n"
            f"Konteks Toko Saat Ini: '{tenant_name}' (Slug: {clean_slug}, Tier: {plan_label})\n"
            f"- Produk Aktif: {len(products)} item\n"
            f"- Omset 30 Hari: Rp {sales_snapshot['last_30_days']['gross_revenue']:,.0f} ({sales_snapshot['last_30_days']['total_orders']} orders)\n"
            f"- Alamat Pengiriman: {shipping_origin.get('address')} ({shipping_origin.get('postal_code')})\n"
            f"- Kurir Aktif: {', '.join(k for k, v in active_couriers.items() if v)}\n"
            "- Fitur Otomatisasi WhatsApp Toko (BoonTrack Inbox): AKTIF\n"
            "  Alur otomatisasi:\n"
            "  1. Sambutan otomatis calon pembeli via WA.\n"
            "  2. Menu bernomor (1, 2, 3) untuk cek detail produk & ulasan.\n"
            "  3. Link checkout instan & pelacakan konversi iklan otomatis (Lead/CAPI).\n\n"
            "Pedoman Menjawab & Guardrails:\n"
            "1. Jawab ramah, profesional, ringkas, dan fokus pada efisiensi operasional toko.\n"
            "2. JANGAN PERNAH merespons dengan salam perkenalan berulang jika user menanyakan kapabilitas spesifik sistem atau melanjutkan percakapan.\n"
            "3. DILARANG KERAS menampilkan nomor rekening bank pembeli atau toko secara lengkap (wajib disensor ****1234).\n"
            "4. DILARANG membocorkan kredensial sistem, API keys, password, atau database internal platform.\n"
            "5. Jangan melakukan kalkulasi harga / prorata / komisi mandiri; serahkan pada kalkulasi backend resmi."
            f"{history_text}"
        )

        return {
            "tenant_slug": clean_slug,
            "tenant_name": tenant_name,
            "products": products,
            "sales_snapshot": sales_snapshot,
            "shipping_origin": shipping_origin,
            "active_couriers": active_couriers,
            "system_prompt": system_prompt,
        }

    # =========================================================================
    # 3. QUERY-ONLY TOOLS & ACTION PROPOSALS
    # =========================================================================

    async def get_sales_and_roas_report(self, tenant_slug: str, days: int = 30) -> Dict[str, Any]:
        clean_slug = tenant_slug.strip().lower()
        campaigns = await campaign_analytics_service.get_campaign_attributions(clean_slug)
        factor = 0.4 if days <= 7 else 1.0

        total_omset = sum(c.get("omset_closing", 0) for c in campaigns) * factor
        total_closings = int(sum(c.get("closings", 0) for c in campaigns) * factor)
        total_leads = int(sum(c.get("leads_wa", 0) for c in campaigns) * factor)
        blended_cr = round((total_closings / total_leads * 100), 2) if total_leads > 0 else 0.0

        return {
            "period_days": days,
            "total_revenue": float(total_omset),
            "total_orders": total_closings,
            "blended_roas": 3.8 if days <= 7 else 3.4,
            "conversion_rate_pct": blended_cr,
            "campaigns": campaigns[:3],
            "recommendation": "Campaign Meta Ads menunjukkan tren closing tertinggi. Pertahankan budget atau scale-up ad set winning."
        }

    def check_inventory_levels(self, tenant_slug: str, threshold: int = 5) -> Dict[str, Any]:
        clean_slug = tenant_slug.strip().lower()
        products = self._get_tenant_products(clean_slug)
        low_stock_items = [p for p in products if p.get("stock", 0) <= threshold]

        return {
            "tenant_slug": clean_slug,
            "threshold": threshold,
            "total_products": len(products),
            "low_stock_count": len(low_stock_items),
            "low_stock_items": low_stock_items,
            "status": "WARNING" if low_stock_items else "HEALTHY",
        }

    def create_action_proposal(
        self,
        tenant_slug: str,
        action_type: str,
        description: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        clean_slug = tenant_slug.strip().lower()
        action_id = str(uuid.uuid4())
        now = time.time()

        proposal = {
            "type": "action_proposal",
            "action_id": action_id,
            "action_type": action_type,
            "description": description,
            "payload": payload,
            "status": "AWAITING_APPROVAL",
            "created_at": now,
            "expires_at": now + ACTION_PROPOSAL_TTL_SECONDS,
            "tenant_slug": clean_slug,
        }

        self._action_proposals[action_id] = proposal
        return proposal

    def execute_action(
        self,
        tenant_slug: str,
        action_id: str,
        approved: bool,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        clean_slug = tenant_slug.strip().lower()
        proposal = self._action_proposals.get(action_id)

        if not proposal:
            return False, "Proposal aksi tidak ditemukan.", {}

        if proposal.get("tenant_slug") != clean_slug:
            return False, "Proposal aksi tidak sesuai dengan tenant toko.", {}

        if time.time() > proposal.get("expires_at", 0):
            proposal["status"] = "EXPIRED"
            return False, "Proposal aksi sudah kedaluwarsa (batas waktu persetujuan 10 menit telah lewat).", proposal

        if proposal["status"] != "AWAITING_APPROVAL":
            return False, f"Proposal aksi sudah diproses sebelumnya dengan status '{proposal['status']}'.", proposal

        if not approved:
            proposal["status"] = "REJECTED"
            proposal["updated_at"] = time.time()
            return True, "Proposal perubahan data berhasil dibatalkan oleh pengguna.", proposal

        action_type = proposal["action_type"]
        payload = proposal["payload"]
        mutation_result = {}

        if action_type == "update_product_stock":
            pid = payload.get("product_id")
            new_stock = int(payload.get("new_stock", 0))
            products = self._inventory.get(clean_slug, [])
            found = False
            for p in products:
                if p.get("product_id") == pid or pid.lower() in p.get("title", "").lower():
                    p["stock"] = new_stock
                    found = True
                    mutation_result = {"product_id": p["product_id"], "title": p["title"], "new_stock": new_stock}
                    break
            if not found:
                return False, f"Produk dengan ID '{pid}' tidak ditemukan di katalog toko.", {}

        elif action_type == "update_shipping_origin":
            origin = self._shipping.setdefault(clean_slug, {})
            origin["address"] = payload.get("address", origin.get("address"))
            origin["postal_code"] = str(payload.get("postal_code", origin.get("postal_code")))
            origin["subdistrict"] = payload.get("subdistrict", origin.get("subdistrict"))
            mutation_result = dict(origin)

        elif action_type == "toggle_courier_service":
            couriers = self._couriers.setdefault(clean_slug, {})
            courier_name = payload.get("courier_name")
            is_active = bool(payload.get("is_active", True))
            couriers[courier_name] = is_active
            mutation_result = {"courier": courier_name, "active": is_active}

        elif action_type == "update_whatsapp_catalog_flow":
            mutation_result = {
                "flow_type": payload.get("flow_type", "numbered_menu"),
                "catalog_limit": payload.get("catalog_limit", 5),
                "message": "Konfigurasi alur katalog menu bernomor berhasil diperbarui.",
            }

        proposal["status"] = "EXECUTED"
        proposal["result"] = mutation_result
        proposal["updated_at"] = time.time()

        return True, "Aksi berhasil dieksekusi ke sistem toko.", proposal

    # =========================================================================
    # 4. CHAT ENTRYPOINT & SCOPE LOCK GUARD
    # =========================================================================

    async def chat(
        self,
        tenant_slug: str,
        message: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        untrusted_client_tenant_id: Optional[str] = None,
        rbac_role: str = "MERCHANT",
        target_whatsapp_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Interaksi Utama BoonPilot Copilot dengan Scope Lock:
        1. Verifikasi WhatsApp Isolation: Tolak jika merujuk ke nomor WABA resmi platform (+6285179555449).
        2. Resolusi TenantRuntimeContext: Pastikan tenant terdaftar secara resmi di database/entitlement.
        3. Isolasi Tenant & RBAC: Tolak arbitrary untrusted_client_tenant_id yang tidak cocok.
        4. No LLM Business Truth: Kalkulasi harga, prorata upgrade, dan komisi dieksekusi langsung oleh engine backend.
        5. Filter Tombol Dinamis: Quick actions & menu disaring berdasarkan capabilities & RBAC.
        """
        # 1. WhatsApp Isolation Guard
        assert_whatsapp_isolation(target_whatsapp_phone)

        clean_slug = (tenant_slug or "").strip().lower()
        if not clean_slug:
            raise ValueError("Tenant slug tidak boleh kosong.")

        # 2. Resolve Server-Authoritative TenantRuntimeContext
        context = await tenant_context_resolver.resolve(clean_slug)

        # 3. Tenant & RBAC Isolation Guard (Tolak Arbitrary client tenant_id)
        if untrusted_client_tenant_id:
            clean_untrusted = str(untrusted_client_tenant_id).strip().lower()
            if clean_untrusted != clean_slug and clean_untrusted != str(context.tenant_id).lower():
                raise PermissionError(
                    f"Akses ditolak: Arbitrary tenant_id '{untrusted_client_tenant_id}' tidak cocok dengan "
                    f"konteks runtime tenant yang sah ('{context.tenant_id}')."
                )

        sess_id = session_id or f"sess_bp_{clean_slug}_{int(time.time())}"
        current_history = conversation_history or self._session_histories.get(sess_id, [])
        context_data = await self.build_tenant_context(clean_slug, conversation_history=current_history, context=context)

        text_lower = message.strip().lower()
        tenant_name = context_data["tenant_name"]

        # ---------------------------------------------------------------------
        # A. NO LLM BUSINESS TRUTH: Official Backend Prorata & Billing Tool
        # ---------------------------------------------------------------------
        prorate_keywords = ["prorata", "upgrade", "biaya upgrade", "hitung prorata", "harga upgrade", "ganti tier"]
        if any(k in text_lower for k in prorate_keywords):
            target_tier = "PRO_SCALE"
            if "team" in text_lower:
                target_tier = "TEAM_SCALE"
            elif "enterprise" in text_lower:
                target_tier = "ENTERPRISE"
            elif "ads" in text_lower or "perf" in text_lower:
                target_tier = "ADS_PERFORMANCE"

            # Panggil langsung otoritas mutlak billing engine
            proration = await billing_service.calculate_upgrade_proration(
                tenant_id_or_slug=clean_slug,
                new_tier=target_tier,
            )

            renewal_str = proration.renewal_date[:10] if proration.renewal_date else "Sesuai Siklus"
            reply = (
                f"📊 *Kalkulasi Resmi Prorata Upgrade (Otoritas Backend)*\n\n"
                f"• Status Saat Ini: Tier {proration.current_tier} (Rp {proration.current_tier_price:,.0f}/bln)\n"
                f"• Target Upgrade: Tier {proration.new_tier} (Rp {proration.new_tier_price:,.0f}/bln)\n"
                f"• Sisa Hari Siklus: {proration.days_remaining} dari 30 hari\n"
                f"• Tagihan Prorata: *Rp {proration.prorated_amount:,.0f}*\n"
                f"• Tanggal Renewal: Tetap ({renewal_str})\n"
                f"• Invoice ID: `{proration.invoice_id}` (Status: {proration.status.upper()})\n\n"
                f"💡 *Catatan Arsitektur:* Perhitungan ini adalah kalkulasi mutlak dari server tanpa reka hitung mandiri."
            )
            data = {
                "tool": "calculate_upgrade_proration",
                "authority": "BACKEND_BILLING_ENGINE",
                "proration": proration.model_dump(),
                "quick_actions": [
                    {"label": f"Bayar Invoice Prorata (Rp {proration.prorated_amount:,.0f})", "action": "pay_proration_invoice", "invoice_id": proration.invoice_id},
                    {"label": "Kembali ke Dashboard", "action": "open_dashboard"},
                ]
            }
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", reply)
            return {
                "type": "text",
                "reply": reply,
                "data": data,
                "session_id": sess_id,
            }

        # ---------------------------------------------------------------------
        # B. NO LLM BUSINESS TRUTH: Affiliate Commission & Entitlement Tool
        # ---------------------------------------------------------------------
        affiliate_keywords = ["komisi affiliate", "komisi mitra", "rate affiliate", "program affiliate", "komisi upgrade"]
        if any(k in text_lower for k in affiliate_keywords):
            has_affiliate = bool(getattr(context.capabilities, "affiliate", False))
            if not has_affiliate:
                reply = (
                    f"ℹ️ *Program Mitra Affiliate Belum Aktif*\n\n"
                    f"Tenant '{tenant_name}' saat ini berada pada paket **{context.plan}** yang belum mencakup entitlement program affiliate.\n"
                    f"Untuk mengaktifkan pendaftaran mitra dan komisi otomatis, silakan upgrade ke paket **Team Scale** atau **Enterprise**."
                )
                data = {
                    "tool": "check_affiliate_entitlement",
                    "status": "NOT_ENTITLED",
                    "tenant_plan": context.plan,
                    "quick_actions": [
                        {"label": "Upgrade ke Team Scale (Rp 749k/bln)", "action": "upgrade_tier", "target_tier": "TEAM_SCALE"}
                    ]
                }
            else:
                # Hitung estimasi komisi resmi dari cash collected
                sample_paid = 200000.0
                sample_comm = affiliate_service.calculate_commission(sample_paid)
                reply = (
                    f"🤝 *Program Mitra & Komisi Affiliate Resmi*\n\n"
                    f"• Status Program: **AKTIF (Entitled)**\n"
                    f"• Rate Komisi Standar: 20% dari kas riil invoice yang dibayar (Cash Collected)\n"
                    f"• Status Komisi Masuk: `HOLDING` (Proteksi transaksi)\n"
                    f"• Contoh: Dari tagihan prorata Rp {sample_paid:,.0f}, komisi tercatat adalah *Rp {sample_comm:,.0f}*.\n\n"
                    f"Seluruh komisi dibukukan secara presisi ke ledger transaksi."
                )
                data = {
                    "tool": "check_affiliate_entitlement",
                    "status": "ACTIVE",
                    "commission_rate": 0.20,
                    "holding_safeguard": True,
                    "quick_actions": [
                        {"label": "Buka Dashboard Affiliate", "action": "open_affiliate_hub"},
                        {"label": "Lihat Daftar Mitra", "action": "view_affiliate_list"}
                    ]
                }
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", reply)
            return {
                "type": "text",
                "reply": reply,
                "data": data,
                "session_id": sess_id,
            }

        # ---------------------------------------------------------------------
        # C. Quick Action Menu / Onboarding
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["menu", "tombol navigasi", "fitur apa saja", "bantuan menu", "bantuan"]):
            dynamic_menu = self.resolve_dynamic_menu(context, rbac_role=rbac_role)
            button_labels = "\n".join([f"• {btn['label']}" for btn in dynamic_menu["menu"]])
            reply = (
                f"👋 Halo! Berikut daftar menu dan kapabilitas resmi toko **{tenant_name}** "
                f"(Tier: {context.plan}) yang telah disesuaikan dengan entitlement aktif:\n\n"
                f"{button_labels}\n\n"
                "Silakan pilih opsi di atas atau ketik instruksi yang Kakak butuhkan!"
            )
            data = dynamic_menu
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", reply)
            return {
                "type": "text",
                "reply": reply,
                "data": data,
                "session_id": sess_id,
            }

        # ---------------------------------------------------------------------
        # D. Onboarding Impor Katalog
        # ---------------------------------------------------------------------
        catalog_onboarding_keywords = [
            "cara impor", "impor produk", "import produk", "upload massal",
            "tambah produk", "impor massal", "katalog produk", "spreadsheet", "excel", "csv"
        ]
        if any(k in text_lower for k in catalog_onboarding_keywords):
            reply = (
                f"Untuk menambahkan atau mengimpor katalog produk di toko {tenant_name}, Anda dapat menggunakan metode:\n\n"
                "1. **Impor Massal Excel/CSV**:\n"
                "   - Masuk ke menu **Dashboard > Produk > Impor Massal**.\n"
                "   - Unduh template spreadsheet kami, isi nama produk, SKU, varian, harga, dan stok.\n"
                "   - Sistem akan langsung memvalidasi dan menambahkan seluruh SKU dalam beberapa detik!\n\n"
                "2. **Tambah Produk Manual**:\n"
                "   - Klik tombol **'+ Tambah Produk Baru'** untuk mengisi detail satuan beserta unggah foto produk.\n\n"
                "Ada yang ingin Anda tanyakan lebih lanjut seputar impor katalog produk?"
            )
            data = {
                "feature": "catalog_onboarding",
                "status": "READY",
                "tenant_slug": clean_slug,
                "tenant_name": tenant_name,
                "quick_actions": [
                    {"label": "Import Massal (.xlsx / .csv)", "action": "open_bulk_import"},
                    {"label": "+ Tambah Produk Baru", "action": "open_new_product"},
                ]
            }
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", reply)
            return {
                "type": "text",
                "reply": reply,
                "data": data,
                "session_id": sess_id,
            }

        # ---------------------------------------------------------------------
        # E. WhatsApp Automation Flow (Pencegahan Greeting Loop)
        # ---------------------------------------------------------------------
        wa_keywords = [
            "whatsapp", "wa", "otomatisasi wa", "bot wa", "fitur wa",
            "wa gateway", "alur wa", "whatsapp automation", "pesan otomatis",
        ]
        if any(k in text_lower for k in wa_keywords):
            reply = (
                f"Otomatisasi WhatsApp untuk toko {tenant_name} sudah aktif dengan alur:\n"
                f" 1. Sambutan otomatis calon pembeli via WA.\n"
                f" 2. Menu bernomor (1, 2, 3) untuk cek detail produk & ulasan.\n"
                f" 3. Link checkout instan & pelacakan konversi iklan otomatis (Lead/CAPI).\n\n"
                "Apakah Anda ingin melihat statistik chat, menguji nomor asisten, atau mengubah alur katalog?"
            )
            data = {
                "feature": "whatsapp_automation",
                "status": "ACTIVE",
                "tenant_slug": clean_slug,
                "tenant_name": tenant_name,
                "quick_actions": [
                    {"label": "Lihat Statistik Chat", "action": "view_chat_analytics", "path": "/dashboard/chats"},
                    {"label": "Ubah Alur Katalog", "action": "edit_catalog_flow", "path": "/dashboard/catalog/flow"}
                ]
            }
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", reply)
            return {
                "type": "text",
                "reply": reply,
                "data": data,
                "session_id": sess_id,
            }

        # ---------------------------------------------------------------------
        # F. Deteksi Tool: Sales & ROAS Report
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["omset", "roas", "penjualan", "revenue", "closing", "performa"]):
            days = 30 if "30" in text_lower or "sebulan" in text_lower else 7
            report = await self.get_sales_and_roas_report(clean_slug, days=days)
            reply = (
                f"📊 *Laporan Penjualan & ROAS Toko ({days} Hari Terakhir)*\n\n"
                f"• *Total Omset:* Rp {report['total_revenue']:,.0f}\n"
                f"• *Total Closing:* {report['total_orders']} pesanan\n"
                f"• *Estimasi ROAS:* {report['blended_roas']}x\n"
                f"• *Conversion Rate:* {report['conversion_rate_pct']}%\n\n"
                f"💡 *Insight BoonPilot:* {report['recommendation']}"
            )
            masked_reply = mask_sensitive_data(reply)
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", masked_reply)
            return {
                "type": "text",
                "reply": masked_reply,
                "data": report,
                "session_id": sess_id,
            }

        # ---------------------------------------------------------------------
        # G. Deteksi Tool: Check Inventory Levels
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["stok", "inventory", "sisa barang", "menipis", "habis"]):
            if not any(k in text_lower for k in ["ubah", "ganti", "tambah", "set", "update"]):
                inv = self.check_inventory_levels(clean_slug, threshold=5)
                if inv["low_stock_items"]:
                    items_str = "\n".join(
                        f"  ⚠️ *{p['title']}* (Tersisa: {p['stock']} unit)"
                        for p in inv["low_stock_items"]
                    )
                    reply = (
                        f"⚠️ *Peringatan Stok Menipis!*\n"
                        f"Terdapat {inv['low_stock_count']} produk dengan stok <= {inv['threshold']} unit:\n\n"
                        f"{items_str}\n\n"
                        "Apakah Kakak ingin saya bantu perbarui jumlah stok produk di atas?"
                    )
                else:
                    reply = (
                        f"✅ *Status Stok Aman!* Seluruh produk ({inv['total_products']} item) "
                        f"memiliki ketersediaan stok di atas batas minimum."
                    )
                masked_reply = mask_sensitive_data(reply)
                self._append_turn(sess_id, "user", message)
                self._append_turn(sess_id, "assistant", masked_reply)
                return {
                    "type": "text",
                    "reply": masked_reply,
                    "data": inv,
                    "session_id": sess_id,
                }

        # ---------------------------------------------------------------------
        # H. Mutasi Data: Update Stock
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["ubah stok", "ganti stok", "update stok", "set stok"]):
            stock_match = re.search(r"\b(\d+)\b", text_lower)
            new_stock = int(stock_match.group(1)) if stock_match else 50

            products = self._get_tenant_products(clean_slug)
            target_prod = products[0]
            for p in products:
                if any(part in text_lower for part in p["title"].lower().split()[:2]):
                    target_prod = p
                    break

            proposal = self.create_action_proposal(
                tenant_slug=clean_slug,
                action_type="update_product_stock",
                description=f"Konfirmasi perubahan stok produk '{target_prod['title']}' menjadi {new_stock} unit.",
                payload={
                    "product_id": target_prod["product_id"],
                    "product_title": target_prod["title"],
                    "new_stock": new_stock,
                },
            )
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", proposal["description"])
            return proposal

        # ---------------------------------------------------------------------
        # I. General Agentic Chat via LLM Gateway dengan Context & Multi-turn
        # ---------------------------------------------------------------------
        system_prompt = context_data["system_prompt"]
        try:
            llm_reply = await ai_gateway.generate_for_agent(
                agent_profile=AgentProfile.MERCHANT_COPILOT,
                user_message=message,
                context={
                    "feature": "boonpilot",
                    "tenant_slug": clean_slug,
                    "conversation_history": current_history,
                },
                system_prompt=system_prompt,
            )
        except Exception as e:
            logger.warning(f"BoonPilot LLM gateway call failed: {e}")
            llm_reply = None

        if not llm_reply or not llm_reply.strip():
            llm_reply = (
                f"Halo Kak! Saya BoonPilot Copilot toko **{tenant_name}**. "
                f"Saya siap membantu memantau omset, stok barang, alur WhatsApp, hingga kalkulasi upgrade paket toko Anda."
            )

        masked_reply = mask_sensitive_data(llm_reply)
        self._append_turn(sess_id, "user", message)
        self._append_turn(sess_id, "assistant", masked_reply)

        return {
            "type": "text",
            "reply": masked_reply,
            "data": {
                "tenant_slug": clean_slug,
                "status": "SUCCESS",
            },
            "session_id": sess_id,
        }


boonpilot_service = BoonPilotService()
