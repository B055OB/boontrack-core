import logging
import os
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from app.schemas.tenant_config import TenantConfig, MenuItem
from app.utils.qris_generator import (
    generate_unique_code,
    get_dynamic_qris_string,
    get_quickchart_qr_url,
)
from app.services.ai_gateway import ai_gateway

logger = logging.getLogger("GENERIC_TENANT_ENGINE")


class GenericTenantEngine:
    """Universal Config-Driven Execution Engine for BoonTrack Tenants.
    
    Menangani:
    1. Keyword navigasi ('menu', 'batal', 'reset', dll) -> reset user context & tampilkan main menu.
    2. Deteksi eskalasi ('admin', 'cs', dll) -> eskalasi ke staf operasional.
    3. Eksekusi item menu / paket -> generate Dynamic QRIS + QuickChart image URL jika ada nominal tagihan.
    4. Persona AI Completion -> generate jawaban cerdas berbasis system_prompt tenant tanpa if-else per-tenant.
    """

    def __init__(self, ai_service=None):
        self.ai_service = ai_service or ai_gateway

    async def handle_message(
        self,
        tenant_config: TenantConfig,
        incoming_message: str,
        user_context: Optional[Dict[str, Any]] = None,
        user_id: str = ""
    ) -> Dict[str, Any]:
        """Memproses pesan masuk untuk tenant tertentu berdasarkan konfigurasi deklaratifnya.
        
        Returns:
            Dict berformat:
            {
                "status": "success",
                "action": "SEND_TEXT" | "SEND_QRIS" | "ESCALATE",
                "text": str,
                "image_url": Optional[str],
                "amount": Optional[int],
                "state": str
            }
        """
        user_context = user_context if user_context is not None else {}
        clean_text = (incoming_message or "").strip()
        lower_text = clean_text.lower()
        tenant_id = tenant_config.identity.tenant_id

        # ---------------------------------------------------------------------
        # 1. CEK KEYWORD NAVIGASI RESET (menu, batal, reset, ulang, start)
        # ---------------------------------------------------------------------
        nav_keywords = tenant_config.menu_config.keywords or {
            "menu": "MAIN_MENU",
            "batal": "RESET",
            "reset": "RESET",
            "ulang": "RESET",
            "start": "MAIN_MENU",
        }
        
        if lower_text in nav_keywords or any(lower_text == k for k in nav_keywords):
            logger.info(f"[{tenant_id}] Navigation trigger detected: '{clean_text}' for user={user_id}")
            user_context["state"] = "IDLE"
            user_context["pending_order"] = None
            
            menu_text = tenant_config.menu_config.main_menu_text
            if tenant_config.persona.welcome_message and user_context.get("first_time"):
                menu_text = f"{tenant_config.persona.welcome_message}\n\n{menu_text}"

            return {
                "status": "success",
                "action": "SEND_TEXT",
                "text": menu_text,
                "image_url": None,
                "amount": None,
                "state": "IDLE"
            }

        # ---------------------------------------------------------------------
        # 2. CEK KEYWORD ESKALASI KE ADMIN / CS
        # ---------------------------------------------------------------------
        escalation_words = tenant_config.menu_config.escalation_keywords or [
            "admin", "cs", "komplain", "refund", "human", "bantuan manusia", "petugas"
        ]
        if any(w in lower_text for w in escalation_words):
            logger.info(f"[{tenant_id}] Escalation trigger detected: '{clean_text}' for user={user_id}")
            user_context["state"] = "ESCALATED"
            msg = tenant_config.menu_config.escalation_message or (
                "Pesan Anda telah kami teruskan ke tim Admin. Staf kami akan segera menghubungi Anda."
            )
            return {
                "status": "success",
                "action": "ESCALATE",
                "text": msg,
                "image_url": None,
                "amount": None,
                "state": "ESCALATED"
            }

        # ---------------------------------------------------------------------
        # 3. CEK MENU OPTIONS (ORDER QRIS, URL, TEXT REPLY)
        # ---------------------------------------------------------------------
        matched_option: Optional[MenuItem] = None
        for opt in tenant_config.menu_config.options:
            if lower_text == opt.id.lower() or lower_text == opt.title.lower():
                matched_option = opt
                break

        if matched_option:
            logger.info(f"[{tenant_id}] Matched menu option '{matched_option.title}' (action={matched_option.action})")
            
            # Jika aksi memicu pembayaran QRIS
            if matched_option.action == "ORDER_QRIS" or matched_option.price_amount > 0:
                base_price = matched_option.price_amount
                unique_code = 0
                if tenant_config.payment_config.use_unique_code:
                    unique_code = generate_unique_code(min_val=100, max_val=999)
                
                total_amount = base_price + unique_code
                master_static = (
                    tenant_config.payment_config.static_qris_payload
                    or os.getenv("BOONTRACK_STATIC_QRIS", "")
                )
                
                dynamic_qris_string = get_dynamic_qris_string(total_amount, master_static)
                qr_url = get_quickchart_qr_url(dynamic_qris_string)

                formatted_amount = f"{total_amount:,}".replace(",", ".")
                formatted_unique = f"{unique_code:,}".replace(",", ".")
                invoice_text = (
                    f"📄 *Tagihan Layanan: {matched_option.title}*\n\n"
                    f"Total Tagihan: *Rp{formatted_amount}*\n"
                )
                if unique_code > 0:
                    invoice_text += f"(Termasuk kode unik transfer: *Rp{formatted_unique}*)\n\n"
                else:
                    invoice_text += "\n"

                invoice_text += (
                    "Silakan scan QRIS di atas menggunakan DANA, BCA, GoPay, OVO, ShopeePay, "
                    "atau Mobile Banking apa pun. Pembayaran Anda akan terkonfirmasi secara otomatis!\n\n"
                    "_Ketik 'menu' jika ingin membatalkan atau kembali ke menu utama._"
                )

                user_context["state"] = "WAITING_PAYMENT"
                user_context["pending_order"] = {
                    "package_id": matched_option.id,
                    "title": matched_option.title,
                    "amount": total_amount,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }

                return {
                    "status": "success",
                    "action": "SEND_QRIS",
                    "text": invoice_text,
                    "image_url": qr_url,
                    "amount": total_amount,
                    "qris_string": dynamic_qris_string,
                    "state": "WAITING_PAYMENT"
                }

            # Aksi OPEN_URL / LINK
            if matched_option.action == "OPEN_URL" and matched_option.payload:
                reply_text = f"Berikut link {matched_option.title}:\n{matched_option.payload}"
                if matched_option.description:
                    reply_text = f"{matched_option.description}\n\n{reply_text}"
                return {
                    "status": "success",
                    "action": "SEND_TEXT",
                    "text": reply_text,
                    "image_url": None,
                    "amount": None,
                    "state": "MENU_SELECTED"
                }

            # Aksi TEXT_REPLY standar
            reply_text = matched_option.description or matched_option.title
            return {
                "status": "success",
                "action": "SEND_TEXT",
                "text": reply_text,
                "image_url": None,
                "amount": None,
                "state": "MENU_SELECTED"
            }

        # ---------------------------------------------------------------------
        # 4. AI COMPLETION BERBASIS PERSONA TENANT
        # ---------------------------------------------------------------------
        if tenant_config.feature_flags.enable_ai_completion and self.ai_service:
            try:
                ai_response = await self.ai_service.generate(
                    user_message=clean_text,
                    context={"user_id": user_id, "tenant": tenant_id},
                    system_prompt=tenant_config.persona.system_prompt
                )
                if ai_response and ai_response.strip():
                    return {
                        "status": "success",
                        "action": "SEND_TEXT",
                        "text": ai_response.strip(),
                        "image_url": None,
                        "amount": None,
                        "state": "AI_CHAT"
                    }
            except Exception as err:
                logger.warning(f"[{tenant_id}] AI completion error: {err}")

        # ---------------------------------------------------------------------
        # 5. DEFAULT FALLBACK MESSAGE
        # ---------------------------------------------------------------------
        return {
            "status": "success",
            "action": "SEND_TEXT",
            "text": tenant_config.persona.default_fallback_message,
            "image_url": None,
            "amount": None,
            "state": "FALLBACK"
        }


# Singleton instance generic tenant engine
generic_tenant_engine = GenericTenantEngine()
