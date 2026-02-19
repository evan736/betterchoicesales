"""Non-pay / past-due notice tracking models."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, Boolean, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class NonPayNotice(Base):
    """Tracks each uploaded non-pay file and its processing results."""
    __tablename__ = "nonpay_notices"

    id = Column(Integer, primary_key=True, index=True)

    # Upload info
    filename = Column(String, nullable=False)
    upload_type = Column(String, nullable=True)  # pdf, csv
    uploaded_by = Column(String, nullable=True)  # username

    # Extraction results
    raw_extracted = Column(JSON, nullable=True)  # full Claude extraction
    policies_found = Column(Integer, default=0)
    policies_matched = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    emails_skipped = Column(Integer, default=0)  # skipped due to 1x/week cap

    # Processing
    status = Column(String, default="pending")  # pending, processing, completed, error
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NonPayEmail(Base):
    """Tracks individual past-due emails sent per policy — enforces 1x/week cap."""
    __tablename__ = "nonpay_emails"

    id = Column(Integer, primary_key=True, index=True)

    # Link to notice batch
    notice_id = Column(Integer, nullable=True, index=True)

    # Policy / customer info
    policy_number = Column(String, nullable=False, index=True)
    customer_id = Column(Integer, nullable=True, index=True)
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    carrier = Column(String, nullable=True)

    # Amount due
    amount_due = Column(Numeric(10, 2), nullable=True)
    due_date = Column(String, nullable=True)  # as extracted from doc

    # Email delivery
    email_status = Column(String, default="sent")  # sent, failed, skipped
    mailgun_message_id = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
