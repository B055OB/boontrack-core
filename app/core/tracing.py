"""app/core/tracing.py
Distributed Tracing, Contextvars Request Correlation & Structured JSON Logging.

CTO Mandate & Architecture:
1. Context Identities:
   - trace_id: UUID per request execution (UUID4 string).
   - correlation_id: Business-cycle identifier (order_id or X-Correlation-ID header).
   - tenant_id: Tenant scope identifier (mandatory in every log record).
2. Standard Structured JSON Log Schema:
   {
     "timestamp": "ISO-8601",
     "trace_id": "...",
     "correlation_id": "...",
     "tenant_id": "...",
     "service": "...",
     "event_type": "...",
     "entity_type": "order|payment|message",
     "entity_id": "...",
     "provider": "meta|tripay|midtrans|xendit",
     "provider_event_id": "...",
     "status": "SUCCESS|FAILED|PENDING",
     "duration_ms": 120,
     "error_code": null
   }
3. Non-blocking, thread-safe and async-safe via contextvars.
"""

import os
import json
import uuid
import time
import logging
from datetime import datetime, timezone
from contextvars import ContextVar
from typing import Optional, Dict, Any, Generator
from contextlib import contextmanager

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# -----------------------------------------------------------------------------
# Context Variables (Execution & Business Correlation Scopes)
# -----------------------------------------------------------------------------

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="default")

OBSERVABILITY_LOGGER_NAME = "BOONTRACK_OBSERVABILITY"
structured_logger = logging.getLogger(OBSERVABILITY_LOGGER_NAME)


def generate_trace_id() -> str:
    """Menghasilkan trace_id acak berbasis UUID4."""
    return str(uuid.uuid4())


def get_trace_context() -> Dict[str, str]:
    """Mengambil konteks tracing aktif (trace_id, correlation_id, tenant_id)."""
    t_id = trace_id_var.get() or ""
    c_id = correlation_id_var.get() or ""
    tenant = tenant_id_var.get() or "default"
    return {
        "trace_id": t_id,
        "correlation_id": c_id,
        "tenant_id": tenant,
    }


