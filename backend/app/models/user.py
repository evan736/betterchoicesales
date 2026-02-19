from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    PRODUCER = "producer"
    MANAGER = "manager"
    RETENTION_SPECIALIST = "retention_specialist"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    
    role = Column(String, default="producer", nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    
    # Producer-specific fields
    producer_code = Column(String, unique=True, nullable=True, index=True)
    commission_tier = Column(Integer, default=1)  # Default tier
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    sales = relationship("Sale", back_populates="producer", cascade="all, delete-orphan")
    commissions = relationship("Commission", back_populates="producer", cascade="all, delete-orphan")
