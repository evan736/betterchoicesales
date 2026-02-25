"""MIA AI Receptionist bypass models.

Supports three bypass tiers:
1. VIP Bypass - permanent phone numbers that skip MIA entirely
2. Temp Authorization - staff-granted temporary bypass for a phone number
3. Passphrase ("ORBIT") - handled in prompt, no DB needed

These are framework-only. Not wired into the live inbound webhook yet.
Will be activated when MIA moves from overflow to front-end receptionist.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class VipBypass(Base):
    """Permanent VIP bypass list. These callers skip MIA entirely."""
    __tablename__ = "mia_vip_bypass"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(10), nullable=False, unique=True, index=True)  # normalized 10-digit
    customer_name = Column(String, nullable=True)
    reason = Column(Text, nullable=True)  # why they're VIP
    added_by = Column(String, nullable=True)  # staff member who added
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TempAuthorization(Base):
    """Temporary direct-line authorization. Staff grants a caller temporary bypass."""
    __tablename__ = "mia_temp_auth"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(10), nullable=False, index=True)  # normalized 10-digit
    customer_name = Column(String, nullable=True)
    authorized_by = Column(String, nullable=True)  # staff member who authorized
    reason = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)  # when this expires
    is_active = Column(Boolean, default=True, nullable=False)  # can be manually revoked
    created_at = Column(DateTime(timezone=True), server_default=func.now())
