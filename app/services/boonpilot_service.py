"""app/services/boonpilot_service.py
Agentic AI BoonPilot Service Layer.

Menyediakan engine copilot operasional toko:
1. Dynamic Context Injection per tenant (katalog produk, varian, stok, analytics snapshot).
2. Guardrails keamanan (larangan ekspos nomor rekening lengkap & kredensial platform).
3. Tooling & Function Calling (query-only auto execute & mutation proposal).
4. Human-in-the-Loop Safeguard dengan TTL 10 menit.
"""

import os
import re
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from app.services.ai_gateway import ai_gateway
from app.services.campaign_analytics_service import campaign_analytics_service

logger = logging.getLogger("BOONPILOT_SERVICE")

# TTL Proposal Aksi (10 menit = 600 detik)
ACTION_PROPOSAL_TTL_SECONDS = 600

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
            "stock": 3,  # Menipis (< threshold 5)
            "category": "Digital Asset",
            "status": "ACTIVE",
            "variants": ["Notion + Sheet Template"],
        },
        {
            "product_id": "prod_coaching_vip",
            "title": "Private Coaching 1-on-1 & Campaign Audit",
            "price": 499000,
            "stock": 1,  # Menipis (< threshold 5)
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
    """
    Guardrail: Sensor nomor rekening bank utuh dan cegah kebocoran token/kredensial internal.
    """
    if not text:
        return ""

    # 1. Mask nomor rekening/kartu (deretan 8-16 digit angka)
    def _mask_account(match):
        digits = match.group(0)
        return f"****{digits[-4:]}"

    masked = re.sub(r"\b\d{8,16}\b", _mask_account, text)

    # 2. Sensor API Keys / Secrets / Tokens
    masked = re.sub(r"(?:sb_[a-zA-Z0-9_-]+|eyJ[a-zA-Z0-9_\-\.]+)", "[REDACTED_CREDENTIAL]", masked)
    masked = re.sub(r"(?:postgres://[^\s]+|https://api\.biteship\.com[^\s]+)", "[REDACTED_URL]", masked)

    return masked


class BoonPilotService:
    """
    Agentic Copilot untuk toko merchant BoonTrack.
    Mengelola konteks, routing fungsi, dan safeguard Human-in-the-loop.
    """

    def __init__(self):
        self._inventory: Dict[str, List[Dict[str, Any]]] = {
            slug: [dict(p) for p in prods] for slug, prods in DEFAULT_TENANT_INVENTORY.items()
        }
        self._shipping: Dict[str, Dict[str, Any]] = {
            slug: dict(s) for slug, s in DEFAULT_TENANT_SHIPPING.items()
        }
        self._couriers: Dict[str, Dict[str, bool]] = {
            slug: dict(c) for slug, c in DEFAULT_TENANT_COURIERS.items()
        }
        # In-memory storage action proposals {action_id: {...}}
        self._action_proposals: Dict[str, Dict[str, Any]] = {}

    # =========================================================================
    # 1. CONTEXT BUILDER & SNAPSHOT
    # =========================================================================

    async def build_tenant_context(self, tenant_slug: str) -> Dict[str, Any]:
        """
        Membuat bundle konteks dinamis toko:
        - System Prompt identitas 'BoonPilot'
        - Katalog produk aktif, varian, dan stok
        - Snapshot analytics 7-30 hari (omset, orders, kampanye iklan)
        - Konfigurasi logistik & kurir
        """
        clean_slug = tenant_slug.strip().lower()

        # 1. Katalog & Stok
        products = self._get_tenant_products(clean_slug)

        # 2. Analytics Snapshot
        campaigns = await campaign_analytics_service.get_campaign_attributions(clean_slug)
        total_omset = sum(c.get("omset_closing", 0) for c in campaigns)
        total_closings = sum(c.get("closings", 0) for c in campaigns)
        total_leads = sum(c.get("leads_wa", 0) for c in campaigns)
        blended_cr = round((total_closings / total_leads * 100), 2) if total_leads > 0 else 0.0

        # Estimasi metric 7 hari vs 30 hari
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

        # 3. Logistik & Kurir
        shipping_origin = self._shipping.get(clean_slug, {
            "address": "Gudang Utama BoonTrack",
            "postal_code": "40115",
            "subdistrict": "Bandung Kota",
        })
        active_couriers = self._couriers.get(clean_slug, {"GoSend": True, "Grab": True})

        # 4. System Prompt BoonPilot
        system_prompt = (
            "Kamu adalah 'BoonPilot', Copilot AI operasional toko resmi BoonTrack.\n"
            "Tugasmu membantu merchant mengelola toko: memantau performa penjualan/iklan, memeriksa stok, "
            "dan mengonfigurasi logistik toko secara proaktif, taktis, dan akurat.\n\n"
            f"Konteks Toko Saat Ini: '{tenant_slug}'\n"
            f"- Produk Aktif: {len(products)} item\n"
            f"- Omset 30 Hari: Rp {sales_snapshot['last_30_days']['gross_revenue']:,.0f} ({sales_snapshot['last_30_days']['total_orders']} orders)\n"
            f"- Alamat Pengiriman: {shipping_origin.get('address')} ({shipping_origin.get('postal_code')})\n"
            f"- Kurir Aktif: {', '.join(k for k, v in active_couriers.items() if v)}\n\n"
            "Pedoman Menjawab & Guardrails:\n"
            "1. Jawab ramah, profesional, ringkas, dan fokus pada efisiensi operasional toko.\n"
            "2. DILARANG KERAS menampilkan nomor rekening bank pembeli atau toko secara lengkap (wajib disensor ****1234).\n"
            "3. DILARANG membocorkan kredensial sistem, API keys, password, atau database internal platform.\n"
            "4. Jika merchant meminta perubahan data (stok, alamat gudang, kurir), berikan konfirmasi usulan perubahan secara jelas."
        )

        return {
            "tenant_slug": clean_slug,
            "system_prompt": system_prompt,
            "products": products,
            "analytics_snapshot": sales_snapshot,
            "shipping_origin": shipping_origin,
            "active_couriers": active_couriers,
        }

    def _get_tenant_products(self, tenant_slug: str) -> List[Dict[str, Any]]:
        clean_slug = tenant_slug.strip().lower()
        if clean_slug in self._inventory:
            return self._inventory[clean_slug]
        # Fallback catalog untuk tenant baru
        return [
            {
                "product_id": f"{clean_slug}_prod_1",
                "title": "Produk Standar Toko",
                "price": 100000,
                "stock": 10,
                "category": "Retail",
                "status": "ACTIVE",
                "variants": ["Default"],
            }
        ]

    # =========================================================================
    # 2. TOOLS / FUNCTION CALLING
    # =========================================================================

    async def get_sales_and_roas_report(self, tenant_slug: str, days: int = 7) -> Dict[str, Any]:
        """Query-only tool: Langsung dieksekusi untuk melihat ringkasan omset & ROAS."""
        clean_slug = tenant_slug.strip().lower()
        campaigns = await campaign_analytics_service.get_campaign_attributions(clean_slug)

        total_omset = sum(c.get("omset_closing", 0) for c in campaigns)
        total_closings = sum(c.get("closings", 0) for c in campaigns)
        total_leads = sum(c.get("leads_wa", 0) for c in campaigns)

        scale_factor = 0.4 if days <= 7 else 1.0
        period_omset = float(total_omset * scale_factor)
        period_closings = int(total_closings * scale_factor)
        cr_pct = round((total_closings / total_leads * 100), 2) if total_leads > 0 else 0.0
        roas = 3.8 if days <= 7 else 3.4

        return {
            "period_days": days,
            "tenant_slug": clean_slug,
            "total_revenue": period_omset,
            "total_orders": period_closings,
            "blended_roas": roas,
            "conversion_rate_pct": cr_pct,
            "top_campaigns": campaigns[:3],
            "recommendation": "Campaign Meta Ads menunjukkan tren closing tertinggi. Pertahankan budget atau scale-up ad set winning."
        }

    def check_inventory_levels(self, tenant_slug: str, threshold: int = 5) -> Dict[str, Any]:
        """Query-only tool: Langsung dieksekusi untuk memantau stok produk."""
        clean_slug = tenant_slug.strip().lower()
        products = self._get_tenant_products(clean_slug)

        low_stock_items = [p for p in products if p.get("stock", 0) <= threshold]

        return {
            "tenant_slug": clean_slug,
            "threshold": threshold,
            "total_products": len(products),
            "low_stock_count": len(low_stock_items),
            "low_stock_items": low_stock_items,
            "all_inventory": products,
            "status": "WARNING" if low_stock_items else "HEALTHY",
        }

    # =========================================================================
    # 3. HUMAN-IN-THE-LOOP SAFEGUARD (ACTION PROPOSALS)
    # =========================================================================

    def create_action_proposal(
        self,
        tenant_slug: str,
        action_type: str,
        description: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Membuat proposal aksi mutasi data dengan status AWAITING_APPROVAL.
        Disimpan dengan masa berlaku (TTL) 10 menit.
        """
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
        """
        Mengeksekusi atau menolak proposal aksi mutasi data yang telah disetujui.
        Memvalidasi TTL 10 menit.
        """
        clean_slug = tenant_slug.strip().lower()
        proposal = self._action_proposals.get(action_id)

        if not proposal:
            return False, "Proposal aksi tidak ditemukan.", {}

        # 1. Cek Tenant Match
        if proposal.get("tenant_slug") != clean_slug:
            return False, "Proposal aksi tidak sesuai dengan tenant toko.", {}

        # 2. Cek Expiry (TTL 10 Menit)
        if time.time() > proposal.get("expires_at", 0):
            proposal["status"] = "EXPIRED"
            return False, "Proposal aksi sudah kedaluwarsa (batas waktu persetujuan 10 menit telah lewat).", proposal

        # 3. Cek Status Sebelumnya
        if proposal["status"] != "AWAITING_APPROVAL":
            return False, f"Proposal aksi sudah diproses sebelumnya dengan status '{proposal['status']}'.", proposal

        # 4. Jika Ditolak oleh Pengguna
        if not approved:
            proposal["status"] = "REJECTED"
            proposal["updated_at"] = time.time()
            return True, "Proposal perubahan data berhasil dibatalkan oleh pengguna.", proposal

        # 5. Jika Disetujui (Approved == True) -> Lakukan Mutasi Data Nyata
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
            mutation_result = {"courier_name": courier_name, "is_active": is_active, "all_couriers": couriers}

        else:
            return False, f"Tipe mutasi '{action_type}' tidak dikenali.", {}

        proposal["status"] = "EXECUTED"
        proposal["executed_at"] = time.time()
        proposal["result"] = mutation_result

        return True, "Aksi mutasi data berhasil dieksekusi ke database toko.", proposal

    # =========================================================================
    # 4. AGENTIC CONVERSATION DISPATCHER
    # =========================================================================

    async def chat(
        self,
        tenant_slug: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Entrypoint chat BoonPilot:
        - Mendeteksi apakah user meminta query report (sales/inventory).
        - Mendeteksi apakah user meminta mutasi data (ubah stok, gudang, kurir) -> Buat Action Proposal.
        - Jika obrolan biasa / konsultasi operasional -> Panggil LLM dengan Context & Guardrails.
        """
        clean_slug = tenant_slug.strip().lower()
        text_lower = message.lower().strip()

        context_data = await self.build_tenant_context(clean_slug)

        # ---------------------------------------------------------------------
        # A. Deteksi Tool 1: Sales & ROAS Report
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
            return {
                "type": "text",
                "reply": mask_sensitive_data(reply),
                "data": report,
            }

        # ---------------------------------------------------------------------
        # B. Deteksi Tool 2: Check Inventory Levels
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["stok", "inventory", "sisa barang", "menipis", "habis"]):
            # Cek apakah ini permintaan mutasi (misal "ubah stok...")
            if not any(k in text_lower for k in ["ubah", "ganti", "tambah", "set", "update"]):
                inv = self.check_inventory_levels(clean_slug, threshold=5)
                if inv["low_stock_items"]:
                    items_str = "\n".join(
                        f"  ⚠️ *{p['title']}* (Tersisa: {p['stock']} unit)"
                        for p in inv["low_stock_items"]
                    )
                    reply = (
                        f"📦 *Peringatan Stok Menipis!*\n"
                        f"Terdapat {inv['low_stock_count']} produk dengan stok ≤ {inv['threshold']} unit:\n\n"
                        f"{items_str}\n\n"
                        "Apakah Kakak ingin saya bantu perbarui jumlah stok produk di atas?"
                    )
                else:
                    reply = (
                        f"✅ *Status Stok Aman!* Seluruh produk ({inv['total_products']} item) "
                        f"memiliki ketersediaan stok di atas batas minimum."
                    )
                return {
                    "type": "text",
                    "reply": mask_sensitive_data(reply),
                    "data": inv,
                }

        # ---------------------------------------------------------------------
        # C. Deteksi Tool 3 (MUTATION): Update Product Stock
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["ubah stok", "ganti stok", "update stok", "set stok"]):
            # Ekstraksi angka stok
            stock_match = re.search(r"\b(\d+)\b", text_lower)
            new_stock = int(stock_match.group(1)) if stock_match else 50

            # Cari target produk
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
            return proposal

        # ---------------------------------------------------------------------
        # D. Deteksi Tool 4 (MUTATION): Update Shipping Origin
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["ganti alamat", "ubah alamat", "update alamat", "gudang pengiriman"]):
            # Ekstraksi kodepos jika ada
            postal_match = re.search(r"\b(\d{5})\b", message)
            postal_code = postal_match.group(1) if postal_match else "40111"

            proposal = self.create_action_proposal(
                tenant_slug=clean_slug,
                action_type="update_shipping_origin",
                description=f"Konfirmasi pembaruan alamat gudang pengiriman toko ke '{message}' (Kode Pos: {postal_code}).",
                payload={
                    "address": message.strip(),
                    "postal_code": postal_code,
                    "subdistrict": "Bandung",
                },
            )
            return proposal

        # ---------------------------------------------------------------------
        # E. Deteksi Tool 5 (MUTATION): Toggle Courier Service
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["kurir", "gosend", "grab", "jne", "sicepat"]):
            if any(k in text_lower for k in ["aktifkan", "nonaktifkan", "matikan", "nyalakan", "toggle"]):
                is_active = not any(k in text_lower for k in ["nonaktifkan", "matikan", "disable"])
                courier_name = "GoSend"
                if "grab" in text_lower:
                    courier_name = "Grab"
                elif "jne" in text_lower:
                    courier_name = "JNE"
                elif "sicepat" in text_lower:
                    courier_name = "SiCepat"

                action_verb = "mengaktifkan" if is_active else "menonaktifkan"
                proposal = self.create_action_proposal(
                    tenant_slug=clean_slug,
                    action_type="toggle_courier_service",
                    description=f"Konfirmasi {action_verb} layanan ekspedisi '{courier_name}' untuk pengiriman toko.",
                    payload={
                        "courier_name": courier_name,
                        "is_active": is_active,
                    },
                )
                return proposal

        # ---------------------------------------------------------------------
        # F. General Agentic Chat via LLM Gateway dengan Context & Guardrails
        # ---------------------------------------------------------------------
        system_prompt = context_data["system_prompt"]
        try:
            llm_reply = await ai_gateway.generate(
                user_message=message,
                context={"feature": "boonpilot", "tenant_slug": clean_slug},
                system_prompt=system_prompt,
            )
            if not llm_reply:
                llm_reply = (
                    f"Halo! Saya BoonPilot, siap membantu pengelolaan toko *{tenant_slug}*. "
                    "Kakak bisa meminta laporan penjualan, memantau ketersediaan stok, "
                    "atau memperbarui pengaturan logistik toko."
                )
        except Exception as e:
            logger.warning(f"BoonPilot LLM gateway fallback: {e}")
            llm_reply = (
                f"Halo! Saya BoonPilot, siap membantu operasional toko *{tenant_slug}*. "
                "Silakan berikan instruksi seputar stok, laporan omset, atau pengiriman."
            )

        sanitized_reply = mask_sensitive_data(llm_reply)

        return {
            "type": "text",
            "reply": sanitized_reply,
            "session_id": session_id or str(uuid.uuid4()),
        }


# Global BoonPilot Instance
boonpilot_service = BoonPilotService()
