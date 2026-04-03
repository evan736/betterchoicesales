"""Commission Payment Tracker — flags policies missing expected commission payments.

Tracks both new business (from sales table) and renewals (from reshops marked renewed
or from NowCerts renewal data) against actual commission statement lines received.

Key logic for Travelers:
- Pays based on policy effective date, not sale date
- Statement cycle ~20th to ~20th (varies 3-5 days)
- Only pays when customer makes first payment
- Policies missing payment 30+ days after effective date are flagged
"""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class CommissionExpectation(Base):
    """A policy we expect to receive commission on.
    
    Created from:
    1. New sales (sales table) — new_business
    2. Renewals (reshops marked 'bound'/'renewed', or NowCerts renewal scan) — renewal
    """
    __tablename__ = "commission_expectations"

    id = Column(Integer, primary_key=True, index=True)

    # Source: where this expectation came from
    source_type = Column(String, nullable=False, index=True)  # "new_business", "renewal"
    source_id = Column(Integer, nullable=True)  # sale.id or reshop.id

    # Policy info
    policy_number = Column(String, nullable=False, index=True)
    customer_name = Column(String, nullable=False)
    carrier = Column(String, nullable=False, index=True)
    policy_type = Column(String, nullable=True)  # auto, home, umbrella, etc.
    
    # Financial
    expected_premium = Column(Numeric(10, 2), nullable=True)
    expected_commission = Column(Numeric(10, 2), nullable=True)  # estimated
    expected_commission_rate = Column(Numeric(5, 4), nullable=True)  # carrier avg rate

    # Dates
    effective_date = Column(DateTime(timezone=True), nullable=False, index=True)
    expected_payment_by = Column(DateTime(timezone=True), nullable=True)  # eff_date + 45 days
    
    # Tracking status
    status = Column(String, default="pending", nullable=False, index=True)
    # pending — waiting for commission
    # paid — matched to statement line
    # overdue — past expected_payment_by, still no payment
    # flagged — manually flagged for follow-up
    # resolved — manually resolved (e.g. confirmed paid separately, policy cancelled, etc.)
    
    # Match to statement
    matched_statement_line_id = Column(Integer, ForeignKey("statement_lines.id"), nullable=True)
    matched_amount = Column(Numeric(10, 2), nullable=True)
    matched_at = Column(DateTime(timezone=True), nullable=True)
    
    # Follow-up
    flag_reason = Column(Text, nullable=True)  # why it was flagged
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Producer
    producer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    producer_name = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    matched_line = relationship("StatementLine", foreign_keys=[matched_statement_line_id])
    producer = relationship("User", foreign_keys=[producer_id])
