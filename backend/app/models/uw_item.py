"""Underwriting tracker model.

A UW item represents a carrier underwriting requirement that the agency must
respond to before a deadline (e.g., 'tree trimming required by 5/15', 'send
photos of roof', 'updated MVR needed'). Created from forwarded emails to
uw@mail.betterchoiceins.com, parsed by Claude, then assigned to a producer or
service-team member to complete.

Design notes:
  - Separate from InboundEmail/Smart Inbox: UW has its own intake, lifecycle,
    notification rules, and tracking dashboard. Sharing a table would couple
    two flows that have different semantics.
  - attachment_data stores PDF blobs (base64) so the kanban drawer can
    inline-preview without a separate fetch. Same shape as
    InboundEmail.attachment_data.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, ForeignKey, Boolean, Date
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class UWItem(Base):
    __tablename__ = "uw_items"

    id = Column(Integer, primary_key=True, index=True)

    # Customer / policy linkage (nullable until matched)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    policy_number = Column(String, nullable=True, index=True)
    carrier = Column(String, nullable=True, index=True)
    line_of_business = Column(String, nullable=True)  # home / auto / commercial / etc.

    # What the carrier wants
    title = Column(String, nullable=True)             # short label (e.g., "Tree trimming")
    description = Column(Text, nullable=True)         # full extracted action description
    required_action = Column(Text, nullable=True)     # plain-language summary of next step
    consequence = Column(Text, nullable=True)         # what happens if not done

    # Deadlines
    due_date = Column(Date, nullable=True, index=True)

    # Assignment (NULL = pending_assignment)
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    assignment_note = Column(Text, nullable=True)

    # Status: pending_assignment | assigned | in_progress | completed | overdue | dismissed
    status = Column(String, nullable=False, default="pending_assignment", index=True)

    # Completion
    completed_at = Column(DateTime(timezone=True), nullable=True)
    completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    completion_note = Column(Text, nullable=True)

    # Original intake data
    intake_email_subject = Column(String, nullable=True)
    intake_email_from = Column(String, nullable=True)        # who forwarded it
    intake_email_carrier_from = Column(String, nullable=True) # original carrier sender
    intake_email_body_text = Column(Text, nullable=True)
    intake_email_body_html = Column(Text, nullable=True)
    intake_received_at = Column(DateTime(timezone=True), nullable=True)
    attachment_data = Column(JSON, nullable=True)  # [{filename, content_type, base64_data}]

    # Notification tracking — track which reminders have already been sent so
    # the daily scheduler doesn't double-send. Booleans flip true once sent.
    notif_assignment_sent = Column(Boolean, default=False)
    notif_3day_sent = Column(Boolean, default=False)
    notif_1day_sent = Column(Boolean, default=False)
    notif_overdue_sent = Column(Boolean, default=False)

    # AI metadata
    ai_extracted = Column(JSON, nullable=True)        # full Claude response for debugging
    ai_confidence = Column(Integer, nullable=True)    # 0-100

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    customer = relationship("Customer", foreign_keys=[customer_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    assigner = relationship("User", foreign_keys=[assigned_by])
    completer = relationship("User", foreign_keys=[completed_by])
    activity = relationship("UWActivity", back_populates="uw_item", cascade="all, delete-orphan")


class UWActivity(Base):
    """Audit trail for each UW item — who did what when.

    Captures: created, assigned, reassigned, edited, completed, reopened,
    dismissed, notified. Useful for a 'history' tab in the kanban drawer
    and for auditing missed deadlines after the fact.
    """
    __tablename__ = "uw_activity"

    id = Column(Integer, primary_key=True, index=True)
    uw_item_id = Column(Integer, ForeignKey("uw_items.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    user_name = Column(String, nullable=True)  # snapshot at time of action
    action = Column(String, nullable=False)    # 'created'|'assigned'|'completed'|...
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    uw_item = relationship("UWItem", back_populates="activity")
