import uuid
import enum
from sqlalchemy import Column, String, Integer, Float, Boolean, ForeignKey, Enum, Text, DateTime
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

# Independent Base untuk memutus circular import
Base = declarative_base()


# --- ENUMS ---

class ARSStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    REVIEW = "REVIEW"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"


class AssetType(str, enum.Enum):
    TEMPLATE = "TEMPLATE"
    CHECKLIST = "CHECKLIST"
    CHEATSHEET = "CHEATSHEET"
    GUIDE = "GUIDE"
    SPREADSHEET = "SPREADSHEET"
    SCRIPT = "SCRIPT"
    FRAMEWORK = "FRAMEWORK"


class DeliveryType(str, enum.Enum):
    GDRIVE = "GDRIVE"
    DIRECT_LINK = "DIRECT_LINK"
    FILE_ID = "FILE_ID"


# --- LAYER 1: DIGITAL ASSET ---

class DigitalAsset(Base):
    __tablename__ = "digital_assets"

    uuid = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = Column(String(255), unique=True, nullable=False, index=True)  # CTO Decision #038
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Domain Mapping
    goal_code = Column(String(50), nullable=False, index=True)
    intent_code = Column(String(50), nullable=False, index=True)
    
    # Metadata
    asset_type = Column(Enum(AssetType), nullable=False, index=True)
    language = Column(String(10), nullable=False, default="id", index=True)
    country = Column(String(10), nullable=False, default="ID", index=True)
    
    # Time & Outcome Metrics
    estimated_time_minutes = Column(Integer, nullable=False, default=15)
    expected_outcome = Column(Text, nullable=False)
    
    # Status & Scores
    status = Column(Enum(ARSStatus), nullable=False, default=ARSStatus.DRAFT, index=True)
    quality_score = Column(Float, default=5.0)
    popularity_score = Column(Float, default=0.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    deliveries = relationship("Delivery", back_populates="asset", cascade="all, delete-orphan")
    knowledge_mappings = relationship("KnowledgeMapping", back_populates="asset", cascade="all, delete-orphan")


# --- LAYER 2: DELIVERY ---

class Delivery(Base):
    __tablename__ = "deliveries"

    uuid = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_uuid = Column(String(36), ForeignKey("digital_assets.uuid"), nullable=False)
    
    delivery_type = Column(Enum(DeliveryType), nullable=False, default=DeliveryType.GDRIVE)
    url_or_file_id = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("DigitalAsset", back_populates="deliveries")


# --- LAYER 3: KNOWLEDGE MAPPING ---

class KnowledgeMapping(Base):
    __tablename__ = "knowledge_mappings"

    uuid = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_uuid = Column(String(36), ForeignKey("digital_assets.uuid"), nullable=False)
    
    keyword = Column(String(100), nullable=False, index=True)
    synonym = Column(String(100), nullable=True)
    search_weight = Column(Float, default=1.0)
    language = Column(String(10), default="id", index=True)
    status = Column(String(20), default="active", index=True) # active / inactive
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("DigitalAsset", back_populates="knowledge_mappings")
