# app/models/session.py

from sqlalchemy import Column, String, DateTime, JSON, Enum as SQLEnum
from sqlalchemy.sql import func
import enum
import uuid
from app.core.database import Base  # Sesuaikan impor Base kamu

class ConversationState(str, enum.Enum):
    START = "START"
    # CV Flow States
    CREATE_CV_NAME = "CREATE_CV_NAME"
    CREATE_CV_CONTACT = "CREATE_CV_CONTACT"
    CREATE_CV_TARGET_ROLE = "CREATE_CV_TARGET_ROLE"
    CREATE_CV_EDUCATION = "CREATE_CV_EDUCATION"
    CREATE_CV_EXPERIENCE = "CREATE_CV_EXPERIENCE"
    CREATE_CV_SKILLS = "CREATE_CV_SKILLS"
    CREATE_CV_REVIEW = "CREATE_CV_REVIEW"
    CREATE_CV_GENERATE = "CREATE_CV_GENERATE"
    # Mode Lain
    INTERVIEW_MODE = "INTERVIEW_MODE"
    VENT_MODE = "VENT_MODE"

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, index=True, nullable=False)
    channel = Column(String, default="telegram")
    state = Column(String, default=ConversationState.START.value)
    goal = Column(String, nullable=True)
    intent = Column(String, nullable=True)
    
    # Menyimpan progress draft CV (Micro-commitments & Context)
    context_json = Column(JSON, nullable=False, default=dict)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
