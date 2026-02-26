"""Support Ticket model — internal bug/issue reporting."""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from datetime import datetime
from app.core.database import Base


class Ticket(Base):
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Who reported
    reporter_id = Column(Integer, nullable=True)
    reporter_name = Column(String(200), default="")
    reporter_username = Column(String(100), default="")

    # Issue details
    title = Column(String(500), default="")
    description = Column(Text, default="")
    page_url = Column(String(1000), default="")
    user_agent = Column(String(500), default="")

    # Screenshot (base64 PNG stored as text — simple, no file storage needed)
    screenshot_data = Column(Text, nullable=True)

    # Status workflow
    status = Column(String(50), default="open")  # open, in_progress, resolved, closed
    priority = Column(String(50), default="normal")  # low, normal, high, critical
    resolution_notes = Column(Text, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(200), nullable=True)
