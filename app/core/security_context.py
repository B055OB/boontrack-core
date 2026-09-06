"""app/core/security_context.py
Security Context Integrity Checks & Composite Redis Session Key Standard.

Enforces:
1. FAIL-CLOSED Tenant Integrity:
   Any entity whose tenant_id does not match the active RequestContext.tenant_id
   raises TenantContextViolation (HTTP 403 Forbidden) and logs SECURITY_TENANT_CONTEXT_MISMATCH.
2. Standard Composite Redis Key:
   bt:{env}:tenant:{tenant_id}:channel:{channel}:session:{session_id}
   Prevents cross-tenant and cross-channel memory leakage.
"""

import logging
from typing import List, Any, Optional
from fastapi import HTTPException, status
from app.schemas.context import RequestContext

logger = logging.getLogger("SECURITY_CONTEXT")


class TenantContextViolation(HTTPException):
    """Exception raised when an entity tenant_id mismatches the resolved RequestContext."""

    def __init__(self, detail: str = "Access Denied: Cross-tenant context integrity violation detected"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


def assert_tenant_integrity(request_context: RequestContext, entity_tenant_ids: List[str]) -> None:
    """
    Validasi integritas tenant (FAIL-CLOSED rule).
    Jika ada satu saja entity (produk, order, riwayat chat, dsb) yang tenant_id-nya
    berbeda dengan request_context.tenant_id, segera lempar TenantContextViolation (HTTP 403)
    dan catat log SECURITY_TENANT_CONTEXT_MISMATCH.
    """
    target_tenant_id = str(request_context.tenant_id).strip()
    target_tenant_slug = str(request_context.tenant_slug).strip().lower()

    for idx, e_tid in enumerate(entity_tenant_ids):
        if not e_tid:
            continue
        clean_e_tid = str(e_tid).strip()
        # Izinkan jika cocok dengan tenant_id atau tenant_slug
        if clean_e_tid != target_tenant_id and clean_e_tid.lower() != target_tenant_slug:
            error_msg = (
                f"SECURITY_TENANT_CONTEXT_MISMATCH: Request tenant [{target_tenant_id}/{target_tenant_slug}] "
                f"attempted to access entity[{idx}] belonging to tenant [{clean_e_tid}]"
            )
            logger.error(error_msg)
            raise TenantContextViolation(detail="Cross-tenant access violation: SECURITY_TENANT_CONTEXT_MISMATCH")


def format_composite_session_key(
    request_context: Optional[RequestContext] = None,
    env: Optional[str] = None,
    tenant_id: Optional[str] = None,
    channel: Optional[str] = None,
    session_id: Optional[str] = None,
    sub_key: Optional[str] = None,
) -> str:
    """
    Format standar komposit Redis session key:
    bt:{env}:tenant:{tenant_id}:channel:{channel}:session:{session_id}
    (opsional :sub_key jika dibutuhkan untuk namespacing riwayat / context)
    """
    if request_context:
        c_env = request_context.environment.strip().lower()
        c_tid = str(request_context.tenant_id).strip()
        c_chan = request_context.channel.strip().lower()
        c_sess = str(request_context.session_id).strip()
    else:
        c_env = (env or "production").strip().lower()
        c_tid = str(tenant_id or "default").strip()
        c_chan = (channel or "webchat").strip().lower()
        c_sess = str(session_id or "global").strip()

    base = f"bt:{c_env}:tenant:{c_tid}:channel:{c_chan}:session:{c_sess}"
    if sub_key:
        return f"{base}:{sub_key.strip()}"
    return base
