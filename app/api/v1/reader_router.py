from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from app.services.reader_parser import parse_reader_notification

router = APIRouter(prefix="/api/v1/reader", tags=["Reader"])

class ReaderPayload(BaseModel):
    tenant_id: str
    app_source: str
    raw_text: str
    notification_id: str

@router.post("/notification", status_code=status.HTTP_200_OK)
async def receive_notification(payload: ReaderPayload):
    extracted = parse_reader_notification(payload.app_source, payload.raw_text)

    if not extracted["is_payment_in"] or extracted["amount"] <= 0:
        return {
            "status": "IGNORED",
            "message": "Bukan notifikasi transaksi uang masuk atau nominal nol."
        }

    # Transaksi uang masuk valid
    return {
        "status": "PROCESSED",
        "tenant_id": payload.tenant_id,
        "amount": extracted["amount"],
        "app_source": payload.app_source,
        "notification_id": payload.notification_id,
        "action": "MATCH_AND_DISPATCH_CAPI"
    }