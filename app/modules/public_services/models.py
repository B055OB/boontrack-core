import enum
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ConversationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class EscalationStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class PublicService(Base):
    __tablename__ = "public_services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requirements: Mapped[dict] = mapped_column(JSONB, default=list, nullable=False)
    process_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_time: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversations: Mapped[List["PublicConversation"]] = relationship(
        back_populates="service"
    )


class PublicConversation(Base):
    __tablename__ = "public_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    user_identifier: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    service_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("public_services.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="public_conversation_status"),
        default=ConversationStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    service: Mapped[Optional["PublicService"]] = relationship(back_populates="conversations")
    messages: Mapped[List["PublicMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    escalation: Mapped[Optional["PublicEscalation"]] = relationship(
        back_populates="conversation", uselist=False
    )


class PublicMessage(Base):
    __tablename__ = "public_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("public_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["PublicConversation"] = relationship(back_populates="messages")


class PublicEscalation(Base):
    __tablename__ = "public_escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("public_conversations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EscalationStatus] = mapped_column(
        Enum(EscalationStatus, name="public_escalation_status"),
        default=EscalationStatus.PENDING,
        nullable=False,
    )
    assigned_to: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["PublicConversation"] = relationship(back_populates="escalation")