"""Lead model — tracks every inbound lead with round-robin agent assignment."""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Contact info
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=True)
    dob = Column(String, nullable=True)

    # Address
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)

    # Quote details
    policy_types = Column(String, nullable=True)        # "Home, Auto, Bundle"
    current_carrier = Column(String, nullable=True)
    current_premium = Column(String, nullable=True)
    renewal_date = Column(String, nullable=True)
    message = Column(Text, nullable=True)               # Full details blob

    # Property
    roof_year = Column(String, nullable=True)
    home_year = Column(String, nullable=True)
    sqft = Column(String, nullable=True)

    # Drivers (JSON string)
    drivers_info = Column(Text, nullable=True)
    vehicles_info = Column(Text, nullable=True)

    # Source tracking
    source = Column(String, nullable=True)              # "quote_intake_form", "ai_coverage_review", "landing_page", "get-quote"
    utm_campaign = Column(String, nullable=True)

    # Assignment
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_to_name = Column(String, nullable=True)    # Denormalized for easy display
    assigned_at = Column(DateTime(timezone=True), nullable=True)

    # Status tracking
    status = Column(String, default="new")              # new, contacted, quoted, sold, lost
    notes = Column(Text, nullable=True)
    contacted_at = Column(DateTime(timezone=True), nullable=True)
    quoted_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    # Duplicate detection
    is_duplicate = Column(Boolean, default=False)
    duplicate_of_id = Column(Integer, nullable=True)

    # Relationships
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
