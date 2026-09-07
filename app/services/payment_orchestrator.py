import json
import logging
from datetime import datetime, date
from typing import Dict, Any, Optional
from fastapi import HTTPException
from supabase import Client

from app.services.whatsapp_delivery_service import WhatsAppDeliveryService

logger = logging.getLogger("boontrack.payment")

class PaymentOrchestrator:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client
        self.wa_service = WhatsAppDeliveryService()

    async def create_qr_code(
        self,
        external_id: str,
        amount: int,
        tenant_id: str = "onlineboost",
        customer_phone: Optional[str] = None,
        product_name: str = "Modul Praktis CPM 24 Jam",
        metadata: Optional[Dict[str, Any]] = None,
        gateway: str = "xendit",
    ) -> Dict[str, Any]:
        """Creates dynamic QRIS code with switchable gateway architecture:
        - Default: 100% official Xendit Production API (no silent fallback).
        - Standby: Isolated local DANA Bisnis generator ONLY when gateway='dana_bisnis'.
        """
        clean_gateway = str(gateway or "xendit").strip().lower()

        # Opsi Standby: DANA Bisnis hanya aktif jika dipanggil secara eksplisit
        if clean_gateway == "dana_bisnis":
            from app.utils.qris_generator import get_dynamic_qris_string, get_qr_code_image_url
            qr_string = get_dynamic_qris_string(amount=amount, invoice_id=external_id)
            return {
                "qr_string": qr_string,
                "qr_code_url": get_qr_code_image_url(qr_string),
                "qr_id": f"dana_{external_id}",
                "status": "ACTIVE",
                "amount": amount,
                "external_id": external_id,
                "provider": "DANA_BISNIS",
            }

        # Jalur Default: 100% Xendit Production API (tanpa silent fallback)
        from app.services.xendit_service import xendit_service
        meta = metadata or {}
        meta["product_name"] = product_name
        return await xendit_service.create_qr_code(
            external_id=external_id,
            amount=amount,
            tenant_id=tenant_id,
            customer_phone=customer_phone,
            metadata=meta,
        )

    async def create_invoice(
        self,
        external_id: str,
        amount: int,
        product_name: str = "Modul Praktis CPM 24 Jam",
        customer_phone: Optional[str] = None,
        tenant_id: str = "onlineboost",
    ) -> Dict[str, Any]:
        """Creates official invoice on Xendit API."""
        from app.services.xendit_service import xendit_service
        return await xendit_service.create_invoice(
            external_id=external_id,
            amount=amount,
            product_name=product_name,
            customer_phone=customer_phone,
            tenant_id=tenant_id,
        )

    async def process_xendit_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler Idempotent untuk Webhook Xendit QRIS / Invoice.
        Memvalidasi transaksi, mencatat status LUNAS, mencatat ledger komisi multi-tier, dan mengirim notifikasi WhatsApp otomatis.
        """
        data_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        event_id = payload.get("id") or payload.get("payment_id") or payload.get("qr_id") or data_obj.get("id") or data_obj.get("payment_id")
        external_id = data_obj.get("external_id") or data_obj.get("reference_id") or payload.get("external_id")
        status = (data_obj.get("status") or payload.get("status") or "").upper()
        amount = float(data_obj.get("amount") or data_obj.get("paid_amount") or payload.get("amount") or 0)

        if not event_id or not external_id:
            logger.error(f"[Payment] Invalid payload received: {payload}")
            raise HTTPException(status_code=400, detail="Missing event_id or external_id")

        logger.info(f"[Payment] Incoming webhook event: {event_id} for order: {external_id}, status: {status}")

        # 1. IDEMPOTENCY CHECK
        existing_event = self.supabase.table("payment_events").select("id, status").eq("event_id", event_id).execute()
        if existing_event.data:
            logger.warning(f"[Payment] Duplicate event detected: {event_id}. Skipping processing.")
            return {"status": "ignored", "reason": "event_already_processed"}

        # 2. CATAT EVENT INTAKE
        self.supabase.table("payment_events").insert({
            "provider": "XENDIT",
            "event_id": event_id,
            "event_type": f"QRIS_{status}",
            "payload": payload,
            "status": "PROCESSING"
        }).execute()

        # Hanya proses jika status resmi PAID / SETTLED / COMPLETED / SUCCEEDED
        if status not in ["PAID", "SETTLED", "COMPLETED", "SUCCEEDED"]:
            logger.info(f"[Payment] Non-paid status ({status}) ignored for order {external_id}.")
            self.supabase.table("payment_events").update({"status": "IGNORED"}).eq("event_id", event_id).execute()
            return {"status": "success", "message": f"Event recorded with status {status}"}

        # 3. VERIFIKASI DATA ORDER
        order_res = self.supabase.table("orders").select("*").eq("id", external_id).execute()
        if not order_res.data:
            order_res = self.supabase.table("orders").select("*").eq("order_id", external_id).execute()

        if not order_res.data:
            logger.info(f"[Payment] Order not found in db: {external_id}. Auto-registering LUNAS order.")
            now_iso = datetime.utcnow().isoformat()
            new_order = {
                "id": str(external_id),
                "order_id": str(external_id),
                "status": "LUNAS",
                "payment_status": "PAID",
                "paid_at": now_iso,
                "total_amount": amount,
                "amount": amount,
                "customer_phone": data_obj.get("customer_phone") or payload.get("customer_phone"),
                "product_name": data_obj.get("product_name") or payload.get("product_name") or "Modul Praktis CPM 24 Jam",
                "tenant_slug": data_obj.get("tenant_id") or payload.get("tenant_id") or "onlineboost"
            }
            try:
                self.supabase.table("orders").insert(new_order).execute()
                order = new_order
            except Exception as ins_err:
                logger.warning(f"[Payment] Auto-order insert note: {ins_err}")
                order = new_order
        else:
            order = order_res.data[0]
            if order.get("status") in ("PAID", "LUNAS"):
                logger.warning(f"[Payment] Order {external_id} was already marked as LUNAS/PAID.")
                self.supabase.table("payment_events").update({"status": "PROCESSED_DUPLICATE_ORDER"}).eq("event_id", event_id).execute()
                return {"status": "ignored", "reason": "order_already_paid"}

            # 4. UPDATE STATUS ORDER MENJADI LUNAS
            paid_at = datetime.utcnow().isoformat()
            self.supabase.table("orders").update({
                "status": "LUNAS",
                "payment_status": "PAID",
                "paid_at": paid_at,
                "payment_event_id": event_id
            }).eq("id", order.get("id") or external_id).execute()

        # 5. ATRIBUSI KOMISI & COMMISSION LEDGER ENTRY
        affiliate_id = order.get("affiliate_id")
        affiliate_code = order.get("affiliate_code")
        manager_id = order.get("manager_id")
        tenant_slug = order.get("tenant_slug", "onlineboost")

        # Jika order memiliki atribusi referral (affiliate_id atau affiliate_code)
        if affiliate_code or affiliate_id:
            try:
                affiliate_rate = float(order.get("affiliate_commission_rate") or 30.0)
                manager_rate = float(order.get("manager_override_rate") or 10.0)

                affiliate_commission = float(order.get("commission_amount") or ((amount * affiliate_rate) / 100.0))
                manager_override = (amount * manager_rate) / 100.0 if manager_id else 0.0
                net_platform = amount - (affiliate_commission + manager_override)

                # Catat ke Commission Ledger (Immutable Source of Truth)
                ledger_payload = {
                    "order_id": external_id,
                    "affiliate_id": affiliate_id,
                    "affiliate_code": affiliate_code or "DEFAULT",
                    "manager_id": manager_id,
                    "tenant_slug": tenant_slug,
                    "gross_amount": amount,
                    "affiliate_commission_rate": affiliate_rate,
                    "affiliate_commission_amount": affiliate_commission,
                    "manager_override_rate": manager_rate,
                    "manager_override_amount": manager_override,
                    "net_platform_revenue": net_platform,
                    "status": "PENDING_PAYOUT"
                }

                self.supabase.table("commission_ledger").insert(ledger_payload).execute()
                logger.info(f"[Payment] Logged commission ledger for Order {external_id} (Ref: {affiliate_code})")

                # Update Daily Aggregate Stats jika affiliate_id tersedia
                if affiliate_id:
                    today_str = date.today().isoformat()
                    stats_res = self.supabase.table("affiliate_daily_stats").select("*").match({
                        "stat_date": today_str,
                        "affiliate_id": affiliate_id
                    }).execute()

                    if stats_res.data:
                        stat_row = stats_res.data[0]
                        self.supabase.table("affiliate_daily_stats").update({
                            "paid_orders": stat_row["paid_orders"] + 1,
                            "total_revenue": float(stat_row["total_revenue"]) + amount,
                            "total_commission": float(stat_row["total_commission"]) + affiliate_commission
                        }).eq("id", stat_row["id"]).execute()
                    else:
                        self.supabase.table("affiliate_daily_stats").insert({
                            "stat_date": today_str,
                            "affiliate_id": affiliate_id,
                            "total_clicks": 0,
                            "total_orders": 1,
                            "paid_orders": 1,
                            "total_revenue": amount,
                            "total_commission": affiliate_commission
                        }).execute()

            except Exception as e:
                logger.error(f"[Payment] Commission ledger recording error: {str(e)}")

        # 6. TRIGGER WHATSAPP AUTO-DELIVERY
        customer_phone = order.get("customer_phone") or order.get("buyer_phone")
        product_name = order.get("product_title") or order.get("product_name") or "Produk Digital BoonTrack"
        download_url = order.get("digital_access_url") or f"https://shop.boontrack.com/{tenant_slug}/access/{external_id}"

        if customer_phone:
            try:
                await self.wa_service.send_order_success_notification(
                    customer_phone=customer_phone,
                    order_id=external_id,
                    product_name=product_name,
                    amount=amount,
                    download_url=download_url
                )
            except Exception as wa_err:
                logger.error(f"[Payment] WA Delivery dispatch failed: {str(wa_err)}")

        # 7. TRIGGER SERVER-SIDE CAPI PURCHASE EVENT (Meta & TikTok)
        try:
            from app.services.tracking_service import dispatch_all_capi
            capi_payload = {
                "order_id": external_id,
                "amount": amount,
                "currency": "IDR",
                "customer_phone": customer_phone,
                "customer_email": order.get("customer_email") or order.get("buyer_email"),
                "product_name": product_name,
                "fbclid": order.get("fbclid"),
                "ttclid": order.get("ttclid"),
                "user_agent": order.get("user_agent"),
                "client_ip": order.get("client_ip"),
            }
            asyncio.create_task(dispatch_all_capi(capi_payload))
            logger.info(f"[Payment] Triggered CAPI Purchase event for Order {external_id}")
        except Exception as capi_err:
            logger.error(f"[Payment] CAPI dispatch failed: {capi_err}")

        # 8. Tandai event selesai diproses
        self.supabase.table("payment_events").update({"status": "PROCESSED"}).eq("event_id", event_id).execute()

        return {
            "status": "success",
            "order_id": external_id,
            "tenant_slug": tenant_slug,
            "customer_phone": customer_phone,
            "product_name": product_name,
            "delivery_url": download_url
        }