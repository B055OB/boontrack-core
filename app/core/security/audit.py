import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.security.encryption import decrypt_pii

logger = logging.getLogger("SECURITY_AUDIT")


async def log_data_access(
    session: AsyncSession,
    tenant_id: str,
    actor_id: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """Merekam akses data sensitif ke tabel audit_logs (append-only)."""
    # Zero PII Logging: Jangan pernah print/log isi identitas
    logger.info(f"[AUDIT] Tenant: {tenant_id} | Actor: {actor_id} | Action: {action} | Resource: {resource_type}:{resource_id}")

    query = text("""
        INSERT INTO public.audit_logs (tenant_id, actor_id, action, resource_type, resource_id, ip_address, metadata)
        VALUES (:t_id, :actor, :act, :res_type, :res_id, :ip, :meta::jsonb)
    """)
    import json
    await session.execute(query, {
        "t_id": tenant_id,
        "actor": actor_id,
        "act": action,
        "res_type": resource_type,
        "res_id": resource_id or "",
        "ip": ip_address or "127.0.0.1",
        "meta": json.dumps(metadata or {})
    })


async def audited_decrypt_nik(
    session: AsyncSession,
    tenant_id: str,
    actor_id: str,
    citizen_id: str,
    encrypted_nik: str,
    ip_address: Optional[str] = None
) -> str:
    """Dekripsi NIK dengan verifikasi audit trail instan."""
    await log_data_access(
        session=session,
        tenant_id=tenant_id,
        actor_id=actor_id,
        action="DECRYPT",
        resource_type="citizen_data",
        resource_id=citizen_id,
        ip_address=ip_address
    )
    return decrypt_pii(tenant_id, encrypted_nik)
