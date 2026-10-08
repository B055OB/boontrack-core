"""app/api/v1/api.py
FastAPI Router Aggregator for API v1.
"""

from fastapi import APIRouter
from app.api.v1.endpoints.whatsapp_webhook import router as whatsapp_webhook_router
from app.api.v1.endpoints.tenant_onboarding import router as tenant_onboarding_router
from app.api.v1.endpoints.payment_webhook import router as payment_webhook_router

api_v1_router = APIRouter()
api_v1_router.include_router(whatsapp_webhook_router)
api_v1_router.include_router(tenant_onboarding_router)
api_v1_router.include_router(payment_webhook_router)

# Alias for general router inclusion
api_router = api_v1_router
