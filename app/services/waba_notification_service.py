"""
app/services/waba_notification_service.py

Layanan notifikasi WhatsApp Business API (WABA Cloud API) transaksional.
HANYA aktif pada event "UANG MASUK" (pembayaran berhasil / lunas).

Policy:
- Trigger 1: Tenant Subscription Paid → notifikasi ke nomor WA tenant
- Trigger 2: Super Admin Alert       → notifikasi ke nomor WA Super Admin
- Trigger 3: Affiliate Referral Paid → notifikasi ke WA Affiliate + WA AM + WA Super Admin
- Trigger 4: AM Closing Paid         → notifikasi ke WA AM + WA Super Admin

Semua fungsi bersifat non-blocking (fire-and-forget via asyncio.create_task).
Dispatcher tunggal: dispatch_payment_success_notifications(order_id)
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any

import httpx

from app.services.whatsapp_service import normalize_phone_number, get_supabase

logger = logging.getLogger("WABA_NOTIFICATION_SERVICE")

# ---------------------------------------------------------------------------
# Environment Config
# ---------------------------------------------------------------------------
# Environment Config
# ---------------------------------------------------------------------------
WABA_ACCESS_TOKEN: str = (
    os.getenv("WABA_ACCESS_TOKEN")
    or os.getenv("META_WA_PERMANENT_TOKEN")
    or os.getenv("WHATSAPP_TOKEN")
    or ""
).strip()

WABA_PHONE_NUMBER_ID: str = (
    os.getenv("META_WABA_PHONE_NUMBER_ID")
    or os.getenv("WABA_PHONE_NUMBER_ID")
    or os.getenv("META_WA_PHONE_NUMBER_ID")
    or os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    or os.getenv("PHONE_NUMBER_ID")
    or "1365010890024026"
).strip()

SUPER_ADMIN_WA_PHONE: str = os.getenv("SUPER_ADMIN_WA_PHONE", "").strip()

META_GRAPH_VERSION: str = (
    os.getenv("META_WABA_API_VERSION")
    or os.getenv("META_GRAPH_VERSION")
    or "v26.0"
)
META_BASE_URL: str = f"https://graph.facebook.com/{META_GRAPH_VERSION}"

# ---------------------------------------------------------------------------
# [SAFETY GUARD] Blocklist nomor/ID yang dinonaktifkan sementara
# Nomor resmi Shop telah diperbarui ke +6285181830080. Gunakan env META_WABA_PHONE_NUMBER_ID.
# ---------------------------------------------------------------------------
_DEACTIVATED_PHONE_IDS: frozenset = frozenset(["1268977686299719"])
_DEACTIVATED_PHONES: frozenset = frozenset()


def _is_blocked_sender(phone_number_id: str) -> bool:
    """Return True jika Phone Number ID termasuk dalam blocklist deactivated."""
    return str(phone_number_id).strip() in _DEACTIVATED_PHONE_IDS


def _is_blocked_recipient(to_phone: str) -> bool:
    """Return True jika nomor tujuan termasuk dalam blocklist deactivated."""
    clean = str(to_phone).strip().lstrip("+")
    return clean in _DEACTIVATED_PHONES


# ---------------------------------------------------------------------------
# Internal: Low-level WABA text sender (FREE-FORM via session window)
# Falls back gracefully when outside 24-hour session window.
# ---------------------------------------------------------------------------

async def _send_waba_text(to_phone: str, message: str, phone_number_id: str = "", access_token: str = "") -> Dict[str, Any]:
    """Kirim free-form text message via WABA Cloud API ke nomor tujuan."""
    pid = phone_number_id or WABA_PHONE_NUMBER_ID
    token = access_token or WABA_ACCESS_TOKEN
    clean = normalize_phone_number(to_phone)

    # [SAFETY GUARD] Blokir sender Phone ID yang dinonaktifkan
    if _is_blocked_sender(pid):
        logger.warning(
            f"[WABA_NOTIF BLOCKED] WABA sender Phone ID '{pid}' dinonaktifkan sementara "
            f"(pending new number replacement). Dispatch ke '{to_phone}' ditahan."
        )
        return {"success": False, "error": "WABA sender deactivated / pending new number replacement", "blocked": True}

    # [SAFETY GUARD] Blokir recipient yang dinonaktifkan
    if _is_blocked_recipient(to_phone):
        logger.warning(
            f"[WABA_NOTIF BLOCKED] Nomor tujuan '{to_phone}' termasuk dalam daftar "
            f"nonaktif (pending replacement). Dispatch ditahan."
        )
        return {"success": False, "error": "WABA recipient deactivated / pending new number replacement", "blocked": True}

    if not pid or not token:
        logger.warning("[WABA_NOTIF] Kredensial WABA tidak terkonfigurasi — skip send.")
        return {"success": False, "error": "WABA credentials not configured"}
    if not clean or len(clean) < 8:
        logger.warning(f"[WABA_NOTIF] Nomor tujuan tidak valid: '{to_phone}'")
        return {"success": False, "error": f"Invalid phone: {to_phone}"}


    url = f"{META_BASE_URL}/{pid}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean,
        "type": "text",
        "text": {"preview_url": False, "body": message},
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                res = resp.json()
                msg_id = (res.get("messages") or [{}])[0].get("id")
                logger.info(f"[WABA_NOTIF ✓] To={clean} | msg_id={msg_id}")
                return {"success": True, "message_id": msg_id, "to": clean}
            else:
                logger.warning(
                    f"[WABA_NOTIF ✗] To={clean} | HTTP {resp.status_code} | {resp.text[:200]}"
                )
                return {"success": False, "status_code": resp.status_code, "error": resp.text}
    except Exception as exc:
        logger.error(f"[WABA_NOTIF Exception] To={clean} | {exc}")
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Trigger 1: Tenant Subscription Paid
# ---------------------------------------------------------------------------

async def notify_tenant_subscription_paid(
    phone: str,
    tenant_name: str,
    package_name: str,
    amount: int,
    active_until: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Kirim ucapan terima kasih + detail paket aktif ke nomor WA tenant
    setelah pembayaran langganan berhasil.
    """
    period_line = f"\n⏳ *Aktif hingga:* {active_until}" if active_until else ""
    message = (
        f"✅ *Pembayaran Langganan Berhasil!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 *Toko:* {tenant_name}\n"
        f"📦 *Paket:* {package_name}\n"
        f"💰 *Nominal:* Rp{amount:,}{period_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Terima kasih telah mempercayakan bisnis Anda kepada BoonTrack! 🚀\n"
        f"Dashboard Anda sudah aktif dan siap digunakan.\n"
        f"Butuh bantuan? Ketik *HELP* kapan saja."
    )
    logger.info(f"[WABA_NOTIF] Trigger 1 — Tenant subscription paid: {tenant_name} @ {phone}")
    return await _send_waba_text(to_phone=phone, message=message)


