"""Retention tracking models.

Tracks customer-level retention by analyzing commission statement data
month-over-month to determine true retention (vs carrier moves within agency).
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Numeric, JSON, ForeignKey, func
from app.core.database import Base


class RetentionRecord(Base):
    """Tracks each policy's renewal outcome.
    
    Created from statement data: when a policy that was active in period X
    does or doesn't appear as a renewal in subsequent periods.
    """
    __tablename__ = "retention_records"

    id = Column(Integer, primary_key=True, index=True)

    # The policy being tracked
    policy_number = Column(String, nullable=False, index=True)
    insured_name = Column(String, nullable=True)
    carrier = Column(String, nullable=True)

    # The period this policy was originally active (appeared on statement)
    original_period = Column(String, nullable=False, index=True)  # "2025-03"
    original_premium = Column(Numeric(10, 2), nullable=True)
    
    # Expected renewal period (original_period + term_months)
    expected_renewal_period = Column(String, nullable=True)  # "2026-03"
    term_months = Column(Integer, default=12)

    # Outcome
    outcome = Column(String, nullable=True, index=True)  
    # "renewed" - same policy renewed on statement
    # "carrier_move" - policy cancelled but customer has new policy at different carrier
    # "lost" - customer has no active policies in agency
    # "pending" - renewal period hasn't arrived yet
    # "rewritten_same_carrier" - new policy number at same carrier

    # If carrier_move, track where they went
    new_policy_number = Column(String, nullable=True)
    new_carrier = Column(String, nullable=True)
    new_premium = Column(Numeric(10, 2), nullable=True)

    # Customer matching
    customer_id = Column(Integer, nullable=True, index=True)
    customer_name_normalized = Column(String, nullable=True, index=True)

    # Renewal details (if renewed)
    renewal_period = Column(String, nullable=True)  # Actual period it renewed
    renewal_premium = Column(Numeric(10, 2), nullable=True)
    premium_change = Column(Numeric(10, 2), nullable=True)  # renewal - original
    premium_change_pct = Column(Numeric(5, 2), nullable=True)

    # Metadata
    last_analyzed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class RetentionSummary(Base):
    """Monthly retention summary — aggregated stats per period."""
    __tablename__ = "retention_summaries"

    id = Column(Integer, primary_key=True, index=True)
    period = Column(String, nullable=False, unique=True, index=True)  # "2025-03"

    # Counts
    policies_up_for_renewal = Column(Integer, default=0)
    policies_renewed = Column(Integer, default=0)
    policies_carrier_moved = Column(Integer, default=0)
    policies_rewritten = Column(Integer, default=0)
    policies_lost = Column(Integer, default=0)
    policies_pending = Column(Integer, default=0)

    # Rates
    true_retention_rate = Column(Numeric(5, 2), nullable=True)  # (renewed + carrier_move + rewritten) / total
    policy_retention_rate = Column(Numeric(5, 2), nullable=True)  # renewed / total (strict)
    
    # Premium
    original_total_premium = Column(Numeric(12, 2), nullable=True)
    renewed_total_premium = Column(Numeric(12, 2), nullable=True)
    lost_premium = Column(Numeric(12, 2), nullable=True)
    avg_premium_change_pct = Column(Numeric(5, 2), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
