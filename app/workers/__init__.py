"""app/workers/__init__.py
Background Stream and Task Workers Package.
"""

def __getattr__(name: str):
    if name in ("WhatsAppInboundWorker", "process_inbound_stream_event"):
        from app.workers.whatsapp_inbound_worker import (
            WhatsAppInboundWorker,
            process_inbound_stream_event,
        )
        return locals()[name]
    raise AttributeError(f"module {__name__} has no attribute {name}")

__all__ = ["WhatsAppInboundWorker", "process_inbound_stream_event"]

