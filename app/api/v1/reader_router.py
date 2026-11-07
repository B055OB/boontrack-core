import logging
from typing import Optional
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.database import get_db_connection
from app.services.whatsapp_service import get_supabase
from app.services.reader_parser import parse_reader_notification
from app.services.order_fulfillment_service import handle_order_paid_fulfillment
from app.services.meta_capi_service import send_meta_capi_purchase

logger = logging.getLogger("READER_ROUTER")

router = APIRouter(prefix="/api/v1/reader", tags=["Reader"])


class ReaderPayload(BaseModel):
    tenant_id: Optional[str] = None
    app_source: str = ""
    raw_text: str = ""
    notification_id: str = ""


@router.post("/notification", status_code=status.HTTP_403_FORBIDDEN)
async def receive_notification(request: Request) -> JSONResponse:
    """Phase 1 Stage 2 (P0-C):
    Direct Tenant Rail (Android Notification Reader mutation auto-settlement)
    is EXPERIMENTAL / PENDING_REVIEW and strictly disabled.

    Always fails closed with HTTP 403 DIRECT_TENANT_RAIL_DISABLED without invoking
    reader parsing, payment matching, order status mutation, fulfillment, or CAPI.
    """
    logger.warning(
        "[PaymentPerimeterLockdown] Blocked FastAPI Direct Tenant Rail reader notification webhook on /api/v1/reader/notification."
    )
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "status": "rejected",
            "error_code": "DIRECT_TENANT_RAIL_DISABLED",
            "detail": (
                "DIRECT_TENANT_RAIL_DISABLED: Direct Tenant Rail (Android Reader / bank mutation auto-settlement) "
                "is EXPERIMENTAL / PENDING_REVIEW and disabled."
            ),
        },
    )
