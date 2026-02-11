from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Enum, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class SaleStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CANCELLED = "cancelled"
    LAPSED = "lapsed"


class LeadSource(str, enum.Enum):
    REFERRAL = "referral"
    CUSTOMER_REFERRAL = "customer_referral"
    WEBSITE = "website"
    COLD_CALL = "cold_call"
    CALL_IN = "call_in"
    SOCIAL_MEDIA = "social_media"
    EMAIL_CAMPAIGN = "email_campaign"
    WALK_IN = "walk_in"
    QUOTE_WIZARD = "quote_wizard"
    INSURANCE_AI_CALL = "insurance_ai_call"
    REWRITE = "rewrite"
    OTHER = "other"


class PolicyType(str, enum.Enum):
    AUTO = "auto"
    HOME = "home"
    RENTERS = "renters"
    CONDO = "condo"
    LANDLORD = "landlord"
    UMBRELLA = "umbrella"
    MOTORCYCLE = "motorcycle"
    BOAT = "boat"
    RV = "rv"
    LIFE = "life"
    HEALTH = "health"
    BUNDLED = "bundled"
    COMMERCIAL = "commercial"
    OTHER = "other"


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    
    # Policy information
    policy_number = Column(String, unique=True, index=True, nullable=False)
    policy_type = Column(String, nullable=True, index=True)
    carrier = Column(String, nullable=True, index=True)
    state = Column(String(2), nullable=True, index=True)
    written_premium = Column(Numeric(10, 2), nullable=False)
    recognized_premium = Column(Numeric(10, 2), nullable=True)
    
    # Producer relationship
    producer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Lead and client info
    lead_source = Column(String, nullable=True)
    item_count = Column(Integer, default=1)
    
    # Client information
    client_name = Column(String, nullable=False)
    client_email = Column(String, nullable=True)
    client_phone = Column(String, nullable=True)
    
    # Status
    status = Column(String, default="active", nullable=False)
    
    # Commission tracking
    commission_status = Column(String, default="pending", nullable=False)  # pending, paid
    commission_paid_date = Column(DateTime(timezone=True), nullable=True)
    commission_paid_period = Column(String, nullable=True)  # "2026-01" — which payroll period paid this
    
    # Cancellation / termination tracking
    cancelled_date = Column(DateTime(timezone=True), nullable=True)
    days_to_cancel = Column(Integer, nullable=True)  # Days from effective_date to cancellation
    
    # Application document
    application_pdf_path = Column(String, nullable=True)
    signature_request_id = Column(String, nullable=True)
    signature_status = Column(String, default="not_sent")
    
    # Dates
    sale_date = Column(DateTime(timezone=True), server_default=func.now())
    effective_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Notes
    notes = Column(Text, nullable=True)
    
    # Welcome email tracking
    welcome_email_sent = Column(Boolean, default=False)
    welcome_email_sent_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    producer = relationship("User", back_populates="sales")
    commissions = relationship("Commission", back_populates="sale", cascade="all, delete-orphan")
