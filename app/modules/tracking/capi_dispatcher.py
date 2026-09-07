import os
import re
import json
import uuid
import hashlib
import logging
import asyncio
import zoneinfo
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any, Tuple
import httpx

from app.core.database import get_db_connection

logger = logging.getLogger("CAPI_DISPATCHER")


def hash_sha256(value: Optional[str]) -> Optional[str]:
    """Meng-hash nilai privasi pengguna (telepon, email) menggunakan SHA-256 lowercase."""
    if not value:
        return None
    clean = str(value).strip().lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def normalize_phone_for_capi(phone: Optional[str]) -> str:
    """
    Format nomor telepon ke standar internasional E.164 tanpa tanda '+' atau spasi.
    Misal: '08123456789' -> '628123456789', '+62 812-345' -> '62812345'.
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if digits.startswith("08"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    return digits


class CapiDispatcher:
    """
    Dispatcher resmi Meta Conversions API (CAPI) & CTWA Attribution Tracking.
    Mendukung multi-tenant credentials, event ledger auditing, dan standardisasi timezone.
    """

    GRAPH_API_VERSION = "v21.0"

    @staticmethod
    def get_daily_reporting_query(tenant_tz: str = "Asia/Jakarta") -> str:
        """
        Helper query SQL reporting omzet & event harian terstandarisasi timezone bisnis tenant.
        Formula: SELECT (occurred_at AT TIME ZONE 'UTC' AT TIME ZONE :tenant_tz)::date AS business_date
        """
        return (
            f"SELECT (occurred_at AT TIME ZONE 'UTC' AT TIME ZONE '{tenant_tz}')::date AS business_date, "
            "event_name, "
            "COUNT(*) AS total_events, "
            "delivery_status "
            "FROM event_ledger "
            "WHERE tenant_id = :tenant_id "
            "GROUP BY business_date, event_name, delivery_status "
            "ORDER BY business_date DESC;"
        )

    @staticmethod
    def convert_to_business_date(occurred_at: datetime, tenant_tz: str = "Asia/Jakarta") -> date:
        """
        Mengonversi timestamp UTC ke tanggal bisnis (business date) lokal tenant.
        Contoh: 17:05 UTC (00:05 WIB esok harinya) jatuh pada tanggal bisnis esok harinya di Asia/Jakarta.
        """
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        tz = zoneinfo.ZoneInfo(tenant_tz)
        return occurred_at.astimezone(tz).date()

    async def resolve_credentials(self, tenant_id: str) -> Tuple[str, str]:
        """
        Mengambil dataset_id dan access_token dari tenant_meta_configs.
        Fallback ke environment variables (META_DATASET_ID / META_CAPI_ACCESS_TOKEN) jika belum ada.
        """
        def _fetch_config():
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT dataset_id, pixel_id, access_token_ref 
                    FROM tenant_meta_configs 
                    WHERE tenant_id = %s AND is_active = TRUE 
                    LIMIT 1;
                    """,
                    (tenant_id,)
                )
                row = cur.fetchone()
                cur.close()
                conn.close()
                if row:
                    ds_id = row[0] or row[1] or ""
                    token = row[2] or ""
                    return str(ds_id).strip(), str(token).strip()
            except Exception as e:
                logger.debug(f"[CAPI Credential Lookup Note] {e}")
            return "", ""

        dataset_id, access_token = await asyncio.to_thread(_fetch_config)

        if not dataset_id:
            dataset_id = (
                os.getenv("META_DATASET_ID")
                or os.getenv("META_PIXEL_ID")
                or ""
            ).strip()

        if not access_token:
            access_token = (
                os.getenv("META_CAPI_ACCESS_TOKEN")
                or os.getenv("META_CAPI_TOKEN")
                or os.getenv("WHATSAPP_TOKEN")
                or os.getenv("META_WA_TOKEN")
                or ""
            ).strip()

        return dataset_id, access_token

    async def record_ledger(
        self,
        tenant_id: str,
        event_name: str,
        occurred_at: datetime,
        payload: Dict[str, Any],
        delivery_status: str,
        response_payload: Optional[str] = None,
        event_id: Optional[uuid.UUID] = None,
    ) -> uuid.UUID:
        """Mencatat entri pengiriman ke tabel event_ledger untuk deduplikasi dan audit trail."""
        if not event_id:
            event_id = uuid.uuid4()

        payload_json = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        def _insert_ledger():
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO event_ledger (
                        event_id, tenant_id, event_name, occurred_at, payload_hash,
                        delivery_status, retry_count, response_payload, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO UPDATE SET
                        delivery_status = EXCLUDED.delivery_status,
                        response_payload = EXCLUDED.response_payload,
                        retry_count = event_ledger.retry_count + 1;
                    """,
                    (
                        str(event_id),
                        tenant_id,
                        event_name,
                        occurred_at,
                        payload_hash,
                        delivery_status,
                        0,
                        response_payload,
                        datetime.now(timezone.utc),
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.error(f"[EVENT LEDGER WRITE ERROR] Failed to record ledger: {e}")

        await asyncio.to_thread(_insert_ledger)
        return event_id

    async def record_marketing_attribution(
        self,
        tenant_id: str,
        session_id: str,
        ctwa_clid: str,
        source_id: Optional[str] = None,
        source_url: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
        conversation_id: Optional[str] = None,
    ) -> uuid.UUID:
        """
        Menyimpan record atribusi iklan Meta CTWA ke tabel marketing_attributions.
        ctwa_clid disimpan dalam kondisi UNHASHED sesuai spesifikasi Meta.
        """
        attr_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        if occurred_at is None:
            occurred_at = now_utc
        elif occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        def _insert_attr():
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO marketing_attributions (
                        id, tenant_id, session_id, conversation_id, channel, source,
                        ctwa_clid, source_id, source_url, occurred_at, received_at, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        str(attr_id),
                        tenant_id,
                        session_id,
                        conversation_id,
                        "WHATSAPP_CTWA",
                        "META_ADS",
                        ctwa_clid,
                        source_id,
                        source_url,
                        occurred_at,
                        now_utc,
                        now_utc,
                    ),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.error(f"[MARKETING ATTRIBUTION WRITE ERROR] {e}")

        await asyncio.to_thread(_insert_attr)
        return attr_id

    async def capture_ctwa_referral(
        self,
        tenant_id: str,
        session_id: str,
        referral_data: Dict[str, Any],
        occurred_at: Optional[datetime] = None,
        conversation_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Mengekstrak ctwa_clid, source_id, source_url dari objek referral inbound WhatsApp,
        lalu menyimpannya ke marketing_attributions. Mengembalikan ctwa_clid unhashed.
        """
        if not referral_data or not isinstance(referral_data, dict):
            return None

        ctwa_clid = referral_data.get("ctwa_clid")
        if not ctwa_clid:
            return None

        source_id = str(referral_data.get("source_id") or "") or None
        source_url = referral_data.get("source_url")

        await self.record_marketing_attribution(
            tenant_id=tenant_id,
            session_id=session_id,
            ctwa_clid=str(ctwa_clid).strip(),
            source_id=source_id,
            source_url=source_url,
            occurred_at=occurred_at,
            conversation_id=conversation_id,
        )
        return str(ctwa_clid).strip()

    async def dispatch_initiate_checkout(
        self,
        tenant_id: str,
        phone: str,
        total_amount: float,
        product_ids: List[str],
        ctwa_clid: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Mengirimkan event 'InitiateCheckout' ke Meta Conversions API.
        Trigger: Saat action validator meloloskan tombol [💳 Beli Sekarang (QR)].
        """
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)
        elif occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        event_epoch = int(occurred_at.timestamp())
        event_uuid = uuid.uuid4()
        clean_phone = normalize_phone_for_capi(phone)
        hashed_phone = hash_sha256(clean_phone)

        user_data: Dict[str, Any] = {}
        if hashed_phone:
            user_data["ph"] = [hashed_phone]
        if ctwa_clid:
            user_data["ctwa_clid"] = str(ctwa_clid).strip()

        content_list = [str(p) for p in product_ids] if isinstance(product_ids, (list, tuple)) else [str(product_ids)]

        event_payload = {
            "event_name": "InitiateCheckout",
            "event_time": event_epoch,
            "event_id": str(event_uuid),
            "action_source": "business_messaging",
            "user_data": user_data,
            "custom_data": {
                "currency": "IDR",
                "value": float(total_amount),
                "content_ids": content_list,
                "content_type": "product",
            },
        }
        body = {"data": [event_payload]}

        dataset_id, token = await self.resolve_credentials(tenant_id)
        delivery_status = "PENDING"
        resp_text = None

        if not dataset_id or not token or dataset_id.startswith("mock_") or token.startswith("mock_"):
            logger.info(
                f"[CAPI MOCK DISPATCH] InitiateCheckout for tenant '{tenant_id}' (Amount: Rp{total_amount:,.0f}) | ctwa_clid={ctwa_clid}"
            )
            delivery_status = "SENT"
            resp_text = json.dumps({"status": "mock_sent", "events_received": 1})
        else:
            url = f"https://graph.facebook.com/{self.GRAPH_API_VERSION}/{dataset_id}/events"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=body, params={"access_token": token})
                    resp_text = resp.text
                    if resp.status_code in (200, 201):
                        delivery_status = "SENT"
                    else:
                        delivery_status = "FAILED"
                        logger.warning(f"[CAPI GRAPH API ERROR] InitiateCheckout {resp.status_code}: {resp_text}")
            except Exception as net_err:
                delivery_status = "FAILED"
                resp_text = str(net_err)
                logger.error(f"[CAPI DISPATCH EXCEPTION] InitiateCheckout: {net_err}")

        await self.record_ledger(
            tenant_id=tenant_id,
            event_name="InitiateCheckout",
            occurred_at=occurred_at,
            payload=body,
            delivery_status=delivery_status,
            response_payload=resp_text,
            event_id=event_uuid,
        )

        return {
            "status": delivery_status,
            "event_id": str(event_uuid),
            "event_epoch": event_epoch,
            "payload": body,
        }

    async def dispatch_purchase(
        self,
        tenant_id: str,
        phone: str,
        total_amount: float,
        product_ids: List[str],
        order_id: str,
        ctwa_clid: Optional[str] = None,
        occurred_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Mengirimkan event 'Purchase' ke Meta Conversions API.
        Trigger: Saat webhook notifikasi pembayaran SUCCEEDED/PAID diterima.
        Deduplikasi: event_id disetel menggunakan order_id/payment_id.
        """
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)
        elif occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        event_epoch = int(occurred_at.timestamp())
        clean_phone = normalize_phone_for_capi(phone)
        hashed_phone = hash_sha256(clean_phone)

        # Generate deterministic UUID from order_id for database ledger primary key if order_id is not already UUID
        try:
            event_uuid = uuid.UUID(str(order_id))
        except (ValueError, AttributeError):
            event_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"boontrack.order.{order_id}")

        user_data: Dict[str, Any] = {}
        if hashed_phone:
            user_data["ph"] = [hashed_phone]
        if ctwa_clid:
            user_data["ctwa_clid"] = str(ctwa_clid).strip()

        content_list = [str(p) for p in product_ids] if isinstance(product_ids, (list, tuple)) else [str(product_ids)]

        event_payload = {
            "event_name": "Purchase",
            "event_time": event_epoch,
            "event_id": str(order_id),
            "action_source": "business_messaging",
            "user_data": user_data,
            "custom_data": {
                "currency": "IDR",
                "value": float(total_amount),
                "order_id": str(order_id),
                "content_ids": content_list,
                "content_type": "product",
            },
        }
        body = {"data": [event_payload]}

        dataset_id, token = await self.resolve_credentials(tenant_id)
        delivery_status = "PENDING"
        resp_text = None

        if not dataset_id or not token or dataset_id.startswith("mock_") or token.startswith("mock_"):
            logger.info(
                f"[CAPI MOCK DISPATCH] Purchase for tenant '{tenant_id}', order '{order_id}' "
                f"(Amount: Rp{total_amount:,.0f}) | ctwa_clid={ctwa_clid}"
            )
            delivery_status = "SENT"
            resp_text = json.dumps({"status": "mock_sent", "events_received": 1})
        else:
            url = f"https://graph.facebook.com/{self.GRAPH_API_VERSION}/{dataset_id}/events"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=body, params={"access_token": token})
                    resp_text = resp.text
                    if resp.status_code in (200, 201):
                        delivery_status = "SENT"
                    else:
                        delivery_status = "FAILED"
                        logger.warning(f"[CAPI GRAPH API ERROR] Purchase {resp.status_code}: {resp_text}")
            except Exception as net_err:
                delivery_status = "FAILED"
                resp_text = str(net_err)
                logger.error(f"[CAPI DISPATCH EXCEPTION] Purchase: {net_err}")

        await self.record_ledger(
            tenant_id=tenant_id,
            event_name="Purchase",
            occurred_at=occurred_at,
            payload=body,
            delivery_status=delivery_status,
            response_payload=resp_text,
            event_id=event_uuid,
        )

        return {
            "status": delivery_status,
            "event_id": str(order_id),
            "event_epoch": event_epoch,
            "payload": body,
        }


# Global singleton instance
capi_dispatcher = CapiDispatcher()
