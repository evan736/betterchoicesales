"""Agency growth snapshot — tracks customer count and premium at regular intervals."""
from sqlalchemy import Column, Integer, Numeric, DateTime, String, Date
from sqlalchemy.sql import func
from app.core.database import Base


class AgencySnapshot(Base):
    """Point-in-time snapshot of agency metrics for growth tracking."""
    __tablename__ = "agency_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, nullable=False, index=True, unique=True)
    period = Column(String, nullable=False, index=True)  # "2026-02", "2026-01"

    # Customer counts
    active_customers = Column(Integer, nullable=False, default=0)
    total_customers = Column(Integer, nullable=False, default=0)

    # Policy counts
    active_policies = Column(Integer, nullable=False, default=0)
    total_policies = Column(Integer, nullable=False, default=0)

    # Premium
    active_premium_annualized = Column(Numeric(14, 2), nullable=False, default=0)

    # Sales metrics for the month
    new_sales_count = Column(Integer, nullable=True, default=0)
    new_sales_premium = Column(Numeric(12, 2), nullable=True, default=0)
    cancellations_count = Column(Integer, nullable=True, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
