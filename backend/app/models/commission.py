from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Enum, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class CommissionStatus(str, enum.Enum):
    PENDING = "pending"
    CALCULATED = "calculated"
    PAID = "paid"
    CHARGEBACK = "chargeback"
    ADJUSTED = "adjusted"


class Commission(Base):
    """Commission records tied to sales and producers"""
    __tablename__ = "commissions"

    id = Column(Integer, primary_key=True, index=True)
    
    # Relationships
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, index=True)
    producer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Commission period (month/year for tier calculations)
    period = Column(String, nullable=False, index=True)  # Format: "2024-01"
    
    # Premium amounts
    written_premium = Column(Numeric(10, 2), nullable=False)  # Premium used for tier calculation
    recognized_premium = Column(Numeric(10, 2), nullable=False)  # Premium used for payment
    
    # Tier and rate at time of calculation
    tier_level = Column(Integer, nullable=False)
    commission_rate = Column(Numeric(5, 4), nullable=False)  # e.g., 0.1250 for 12.5%
    
    # Calculated amounts
    commission_amount = Column(Numeric(10, 2), nullable=False)
    net_commission = Column(Numeric(10, 2), nullable=False)  # After adjustments
    
    # Status and adjustments
    status = Column(Enum(CommissionStatus), default=CommissionStatus.PENDING, nullable=False)
    is_chargeback = Column(Boolean, default=False)
    adjustment_amount = Column(Numeric(10, 2), default=0)
    adjustment_reason = Column(Text, nullable=True)
    
    # Carry-forward for negative balances
    carry_forward_amount = Column(Numeric(10, 2), default=0)
    
    # Payment information
    paid_date = Column(DateTime(timezone=True), nullable=True)
    payment_reference = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    calculated_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    sale = relationship("Sale", back_populates="commissions")
    producer = relationship("User", back_populates="commissions")


class CommissionTier(Base):
    """Commission tier structure for tier-based calculations"""
    __tablename__ = "commission_tiers"

    id = Column(Integer, primary_key=True, index=True)
    
    tier_level = Column(Integer, nullable=False, unique=True)
    min_written_premium = Column(Numeric(10, 2), nullable=False)  # Minimum monthly written premium
    max_written_premium = Column(Numeric(10, 2), nullable=True)  # Maximum (null = no limit)
    commission_rate = Column(Numeric(5, 4), nullable=False)  # Commission percentage as decimal
    
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
