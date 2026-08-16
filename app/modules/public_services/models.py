import enum
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EscalationStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


class PublicConversation(Base):
    __tablename__ = "public_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(50), nullable=False, default="webchat")
    user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    session_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    identified_service: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    messages: Mapped[List["PublicMessage"]] = relationship(
        "PublicMessage", back_populates="conversation", cascade="all, delete-orphan"
    )
    escalation: Mapped[Optional["PublicEscalation"]] = relationship(
        "PublicEscalation", back_populates="conversation", uselist=False, cascade="all, delete-orphan"
    )


class PublicMessage(Base):
    __tablename__ = "public_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("public_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["PublicConversation"] = relationship(
        "PublicConversation", back_populates="messages"
    )


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

    conversation: Mapped["PublicConversation"] = relationship(
        "PublicConversation", back_populates="escalation"
    )