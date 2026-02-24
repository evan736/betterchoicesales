"""Inspection email draft model — holds auto-generated customer emails pending approval."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, LargeBinary, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class InspectionDraft(Base):
    """Stores a drafted inspection follow-up email awaiting Evan's approval."""
    __tablename__ = "inspection_drafts"

    id = Column(Integer, primary_key=True, index=True)

    # Status: pending_review → approved → sent  OR  pending_review → rejected
    status = Column(String, default="pending_review", index=True)

    # Approval token (for one-click approve from email)
    approval_token = Column(String, unique=True, nullable=False, index=True)

    # Source email info
    source_sender = Column(String, nullable=True)
    source_subject = Column(String, nullable=True)

    # Extracted details (from Claude API)
    policy_number = Column(String, nullable=True, index=True)
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    deadline = Column(String, nullable=True)
    action_required = Column(Text, nullable=True)
    issues_found = Column(JSON, nullable=True)  # list of strings
    severity = Column(String, nullable=True)
    extraction_details = Column(JSON, nullable=True)  # full Claude extraction

    # Customer ID link
    customer_id = Column(Integer, nullable=True, index=True)

    # Drafted email content
    draft_subject = Column(String, nullable=True)
    draft_html = Column(Text, nullable=True)

    # PDF attachments stored as binary (for sending on approval)
    # Stored as JSON list of {filename, size} — actual bytes in separate column
    attachment_info = Column(JSON, nullable=True)
    attachment_data = Column(LargeBinary, nullable=True)  # pickled list of (name, bytes)

    # Task link
    task_id = Column(Integer, nullable=True, index=True)

    # After approval
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    mailgun_message_id = Column(String, nullable=True)
    send_error = Column(Text, nullable=True)

    # NowCerts
    nowcerts_note_pushed = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
