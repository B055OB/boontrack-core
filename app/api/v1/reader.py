"""app/api/v1/reader.py
Webhook Controller untuk Android Reader Notifications - LOCAL_SERVICE_V1.

Endpoint: POST /api/v1/reader/notification
Auth    : Header X-Reader-Secret (dibandingkan dengan env READER_WEBHOOK_SECRET)

Alur:
    1. Validasi header X-Reader-Secret
    2. Parse payload JSON (title, body, package_name, tenant_id, ref, dll.)
    3. Simpan audit trail ke reader_notifications
    4. Jalankan HybridReaderProcessor
    5. Return HTTP 200 dengan JSON respons status
"""

import logging
import os
from aiohttp import web

logger = logging.getLogger("READER_WEBHOOK")

READER_SECRET_ENV = "READER_WEBHOOK_SECRET"
DEFAULT_SECRET_FALLBACK = "boontrack-reader-secret-change-me"


def get_reader_secret() -> str:
    """Ambil secret dari environment variable."""
    return os.getenv(READER_SECRET_ENV, DEFAULT_SECRET_FALLBACK)


async def handle_reader_notification(request: web.Request) -> web.Response:
    """POST /api/v1/reader/notification

    Menerima notifikasi dari Android Reader app (GoPay, DANA, BCA),
    memprosesnya via HybridReaderProcessor, dan mengembalikan status.

    Headers Required:
        X-Reader-Secret: <secret_token>

    Body JSON:
        {
            "title": "Pembayaran Masuk",
            "body": "Rp25.300 diterima GoPay dari Budi Santoso",
            "package_name": "com.gojek.gopay.merchant",
            "tenant_id": "uuid-...",
            "ref": "TRX202409150001"  (opsional)
        }

    Response 200:
        {
            "received": true,
            "status": "MATCHED" | "UNMATCHED" | "DUPLICATE" | "PARSE_FAILED",
            "transaction_ref": "GOPAY_MERCHANT_TRX...",
            "parsed_amount": 25300,
            "notification_id": "uuid-...",
            "matched_booking_id": "INV-001" | null,
            "capi_dispatched": true | false
        }

    Response 401: Missing atau invalid X-Reader-Secret
    Response 400: Invalid JSON atau missing tenant_id
    """
    # --- 1. Header Authentication ---
    provided_secret = request.headers.get("X-Reader-Secret", "")
    expected_secret = get_reader_secret()

    if not provided_secret or provided_secret != expected_secret:
        logger.warning(
            f"[READER] Unauthorized request from {request.remote}: "
            f"secret={'<missing>' if not provided_secret else '<invalid>'}"
        )
        return web.json_response(
            {"received": False, "error": "unauthorized", "detail": "Invalid X-Reader-Secret"},
            status=401,
        )

    # --- 2. Parse JSON payload ---
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"[READER] Invalid JSON payload: {e}")
        return web.json_response(
            {"received": False, "error": "invalid_json"},
            status=400,
        )

    if not isinstance(payload, dict):
        return web.json_response(
            {"received": False, "error": "payload_must_be_object"},
            status=400,
        )

    tenant_id = str(payload.get("tenant_id") or "").strip()
    if not tenant_id:
        return web.json_response(
            {"received": False, "error": "missing_tenant_id"},
            status=400,
        )

    # --- 3. Parse notification content ---
    from app.services.hybrid_reader_service import parse_gopay_notification

    parsed = parse_gopay_notification(payload)
    app_source = parsed["app_source"]
    raw_text = parsed["raw_text"]
    explicit_ref = str(payload.get("ref") or payload.get("transaction_ref") or "")

    logger.info(
        f"[READER] Incoming: tenant={tenant_id} "
        f"source={app_source} "
        f"amount={parsed['parsed_amount']} "
        f"ref={parsed['transaction_ref']}"
    )

    # --- 4. Process via HybridReaderProcessor ---
    result = {
        "received": True,
        "status": "PROCESSING_ERROR",
        "transaction_ref": parsed["transaction_ref"],
        "parsed_amount": parsed["parsed_amount"],
        "notification_id": None,
        "matched_booking_id": None,
        "capi_dispatched": False,
    }

    try:
        # Database session - gunakan dependency injection dari app state
        db_session = request.app.get("db_session")

        if db_session is not None:
            from app.services.hybrid_reader_service import HybridReaderProcessor
            processor = HybridReaderProcessor(db=db_session)
            processing_result = await processor.process_notification(
                tenant_id=tenant_id,
                app_source=app_source,
                raw_text=raw_text,
                explicit_ref=explicit_ref,
                order_data=payload,
            )
            result.update(processing_result)
        else:
            # Mode tanpa DB: proses parser-only (audit trail tidak disimpan)
            logger.warning(
                "[READER] No db_session in app state - "
                "processing in parser-only mode (no audit trail)"
            )
            result["status"] = "PARSED_NO_DB"
            result["parsed_amount"] = parsed["parsed_amount"]

    except Exception as exc:
        import traceback
        logger.error(
            f"[READER] Processing exception for tenant={tenant_id}: "
            f"{exc}\n{traceback.format_exc()}"
        )
        result["status"] = "PROCESSING_ERROR"
        result["error_detail"] = str(exc)[:256]

    result["received"] = True
    return web.json_response(result, status=200)


def register_reader_routes(app: web.Application) -> None:
    """Daftarkan endpoint Reader ke aplikasi aiohttp."""
    app.router.add_post("/api/v1/reader/notification", handle_reader_notification)
    logger.info("[BOOT] Reader webhook route registered at POST /api/v1/reader/notification")
