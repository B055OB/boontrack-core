"""app/api/v1/endpoints/__init__.py
API v1 Endpoints Package.
"""
from app.api.v1.endpoints.whatsapp_webhook import router as whatsapp_webhook_router

__all__ = ["whatsapp_webhook_router"]
