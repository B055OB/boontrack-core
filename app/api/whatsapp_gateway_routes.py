"""
app/api/whatsapp_gateway_routes.py
Re-export bridge to app.routes.whatsapp_gateway_routes for backward compatibility.
"""

from app.routes.whatsapp_gateway_routes import (
    router,
    InboundPayload,
    connect_growth_session,
    process_inbound_message,
    handle_evolution_webhook,
)

__all__ = [
    "router",
    "InboundPayload",
    "connect_growth_session",
    "process_inbound_message",
    "handle_evolution_webhook",
]
