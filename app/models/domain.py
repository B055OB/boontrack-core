import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum as SQLEnum, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import UUID

# Didefinisikan langsung di sini, JANGAN di-import dari app.models.domain!
Base = declarative_base()


class GoalCode(str, enum.Enum):
    GET_JOB = "GET_JOB"
    WRITE_THESIS = "WRITE_THESIS"
    START_BUSINESS = "START_BUSINESS"


class IntentCode(str, enum.Enum):
    CREATE_CV = "CREATE_CV"
    WRITE_COVER_LETTER = "WRITE_COVER_LETTER"
    PREPARE_INTERVIEW = "PREPARE_INTERVIEW"
    NEGOTIATE_SALARY = "NEGOTIATE_SALARY"
    BUILD_LINKEDIN = "BUILD_LINKEDIN"
    FIND_JOB = "FIND_JOB"


class User(Base):
    __tablename__ = "users"

    uuid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name = Column(String(100), nullable=True)
    preferred_language = Column(String(10), default="id")
    country = Column(String(10), default="ID")
    timezone = Column(String(50), default="Asia/Jakarta")
    created_at = Column(DateTime, default=datetime.utcnow)


class Goal(Base):
    __tablename__ = "goals"

    uuid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(SQLEnum(GoalCode), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    intents = relationship("Intent", back_populates="goal", cascade="all, delete-orphan")


class Intent(Base):
    __tablename__ = "intents"

    uuid = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_uuid = Column(UUID(as_uuid=True), ForeignKey("goals.uuid", ondelete="RESTRICT"), nullable=False)
    code = Column(SQLEnum(IntentCode), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    goal = relationship("Goal", back_populates="intents")