# ---------------------------------------------------------------------------
# Trigger 2: Super Admin Payment Alert
# ---------------------------------------------------------------------------

async def notify_super_admin_payment(
    order_id: str,
    payer_name: str,
    amount: int,
    source_type: str,
    tenant_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Tembak notifikasi ringkasan instan ke WA Super Admin
    setiap ada pembayaran berhasil dari tenant / order manapun.
    source_type: 'subscription' | 'order' | 'manual' | 'affiliate_referral' | 'am_closing'
    """
    if not SUPER_ADMIN_WA_PHONE:
        logger.warning("[WABA_NOTIF] SUPER_ADMIN_WA_PHONE belum diset di env — skip alert admin.")
        return {"success": False, "error": "SUPER_ADMIN_WA_PHONE not configured"}

    tenant_line = f"\n🏪 *Tenant:* {tenant_name}" if tenant_name else ""
    message = (
        f"💸 *UANG MASUK — BoonTrack Alert*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 *Order ID:* `{order_id}`\n"
        f"👤 *Dari:* {payer_name}\n"
        f"💰 *Nominal:* Rp{amount:,}\n"
        f"📋 *Jenis:* {source_type.upper()}{tenant_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {_now_str()}"
    )
    logger.info(f"[WABA_NOTIF] Trigger 2 — Super Admin alert: order={order_id} amount=Rp{amount:,}")
    return await _send_waba_text(to_phone=SUPER_ADMIN_WA_PHONE, message=message)


# ---------------------------------------------------------------------------
# Trigger 3: Affiliate Referral Earned
# ---------------------------------------------------------------------------

async def notify_affiliate_earning(
    affiliate_phone: str,
    affiliate_name: str,
    commission_amount: int,
    order_id: str,
    am_phone: Optional[str] = None,
    am_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Kirim notifikasi komisi cair ke:
    - WA Affiliate (primary recipient)
    - WA AM terkait (jika ada)
    - WA Super Admin (selalu)
    Semua dikirim paralel via asyncio.gather.
    """
    affiliate_msg = (
        f"🎉 *Komisi Referral Cair!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Hai, {affiliate_name}!*\n"
        f"🧾 *Order Referral:* `{order_id}`\n"
        f"💰 *Komisi Anda:* Rp{commission_amount:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Dana komisi sedang diproses ke rekening terdaftar Anda.\n"
        f"Terus referensikan BoonTrack dan dapatkan lebih banyak! 🚀"
    )

    super_admin_msg = (
        f"🤝 *KOMISI AFFILIATE CAIR — Alert*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 *Order ID:* `{order_id}`\n"
        f"👤 *Affiliate:* {affiliate_name} ({affiliate_phone})\n"
        f"💰 *Komisi:* Rp{commission_amount:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {_now_str()}"
    )

    tasks = [
        _send_waba_text(to_phone=affiliate_phone, message=affiliate_msg),
    ]

    if SUPER_ADMIN_WA_PHONE:
        tasks.append(_send_waba_text(to_phone=SUPER_ADMIN_WA_PHONE, message=super_admin_msg))

    if am_phone and am_name:
        am_msg = (
            f"📊 *Komisi Referral AM — Notifikasi*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *AM:* {am_name}\n"
            f"🤝 *Affiliate:* {affiliate_name}\n"
            f"🧾 *Order:* `{order_id}`\n"
            f"💰 *Komisi Affiliate Cair:* Rp{commission_amount:,}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {_now_str()}"
        )
        tasks.append(_send_waba_text(to_phone=am_phone, message=am_msg))

    logger.info(
        f"[WABA_NOTIF] Trigger 3 — Affiliate earning: affiliate={affiliate_name} "
        f"commission=Rp{commission_amount:,} order={order_id} | {len(tasks)} recipients"
    )
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return {"success": True, "results": [r if not isinstance(r, Exception) else str(r) for r in results]}


# ---------------------------------------------------------------------------
# Trigger 4: AM Closing Paid
# ---------------------------------------------------------------------------

async def notify_am_closing(
    am_phone: str,
    am_name: str,
    amount: int,
    order_id: str,
    closing_fee: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Kirim notifikasi closing ke WA AM dan WA Super Admin secara paralel.
    """
    fee_line = f"\n🏅 *Closing Fee:* Rp{closing_fee:,}" if closing_fee else ""
    am_msg = (
        f"🏆 *Closing Berhasil! — BoonTrack AM*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *AM:* {am_name}\n"
        f"🧾 *Order:* `{order_id}`\n"
        f"💰 *Nominal Order:* Rp{amount:,}{fee_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Kerja bagus! Komisi/closing fee Anda sedang diproses. 💪\n"
        f"⏰ {_now_str()}"
    )

    tasks = [_send_waba_text(to_phone=am_phone, message=am_msg)]

    if SUPER_ADMIN_WA_PHONE:
        admin_msg = (
            f"🏆 *CLOSING AM — Alert Super Admin*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *AM:* {am_name} ({am_phone})\n"
            f"🧾 *Order:* `{order_id}`\n"
            f"💰 *Nominal:* Rp{amount:,}{fee_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {_now_str()}"
        )
        tasks.append(_send_waba_text(to_phone=SUPER_ADMIN_WA_PHONE, message=admin_msg))

    logger.info(f"[WABA_NOTIF] Trigger 4 — AM closing: am={am_name} order={order_id} amount=Rp{amount:,}")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return {"success": True, "results": [r if not isinstance(r, Exception) else str(r) for r in results]}


# ---------------------------------------------------------------------------
# ORCHESTRATOR: dispatch_payment_success_notifications
# ---------------------------------------------------------------------------

async def dispatch_payment_success_notifications(order_id: str) -> Dict[str, Any]:
    """
    Orchestrator tunggal — dipanggil setelah setiap pembayaran berhasil.

    Alur:
    1. Ambil data order dari Supabase (orders, tenants, affiliates, cs_agents).
    2. Deteksi jenis transaksi: subscription / order, affiliate, AM closing.
    3. Tembak semua notifikasi relevan secara paralel via asyncio.gather.

    Bersifat fault-tolerant: jika satu notifikasi gagal, yang lain tetap berjalan.
    """
    logger.info(f"[WABA_NOTIF Orchestrator] Dispatch dimulai untuk order_id={order_id}")

    try:
        supabase = get_supabase()
        # --- Fetch order ---
        order_res = (
            supabase.table("orders")
            .select("*, tenants(name, wa_phone), affiliates(*), cs_agents(name, phone)")
            .eq("id", order_id)
            .maybe_single()
            .execute()
        )
        order: Dict[str, Any] = order_res.data or {}

        if not order:
            logger.warning(f"[WABA_NOTIF Orchestrator] Order {order_id} tidak ditemukan di Supabase.")
            return {"success": False, "error": "Order not found", "order_id": order_id}

        amount: int = int(order.get("total_amount") or order.get("amount") or 0)
        payer_name: str = order.get("buyer_name") or order.get("customer_name") or "Pelanggan"
        source_type: str = order.get("order_type") or "order"
        order_status: str = (order.get("status") or "").upper()
        tenant_data: Dict = order.get("tenants") or {}
        tenant_name: str = tenant_data.get("name") or order.get("tenant_id") or "—"
        tenant_wa: str = tenant_data.get("wa_phone") or ""
        affiliate_data: Dict = order.get("affiliates") or {}
        am_data: Dict = order.get("cs_agents") or {}

        # Kumpulkan coroutine yang akan dijalankan paralel
        tasks = []

        # --- Trigger 1: Subscription Paid ---
        if "subscription" in source_type.lower() and tenant_wa:
            package_name = order.get("package_name") or source_type
            active_until = order.get("subscription_end_date") or order.get("expires_at")
            tasks.append(
                notify_tenant_subscription_paid(
                    phone=tenant_wa,
                    tenant_name=tenant_name,
                    package_name=package_name,
                    amount=amount,
                    active_until=active_until,
                )
            )

        # --- Trigger 2: Super Admin Alert (SELALU) ---
        tasks.append(
            notify_super_admin_payment(
                order_id=order_id,
                payer_name=payer_name,
                amount=amount,
                source_type=source_type,
                tenant_name=tenant_name,
            )
        )

        # --- Trigger 3: Affiliate Referral ---
        if affiliate_data and affiliate_data.get("phone"):
            commission = _calc_commission(amount, affiliate_data.get("commission_rate", 10))
            am_phone = am_data.get("phone") if am_data else None
            am_name = am_data.get("name") if am_data else None
            tasks.append(
                notify_affiliate_earning(
                    affiliate_phone=affiliate_data["phone"],
                    affiliate_name=affiliate_data.get("name", "Affiliate"),
                    commission_amount=commission,
                    order_id=order_id,
                    am_phone=am_phone,
                    am_name=am_name,
                )
            )
        # --- Trigger 4: AM Closing (jika ada AM tanpa affiliate) ---
        elif am_data and am_data.get("phone") and not affiliate_data:
            closing_fee = _calc_closing_fee(amount, am_data.get("closing_rate", 5))
            tasks.append(
                notify_am_closing(
                    am_phone=am_data["phone"],
                    am_name=am_data.get("name", "Account Manager"),
                    amount=amount,
                    order_id=order_id,
                    closing_fee=closing_fee,
                )
            )

        # Jalankan semua task paralel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(
            f"[WABA_NOTIF Orchestrator ✓] order={order_id} | {len(tasks)} notifikasi dikirim."
        )
        return {
            "success": True,
            "order_id": order_id,
            "notifications_sent": len(tasks),
            "results": [r if not isinstance(r, Exception) else str(r) for r in results],
        }

    except Exception as exc:
        logger.error(f"[WABA_NOTIF Orchestrator ERROR] order={order_id} | {exc}", exc_info=True)
        return {"success": False, "order_id": order_id, "error": str(exc)}


# ---------------------------------------------------------------------------
# Helper Utilities
# ---------------------------------------------------------------------------

def _now_str() -> str:
    """Waktu sekarang dalam format WIB untuk body pesan."""
    from datetime import datetime, timezone, timedelta
    wib = timezone(timedelta(hours=7))
    return datetime.now(wib).strftime("%d %b %Y %H:%M WIB")


def _calc_commission(amount: int, rate_percent: float) -> int:
    """Kalkulasi komisi affiliate berdasarkan persentase."""
    return int(amount * rate_percent / 100)


def _calc_closing_fee(amount: int, rate_percent: float) -> int:
    """Kalkulasi closing fee AM berdasarkan persentase."""
    return int(amount * rate_percent / 100)
