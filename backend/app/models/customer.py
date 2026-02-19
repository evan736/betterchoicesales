"""Customer model — local cache of NowCerts insured data."""
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, Boolean, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)

    # NowCerts identifiers
    nowcerts_insured_id = Column(String, unique=True, nullable=True, index=True)

    # Core info
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    full_name = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True, index=True)
    phone = Column(String, nullable=True)
    mobile_phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)

    # Status
    is_prospect = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    tags = Column(JSON, nullable=True)  # list of tag strings

    # Agent / producer assignment
    agent_name = Column(String, nullable=True)

    # Sync tracking
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    nowcerts_raw = Column(JSON, nullable=True)  # raw API response for reference

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class CustomerPolicy(Base):
    __tablename__ = "customer_policies"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, nullable=False, index=True)

    # NowCerts identifiers
    nowcerts_policy_id = Column(String, unique=True, nullable=True, index=True)

    # Policy info
    policy_number = Column(String, nullable=True, index=True)
    carrier = Column(String, nullable=True)
    line_of_business = Column(String, nullable=True)  # Auto, Home, etc.
    policy_type = Column(String, nullable=True)
    status = Column(String, nullable=True)  # Active, Cancelled, Expired

    # Dates
    effective_date = Column(DateTime, nullable=True)
    expiration_date = Column(DateTime, nullable=True)

    # Premium
    premium = Column(Numeric(10, 2), nullable=True)

    # Agent
    agent_name = Column(String, nullable=True)

    # Raw data
    nowcerts_raw = Column(JSON, nullable=True)

    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
