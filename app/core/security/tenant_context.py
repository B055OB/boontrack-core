from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


@asynccontextmanager
async def tenant_scope(session: AsyncSession, tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """
    Menetapkan tenant session menggunakan SET LOCAL dalam transaksi.
    Otomatis reset saat scope block selesai / commit / rollback.
    """
    if not tenant_id:
        raise ValueError("tenant_id wajib disertakan dalam tenant_scope.")

    async with session.begin():
        # Wajib SET LOCAL agar berlaku hanya dalam blok transaksi ini
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :t_id"),
            {"t_id": tenant_id}
        )
        try:
            yield session
        finally:
            pass