def set_trace_context(
    trace_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Dict[str, str]:
    """Mengatur konteks tracing aktif pada contextvars saat ini."""
    if trace_id:
        trace_id_var.set(str(trace_id).strip())
    elif not trace_id_var.get():
        trace_id_var.set(generate_trace_id())

    if correlation_id is not None:
        correlation_id_var.set(str(correlation_id).strip())

    if tenant_id is not None:
        tenant_id_var.set(str(tenant_id).strip() or "default")

    return get_trace_context()


def clear_trace_context() -> None:
    """Membersihkan contextvars tracing kembali ke kondisi default."""
    trace_id_var.set("")
    correlation_id_var.set("")
    tenant_id_var.set("default")


@contextmanager
def tracing_context(
    trace_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Generator[Dict[str, str], None, None]:
    """Context manager untuk mengisolasi trace_id, correlation_id, dan tenant_id."""
    token_trace = trace_id_var.set(trace_id or generate_trace_id())
    token_corr = correlation_id_var.set(correlation_id or "")
    token_tenant = tenant_id_var.set(tenant_id or "default")
    try:
        yield get_trace_context()
    finally:
        trace_id_var.reset(token_trace)
        correlation_id_var.reset(token_corr)
        tenant_id_var.reset(token_tenant)


# -----------------------------------------------------------------------------
# Structured JSON Formatter
# -----------------------------------------------------------------------------

class StructuredJsonFormatter(logging.Formatter):
    """
    Formatter log yang menghasilkan JSON terstruktur sesuai spesifikasi standar CTO:
    {
      "timestamp": "ISO-8601",
      "trace_id": "...",
      "correlation_id": "...",
      "tenant_id": "...",
      "service": "...",
      "event_type": "...",
      "entity_type": "order|payment|message",
      "entity_id": "...",
      "provider": "meta|tripay|midtrans|xendit",
      "provider_event_id": "...",
      "status": "SUCCESS|FAILED|PENDING",
      "duration_ms": 120,
      "error_code": null
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_trace_context()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Ekstraksi field dari attribute record jika disuplai via extra={}
        trace_id = getattr(record, "trace_id", None) or ctx["trace_id"] or generate_trace_id()
        correlation_id = getattr(record, "correlation_id", None) or ctx["correlation_id"] or ""
        tenant_id = getattr(record, "tenant_id", None) or ctx["tenant_id"] or "default"

        service = getattr(record, "service", None) or record.name
        event_type = getattr(record, "event_type", None) or "LOG_ENTRY"
        entity_type = getattr(record, "entity_type", None) or "order"
        entity_id = getattr(record, "entity_id", None) or correlation_id or ""
        provider = getattr(record, "provider", None)
        provider_event_id = getattr(record, "provider_event_id", None)
        status = getattr(record, "status", None) or ("FAILED" if record.levelno >= logging.ERROR else "SUCCESS")
        duration_ms = getattr(record, "duration_ms", None)
        error_code = getattr(record, "error_code", None)

        log_data = {
            "timestamp": now_iso,
            "trace_id": trace_id,
            "correlation_id": correlation_id,
            "tenant_id": tenant_id,
            "service": service,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "provider": provider,
            "provider_event_id": provider_event_id,
            "status": status,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "message": record.getMessage(),
        }

        # Tambahkan metadata tambahan jika ada
        extra_meta = getattr(record, "extra_meta", None)
        if extra_meta and isinstance(extra_meta, dict):
            log_data["metadata"] = extra_meta

        return json.dumps(log_data, default=str)


def log_structured_event(
    service: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    status: str = "SUCCESS",
    provider: Optional[str] = None,
    provider_event_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    error_code: Optional[str] = None,
    tenant_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    message: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Mencatat event terstruktur standar ke logger observabilitas dan mengembalikan dictionary event.
    """
    ctx = get_trace_context()
    resolved_trace_id = trace_id or ctx["trace_id"] or generate_trace_id()
    resolved_corr_id = correlation_id if correlation_id is not None else ctx["correlation_id"]
    resolved_tenant = tenant_id or ctx["tenant_id"] or "default"
    now_iso = datetime.now(timezone.utc).isoformat()

    event_payload = {
        "timestamp": now_iso,
        "trace_id": resolved_trace_id,
        "correlation_id": resolved_corr_id,
        "tenant_id": resolved_tenant,
        "service": service,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "provider": provider,
        "provider_event_id": provider_event_id,
        "status": status,
        "duration_ms": duration_ms,
        "error_code": error_code,
    }

    log_level = logging.ERROR if status == "FAILED" else logging.INFO
    log_msg = message or f"[{service}] {event_type} on {entity_type} {entity_id}: {status}"

    extra = {
        "trace_id": resolved_trace_id,
        "correlation_id": resolved_corr_id,
        "tenant_id": resolved_tenant,
        "service": service,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "provider": provider,
        "provider_event_id": provider_event_id,
        "status": status,
        "duration_ms": duration_ms,
        "error_code": error_code,
        "extra_meta": extra_metadata or {},
    }

    structured_logger.log(log_level, log_msg, extra=extra)
    return event_payload


# -----------------------------------------------------------------------------
# FastAPI HTTP Middleware
# -----------------------------------------------------------------------------

class TracingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI Middleware untuk otomatis mengekstrak & mempropagasi:
    - X-Trace-ID / trace_id
    - X-Correlation-ID / correlation_id
    - X-Tenant-ID / tenant_id
    Menyuntikkan trace_id dan correlation_id ke header respon HTTP.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()

        # Ekstrak trace_id dari header atau generate baru
        inbound_trace_id = (
            request.headers.get("x-trace-id")
            or request.headers.get("x-request-id")
            or generate_trace_id()
        )

        # Ekstrak correlation_id dari header
        inbound_corr_id = (
            request.headers.get("x-correlation-id")
            or request.headers.get("x-order-id")
            or ""
        )

        # Ekstrak tenant_id dari header atau host subdomain
        inbound_tenant = (
            request.headers.get("x-tenant-id")
            or request.headers.get("x-tenant-slug")
            or "default"
        )

        # Simpan ke request.state
        request.state.trace_id = inbound_trace_id
        request.state.correlation_id = inbound_corr_id
        request.state.tenant_id = inbound_tenant

        with tracing_context(
            trace_id=inbound_trace_id,
            correlation_id=inbound_corr_id,
            tenant_id=inbound_tenant,
        ):
            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                log_structured_event(
                    service="http_inbound",
                    event_type="REQUEST_FAILED",
                    entity_type="order" if inbound_corr_id else "message",
                    entity_id=inbound_corr_id or inbound_trace_id,
                    status="FAILED",
                    duration_ms=duration_ms,
                    error_code="UNHANDLED_EXCEPTION",
                    tenant_id=inbound_tenant,
                    correlation_id=inbound_corr_id,
                    trace_id=inbound_trace_id,
                    message=f"Request to {request.url.path} failed with exception: {exc}",
                )
                raise exc

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            response.headers["x-trace-id"] = inbound_trace_id
            if inbound_corr_id:
                response.headers["x-correlation-id"] = inbound_corr_id

            return response
