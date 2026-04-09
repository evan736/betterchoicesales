"""Dialer campaign models — outbound lead calling."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float
from sqlalchemy.sql import func
from app.core.database import Base


class DialerCampaign(Base):
    __tablename__ = "dialer_campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    agent_id = Column(String, nullable=False)  # Retell agent ID
    agent_name = Column(String, nullable=True)
    from_number = Column(String, nullable=True)
    status = Column(String, default="paused")  # active, paused, completed
    max_calls_per_day = Column(Integer, default=300)
    max_calls_per_session = Column(Integer, default=75)
    min_delay_seconds = Column(Integer, default=30)
    max_delay_seconds = Column(Integer, default=60)
    max_lead_age_days = Column(Integer, default=75)
    concurrency_cap = Column(Integer, default=1)  # Max simultaneous live calls before pausing dialer
    total_leads = Column(Integer, default=0)
    total_dialed = Column(Integer, default=0)
    total_transferred = Column(Integer, default=0)
    total_callbacks = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DialerLead(Base):
    __tablename__ = "dialer_leads"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, nullable=False, index=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True)
    address = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    home_value = Column(String, nullable=True)
    roof_installed = Column(String, nullable=True)
    prop_type = Column(String, nullable=True)
    insurance_exp = Column(DateTime, nullable=True)  # Insurance expiration date
    state = Column(String, nullable=True)
    city = Column(String, nullable=True)
    dob = Column(String, nullable=True)
    request_date = Column(DateTime, nullable=True)
    status = Column(String, default="pending", index=True)
    # pending, dialed, transferred, callback_scheduled, soft_no, hard_no,
    # voicemail, no_answer, wrong_number, do_not_call, exhausted, expired
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=10)
    last_attempt_at = Column(DateTime, nullable=True)
    last_time_slot = Column(String, nullable=True)
    next_attempt_after = Column(DateTime, nullable=True)
    interest_level = Column(String, nullable=True)  # hot, warm, cold, hostile
    call_ids = Column(JSON, default=[])
    notes = Column(Text, nullable=True)
    extra_data = Column(JSON, nullable=True)  # Any extra CSV columns
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DialerDNC(Base):
    __tablename__ = "dialer_dnc"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, nullable=False, index=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class DialerPhoneNumber(Base):
    """Outbound phone numbers for the dialer with rotation/cooldown tracking."""
    __tablename__ = "dialer_phone_numbers"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default="active")  # active, resting, available, retired
    first_used_date = Column(DateTime, nullable=True)  # When this number started being used
    rest_until = Column(DateTime, nullable=True)  # When cooldown ends
    total_calls = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
