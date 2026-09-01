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

    async def process_xendit_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler Idempotent untuk Webhook Xendit QRIS / Invoice.
        Memvalidasi transaksi, mencatat ledger komisi multi-tier, dan mengirim notifikasi WhatsApp otomatis.
        """
        event_id = payload.get("id") or payload.get("payment_id") or payload.get("qr_id")
        external_id = payload.get("external_id")  # Menyimpan order_id BoonTrack
        status = payload.get("status", "").upper()
        amount = float(payload.get("amount", 0) or payload.get("paid_amount", 0))

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

        # Hanya proses jika status resmi PAID / SETTLED / COMPLETED
        if status not in ["PAID", "SETTLED", "COMPLETED"]:
            logger.info(f"[Payment] Non-paid status ({status}) ignored for order {external_id}.")
            self.supabase.table("payment_events").update({"status": "IGNORED"}).eq("event_id", event_id).execute()
            return {"status": "success", "message": f"Event recorded with status {status}"}

        # 3. VERIFIKASI DATA ORDER
        order_res = self.supabase.table("orders").select("*").eq("id", external_id).execute()
        if not order_res.data:
            logger.error(f"[Payment] Order not found: {external_id}")
            self.supabase.table("payment_events").update({"status": "ORDER_NOT_FOUND"}).eq("event_id", event_id).execute()
            raise HTTPException(status_code=404, detail="Order reference not found")

        order = order_res.data[0]
        
        if order.get("status") == "PAID":
            logger.warning(f"[Payment] Order {external_id} was already marked as PAID.")
            self.supabase.table("payment_events").update({"status": "PROCESSED_DUPLICATE_ORDER"}).eq("event_id", event_id).execute()
            return {"status": "ignored", "reason": "order_already_paid"}

        # 4. UPDATE STATUS ORDER MENJADI PAID
        paid_at = datetime.utcnow().isoformat()
        self.supabase.table("orders").update({
            "status": "PAID",
            "paid_at": paid_at,
            "payment_event_id": event_id
        }).eq("id", external_id).execute()

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

        # 7. Tandai event selesai diproses
        self.supabase.table("payment_events").update({"status": "PROCESSED"}).eq("event_id", event_id).execute()

        return {
            "status": "success",
            "order_id": external_id,
            "tenant_slug": tenant_slug,
            "customer_phone": customer_phone,
            "product_name": product_name,
            "delivery_url": download_url
        }