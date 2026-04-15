"""Quote Job model — tracks automated quoting requests from reshop pipeline."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, JSON, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class QuoteJob(Base):
    """A request to auto-quote a customer across multiple carriers."""
    __tablename__ = "quote_jobs"

    id = Column(Integer, primary_key=True, index=True)
    
    # Source — which reshop triggered this
    reshop_id = Column(Integer, nullable=True, index=True)
    
    # Customer info
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    customer_dob = Column(String, nullable=True)
    
    # Address
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    
    # Policy info
    line_of_business = Column(String, nullable=False)  # auto, home
    current_carrier = Column(String, nullable=True)
    current_policy_number = Column(String, nullable=True)
    current_premium = Column(Numeric(10, 2), nullable=True)
    effective_date = Column(DateTime, nullable=True)  # desired effective date for new quotes
    
    # Full policy details from NowCerts (vehicles, drivers, property, coverages)
    policy_data = Column(JSON, nullable=True)
    
    # Which carriers to quote
    target_carriers = Column(JSON, nullable=False)  # ["Travelers", "Progressive", "National General"]
    
    # Status tracking
    status = Column(String, default="pending", nullable=False)  # pending, quoting, completed, failed, cancelled
    
    # Results — one entry per carrier quoted
    results = Column(JSON, nullable=True)
    # [{"carrier": "Progressive", "status": "quoted", "premium": 1234.56, "quote_number": "Q123", "details": {...}},
    #  {"carrier": "Travelers", "status": "failed", "error": "Login failed"}, ...]
    
    # Assigned producer
    producer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Error info
    error_message = Column(Text, nullable=True)
