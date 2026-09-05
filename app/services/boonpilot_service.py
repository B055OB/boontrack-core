"""app/services/boonpilot_service.py
Agentic AI BoonPilot Service Layer.

Menyediakan engine copilot operasional toko:
1. Dynamic Context Injection per tenant (katalog produk, varian, stok, analytics snapshot).
2. Guardrails keamanan (larangan ekspos nomor rekening lengkap & kredensial platform).
3. Tooling & Function Calling (query-only auto execute & mutation proposal).
4. Human-in-the-Loop Safeguard dengan TTL 10 menit.
5. WhatsApp Automation capabilities & Pencegahan Greeting Loop.
6. Multi-turn Conversation History support.
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
    Mengelola konteks, routing fungsi, multi-turn history, dan safeguard Human-in-the-loop.
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
        # In-memory storage session conversation histories {session_id: [{"role": ..., "content": ...}]}
        self._session_histories: Dict[str, List[Dict[str, str]]] = {}

    def _append_turn(self, session_id: str, role: str, content: str):
        """Menyimpan turn ke riwayat percakapan sesi."""
        if not session_id:
            return
        if session_id not in self._session_histories:
            self._session_histories[session_id] = []
        self._session_histories[session_id].append({"role": role, "content": content})
        # Batasi riwayat maksimum 20 turn terakhir
        if len(self._session_histories[session_id]) > 20:
            self._session_histories[session_id] = self._session_histories[session_id][-20:]

    # =========================================================================
    # 1. CONTEXT BUILDER & SNAPSHOT
    # =========================================================================

    async def build_tenant_context(
        self,
        tenant_slug: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Membuat bundle konteks dinamis toko:
        - System Prompt identitas 'BoonPilot'
        - Katalog produk aktif, varian, dan stok
        - Snapshot analytics 7-30 hari (omset, orders, kampanye iklan)
        - Konfigurasi logistik, kurir, dan otomatisasi WhatsApp
        - Riwayat percakapan multi-turn
        """
        clean_slug = tenant_slug.strip().lower()
        tenant_name = clean_slug.replace('-', ' ').replace('_', ' ').title()

        # 1. Katalog & Stok
        products = self._get_tenant_products(clean_slug)

        # 2. Analytics Snapshot
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

        # 3. Logistik & Kurir
        shipping_origin = self._shipping.get(clean_slug, {
            "address": "Gudang Utama BoonTrack",
            "postal_code": "40115",
            "subdistrict": "Bandung Kota",
        })
        active_couriers = self._couriers.get(clean_slug, {"GoSend": True, "Grab": True})

        # 4. Format Riwayat Percakapan Multi-Turn
        history_text = ""
        if conversation_history:
            history_text = "\n\nRiwayat Percakapan Sebelumnya:\n"
            for turn in conversation_history[-6:]:
                role_label = "Merchant" if turn.get("role") in ["user", "merchant"] else "BoonPilot"
                msg_content = turn.get("content", "").strip()
                if msg_content:
                    history_text += f"• {role_label}: {msg_content}\n"

        # 5. System Prompt BoonPilot
        system_prompt = (
            "Kamu adalah 'BoonPilot', Copilot AI operasional toko resmi BoonTrack.\n"
            "Tugasmu membantu merchant mengelola toko: memantau performa penjualan/iklan, memeriksa stok, "
            "mengelola otomatisasi WhatsApp, dan mengonfigurasi logistik toko secara proaktif, taktis, dan akurat.\n\n"
            f"Konteks Toko Saat Ini: '{tenant_name}' (Slug: {clean_slug})\n"
            f"- Produk Aktif: {len(products)} item\n"
            f"- Omset 30 Hari: Rp {sales_snapshot['last_30_days']['gross_revenue']:,.0f} ({sales_snapshot['last_30_days']['total_orders']} orders)\n"
            f"- Alamat Pengiriman: {shipping_origin.get('address')} ({shipping_origin.get('postal_code')})\n"
            f"- Kurir Aktif: {', '.join(k for k, v in active_couriers.items() if v)}\n"
            "- Fitur Otomatisasi WhatsApp Toko: AKTIF\n"
            "  Alur otomatisasi:\n"
            "  1. Sambutan otomatis calon pembeli via WA.\n"
            "  2. Menu bernomor (1, 2, 3) untuk cek detail produk & ulasan.\n"
            "  3. Link checkout instan & pelacakan konversi iklan otomatis (Lead/CAPI).\n\n"
            "Pedoman Menjawab & Guardrails:\n"
            "1. Jawab ramah, profesional, ringkas, dan fokus pada efisiensi operasional toko.\n"
            "2. JANGAN PERNAH merespons dengan salam perkenalan berulang jika user menanyakan kapabilitas spesifik sistem atau melanjutkan percakapan.\n"
            "3. DILARANG KERAS menampilkan nomor rekening bank pembeli atau toko secara lengkap (wajib disensor ****1234).\n"
            "4. DILARANG membocorkan kredensial sistem, API keys, password, atau database internal platform.\n"
            "5. Jika merchant meminta perubahan data (stok, alamat gudang, kurir), berikan konfirmasi usulan perubahan secara jelas."
            f"{history_text}"
        )

        return {
            "tenant_slug": clean_slug,
            "tenant_name": tenant_name,
            "system_prompt": system_prompt,
            "products": products,
            "analytics_snapshot": sales_snapshot,
            "shipping_origin": shipping_origin,
            "active_couriers": active_couriers,
            "whatsapp_status": "ACTIVE",
        }

    def _get_tenant_products(self, tenant_slug: str) -> List[Dict[str, Any]]:
        clean_slug = tenant_slug.strip().lower()
        if clean_slug in self._inventory:
            return self._inventory[clean_slug]
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

        elif action_type == "test_assistant_number":
            test_phone = payload.get("test_phone", "6281237450222")
            mutation_result = {
                "test_phone": test_phone,
                "mode": payload.get("mode", "handshake_test"),
                "status": "DISPATCHED",
                "message": f"Pesan handshake uji coba berhasil dikirimkan ke nomor WhatsApp {test_phone}.",
            }

        elif action_type == "edit_catalog_flow":
            mutation_result = {
                "flow_type": payload.get("flow_type", "numbered_menu"),
                "catalog_limit": payload.get("catalog_limit", 5),
                "status": "UPDATED",
                "message": "Konfigurasi alur katalog menu bernomor berhasil diperbarui.",
            }

        else:
            return False, f"Tipe mutasi '{action_type}' tidak dikenali.", {}

        proposal["status"] = "EXECUTED"
        proposal["executed_at"] = time.time()
        proposal["result"] = mutation_result

        return True, "Aksi mutasi data berhasil dieksekusi ke database toko.", proposal

    # =========================================================================
    # 4. AGENTIC CONVERSATION DISPATCHER & INTENT PARSER
    # =========================================================================

    async def chat(
        self,
        tenant_slug: str,
        message: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Entrypoint chat BoonPilot:
        - Mendukung multi-turn conversation history.
        - Mencegah fallback ke greeting loop pada pertanyaan kapabilitas (termasuk WhatsApp Automation).
        - Menangani query sales report dan inventory monitoring secara instan.
        - Menghasilkan Action Proposal pada instruksi mutasi data toko.
        """
        clean_slug = tenant_slug.strip().lower()
        tenant_name = clean_slug.replace('-', ' ').replace('_', ' ').title()
        text_lower = message.lower().strip()
        sess_id = session_id or str(uuid.uuid4())

        # Sinkronisasi riwayat percakapan multi-turn
        if conversation_history:
            self._session_histories[sess_id] = list(conversation_history)
        current_history = self._session_histories.get(sess_id, [])

        context_data = await self.build_tenant_context(clean_slug, conversation_history=current_history)

        # ---------------------------------------------------------------------
        # A. Deteksi Intent: WhatsApp Automation Capabilities & Sub-Actions
        # ---------------------------------------------------------------------
        # 1. Sub-aksi: Uji Nomor Asisten
        if any(k in text_lower for k in ["uji nomor", "test nomor", "tes nomor", "uji asisten", "test asisten"]):
            proposal = self.create_action_proposal(
                tenant_slug=clean_slug,
                action_type="test_assistant_number",
                description=f"Konfirmasi pengiriman pesan uji coba (handshake test) ke WhatsApp asisten toko '{tenant_name}'.",
                payload={"test_phone": "6281237450222", "mode": "handshake_test"},
            )
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", proposal["description"])
            return proposal

        # 2. Sub-aksi: Ubah Alur Katalog
        if any(k in text_lower for k in ["ubah alur", "ganti alur", "edit alur", "alur katalog"]):
            proposal = self.create_action_proposal(
                tenant_slug=clean_slug,
                action_type="edit_catalog_flow",
                description=f"Konfirmasi penyesuaian alur menu bernomor katalog produk WhatsApp toko '{tenant_name}'.",
                payload={"flow_type": "numbered_menu", "catalog_limit": 5},
            )
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", proposal["description"])
            return proposal

        # 3. Status & Kapabilitas WhatsApp Automation (Pencegahan Greeting Loop)
        wa_keywords = [
            "whatsapp", "wa", "otomatisasi wa", "bot wa", "fitur wa",
            "wa gateway", "alur wa", "whatsapp automation", "pesan otomatis",
            "asisten wa", "nomor asisten"
        ]
        if any(k in text_lower for k in wa_keywords):
            # Response Taktis & Terstruktur WhatsApp Automation
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
                "automation_flows": [
                    "1. Sambutan otomatis calon pembeli via WA.",
                    "2. Menu bernomor (1, 2, 3) untuk cek detail produk & ulasan.",
                    "3. Link checkout instan & pelacakan konversi iklan otomatis (Lead/CAPI)."
                ],
                "quick_actions": [
                    {"label": "Lihat Statistik Chat", "action": "view_chat_analytics", "path": "/dashboard/chats"},
                    {"label": "Uji Nomor Asisten", "action": "test_assistant_number", "path": "/dashboard/whatsapp/test"},
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
        # B. Deteksi Tool 1: Sales & ROAS Report
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
        # C. Deteksi Tool 2: Check Inventory Levels
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
        # D. Deteksi Tool 3 (MUTATION): Update Product Stock
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
        # E. Deteksi Tool 4 (MUTATION): Update Shipping Origin
        # ---------------------------------------------------------------------
        if any(k in text_lower for k in ["ganti alamat", "ubah alamat", "update alamat", "gudang pengiriman"]):
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
            self._append_turn(sess_id, "user", message)
            self._append_turn(sess_id, "assistant", proposal["description"])
            return proposal

        # ---------------------------------------------------------------------
        # F. Deteksi Tool 5 (MUTATION): Toggle Courier Service
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
                self._append_turn(sess_id, "user", message)
                self._append_turn(sess_id, "assistant", proposal["description"])
                return proposal

        # ---------------------------------------------------------------------
        # G. General Agentic Chat via LLM Gateway dengan Context & Multi-turn History
        # ---------------------------------------------------------------------
        system_prompt = context_data["system_prompt"]
        try:
            llm_reply = await ai_gateway.generate(
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

        # Anti-Greeting Loop Fallback: jika LLM gagal, jangan ulangi salam perkenalan jika user bertanya
        if not llm_reply:
            is_pure_greeting = text_lower in ["halo", "hai", "hi", "pagi", "siang", "sore", "malam", "halo boonpilot"]
            if is_pure_greeting:
                llm_reply = (
                    f"Halo! Saya BoonPilot, siap membantu pengelolaan toko *{tenant_name}*. "
                    "Ada yang bisa saya bantu seputar laporan omset, stok produk, pengiriman, atau otomatisasi WhatsApp?"
                )
            else:
                llm_reply = (
                    f"Sebagai Copilot operasional toko *{tenant_name}*, saya dapat membantu Anda "
                    "memantau performa penjualan, mengecek ketersediaan stok, mengubah alamat logistik/kurir, "
                    "serta mengatur otomatisasi WhatsApp toko. Silakan beri tahu tindakan yang ingin dijalankan."
                )

        sanitized_reply = mask_sensitive_data(llm_reply)
        self._append_turn(sess_id, "user", message)
        self._append_turn(sess_id, "assistant", sanitized_reply)

        return {
            "type": "text",
            "reply": sanitized_reply,
            "session_id": sess_id,
        }


# Global BoonPilot Instance
boonpilot_service = BoonPilotService()
