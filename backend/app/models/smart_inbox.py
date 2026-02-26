"""
Smart Inbox models — AI-powered inbound email processing.

Tables:
  - inbound_emails: stores every forwarded email with AI classification
  - outbound_queue: stores AI-drafted responses pending approval or auto-sent
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float,
    ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


# ── Enums ────────────────────────────────────────────────────────────────────

class EmailCategory(str, enum.Enum):
    NON_PAYMENT = "non_payment"
    CANCELLATION = "cancellation"
    NON_RENEWAL = "non_renewal"
    UNDERWRITING_REQUIREMENT = "underwriting_requirement"
    RENEWAL_NOTICE = "renewal_notice"
    POLICY_CHANGE = "policy_change"
    CLAIM_NOTICE = "claim_notice"
    BILLING_INQUIRY = "billing_inquiry"
    CUSTOMER_REQUEST = "customer_request"
    GENERAL_INQUIRY = "general_inquiry"
    ENDORSEMENT = "endorsement"
    NEW_BUSINESS_CONFIRMATION = "new_business_confirmation"
    AUDIT_NOTICE = "audit_notice"
    OTHER = "other"


class SensitivityLevel(str, enum.Enum):
    ROUTINE = "routine"       # Auto-send OK
    MODERATE = "moderate"     # Auto-send with logging
    SENSITIVE = "sensitive"   # Queue for approval
    CRITICAL = "critical"     # Queue + alert Evan


class ProcessingStatus(str, enum.Enum):
    RECEIVED = "received"             # Just arrived
    PARSING = "parsing"               # AI is analyzing
    PARSED = "parsed"                 # AI analysis complete
    CUSTOMER_MATCHED = "customer_matched"  # Matched to NowCerts customer
    CUSTOMER_NOT_FOUND = "customer_not_found"
    LOGGED = "logged"                 # Note added to customer file
    OUTBOUND_QUEUED = "outbound_queued"    # Response drafted & queued
    OUTBOUND_SENT = "outbound_sent"        # Response sent to client
    OUTBOUND_APPROVED = "outbound_approved" # Manual approval given
    OUTBOUND_REJECTED = "outbound_rejected" # Manual rejection
    COMPLETED = "completed"           # Fully processed
    FAILED = "failed"                 # Processing error
    SKIPPED = "skipped"               # No action needed


class OutboundStatus(str, enum.Enum):
    DRAFT = "draft"           # AI drafted, not yet decided
    PENDING_APPROVAL = "pending_approval"  # Waiting for Evan
    APPROVED = "approved"     # Approved, ready to send
    SENT = "sent"             # Sent to customer
    REJECTED = "rejected"     # Evan rejected the draft
    AUTO_SENT = "auto_sent"   # Routine — sent automatically


# ── Inbound Email ────────────────────────────────────────────────────────────

class InboundEmail(Base):
    __tablename__ = "inbound_emails"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Raw email data from Mailgun
    message_id = Column(String, unique=True, nullable=True, index=True)
    from_address = Column(String, nullable=False)
    to_address = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    body_plain = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    sender_name = Column(String, nullable=True)
    forwarded_by = Column(String, nullable=True)  # who forwarded it to us

    # Attachments metadata
    attachment_count = Column(Integer, default=0)
    attachment_names = Column(JSON, nullable=True)  # list of filenames
    attachment_data = Column(JSON, nullable=True)   # list of {filename, content_type, base64_data} for PDFs/images

    # AI Classification
    category = Column(SAEnum(EmailCategory), nullable=True)
    sensitivity = Column(SAEnum(SensitivityLevel), nullable=True)
    ai_summary = Column(Text, nullable=True)          # One-line summary
    ai_analysis = Column(JSON, nullable=True)          # Full structured analysis
    confidence_score = Column(Float, nullable=True)    # 0.0 - 1.0

    # Extracted data
    extracted_policy_number = Column(String, nullable=True)
    extracted_insured_name = Column(String, nullable=True)
    extracted_carrier = Column(String, nullable=True)
    extracted_due_date = Column(DateTime, nullable=True)
    extracted_amount = Column(Float, nullable=True)

    # Customer matching
    nowcerts_insured_id = Column(String, nullable=True)
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    match_method = Column(String, nullable=True)  # policy_number, name, email, phone
    match_confidence = Column(Float, nullable=True)

    # Processing
    status = Column(SAEnum(ProcessingStatus), default=ProcessingStatus.RECEIVED, index=True)
    processing_notes = Column(Text, nullable=True)
    nowcerts_note_logged = Column(Boolean, default=False)
    nowcerts_note_id = Column(String, nullable=True)

    # Error tracking
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # Inbox management
    is_read = Column(Boolean, default=False, index=True)
    is_archived = Column(Boolean, default=False, index=True)

    # Batch report support (one carrier email → multiple customer items)
    is_batch_report = Column(Boolean, default=False)
    batch_item_count = Column(Integer, nullable=True)
    parent_email_id = Column(Integer, ForeignKey("inbound_emails.id"), nullable=True)
    parent_email = relationship("InboundEmail", remote_side=[id], backref="child_items")

    # Relationships
    outbound_messages = relationship("OutboundQueue", back_populates="inbound_email")


# ── Outbound Queue ───────────────────────────────────────────────────────────

class OutboundQueue(Base):
    __tablename__ = "outbound_queue"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Link to inbound
    inbound_email_id = Column(Integer, ForeignKey("inbound_emails.id"), nullable=False)
    inbound_email = relationship("InboundEmail", back_populates="outbound_messages")

    # Recipient
    to_email = Column(String, nullable=False)
    to_name = Column(String, nullable=True)
    cc_email = Column(String, nullable=True)

    # Message content
    subject = Column(String, nullable=False)
    body_html = Column(Text, nullable=False)
    body_plain = Column(Text, nullable=True)

    # AI metadata
    ai_rationale = Column(Text, nullable=True)  # Why AI thinks this should be sent
    template_used = Column(String, nullable=True)

    # Approval workflow
    status = Column(SAEnum(OutboundStatus), default=OutboundStatus.DRAFT, index=True)
    sensitivity = Column(SAEnum(SensitivityLevel), nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_reason = Column(Text, nullable=True)

    # Sending
    sent_at = Column(DateTime, nullable=True)
    mailgun_message_id = Column(String, nullable=True)
    send_error = Column(Text, nullable=True)
