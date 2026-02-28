from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base


class CustomerNote(Base):
    __tablename__ = "customer_notes"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, index=True, nullable=True)  # Local customer ID
    nowcerts_insured_id = Column(String, index=True, nullable=True)  # NowCerts insured ID
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    source = Column(String, default="orbit")  # orbit, smart_inbox, campaign, manual, etc.
    created_by = Column(String, nullable=True)  # Username who created it
    pushed_to_nowcerts = Column(String, default="no")  # yes/no/failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
