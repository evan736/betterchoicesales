"""SystemSetting — generic singleton key/value store for runtime-tunable
config that we don't want to require a Render env-var change to update.

Uses a string key + string value (we cast on read). Designed for
admin-controlled UI toggles like outreach scheduler caps where Evan
wants to ramp pace without redeploying.

For typed sets (carriers, lead sources) use AgencyConfig instead.
"""
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)  # always stored as string; caller casts
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by = Column(String, nullable=True)  # username of last editor (audit trail)
