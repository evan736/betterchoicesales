"""Life Cross-Sell Campaign tracking model."""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Numeric, func
from app.core.database import Base


class LifeCrossSellContact(Base):
    """Tracks each customer's life cross-sell campaign progress."""
    __tablename__ = "life_crosssell_contacts"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=False, index=True)
    agent_name = Column(String, nullable=True)
    agent_email = Column(String, nullable=True)

    # Campaign progress
    touch_number = Column(Integer, default=0)  # 0=queued, 1-4=sent touches
    next_touch_date = Column(DateTime, nullable=True)
    status = Column(String, default="queued")  # queued, active, completed, opted_out, converted

    # Tracking
    touch1_sent_at = Column(DateTime, nullable=True)
    touch2_sent_at = Column(DateTime, nullable=True)
    touch3_sent_at = Column(DateTime, nullable=True)
    touch4_sent_at = Column(DateTime, nullable=True)
    last_opened_at = Column(DateTime, nullable=True)
    last_clicked_at = Column(DateTime, nullable=True)
    total_opens = Column(Integer, default=0)
    total_clicks = Column(Integer, default=0)

    # Source
    source_sale_id = Column(Integer, nullable=True)
    source_policy_type = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
