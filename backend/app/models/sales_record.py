"""Sales Records — tracks all-time daily and monthly bests."""
from sqlalchemy import Column, Integer, String, DateTime, Numeric, Text
from sqlalchemy.sql import func
from app.core.database import Base


class SalesRecord(Base):
    __tablename__ = "sales_records"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    record_type = Column(String, nullable=False, index=True)  # "daily_premium", "daily_count", "monthly_premium", "monthly_count"
    period_label = Column(String, nullable=False)              # "2025-08" or "2025-09-15"
    premium = Column(Numeric(12, 2), nullable=False)
    sale_count = Column(Integer, nullable=False)
    previous_record_premium = Column(Numeric(12, 2), nullable=True)
    previous_record_count = Column(Integer, nullable=True)
    previous_record_period = Column(String, nullable=True)     # What period held the old record
    notified = Column(String, default="pending")               # "pending", "sent", "skipped"
    notes = Column(Text, nullable=True)
