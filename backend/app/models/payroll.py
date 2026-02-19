"""Payroll models for finalized monthly commission records."""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class PayrollRecord(Base):
    """Finalized monthly payroll — snapshot of agent pay for a period."""
    __tablename__ = "payroll_records"

    id = Column(Integer, primary_key=True, index=True)

    # Period
    period = Column(String, nullable=False, index=True)  # "2026-01"
    period_display = Column(String, nullable=True)  # "January 2026"

    # Status
    status = Column(String, default="draft", nullable=False)  # draft, submitted, paid
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    is_locked = Column(Boolean, default=False)

    # Totals snapshot
    total_agents = Column(Integer, default=0)
    total_premium = Column(Numeric(12, 2), default=0)
    total_agent_pay = Column(Numeric(12, 2), default=0)
    total_chargebacks = Column(Numeric(12, 2), default=0)
    total_carriers = Column(Integer, default=0)

    # Full snapshot data (JSON blob of the monthly pay result)
    snapshot_data = Column(JSON, nullable=True)

    # Notes
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    submitted_by = relationship("User", foreign_keys=[submitted_by_id])
    agent_payroll_lines = relationship("PayrollAgentLine", back_populates="payroll_record", cascade="all, delete-orphan")


class PayrollAgentLine(Base):
    """Per-agent line item within a finalized payroll."""
    __tablename__ = "payroll_agent_lines"

    id = Column(Integer, primary_key=True, index=True)
    payroll_record_id = Column(Integer, ForeignKey("payroll_records.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Agent info snapshot
    agent_name = Column(String, nullable=False)
    agent_role = Column(String, nullable=True)
    tier_level = Column(Integer, default=1)
    commission_rate = Column(Numeric(5, 4), nullable=True)

    # Financials
    total_premium = Column(Numeric(12, 2), default=0)
    new_business_premium = Column(Numeric(12, 2), default=0)
    total_agent_commission = Column(Numeric(12, 2), default=0)
    chargebacks = Column(Numeric(12, 2), default=0)
    chargeback_premium = Column(Numeric(12, 2), default=0)
    chargeback_count = Column(Integer, default=0)
    net_agent_pay = Column(Numeric(12, 2), default=0)
    line_count = Column(Integer, default=0)

    # Manual overrides
    rate_adjustment = Column(Numeric(5, 4), default=0)  # +/-0.005
    bonus = Column(Numeric(12, 2), default=0)
    grand_total = Column(Numeric(12, 2), default=0)  # commission + bonus

    # Carrier breakdown (JSON)
    carrier_breakdown = Column(JSON, nullable=True)

    # Commission paid status
    commission_status = Column(String, default="pending")  # pending, paid
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    payroll_record = relationship("PayrollRecord", back_populates="agent_payroll_lines")
    agent = relationship("User", foreign_keys=[agent_id])
