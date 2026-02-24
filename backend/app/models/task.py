"""Task model for CRM task management."""
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    task_type = Column(String, nullable=True)  # non_renewal, uw_requirement, undeliverable, general
    priority = Column(Enum(TaskPriority), default=TaskPriority.MEDIUM)
    status = Column(Enum(TaskStatus), default=TaskStatus.OPEN)

    # Assignment
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    created_by = Column(String, nullable=True)  # "system", "evan.larson", etc.

    # Related data
    customer_name = Column(String, nullable=True)
    policy_number = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    source = Column(String, nullable=True)  # "natgen_activity", "manual", etc.
    notes = Column(Text, nullable=True)

    # Communication tracking
    customer_email = Column(String, nullable=True)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)
    send_count = Column(Integer, default=0)
    last_send_method = Column(String, nullable=True)  # "email", "letter"

    # Non-renewal escalation tracking
    last_notification_tier = Column(String, nullable=True)  # "60d", "45d", "30d", "14d", "7d", "3d"
    notifications_disabled = Column(Boolean, default=False)
    customer_notified = Column(Boolean, default=False)  # Has the insured been emailed yet?

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class NonRenewalNotification(Base):
    """Log of every non-renewal escalation notification sent."""
    __tablename__ = "non_renewal_notifications"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    policy_number = Column(String, nullable=False)
    tier = Column(String, nullable=False)  # "60d", "45d", "30d", "14d", "7d", "3d"
    days_remaining = Column(Integer, nullable=True)

    # What was sent
    producer_emailed = Column(Boolean, default=False)
    service_emailed = Column(Boolean, default=False)
    customer_emailed = Column(Boolean, default=False)
    evan_emailed = Column(Boolean, default=False)

    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow)
