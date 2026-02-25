"""Reshop pipeline model — tracks customer reshop/rewrite requests through workflow."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Reshop(Base):
    __tablename__ = "reshops"

    id = Column(Integer, primary_key=True, index=True)

    # Customer linkage
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    customer = relationship("Customer", foreign_keys=[customer_id])
    customer_name = Column(String, nullable=False)
    customer_phone = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)

    # Policy being reshopped
    policy_number = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    line_of_business = Column(String, nullable=True)
    current_premium = Column(Numeric(10, 2), nullable=True)
    expiration_date = Column(DateTime, nullable=True)

    # Pipeline stage
    # new_request, quoting, quote_ready, presenting, bound, lost, cancelled, proactive
    stage = Column(String, nullable=False, default="new_request", index=True)
    priority = Column(String, default="normal")  # low, normal, high, urgent

    # Source tracking
    # inbound_call, inbound_email, producer_referral, proactive_renewal, walk_in, other
    source = Column(String, nullable=True)
    source_detail = Column(Text, nullable=True)  # e.g. "Joseph forwarded email" or "nonpay escalation"
    referred_by = Column(String, nullable=True)  # producer who sent it over

    # Assignment
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assignee = relationship("User", foreign_keys=[assigned_to])
    quoter = Column(String, nullable=True)  # who is pulling quotes (e.g. "Andrey")
    presenter = Column(String, nullable=True)  # who presents (e.g. "Michelle", "Salma")

    # Quote details
    quoted_carrier = Column(String, nullable=True)
    quoted_premium = Column(Numeric(10, 2), nullable=True)
    premium_savings = Column(Numeric(10, 2), nullable=True)
    quote_notes = Column(Text, nullable=True)

    # Outcome
    outcome = Column(String, nullable=True)  # bound, stayed, left, no_response
    outcome_notes = Column(Text, nullable=True)
    bound_carrier = Column(String, nullable=True)
    bound_premium = Column(Numeric(10, 2), nullable=True)
    bound_date = Column(DateTime, nullable=True)

    # Reason for reshop
    reason = Column(String, nullable=True)  # price_increase, service_issue, coverage_change, shopping, nonpay, other
    reason_detail = Column(Text, nullable=True)

    # General notes
    notes = Column(Text, nullable=True)

    # Proactive detection fields
    is_proactive = Column(Boolean, default=False)
    renewal_premium = Column(Numeric(10, 2), nullable=True)  # new renewal premium if known
    premium_change_pct = Column(Numeric(5, 2), nullable=True)  # % change

    # Timestamps
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    stage_updated_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ReshopActivity(Base):
    """Activity log for reshop pipeline items."""
    __tablename__ = "reshop_activities"

    id = Column(Integer, primary_key=True, index=True)
    reshop_id = Column(Integer, ForeignKey("reshops.id"), nullable=False, index=True)
    reshop = relationship("Reshop", foreign_keys=[reshop_id])

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user = relationship("User", foreign_keys=[user_id])
    user_name = Column(String, nullable=True)

    action = Column(String, nullable=False)  # created, stage_change, assigned, note, quoted, presented, bound, lost
    detail = Column(Text, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
