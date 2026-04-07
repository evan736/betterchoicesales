"""Renewal Survey models — dynamic multi-question survey for homeowner renewals.

Sent 60 days before homeowner renewal. Branching logic based on happiness rating.
Responses auto-trigger reshop entries, NowCerts updates, and agent notifications.

TEST MODE: Not connected to any automated sender. Manual trigger only.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, JSON, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class RenewalSurvey(Base):
    """A renewal survey instance sent to a customer."""
    __tablename__ = "renewal_surveys"

    id = Column(Integer, primary_key=True, index=True)

    # Customer linkage
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)

    # Policy info
    policy_number = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    current_premium = Column(Numeric(10, 2), nullable=True)
    renewal_date = Column(DateTime, nullable=True)

    # Survey token for public access (no auth needed)
    token = Column(String, unique=True, nullable=False, index=True)

    # Status: pending, started, completed, expired
    status = Column(String, default="pending", index=True)

    # Responses stored as JSON — each question keyed by question_id
    # Example: {"happiness": 4, "home_updates": ["roof", "kitchen"], "filed_claim": false, ...}
    responses = Column(JSON, default=dict)

    # Computed fields from responses
    happiness_rating = Column(Integer, nullable=True)  # 1-5
    is_happy = Column(Boolean, nullable=True)  # True if 4-5, False if 1-3
    wants_callback = Column(Boolean, default=False)
    interested_rate_lock = Column(Boolean, default=False)
    interested_higher_deductible = Column(Boolean, default=False)
    filed_claim = Column(Boolean, default=False)
    home_updates = Column(JSON, default=list)  # ["roof", "kitchen", ...]
    unhappy_reason = Column(String, nullable=True)
    feedback_text = Column(Text, nullable=True)

    # Actions taken
    reshop_created = Column(Boolean, default=False)
    reshop_id = Column(Integer, ForeignKey("reshops.id"), nullable=True)
    nowcerts_updated = Column(Boolean, default=False)
    agent_notified = Column(Boolean, default=False)
    google_review_redirected = Column(Boolean, default=False)

    # Agent assignment
    assigned_agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_agent_name = Column(String, nullable=True)

    # Tracking
    sent_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    customer = relationship("Customer", foreign_keys=[customer_id])
