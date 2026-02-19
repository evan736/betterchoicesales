"""Time clock model for employee attendance tracking.

Attendance rules for commission adjustment:
- 0-1 late days in the month → +0.5% commission bonus
- 2-3 late days → no adjustment (base rate)
- 4+ late days → -0.5% commission penalty
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Date, Numeric, Time
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class TimeClockEntry(Base):
    """Individual clock-in / clock-out record."""
    __tablename__ = "timeclock_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # Date of this entry
    work_date = Column(Date, nullable=False, index=True)
    
    # Clock times
    clock_in = Column(DateTime(timezone=True), nullable=False)
    clock_out = Column(DateTime(timezone=True), nullable=True)
    
    # Expected start time (default 9:00 AM, can be customized per employee)
    expected_start = Column(Time, nullable=True)  # null = use default 9:00 AM
    
    # Late tracking
    is_late = Column(Boolean, default=False)
    minutes_late = Column(Integer, default=0)
    
    # Notes / reason
    note = Column(String, nullable=True)
    
    # GPS location
    latitude = Column(Numeric(10, 7), nullable=True)
    longitude = Column(Numeric(10, 7), nullable=True)
    gps_accuracy = Column(Numeric(8, 2), nullable=True)  # meters
    location_address = Column(String, nullable=True)  # reverse-geocoded (optional)
    is_at_office = Column(Boolean, nullable=True)  # True if within office geofence
    
    # Admin override
    excused = Column(Boolean, default=False)
    excused_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    excused_note = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="timeclock_entries")
    excused_by_user = relationship("User", foreign_keys=[excused_by])
