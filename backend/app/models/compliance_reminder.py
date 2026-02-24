"""Compliance reminder tracking — logs every follow-up sent for inspections, UW, non-pay tasks."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from app.core.database import Base


class ComplianceReminder(Base):
    """Log of every compliance follow-up reminder sent."""
    __tablename__ = "compliance_reminders"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    policy_number = Column(String, nullable=False)
    task_type = Column(String, nullable=False)  # inspection, uw_requirement, non_pay
    reminder_tier = Column(String, nullable=False)  # "initial", "60d", "30d", "14d", "7d", "3d", "1d", "overdue"

    days_remaining = Column(Integer, nullable=True)
    customer_emailed = Column(Boolean, default=False)
    customer_email = Column(String, nullable=True)
    customer_name = Column(String, nullable=True)
    carrier = Column(String, nullable=True)

    email_subject = Column(String, nullable=True)
    email_status = Column(String, nullable=True)  # sent, failed, skipped

    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow)
