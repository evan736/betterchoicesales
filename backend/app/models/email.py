"""Email models — shared inbox, threads, messages, assignments."""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class EmailThread(Base):
    """A conversation thread (grouped by subject + participants)."""
    __tablename__ = "email_threads"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(500), nullable=False, index=True)
    
    # Mailbox this thread belongs to (e.g. "service", "evan.larson", "quotes")
    mailbox = Column(String(100), nullable=False, default="service", index=True)
    
    # Status workflow
    status = Column(String(20), nullable=False, default="open", index=True)  # open, assigned, snoozed, closed
    priority = Column(String(10), nullable=False, default="normal")  # low, normal, high, urgent
    
    # Assignment
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    
    # Customer linkage
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    customer = relationship("Customer", foreign_keys=[customer_id])
    
    # Participants (JSON array of email addresses)
    from_email = Column(String(255), nullable=True, index=True)
    from_name = Column(String(255), nullable=True)
    participants = Column(JSON, default=list)  # [{email, name, type: "to"|"cc"|"bcc"}]
    
    # Tags/labels (JSON array of strings)
    tags = Column(JSON, default=list)  # ["billing", "claims", "new-business", etc.]
    
    # AI summary of the thread
    ai_summary = Column(Text, nullable=True)
    
    # Snooze
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    
    # NowCerts logged
    nowcerts_logged = Column(Boolean, default=False)
    
    # Timestamps
    last_message_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages = relationship("EmailMessage", back_populates="thread", cascade="all, delete-orphan", order_by="EmailMessage.created_at")

    __table_args__ = (
        Index("ix_email_threads_status_mailbox", "status", "mailbox"),
        Index("ix_email_threads_assigned_status", "assigned_to_id", "status"),
    )


class EmailMessage(Base):
    """Individual email message within a thread."""
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    thread = relationship("EmailThread", back_populates="messages")

    # Direction
    direction = Column(String(10), nullable=False)  # "inbound" or "outbound"
    
    # Sender/Recipients
    from_email = Column(String(255), nullable=False)
    from_name = Column(String(255), nullable=True)
    to_emails = Column(JSON, default=list)  # ["email1", "email2"]
    cc_emails = Column(JSON, default=list)
    
    # Content
    subject = Column(String(500), nullable=True)
    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    
    # Attachments (JSON array of {filename, path, size, content_type})
    attachments = Column(JSON, default=list)
    
    # Mailgun message ID for threading
    mailgun_message_id = Column(String(255), nullable=True, index=True)
    in_reply_to = Column(String(255), nullable=True)
    references = Column(Text, nullable=True)  # space-separated message IDs
    
    # AI draft (if AI generated a suggested reply)
    ai_draft = Column(Text, nullable=True)
    ai_draft_generated_at = Column(DateTime(timezone=True), nullable=True)
    
    # Who sent this (for outbound)
    sent_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sent_by = relationship("User", foreign_keys=[sent_by_id])
    
    # Read tracking (JSON: {user_id: timestamp})
    read_by = Column(JSON, default=dict)
    
    # NowCerts logged
    nowcerts_logged = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_email_messages_thread_created", "thread_id", "created_at"),
    )


class EmailRule(Base):
    """Automation rules (like Missive rules) — match conditions → actions."""
    __tablename__ = "email_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=100)  # lower = runs first

    # Conditions (JSON): [{field, operator, value}]
    # field: "from", "to", "subject", "body", "mailbox"
    # operator: "contains", "equals", "starts_with", "ends_with", "regex"
    conditions = Column(JSON, default=list)
    match_mode = Column(String(5), default="all")  # "all" or "any"

    # Actions (JSON): [{action, params}]
    # action: "assign", "tag", "set_priority", "auto_reply", "close", "move_mailbox", "notify"
    actions = Column(JSON, default=list)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
