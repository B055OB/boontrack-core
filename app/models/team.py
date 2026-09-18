"""
app/models/team.py
------------------
SQLAlchemy model untuk Multi-User / Team Access Tenant (Operasional Toko).
Merepresentasikan tabel `cs_agents` di database.
"""

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TeamMemberRole(str, enum.Enum):
    """Peran operasional anggota tim toko."""
    OWNER = "owner"
    SUPERVISOR = "supervisor"
    AGENT = "agent"
    ADMIN = "admin"  # Backward compatibility


class AgentPresence(str, enum.Enum):
    """Status kehadiran agen CS untuk routing."""
    ACTIVE = "active"
    BREAK = "break"
    OFFLINE = "offline"


class TenantTeamMember(Base):
    """
    Model SQLAlchemy resmi untuk Anggota Tim Tenant / CS Agent.
    Tabel: cs_agents
    
    Mendukung role:
    - owner: Pemilik toko dengan hak akses penuh operasional & pengaturan tim.
    - supervisor: Pengawas operasional yang dapat mengelola antrean chat & memantau CS.
    - agent: Staf CS lini depan yang menangani interaksi chat langsung.
    """
    __tablename__ = "cs_agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default=TeamMemberRole.AGENT.value, nullable=False)
    presence: Mapped[str] = mapped_column(String(20), default=AgentPresence.OFFLINE.value, nullable=False)
    max_active_chats: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# Alias untuk backward compatibility & semantic usage
CSAgent = TenantTeamMember
